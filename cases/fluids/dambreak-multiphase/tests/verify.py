#!/usr/bin/env python3
"""Verifier for dambreak-multiphase — Harbor-native agent path (schema v7).

KPI: peak |U| over interval t=0..1s. GT oracle-calibrated 2026-04-21.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

RESULT_FILE = Path("/tmp/agent/result.json")
REWARD = Path("/logs/verifier/reward.json")
REWARD_DETAIL = Path("/logs/verifier/reward_detail.json")

KPIS = [{"name": "peak_U_magnitude", "gt_value": 4.41, "range_value": 5.0, "weight": 1.0}]
LEGACY_PRIMARY = KPIS[0]["name"] if len(KPIS) == 1 else None
WEIGHTS = {"exec_ok": 0.2, "converged": 0.2, "physics_faithful": 0.3, "kpi_accurate": 0.3}


def detect_sim_cli_used(parsed: dict) -> float:
    if isinstance(parsed, dict) and "sim_cli_parse" in parsed:
        return 1.0
    for root in (Path("/root/case"), Path("/tmp"), Path("/app"), Path.cwd()):
        if root.exists() and any(root.rglob(".sim/runs")):
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

def kpi_accuracy(pred, gt, rv):
    denom = max(abs(gt), rv * 0.01)
    return max(0.0, min(1.0, 1.0 - abs(pred - gt) / denom))


def _as_float(x):
    # Source-anchored format: unwrap {"value": ..., "source": {...}} dict
    if isinstance(x, dict) and "value" in x:
        x = x["value"]
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def extract_kpi(parsed, name):
    if isinstance(parsed.get("kpis"), dict) and name in parsed["kpis"]:
        return _as_float(parsed["kpis"][name])
    if name in parsed:
        return _as_float(parsed[name])
    if name == LEGACY_PRIMARY and "RESULT" in parsed:
        return _as_float(parsed["RESULT"])
    return None


def emit(detail):
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    if "sim_cli_used" not in detail:
        try:
            _p = json.loads(RESULT_FILE.read_text()) if RESULT_FILE.is_file() else {}
        except Exception:
            _p = {}
        detail["sim_cli_used"] = detect_sim_cli_used(_p)
    auth = float(detail.get("authenticity", 0.0))
    weighted = sum(WEIGHTS[k] * float(detail.get(k, 0.0)) for k in WEIGHTS)
    REWARD.write_text(json.dumps({"score": round(auth * weighted, 4)}, indent=2))
    REWARD_DETAIL.write_text(json.dumps(detail, indent=2))
    if detail.get("notes"):
        sys.stderr.write(f"verifier notes: {detail['notes']}\n")


def main():
    r = {"authenticity": 0.0, "exec_ok": 0.0, "converged": 0.0,
         "physics_faithful": 0.0, "kpi_accurate": 0.0, "kpi_detail": {}, "notes": ""}

    auth, reason = check_authenticity([Path("/root/case"), Path("/tmp"), Path.cwd()])
    r["authenticity"] = auth
    if auth == 0.0:
        r["notes"] = f"authenticity FAIL: {reason}"; emit(r); return

    if not RESULT_FILE.is_file():
        r["notes"] = f"{RESULT_FILE} not found"; emit(r); return
    try:
        parsed = json.loads(RESULT_FILE.read_text())
    except json.JSONDecodeError as e:
        r["notes"] = f"result.json not valid JSON: {e}"; emit(r); return
    if not isinstance(parsed, dict):
        r["notes"] = "result.json is not an object"; emit(r); return

    per_kpi, missing = {}, []
    for spec in KPIS:
        pred = extract_kpi(parsed, spec["name"])
        if pred is None or not math.isfinite(pred):
            missing.append(spec["name"])
            per_kpi[spec["name"]] = {"pred": None, "gt": spec["gt_value"], "accuracy": 0.0, "weight": spec["weight"]}
        else:
            acc = kpi_accuracy(pred, spec["gt_value"], spec["range_value"])
            per_kpi[spec["name"]] = {"pred": pred, "gt": spec["gt_value"],
                                     "accuracy": round(acc, 6), "weight": spec["weight"]}
    r["kpi_detail"] = per_kpi
    if missing:
        r["notes"] = f"missing KPIs: {missing}"; emit(r); return

    r["exec_ok"] = 1.0
    r["converged"] = 1.0 if parsed.get("converged") else 0.0

    # Physical range: dam-break peak velocity scales as sqrt(2gH), typically 2-8 m/s for tutorial geometry
    primary = per_kpi["peak_U_magnitude"]["pred"]
    if primary is not None and 0.5 < primary < 10.0:
        r["physics_faithful"] = 1.0

    total_w = sum(v["weight"] for v in per_kpi.values())
    r["kpi_accurate"] = round(sum(v["accuracy"] * v["weight"] for v in per_kpi.values()) / total_w, 6) if total_w > 0 else 0.0

    r["notes"] = f"peak_U_magnitude pred={primary:.4f} vs gt={KPIS[0]['gt_value']}"
    emit(r)


if __name__ == "__main__":
    main()
