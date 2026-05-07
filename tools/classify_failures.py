#!/usr/bin/env python3
"""Apply failure_class enum retrospectively to existing reward_detail.json.

Reads each trial's `verifier/reward_detail.json` + `agent/result.json` (or
`/tmp/agent/result.json`-equivalent) under one or more job dirs and emits a
per-trial + per-run failure-class distribution.

Useful for back-filling diagnostic data on runs scored before the verifier
gained the failure_class field. Once the new verifier is in the trial
container image, `reward_detail.json` will already carry `failure_class`
on each per_kpi entry — this tool is a bridge.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sim_benchmark_verifier.failure_class import (
    PER_KPI_CLASSES,
    classify_kpi,
)


def classify_trial(trial_dir: Path) -> dict | None:
    rd = trial_dir / "verifier" / "reward_detail.json"
    if not rd.is_file():
        return None
    try:
        d = json.loads(rd.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    per_kpi = (d.get("kpi_detail") or {}).get("per_kpi") or {}
    # The agent's claimed result.json is mounted into the trial container at
    # runtime, but the trial dir doesn't always preserve it under a stable
    # path. We fall back to per_kpi[*].value which the verifier already
    # captures (only enough to disambiguate "absent" vs "present claim").
    result_obj = {
        name: ({"value": k.get("value")} if k.get("value") is not None else None)
        for name, k in per_kpi.items()
    }
    counts: dict[str, int] = {c: 0 for c in PER_KPI_CLASSES}
    rows: dict[str, str] = {}
    for name, kpi_result in per_kpi.items():
        cls = classify_kpi(kpi_result, result_obj.get(name))
        rows[name] = cls
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "trial":      trial_dir.name,
        "case":       trial_dir.name.rsplit("__", 1)[0],
        "per_kpi":    rows,
        "counts":     counts,
        "kpi_score":  d.get("kpi_score"),
        "final_score": d.get("final_score"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dirs", nargs="+", type=Path)
    ap.add_argument("--output-json", type=Path, default=None)
    args = ap.parse_args(argv)

    overall: dict = {"runs": []}
    for jd in args.job_dirs:
        if not jd.is_dir():
            print(f"not a directory: {jd}", file=sys.stderr)
            return 2
        trials: list[dict] = []
        for sub in sorted(jd.iterdir()):
            if not sub.is_dir():
                continue
            row = classify_trial(sub)
            if row:
                trials.append(row)
        run_counts: dict[str, int] = {c: 0 for c in PER_KPI_CLASSES}
        for t in trials:
            for c, n in t["counts"].items():
                run_counts[c] = run_counts.get(c, 0) + n
        overall["runs"].append({
            "run_label": jd.name,
            "n_trials":  len(trials),
            "counts":    run_counts,
            "trials":    trials,
        })

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(overall, indent=2) + "\n",
                                    encoding="utf-8")
        print(f"wrote {args.output_json}")

    # Brief table to stdout
    print()
    print(f"{'Run':<50} " + " ".join(f"{c[:6]:>7}" for c in PER_KPI_CLASSES))
    for run in overall["runs"]:
        cells = " ".join(f"{run['counts'].get(c, 0):>7}" for c in PER_KPI_CLASSES)
        print(f"{run['run_label']:<50} {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
