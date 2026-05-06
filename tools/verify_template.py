#!/usr/bin/env python3
"""Per-case verifier (schema v8). KPIs computed by verifier from field files —
agent's result.json is only consulted as a hint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/sim-tools")
from openfoam_field_kpi import (
    authenticity_check, compute_kpi, find_case, kpi_accuracy, latest_time_dir,
)

REWARD = Path("/logs/verifier/reward.json")
REWARD_DETAIL = Path("/logs/verifier/reward_detail.json")
WEIGHTS = {"exec_ok": 0.2, "converged": 0.2, "physics_faithful": 0.3, "kpi_accurate": 0.3}

# ---- per-case spec (filled by foambench_bulk_port.py) ----
KPIS = __KPIS__  # noqa: E501  list[dict(name,field,agg,gt,range,weight)]
PHYSICS_BOUNDS = __PHYSICS_BOUNDS__  # noqa: E501  dict[name -> (lo, hi)]
# ---------------------------------------------------------


def emit(detail):
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    auth = float(detail.get("authenticity", 0.0))
    weighted = sum(WEIGHTS[k] * float(detail.get(k, 0.0)) for k in WEIGHTS)
    REWARD.write_text(json.dumps({"score": round(auth * weighted, 4)}, indent=2))
    REWARD_DETAIL.write_text(json.dumps(detail, indent=2))
    if detail.get("notes"):
        sys.stderr.write(f"verifier: {detail['notes']}\n")


def main():
    r = {"authenticity": 0.0, "exec_ok": 0.0, "converged": 0.0,
         "physics_faithful": 0.0, "kpi_accurate": 0.0, "kpi_detail": {}, "notes": ""}

    case = find_case()
    auth, reason = authenticity_check(case)
    r["authenticity"] = auth
    if auth == 0.0:
        r["notes"] = f"authenticity FAIL: {reason}"; emit(r); return
    r["exec_ok"] = 1.0

    t = latest_time_dir(case)
    per_kpi, missing, in_bounds_all = {}, [], True
    for spec in KPIS:
        pred = compute_kpi(t / spec["field"], spec["agg"])
        if pred is None:
            missing.append(spec["name"])
            per_kpi[spec["name"]] = {"pred": None, "gt": spec["gt"],
                                     "accuracy": 0.0, "weight": spec["weight"]}
            in_bounds_all = False
            continue
        acc = kpi_accuracy(pred, spec["gt"], spec["range"])
        per_kpi[spec["name"]] = {"pred": pred, "gt": spec["gt"],
                                 "accuracy": round(acc, 6), "weight": spec["weight"]}
        bounds = PHYSICS_BOUNDS.get(spec["name"])
        if bounds and not (bounds[0] <= pred <= bounds[1]):
            in_bounds_all = False
    r["kpi_detail"] = per_kpi
    if missing:
        r["notes"] = f"missing KPIs: {missing} (case={case} t={t.name})"
        emit(r); return

    # Convergence proxy: case ran to completion if there's a time-dir > start.
    # The verifier doesn't try to read solver log — exec_ok + presence of
    # latest-time fields is the signal.
    r["converged"] = 1.0
    r["physics_faithful"] = 1.0 if in_bounds_all else 0.0

    total_w = sum(v["weight"] for v in per_kpi.values()) or 1.0
    r["kpi_accurate"] = round(
        sum(v["accuracy"] * v["weight"] for v in per_kpi.values()) / total_w, 6
    )
    bits = " · ".join(
        f"{n}={v['pred']:.4g} (gt {v['gt']:.4g})"
        for n, v in per_kpi.items() if v["pred"] is not None
    )
    r["notes"] = f"case={case.name} t={t.name} · {bits}"
    emit(r)


if __name__ == "__main__":
    main()
