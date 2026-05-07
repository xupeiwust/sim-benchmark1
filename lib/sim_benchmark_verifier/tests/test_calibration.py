"""Calibration suite — end-to-end fixtures asserting failure_class TPR.

For each ``provenance_stage`` and ``solver_stage`` value we care about,
build a deliberately broken fixture (kpis.json + result.json + mocked
sim records), run the full verifier via ``main()``, and assert the
right class fires on the right KPI.

Mirrors ccl-evaluator's calibration discipline: a check is
"validated" only when there is at least one fixture that exhibits the
failure mode AND the detector flags it (TPR > 0). False-positive rate
(FPR = 0) is asserted by cross-checking that a passing fixture does
not light up off-target classes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim_benchmark_verifier import score as score_mod
from sim_benchmark_verifier.score import main


def _patch_sim(monkeypatch, records):
    monkeypatch.setattr(score_mod, "_query_sim_history", lambda: list(records))


def _write_kpis(tmp_path: Path, kpi_spec: dict, group_weight: float = 1.0) -> Path:
    p = tmp_path / "tests"
    p.mkdir(exist_ok=True)
    f = p / "kpis.json"
    f.write_text(json.dumps({
        "case_id":    "calibration",
        "kpi_groups": {"outputs": {"weight": group_weight}},
        "kpis":       {"u": {"group": "outputs", **kpi_spec}},
    }))
    return f


def _run(tmp_path: Path, kpis_path: Path, result_obj) -> dict:
    result = tmp_path / "result.json"
    result.write_text(json.dumps(result_obj))
    out = tmp_path / "out" / "reward.json"
    main(["--kpis", str(kpis_path), "--result", str(result), "--reward-out", str(out)])
    return json.loads(out.with_name("reward_detail.json").read_text())


# ─── Provenance axis fixtures ──────────────────────────────────────────


def test_calib_P0_hallucination_bare_number(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {"u": 0.5})  # bare number, no source
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P0_hallucination"
    assert k["solver_stage"] is None  # cascading; can't trust solver-axis


def test_calib_P0_hallucination_kpi_absent(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {})  # KPI not even claimed
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P0_hallucination"


def test_calib_P1_path_invalid(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5, "source": {
            "kind": "file_extract", "path": "/tmp/this_definitely_does_not_exist.log",
            "extract": "cat",
        }},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P1_path_invalid"


def test_calib_P2_extract_unrunnable(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("0.5\n")
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5, "source": {
            "kind": "file_extract", "path": str(data),
            # python3 is sandbox-blacklisted (only awk/sed/cut/etc allowed)
            "extract": "python3 -c 'print(0.5)'",
        }},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P2_extract_unrunnable"


def test_calib_P3_extract_mismatch(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("100.0\n")  # file actually says 100
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5,  # claim says 0.5 — mismatch!
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P3_extract_mismatch"


def test_calib_P4_pass_happy_path(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("0.5\n")
    kpis = _write_kpis(tmp_path, {
        "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3,
        "physics_min": 0.0, "physics_max": 1.0,
    })
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5,
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P4_pass"
    assert k["solver_stage"] == "L6_pass"
    assert k["failure_class"] == "null"


# ─── Solver axis fixtures ──────────────────────────────────────────────


def test_calib_L5_physics_outside_range(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("5.0\n")  # value extracted = 5.0, claim = 5.0, but physics_max = 1.0
    kpis = _write_kpis(tmp_path, {
        "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3,
        "physics_min": 0.0, "physics_max": 1.0,
    })
    rd = _run(tmp_path, kpis, {
        "u": {"value": 5.0,
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P4_pass"
    assert k["solver_stage"] == "L5_physics"


def test_calib_L5_quantitative_far_from_gt(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("0.95\n")  # in physics range, but |0.95 − 0.5| = 0.45 > T_bad=0.3
    kpis = _write_kpis(tmp_path, {
        "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3,
        "physics_min": 0.0, "physics_max": 1.0,
    })
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.95,
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P4_pass"
    assert k["solver_stage"] == "L5_quantitative"


def test_calib_L2_solver_crash_when_records_all_failed(tmp_path, monkeypatch):
    # All sim records show solver invocation failed — combined with a
    # provenance failure that's plausibly a downstream effect, attribute L2.
    _patch_sim(monkeypatch, [
        {"kind": "run", "solver": "openfoam", "ok": False, "exit_code": 1},
        {"kind": "run", "solver": "openfoam", "ok": False, "exit_code": 1},
    ])
    kpis = _write_kpis(tmp_path, {"gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3})
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5, "source": {
            "kind": "file_extract", "path": "/tmp/never_produced_by_solver.dat",
            "extract": "cat"}},
    })
    k = rd["kpi_detail"]["per_kpi"]["u"]
    assert k["provenance_stage"] == "P1_path_invalid"
    assert k["solver_stage"] == "L2_solver_crash"


# ─── FPR (false positive rate) checks ───────────────────────────────────
#
# Confirm that the happy-path fixture doesn't accidentally light up
# off-target classes. Explicit, because flat-enum bugs love to live here.


def test_calib_happy_path_no_off_target_failures(tmp_path, monkeypatch):
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    data = tmp_path / "data.txt"
    data.write_text("0.5\n")
    kpis = _write_kpis(tmp_path, {
        "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3,
        "physics_min": 0.0, "physics_max": 1.0,
    })
    rd = _run(tmp_path, kpis, {
        "u": {"value": 0.5,
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    })
    counts_p = rd["kpi_detail"]["provenance_stage_counts"]
    counts_s = rd["kpi_detail"]["solver_stage_counts"]
    # exactly one P4_pass, exactly one L6_pass, nothing else
    assert counts_p["P4_pass"] == 1
    assert sum(v for k, v in counts_p.items() if k != "P4_pass") == 0
    assert counts_s["L6_pass"] == 1
    assert sum(v for k, v in counts_s.items() if k != "L6_pass") == 0


# ─── Calibration manifest test ──────────────────────────────────────────


def test_calibration_covers_every_currently_implemented_class():
    """Self-check: every class produced by Phase 1+2 detectors has at
    least one fixture above. If you add a new class without a fixture,
    this fails."""
    implemented = {
        # provenance — all 5 production values fixtured (spec_error
        # is a case-author bug surface, not a model failure mode)
        "P0_hallucination", "P1_path_invalid",
        "P2_extract_unrunnable", "P3_extract_mismatch", "P4_pass",
        # solver — Phase 1 + Phase 2
        "L5_physics", "L5_quantitative", "L6_pass", "L2_solver_crash",
    }
    fixtures = {
        # provenance
        "P0_hallucination":     "test_calib_P0_hallucination_bare_number",
        "P1_path_invalid":      "test_calib_P1_path_invalid",
        "P2_extract_unrunnable": "test_calib_P2_extract_unrunnable",
        "P3_extract_mismatch":  "test_calib_P3_extract_mismatch",
        "P4_pass":              "test_calib_P4_pass_happy_path",
        # solver
        "L5_physics":           "test_calib_L5_physics_outside_range",
        "L5_quantitative":      "test_calib_L5_quantitative_far_from_gt",
        "L6_pass":              "test_calib_P4_pass_happy_path",
        "L2_solver_crash":      "test_calib_L2_solver_crash_when_records_all_failed",
    }
    missing = implemented - set(fixtures)
    assert not missing, f"calibration coverage gap: {missing}"
