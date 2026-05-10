#!/usr/bin/env python3
"""
Verifier for lid-driven-cavity-re100 — Harbor-native agent path.

Grading contract (see SCHEMA.md):
  1. authenticity gate — a real OpenFOAM case must exist somewhere under
     /root/case, /tmp, or cwd. No case → score forced to 0 (anti-cheat).
  2. result.json must be readable JSON containing the declared KPI(s).
     This case has one KPI: `u_centerline`. Legacy `RESULT` shorthand is
     accepted for single-KPI cases.
  3. reward = authenticity × (0.2·exec + 0.2·converged + 0.3·phys + 0.3·kpi)

Ref: Ghia, Ghia & Shin (1982) Table I, Re=100: u_centerline_y0.5 ≈ -0.20581.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

RESULT_FILE = Path("/tmp/agent/result.json")
REWARD = Path("/logs/verifier/reward.json")
REWARD_DETAIL = Path("/logs/verifier/reward_detail.json")

# KPIs declared here match task.toml [[metadata.sim.kpis]]. They are the
# SCORING authority for this case; task.toml is the human-readable doc.
KPIS = [
    {
        "name":        "u_centerline",
        "gt_value":    -0.20581,
        "range_value": 1.0,
        "weight":      1.0,
    },
]
# For single-KPI cases, verify.py accepts `RESULT` as shorthand for KPI[0].
LEGACY_PRIMARY = KPIS[0]["name"] if len(KPIS) == 1 else None

WEIGHTS = {"exec_ok": 0.2, "converged": 0.2, "physics_faithful": 0.3, "kpi_accurate": 0.3}


def detect_sim_cli_used(parsed: dict) -> float:
    if isinstance(parsed, dict) and "sim_cli_parse" in parsed:
        return 1.0
    for root in (Path("/root/case"), Path("/tmp"), Path("/app"), Path.cwd()):
        if not root.exists():
            continue
        if any(root.rglob(".sim/runs")):
            return 1.0
    return 0.0


def check_authenticity(search_roots):
    standard_fields = {"U", "p", "T", "k", "omega", "epsilon", "nut", "alpha.water", "rho", "phi", "p_rgh"}
    for root in search_roots:
        if not root.exists():
            continue
        for polymesh in root.rglob("polyMesh"):
            if not polymesh.is_dir():
                continue
            if polymesh.parent.name != "constant":
                continue
            case = polymesh.parent.parent
            time_dirs = []
            for p in case.iterdir():
                if p.is_dir():
                    try:
                        float(p.name); time_dirs.append(p)
                    except ValueError:
                        pass
            if not time_dirs:
                continue
            latest = max(time_dirs, key=lambda p: float(p.name))
            found = [f.name for f in latest.iterdir() if f.is_file() and f.name in standard_fields]
            if found:
                return 1.0, f"ok: case={case} t={latest.name} fields={found[:4]}"
    return 0.0, "no valid OpenFOAM case artifact found"


def kpi_accuracy(pred: float, gt: float, range_value: float) -> float:
    denom = max(abs(gt), range_value * 0.01)
    raw = 1.0 - abs(pred - gt) / denom
    return max(0.0, min(1.0, raw))


def extract_kpi(parsed: dict, name: str) -> float | None:
    """Try `parsed['kpis'][name]`, then `parsed[name]`, then `RESULT` iff this is the only KPI."""
    if isinstance(parsed.get("kpis"), dict) and name in parsed["kpis"]:
        return _as_float(parsed["kpis"][name])
    if name in parsed:
        return _as_float(parsed[name])
    if name == LEGACY_PRIMARY and "RESULT" in parsed:
        return _as_float(parsed["RESULT"])
    return None


def _as_float(x) -> float | None:
    if isinstance(x, dict) and "value" in x:
        x = x["value"]
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def emit(detail: dict) -> None:
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    if "sim_cli_used" not in detail:
        try:
            _p = json.loads(RESULT_FILE.read_text()) if RESULT_FILE.is_file() else {}
        except Exception:
            _p = {}
        detail["sim_cli_used"] = detect_sim_cli_used(_p)
    auth = float(detail.get("authenticity", 0.0))
    weighted = sum(WEIGHTS[k] * float(detail.get(k, 0.0)) for k in WEIGHTS)
    score = auth * weighted
    REWARD.write_text(json.dumps({"score": round(score, 4)}, indent=2))
    REWARD_DETAIL.write_text(json.dumps(detail, indent=2))
    if detail.get("notes"):
        sys.stderr.write(f"verifier notes: {detail['notes']}\n")


def main() -> None:
    reward = {
        "authenticity":     0.0,
        "exec_ok":          0.0,
        "converged":        0.0,
        "physics_faithful": 0.0,
        "kpi_accurate":     0.0,
        "kpi_detail":       {},
        "notes":            "",
    }

    # 1. Authenticity gate
    auth_score, auth_reason = check_authenticity([Path("/root/case"), Path("/tmp"), Path.cwd()])
    reward["authenticity"] = auth_score
    if auth_score == 0.0:
        reward["notes"] = f"authenticity FAIL: {auth_reason}"
        emit(reward)
        return

    # 2. result.json presence + validity
    if not RESULT_FILE.is_file():
        reward["notes"] = f"{RESULT_FILE} not found — agent produced no answer"
        emit(reward)
        return
    try:
        parsed = json.loads(RESULT_FILE.read_text())
    except json.JSONDecodeError as e:
        reward["notes"] = f"{RESULT_FILE} is not valid JSON: {e}"
        emit(reward)
        return
    if not isinstance(parsed, dict):
        reward["notes"] = f"result.json is not an object; got {type(parsed).__name__}"
        emit(reward)
        return

    # 3. Per-KPI extraction and scoring
    per_kpi = {}
    any_kpi_missing = False
    for spec in KPIS:
        pred = extract_kpi(parsed, spec["name"])
        if pred is None or not math.isfinite(pred):
            any_kpi_missing = True
            per_kpi[spec["name"]] = {"pred": None, "gt": spec["gt_value"], "accuracy": 0.0, "weight": spec["weight"]}
            continue
        acc = kpi_accuracy(pred, spec["gt_value"], spec["range_value"])
        per_kpi[spec["name"]] = {
            "pred": pred, "gt": spec["gt_value"],
            "accuracy": round(acc, 6), "weight": spec["weight"],
        }
    reward["kpi_detail"] = per_kpi

    if any_kpi_missing:
        reward["notes"] = f"one or more KPIs missing from result.json: " + \
            ", ".join(n for n, v in per_kpi.items() if v["pred"] is None)
        # exec_ok remains 0 — missing KPI is equivalent to no answer
        emit(reward)
        return

    reward["exec_ok"] = 1.0
    reward["converged"] = 1.0 if parsed.get("converged") else 0.0

    # 4. physics_faithful — case-specific sanity. For cavity-Re100:
    #    primary vortex below geometric center ⇒ u_x(0.05, 0.05) is negative,
    #    magnitude 0.05 < |u_x| < 0.5.
    primary = per_kpi["u_centerline"]["pred"]
    if primary is not None and primary < 0 and 0.05 < abs(primary) < 0.5:
        reward["physics_faithful"] = 1.0

    # 5. kpi_accurate — weight-normalized average
    total_w = sum(v["weight"] for v in per_kpi.values())
    if total_w > 0:
        reward["kpi_accurate"] = round(
            sum(v["accuracy"] * v["weight"] for v in per_kpi.values()) / total_w,
            6,
        )

    reward["notes"] = (
        f"u_centerline pred={primary:.5f} vs gt={KPIS[0]['gt_value']} · "
        f"converged={reward['converged']} · auth={auth_reason}"
    )
    emit(reward)


if __name__ == "__main__":
    main()
