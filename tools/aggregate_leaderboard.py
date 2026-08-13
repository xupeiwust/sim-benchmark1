#!/usr/bin/env python3
"""
Aggregate a Harbor job directory into a markdown leaderboard table.

Given `harbor run -c <config>` output at `jobs/<name>/<timestamp>/`, walks
each trial subdir, reads `verifier/reward.json` (single-key score) and
optionally `verifier/reward_detail.json` (four-tier breakdown), and prints
a table: rows = models, cols = tasks, cells = score.

Usage:
    python3 tools/aggregate_leaderboard.py jobs/matrix/2026-04-21__HH-MM-SS/

Run with `--details` for a per-case four-tier breakdown.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def build_tier_index(cases_root: Path) -> dict[str, str]:
    """Map short task name (from dir basename) -> difficulty_tier from task.toml.

    Falls back to "?" for any case missing [metadata.sim].difficulty_tier.
    """
    index: dict[str, str] = {}
    for toml_path in cases_root.rglob("task.toml"):
        try:
            with toml_path.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError:
            continue
        tier = ((data.get("metadata") or {}).get("sim") or {}).get("difficulty_tier", "?")
        index[toml_path.parent.name] = tier
    return index


def parse_trial_dir(trial: Path) -> dict | None:
    """Extract task + agent + reward from a trial directory."""
    cfg = trial / "config.json"
    reward = trial / "verifier" / "reward.json"
    if not (cfg.is_file() and reward.is_file()):
        return None

    try:
        config = json.loads(cfg.read_text())
        r = json.loads(reward.read_text())
    except json.JSONDecodeError:
        return None

    agent = config.get("agent", {}) or {}
    task = config.get("task", {}) or {}
    # Harbor config.json schema: task.name, agent.name, agent.model_name
    task_name = task.get("name") or trial.name.rsplit("__", 1)[0]
    agent_name = agent.get("name") or "unknown"
    model_name = agent.get("model_name") or ""

    detail = None
    rd = trial / "verifier" / "reward_detail.json"
    if rd.is_file():
        try:
            detail = json.loads(rd.read_text())
        except json.JSONDecodeError:
            pass

    # Our convention (SCHEMA.md §6) is a single "score" key, but tolerate an
    # unnamed single-key dict as a fallback for early case drafts.
    if isinstance(r, dict) and "score" in r:
        score = r["score"]
    elif isinstance(r, dict) and len(r) == 1:
        score = next(iter(r.values()))
    else:
        score = None

    return {
        "trial": trial.name,
        "task": task_name,
        "agent": agent_name,
        "model": model_name,
        "score": score,
        "detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dirs", type=Path, nargs="+", help="one or more jobs/<name>/<timestamp>/")
    ap.add_argument("--details", action="store_true", help="print four-tier per-trial breakdown")
    ap.add_argument("--cases-root", type=Path, default=Path("cases"),
                    help="root under which to find task.toml for tier stratification (default: cases/)")
    args = ap.parse_args()

    tier_by_case = build_tier_index(args.cases_root) if args.cases_root.is_dir() else {}

    for jd in args.job_dirs:
        if not jd.is_dir():
            print(f"not a directory: {jd}", file=sys.stderr)
            return 2

    # dedupe by (model, task); keep the highest score seen across jobs
    by_key: dict[tuple[str, str], dict] = {}
    for jd in args.job_dirs:
        for sub in sorted(jd.iterdir()):
            if not sub.is_dir():
                continue
            row = parse_trial_dir(sub)
            if row is None:
                continue
            key = (row.get("model") or row.get("agent"), row["task"])
            prev = by_key.get(key)
            if prev is None or (
                isinstance(row.get("score"), (int, float))
                and isinstance(prev.get("score"), (int, float))
                and row["score"] > prev["score"]
            ):
                by_key[key] = row
    results = list(by_key.values())

    if not results:
        print(f"no trials with reward.json under {args.job_dirs}", file=sys.stderr)
        return 3

    # Canonical short label per model
    def label(row):
        m = row["model"]
        if "/" in m:
            m = m.split("/", 1)[1]
        return m or row["agent"]

    # Wide matrix: rows = models, cols = tasks
    models = sorted({label(r) for r in results})
    tasks = sorted({r["task"] for r in results})
    cell: dict[tuple[str, str], float] = {}
    for r in results:
        cell[(label(r), r["task"])] = r["score"]

    print("## Leaderboard (Harbor-native terminus-2)")
    print()
    header_tiers = " | ".join(f"{t} ({tier_by_case.get(t, '?')})" for t in tasks)
    header = "| Model | " + header_tiers + " | mean |"
    sep = "|---|" + "---|" * (len(tasks) + 1)
    print(header)
    print(sep)
    for m in models:
        cells = [cell.get((m, t)) for t in tasks]
        numeric = [c for c in cells if isinstance(c, (int, float))]
        mean = sum(numeric) / len(numeric) if numeric else 0.0
        fmt_cells = [f"{c:.4f}" if isinstance(c, (int, float)) else "—" for c in cells]
        print(f"| {m} | " + " | ".join(fmt_cells) + f" | **{mean:.4f}** |")

    # Per-tier stratified means — the discriminator S vs M vs L
    tiers_present = sorted({tier_by_case.get(t, "?") for t in tasks})
    if tier_by_case and len(tiers_present) > 1:
        print()
        print("### Per-tier means")
        print()
        print("| Model | " + " | ".join(f"tier {t}" for t in tiers_present) + " | overall |")
        print("|---|" + "---|" * (len(tiers_present) + 1))
        for m in models:
            row_cells = []
            for tier in tiers_present:
                tier_tasks = [t for t in tasks if tier_by_case.get(t, "?") == tier]
                scores = [cell[(m, t)] for t in tier_tasks if isinstance(cell.get((m, t)), (int, float))]
                row_cells.append(f"{sum(scores)/len(scores):.4f}" if scores else "—")
            all_scores = [cell[(m, t)] for t in tasks if isinstance(cell.get((m, t)), (int, float))]
            overall = f"{sum(all_scores)/len(all_scores):.4f}" if all_scores else "—"
            print(f"| {m} | " + " | ".join(row_cells) + f" | **{overall}** |")

    if args.details:
        print()
        print("### Per-trial four-tier breakdown")
        print()
        print("| Model | Task | exec_ok | conv | phys | kpi | notes |")
        print("|---|---|---|---|---|---|---|")
        for r in sorted(results, key=lambda r: (label(r), r["task"])):
            d = r["detail"] or {}
            print(f"| {label(r)} | {r['task']} | "
                  f"{d.get('exec_ok', '—')} | {d.get('converged', '—')} | "
                  f"{d.get('physics_faithful', '—')} | "
                  f"{d.get('kpi_accurate', 0):.3f} | "
                  f"{d.get('notes', '')[:60]} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
