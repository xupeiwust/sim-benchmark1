#!/usr/bin/env python3
"""Roll up per-trial cost.json files into a per-run economics summary.

Reads cost.json files (produced by tools/cost_meter.py) under one or more
job dirs and emits two artifacts to stdout (or to --output-json / --output-md):

  1. Per-case detail rows: case | model | turns | wall_s | tokens_in/out/cache | $cost
  2. Per-run summary    : model | n_cases | total_turns | total_wall_s | total_tokens_* | $cost

USD cost rules:
  - claude_code_assistant_sum source: use claude-code's `total_cost_usd`
    (trial-cumulative, accurate, surfaced by cost_meter.py).
  - openai_usage_proxy source: compute `(billable_input × input_price +
    cache_read × cache_read_price + output × output_price) / 1M` from the
    per-model price table below. Where a price isn't known, leave None.

Usage:
  python3 tools/aggregate_economics.py jobs/release-v0.1-ltspice20-minimax-m25/2026-05-06__17-13-51 \
      jobs/release-v0.1-ltspice20-minimax-m27/2026-05-06__22-06-27 \
      --output-json results/v0.1/economics.json \
      --output-md  results/v0.1/economics.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# USD per 1M tokens. Sources:
# - MiniMax-M2.5 / M2.7: pricepertoken.com (May 2026)
# - MiniMax-M2.5-highspeed (a.k.a. M2.5-Lightning): verdent.ai pricing guide
#   (May 2026); cache_read price is not officially listed for the highspeed
#   variant, so we apply the 20 % of input ratio observed on the base + M2.7
#   tiers as a stable estimate.
# Updates: keep this dict in sync with sources cited in
# `results/v0.1/economics.md`.
MODEL_PRICES: dict[str, dict[str, float]] = {
    "MiniMax-M2.5-highspeed": {
        "input": 0.30, "output": 2.40, "cache_read": 0.06,
        "source": "verdent.ai (May 2026); cache rate estimated",
    },
    "MiniMax-M2.7": {
        "input": 0.30, "output": 1.20, "cache_read": 0.059,
        "source": "pricepertoken.com (May 2026)",
    },
    "MiniMax-M2.5": {
        "input": 0.15, "output": 1.15, "cache_read": 0.03,
        "source": "pricepertoken.com (May 2026)",
    },
}


def compute_usd(row: dict) -> float | None:
    """Compute trial USD cost from token totals + per-model price table.

    Returns None when (a) tokens_source != openai_usage_proxy or (b) the
    model is missing from MODEL_PRICES.
    """
    if row.get("tokens_source") != "openai_usage_proxy":
        return None
    model = row.get("model")
    prices = MODEL_PRICES.get(model)
    if not prices:
        return None
    in_t = row.get("input_tokens") or 0
    out_t = row.get("output_tokens") or 0
    cache = row.get("cache_read_tokens") or 0
    billable_in = max(in_t - cache, 0)
    cost = (
        billable_in * prices["input"]
        + cache * prices["cache_read"]
        + out_t * prices["output"]
    ) / 1_000_000.0
    return round(cost, 4)


def collect(job_dir: Path) -> tuple[str, list[dict]]:
    """Return (run_label, list-of-cost-records) for one job dir."""
    rows: list[dict] = []
    for trial in sorted(job_dir.iterdir()):
        if not trial.is_dir():
            continue
        cj = trial / "cost.json"
        if not cj.is_file():
            continue
        try:
            cost = json.loads(cj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        agent = cost.get("agent") or {}
        compute = cost.get("compute") or {}
        row = {
            "case": cost.get("case"),
            "trial": cost.get("trial"),
            "model": agent.get("model"),
            "turns": agent.get("turns"),
            "wall_s": agent.get("wall_seconds"),
            "input_tokens": agent.get("input_tokens"),
            "output_tokens": agent.get("output_tokens"),
            "cache_read_tokens": agent.get("cache_read_tokens"),
            "cache_creation_tokens": agent.get("cache_creation_tokens"),
            "reasoning_tokens": agent.get("reasoning_tokens"),
            "tokens_source": agent.get("tokens_source"),
            "total_cost_usd": agent.get("total_cost_usd"),
            "solver_wall_s": compute.get("solver_wall_seconds"),
        }
        if row["total_cost_usd"] is None:
            row["total_cost_usd"] = compute_usd(row)
        rows.append(row)
    label = job_dir.name
    return label, rows


def per_run_summary(label: str, rows: list[dict]) -> dict:
    """Reduce per-trial rows into one summary record."""
    def _sum(field: str) -> int | float | None:
        vals = [r.get(field) for r in rows if isinstance(r.get(field), (int, float))]
        if not vals:
            return None
        return sum(vals)

    def _mean(field: str) -> float | None:
        vals = [r.get(field) for r in rows if isinstance(r.get(field), (int, float))]
        if not vals:
            return None
        return sum(vals) / len(vals)

    models = {r["model"] for r in rows if r.get("model")}
    sources = {r.get("tokens_source") for r in rows if r.get("tokens_source")}
    return {
        "run_label": label,
        "n_cases": len(rows),
        "model": next(iter(models), None) if len(models) <= 1 else sorted(models),
        "tokens_source": next(iter(sources), None) if len(sources) <= 1 else sorted(sources),
        "total_turns": _sum("turns"),
        "total_wall_s": _sum("wall_s"),
        "total_input_tokens": _sum("input_tokens"),
        "total_output_tokens": _sum("output_tokens"),
        "total_cache_read_tokens": _sum("cache_read_tokens"),
        "total_cache_creation_tokens": _sum("cache_creation_tokens"),
        "total_reasoning_tokens": _sum("reasoning_tokens"),
        "total_cost_usd": _sum("total_cost_usd"),
        "total_solver_wall_s": _sum("solver_wall_s"),
        "mean_turns_per_case": _mean("turns"),
        "mean_wall_s_per_case": _mean("wall_s"),
        "mean_cost_usd_per_case": _mean("total_cost_usd"),
    }


def render_md(summaries: list[dict], detail: list[dict]) -> str:
    out: list[str] = []
    out.append("# Economics — sim-benchmark v0.1 reference runs\n")
    out.append("Auto-generated from `tools/aggregate_economics.py` "
               "over per-trial `cost.json` files.\n")

    out.append("## Per-run summary\n")
    out.append("Cross-model comparable: turns, wall_seconds. "
               "Token / `$` cost columns vary by tokens_source — see methodology note below.\n")
    out.append("| Run | Model | Cases | Mean turns/case | Mean wall/case (s) | "
               "Total turns | Total wall (s) | Total tokens out | Total cost (USD) | tokens_source |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in summaries:
        m = s["model"] if isinstance(s["model"], str) else (
            ", ".join(s["model"]) if s["model"] else "—")
        ts = s.get("tokens_source") or "—"
        if isinstance(ts, list):
            ts = ", ".join(ts)
        out.append(
            f"| `{s['run_label']}` | {m} | {s['n_cases']} | "
            f"{_fmt(s['mean_turns_per_case'], 1)} | "
            f"{_fmt(s['mean_wall_s_per_case'], 1)} | "
            f"{_fmt(s['total_turns'], 0)} | {_fmt(s['total_wall_s'], 1)} | "
            f"{_fmt(s['total_output_tokens'], 0)} | "
            f"{_fmt(s.get('total_cost_usd'), 2)} | {ts} |"
        )

    out.append("\n## Per-case detail\n")
    out.append("Same caveat: trust turns + wall across models; tokens / `$` only within a tokens_source.\n")
    out.append("| Run | Case | Turns | Wall (s) | Output tok | Cost (USD) |")
    out.append("|---|---|---:|---:|---:|---:|")
    for r in detail:
        out.append(
            f"| `{r['run_label']}` | `{r['case']}` | "
            f"{_fmt(r.get('turns'), 0)} | {_fmt(r.get('wall_s'), 1)} | "
            f"{_fmt(r.get('output_tokens'), 0)} | "
            f"{_fmt(r.get('total_cost_usd'), 2)} |"
        )

    out.append("\n## Methodology note\n")
    out.append(
        "- **`turns`**: number of agent round-trips (claude-code's `result.num_turns`). Comparable across models.\n"
        "- **`wall_s`**: end-to-end trial wall time (claude-code's `result.duration_ms`). Comparable across models.\n"
        "- **`tokens_source = openai_usage_proxy`**: ccr-routed runs (MiniMax). Tokens are the proxy's exact "
        "request-by-request sum. USD cost is computed from the price table baked into "
        "`tools/aggregate_economics.py` (see sources below); accurate to first-order but caveated by "
        "(a) any upstream price changes since this snapshot, and (b) `MiniMax-M2.5-highspeed`'s cache rate "
        "being estimated at 20 % of input rate (officially listed price absent).\n"
        "- **`tokens_source = claude_code_assistant_sum`**: direct-Anthropic runs (Claude Opus 4.6). "
        "Per-message usage on streaming events is incomplete in the SDK transcript, so token totals here "
        "**undercount** the true cumulative; `$` cost is taken from claude-code's "
        "`total_cost_usd` (trial-cumulative, accurate).\n"
    )
    out.append("\n### Price table (USD / 1M tokens)\n")
    out.append("| Model | Input | Output | Cache read | Source |")
    out.append("|---|---:|---:|---:|---|")
    for name, p in MODEL_PRICES.items():
        out.append(
            f"| {name} | {p['input']:.3f} | {p['output']:.3f} | "
            f"{p['cache_read']:.3f} | {p['source']} |"
        )
    return "\n".join(out) + "\n"


def _fmt(x, digits: int) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{digits}f}"
    return f"{x:,}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dirs", nargs="+", type=Path,
                    help="one or more harbor job dirs containing trial/<...>/cost.json")
    ap.add_argument("--output-json", type=Path, default=None)
    ap.add_argument("--output-md", type=Path, default=None)
    args = ap.parse_args(argv)

    summaries: list[dict] = []
    detail_rows: list[dict] = []
    for jd in args.job_dirs:
        if not jd.is_dir():
            print(f"not a directory: {jd}", file=sys.stderr)
            return 2
        label, rows = collect(jd)
        for r in rows:
            r["run_label"] = label
            detail_rows.append(r)
        summaries.append(per_run_summary(label, rows))

    payload = {"summaries": summaries, "detail": detail_rows}

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2) + "\n",
                                    encoding="utf-8")
        print(f"wrote {args.output_json}")
    elif not args.output_md:
        print(json.dumps(payload, indent=2))

    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_md(summaries, detail_rows),
                                  encoding="utf-8")
        print(f"wrote {args.output_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
