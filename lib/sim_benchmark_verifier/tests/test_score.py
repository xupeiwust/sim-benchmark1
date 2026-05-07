"""Unit tests for the v3 grader (KPI groups + provenance)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim_benchmark_verifier.score import (
    W_META, W_KPI,
    _physics_pass,
    _t_decay,
    _tgood_tbad_decay,
    _validate_groups,
    main,
    meta_check,
)
from sim_benchmark_verifier.provenance import VerifyResult, verify_source


# ── decay helpers ──────────────────────────────────────────────────────

def test_decay_perfect():
    assert _tgood_tbad_decay(0.0, 0.1, 1.0) == 1.0

def test_decay_good_boundary():
    assert _tgood_tbad_decay(0.1, 0.1, 1.0) == 1.0

def test_decay_bad_boundary():
    assert _tgood_tbad_decay(1.0, 0.1, 1.0) == 0.0

def test_decay_linear_midpoint():
    s = _tgood_tbad_decay(0.55, 0.1, 1.0)
    assert abs(s - 0.5) < 0.01

def test_t_decay_uses_gt_value():
    spec = {"gt_value": -0.06, "T_good": 0.015, "T_bad": 0.05}
    assert _t_decay(spec, -0.06) == 1.0
    assert _t_decay(spec, -0.21) == 0.0  # err = 0.15, well past T_bad

def test_physics_pass_in_range():
    assert _physics_pass({"physics_min": 0, "physics_max": 1}, 0.5)[0] == 1.0

def test_physics_pass_below_min():
    assert _physics_pass({"physics_min": 0}, -1)[0] == 0.0

def test_physics_pass_above_max():
    assert _physics_pass({"physics_max": 1}, 2)[0] == 0.0

def test_physics_pass_nan():
    assert _physics_pass({}, float("nan"))[0] == 0.0


# ── meta gate ──────────────────────────────────────────────────────────

def _q(records):
    return lambda: list(records)

def _q_raises(msg):
    def f():
        raise RuntimeError(msg)
    return f


def test_meta_no_sim():
    s, d = meta_check(_query=_q_raises("sim CLI not on PATH"))
    assert s == 0.0
    assert d["exec_ok"] == 0.0 and d["process_ok"] == 0.0

def test_meta_no_runs():
    s, d = meta_check(_query=_q([]))
    assert s == 0.0
    assert d["exec_ok"] == 0.0

def test_meta_only_failed_run():
    s, d = meta_check(_query=_q([{"kind": "run", "ok": False}]))
    assert s == 0.5  # exec_ok=1, process_ok=0
    assert d["exec_ok"] == 1.0 and d["process_ok"] == 0.0

def test_meta_one_ok_run():
    s, d = meta_check(_query=_q([{"kind": "run", "ok": True, "solver": "openfoam"}]))
    assert s == 1.0
    assert d["n_ok_runs"] == 1

def test_meta_ignores_non_run_kind():
    s, d = meta_check(_query=_q([
        {"kind": "connect", "ok": True},
        {"kind": "run", "ok": True},
    ]))
    assert s == 1.0
    assert d["n_runs"] == 1


# ── group validation ───────────────────────────────────────────────────

def test_validate_groups_weights_must_sum_to_one():
    err = _validate_groups({"a": {"weight": 0.5}, "b": {"weight": 0.4}}, {})
    assert err is not None and "1.0" in err

def test_validate_groups_kpi_must_reference_known_group():
    err = _validate_groups(
        {"outputs": {"weight": 1.0}},
        {"k1": {"group": "phantom"}},
    )
    assert err is not None and "phantom" in err

def test_validate_groups_ok():
    err = _validate_groups(
        {"outputs": {"weight": 1.0}},
        {"k1": {"group": "outputs"}},
    )
    assert err is None


# ── provenance: file_extract ───────────────────────────────────────────

def test_provenance_file_extract_ok(tmp_path: Path):
    f = tmp_path / "data.csv"
    f.write_text("0.5,2.0\n0.6,3.0\n")
    claim = {
        "value": 3.0,
        "source": {"kind": "file_extract", "path": str(f),
                   "extract": "tail -1 | cut -d, -f2"},
    }
    r = verify_source(claim, [])
    assert r.ok, r.why

def test_provenance_file_missing(tmp_path: Path):
    claim = {"value": 1.0, "source": {"kind": "file_extract",
                                       "path": str(tmp_path / "nope.dat"),
                                       "extract": "cat"}}
    r = verify_source(claim, [])
    assert not r.ok

def test_provenance_file_value_mismatch(tmp_path: Path):
    f = tmp_path / "data.txt"
    f.write_text("0.42\n")
    claim = {"value": 0.99, "source": {"kind": "file_extract",
                                        "path": str(f), "extract": "cat"}}
    r = verify_source(claim, [])
    assert not r.ok and "mismatch" in r.why

def test_provenance_tolerates_5sig_truncation(tmp_path: Path):
    """Agent reads -0.0607829 from the file but copies -0.060783 into
    result.json (5 sig figs). Provenance check should still accept."""
    f = tmp_path / "data.txt"
    f.write_text("-0.0607829\n")
    claim = {"value": -0.060783, "source": {"kind": "file_extract",
                                              "path": str(f), "extract": "cat"}}
    r = verify_source(claim, [])
    assert r.ok, r.why

def test_provenance_rejects_off_by_factor(tmp_path: Path):
    """100x off (e.g. wrong column in CSV: agent reports 0.003 but
    file column has 3e-5) is unambiguously "not from this file"."""
    f = tmp_path / "data.txt"
    f.write_text("3e-5\n")
    claim = {"value": 0.003, "source": {"kind": "file_extract",
                                         "path": str(f), "extract": "cat"}}
    r = verify_source(claim, [])
    assert not r.ok and "mismatch" in r.why

def test_provenance_accepts_3_digit_truncation(tmp_path: Path):
    """1% provenance tolerance: agent rounding -0.0608 → -0.061 still
    passes (T_good/T_bad downstream catches if accuracy is bad)."""
    f = tmp_path / "data.txt"
    f.write_text("-0.0608\n")
    claim = {"value": -0.061, "source": {"kind": "file_extract",
                                          "path": str(f), "extract": "cat"}}
    r = verify_source(claim, [])
    assert r.ok, r.why

def test_provenance_relative_path_rejected(tmp_path: Path):
    claim = {"value": 1.0, "source": {"kind": "file_extract",
                                       "path": "data.txt", "extract": "cat"}}
    r = verify_source(claim, [])
    assert not r.ok and "absolute" in r.why

def test_provenance_dotdot_rejected(tmp_path: Path):
    claim = {"value": 1.0, "source": {"kind": "file_extract",
                                       "path": "/foo/../etc/passwd", "extract": "cat"}}
    r = verify_source(claim, [])
    assert not r.ok and ".." in r.why

def test_provenance_extractor_disallowed_binary(tmp_path: Path):
    f = tmp_path / "data.txt"
    f.write_text("0.5\n")
    claim = {"value": 0.5, "source": {"kind": "file_extract",
                                       "path": str(f),
                                       "extract": "rm -rf /"}}
    r = verify_source(claim, [])
    assert not r.ok and "disallowed" in r.why

def test_provenance_extractor_redirection_rejected(tmp_path: Path):
    f = tmp_path / "data.txt"
    f.write_text("0.5\n")
    claim = {"value": 0.5, "source": {"kind": "file_extract",
                                       "path": str(f),
                                       "extract": "cat > /tmp/owned"}}
    r = verify_source(claim, [])
    assert not r.ok and "redirect" in r.why

def test_provenance_awk_with_gt_in_program_passes(tmp_path: Path):
    """awk 'NR>1 ...' has > inside the awk script — must NOT be rejected."""
    f = tmp_path / "data.csv"
    f.write_text("header\n1\n2\n3\n")
    claim = {"value": 1.0, "source": {"kind": "file_extract",
                                       "path": str(f),
                                       "extract": "awk 'NR>1 {print; exit}'"}}
    r = verify_source(claim, [])
    assert r.ok, r.why

def test_provenance_awk_with_semicolon_in_program_passes(tmp_path: Path):
    """awk 'BEGIN{a=1; print a}' has ; inside awk — must NOT be rejected."""
    f = tmp_path / "data.txt"
    f.write_text("ignored\n")
    claim = {"value": 1.0, "source": {"kind": "file_extract",
                                       "path": str(f),
                                       "extract": "awk 'BEGIN{a=1; print a; exit}'"}}
    r = verify_source(claim, [])
    assert r.ok, r.why

def test_provenance_python3_rejected(tmp_path: Path):
    """python3 -c can run anything; must not be allowed."""
    f = tmp_path / "data.txt"; f.write_text("0\n")
    claim = {"value": 0, "source": {"kind": "file_extract",
                                     "path": str(f),
                                     "extract": "python3 -c 'print(0)'"}}
    r = verify_source(claim, [])
    assert not r.ok


# ── provenance: ltspice_log ────────────────────────────────────────────

def test_provenance_ltspice_log_completed_ok(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("foo\nTotal elapsed time: 0.1 seconds\n")
    claim = {"value": 1, "source": {"kind": "ltspice_log",
                                     "path": str(f), "query": "completed"}}
    r = verify_source(claim, [])
    assert r.ok, r.why
    assert r.extracted == "1"


def test_provenance_ltspice_log_completed_error(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("*** error: bad netlist\nTotal elapsed time: 0.1 seconds\n")
    claim = {"value": 1, "source": {"kind": "ltspice_log",
                                     "path": str(f), "query": "completed"}}
    r = verify_source(claim, [])
    assert not r.ok
    assert r.extracted == "0"


def test_provenance_ltspice_log_scalar_measure(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("gain: mag(v(out))=(-16.0947dB,-10.4deg) at 1000\n")
    claim = {"value": -16.0947, "source": {"kind": "ltspice_log",
                                            "path": str(f), "query": "measure",
                                            "measurement": "gain"}}
    r = verify_source(claim, [])
    assert r.ok, r.why
    assert r.extracted == "-16.0947"


def test_provenance_ltspice_log_when_measure_uses_axis_value(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("f_3db: mag(v(out))=0.123 at 175.644\n")
    claim = {"value": 175.644, "source": {"kind": "ltspice_log",
                                           "path": str(f), "query": "measure",
                                           "measurement": "f_3db"}}
    r = verify_source(claim, [])
    assert r.ok, r.why


def test_provenance_ltspice_log_t90_measure_uses_axis_value(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("t90: V(out)=0.9  AT 0.000453901624939\n")
    claim = {"value": 0.000453901624939, "source": {"kind": "ltspice_log",
                                                     "path": str(f), "query": "measure",
                                                     "measurement": "t90"}}
    r = verify_source(claim, [])
    assert r.ok, r.why


def test_provenance_ltspice_log_stepped_measure(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("""Measurement: gain_10hz
 step gain_10hz
 1    (-0.2dB,0deg)
 2    (-0.5dB,0deg)
 3    (-0.842dB,0deg)
Measurement: atten_1khz
 1    (-9.9dB,0deg)
""")
    claim = {"value": -0.842, "source": {"kind": "ltspice_log",
                                          "path": str(f), "query": "measure",
                                          "measurement": "gain_10hz",
                                          "step": 3}}
    r = verify_source(claim, [])
    assert r.ok, r.why
    assert r.extracted == "-0.842"


def test_provenance_ltspice_log_step_param(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text(""".step cval=4.7e-07
.step cval=1e-06
.step cval=2.2e-06
Total elapsed time: 0.1
""")
    claim = {"value": 2.2, "source": {"kind": "ltspice_log",
                                       "path": str(f), "query": "step_param",
                                       "param": "cval", "step": 3,
                                       "scale": 1000000}}
    r = verify_source(claim, [])
    assert r.ok, r.why
    assert r.extracted == "2.2"


def test_provenance_ltspice_log_utf16_nul(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_bytes("vout_avg: AVG(v(out))=9.659\nTotal elapsed time: 1\n".encode("utf-16-le"))
    claim = {"value": 9.659, "source": {"kind": "ltspice_log",
                                         "path": str(f), "query": "measure",
                                         "measurement": "vout_avg"}}
    r = verify_source(claim, [])
    assert r.ok, r.why


def test_provenance_ltspice_log_missing_measure(tmp_path: Path):
    f = tmp_path / "run.log"
    f.write_text("other: x=1\n")
    claim = {"value": 1, "source": {"kind": "ltspice_log",
                                     "path": str(f), "query": "measure",
                                     "measurement": "gain"}}
    r = verify_source(claim, [])
    assert not r.ok
    assert "not found" in r.why


# ── provenance: sim_run_stdout ─────────────────────────────────────────

def test_provenance_sim_stdout_ok():
    records = [{
        "run_id": "001", "kind": "run", "ok": True,
        "stdout": "Final residual = 8.5e-6\nAnother line\n",
    }]
    claim = {
        "value": 8.5e-6,
        "source": {"kind": "sim_run_stdout", "run_id": "001",
                   "extract": "awk '/residual/ {print $4}' | head -1"},
    }
    r = verify_source(claim, records)
    assert r.ok, r.why

def test_provenance_sim_stdout_run_not_found():
    claim = {"value": 1.0, "source": {"kind": "sim_run_stdout",
                                       "run_id": "999", "extract": "cat"}}
    r = verify_source(claim, [{"run_id": "001", "stdout": "x"}])
    assert not r.ok and "999" in r.why


# ── provenance: sim_run_kpi ────────────────────────────────────────────

def test_provenance_sim_kpi_ok():
    records = [{
        "run_id": "002", "kind": "run", "ok": True,
        "parsed_output": {"Cd": 0.8523},
    }]
    claim = {"value": 0.8523, "source": {"kind": "sim_run_kpi",
                                          "run_id": "002", "field": "Cd"}}
    r = verify_source(claim, records)
    assert r.ok, r.why

def test_provenance_sim_kpi_missing_field():
    records = [{"run_id": "002", "kind": "run", "parsed_output": {"Cd": 1.0}}]
    claim = {"value": 1.0, "source": {"kind": "sim_run_kpi",
                                       "run_id": "002", "field": "Cl"}}
    r = verify_source(claim, records)
    assert not r.ok


# ── provenance: shape rejection ────────────────────────────────────────

def test_provenance_bare_value_rejected():
    r = verify_source(0.5, [])
    assert not r.ok

def test_provenance_no_source_rejected():
    r = verify_source({"value": 0.5}, [])
    assert not r.ok and "source" in r.why

def test_provenance_unknown_kind():
    r = verify_source({"value": 1.0, "source": {"kind": "magic"}}, [])
    assert not r.ok and "magic" in r.why


# ── end-to-end: main() ─────────────────────────────────────────────────

def _patch_sim(monkeypatch, records):
    from sim_benchmark_verifier import score as score_mod
    monkeypatch.setattr(score_mod, "_query_sim_history", lambda: list(records))


def _write_kpis(tmp_path, groups, kpis):
    p = tmp_path / "tests"
    p.mkdir()
    f = p / "kpis.json"
    f.write_text(json.dumps({
        "case_id":     "unit_test",
        "kpi_groups":  groups,
        "kpis":        kpis,
    }))
    return f


def test_main_perfect_score(tmp_path, monkeypatch):
    """Single group, single KPI, agent reports value with file_extract source."""
    data = tmp_path / "data.txt"
    data.write_text("0.5\n")
    kpis_path = _write_kpis(tmp_path,
        {"outputs": {"weight": 1.0}},
        {"u": {"group": "outputs", "shape": "scalar",
               "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3,
               "physics_min": 0.0, "physics_max": 1.0}})
    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "u": {"value": 0.5,
              "source": {"kind": "file_extract", "path": str(data), "extract": "cat"}},
    }))
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True, "solver": "openfoam"}])
    out = tmp_path / "out" / "reward.json"
    assert main(["--kpis", str(kpis_path), "--result", str(result), "--reward-out", str(out)]) == 0
    rj = json.loads(out.read_text())
    assert list(rj.keys()) == ["score"]
    assert rj["score"] == pytest.approx(W_META + W_KPI)  # 1.0
    rd = json.loads(out.with_name("reward_detail.json").read_text())
    assert rd["schema_version"].startswith("reward-v3")
    assert rd["meta_score"] == 1.0
    assert rd["kpi_score"] == 1.0


def test_main_bare_value_caught(tmp_path, monkeypatch):
    """Agent writes naked number — provenance gate fails the KPI."""
    kpis_path = _write_kpis(tmp_path,
        {"outputs": {"weight": 1.0}},
        {"u": {"group": "outputs", "gt_value": 0.5, "T_good": 0.05, "T_bad": 0.3}})
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"u": 0.5}))  # bare number — schema violation
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    out = tmp_path / "out" / "reward.json"
    main(["--kpis", str(kpis_path), "--result", str(result), "--reward-out", str(out)])
    rj = json.loads(out.read_text())
    assert rj["score"] == pytest.approx(W_META)  # only meta credit
    rd = json.loads(out.with_name("reward_detail.json").read_text())
    assert rd["kpi_detail"]["per_kpi"]["u"]["source_verified"] == 0.0


def test_main_kpi_groups_partial_credit(tmp_path, monkeypatch):
    """Solid group succeeds, fluid group fails (multi-solver pipeline)."""
    f1 = tmp_path / "stress.txt";   f1.write_text("1.2e6\n")
    f2 = tmp_path / "drag.txt";     f2.write_text("999\n")  # fluid wrong
    kpis_path = _write_kpis(tmp_path,
        {"solid": {"weight": 0.5}, "fluid": {"weight": 0.5}},
        {
            "solid_max_stress": {
                "group": "solid", "gt_value": 1.2e6,
                "T_good": 1e5, "T_bad": 5e5},
            "fluid_drag":       {
                "group": "fluid", "gt_value": 0.85,
                "T_good": 0.05, "T_bad": 0.2,
                "physics_max": 10.0},
        })
    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "solid_max_stress": {"value": 1.2e6,
            "source": {"kind": "file_extract", "path": str(f1), "extract": "cat"}},
        "fluid_drag":       {"value": 999.0,
            "source": {"kind": "file_extract", "path": str(f2), "extract": "cat"}},
    }))
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    out = tmp_path / "out" / "reward.json"
    main(["--kpis", str(kpis_path), "--result", str(result), "--reward-out", str(out)])
    rj = json.loads(out.read_text())
    # meta=1.0 (diagnostic, weight 0); solid group=1, fluid group=0 (physics_max violated)
    # kpi_score = 0.5 * 1.0 + 0.5 * 0.0 = 0.5
    # final = W_META · 1 + W_KPI · 0.5 (constants — numbers depend on current weights)
    assert rj["score"] == pytest.approx(W_META * 1.0 + W_KPI * 0.5)


def test_main_missing_kpi_in_result_scores_zero(tmp_path, monkeypatch):
    """A KPI declared in spec but absent from result.json scores 0 — penalises skipped stages."""
    kpis_path = _write_kpis(tmp_path,
        {"outputs": {"weight": 1.0}},
        {
            "u_centerline": {"group": "outputs", "gt_value": 0.5,
                             "T_good": 0.05, "T_bad": 0.3},
            "u_min":        {"group": "outputs", "gt_value": 0.5,
                             "T_good": 0.05, "T_bad": 0.3},
        })
    f = tmp_path / "v.txt"; f.write_text("0.5\n")
    result = tmp_path / "result.json"
    # Only one of two KPIs reported
    result.write_text(json.dumps({
        "u_centerline": {"value": 0.5,
            "source": {"kind": "file_extract", "path": str(f), "extract": "cat"}},
    }))
    _patch_sim(monkeypatch, [{"kind": "run", "ok": True}])
    out = tmp_path / "out" / "reward.json"
    main(["--kpis", str(kpis_path), "--result", str(result), "--reward-out", str(out)])
    rj = json.loads(out.read_text())
    # group = mean(1.0, 0.0) = 0.5; kpi_score = 0.5
    # final = W_META + W_KPI · 0.5 (constants — meta gate currently weight 0)
    assert rj["score"] == pytest.approx(W_META + W_KPI * 0.5)


def test_main_invalid_groups_hard_fails(tmp_path, monkeypatch):
    """Weights don't sum to 1 — verifier writes 0 + error in detail."""
    kpis_path = _write_kpis(tmp_path,
        {"a": {"weight": 0.3}, "b": {"weight": 0.4}},  # sums to 0.7
        {})
    out = tmp_path / "out" / "reward.json"
    rc = main(["--kpis", str(kpis_path),
               "--result", str(tmp_path / "missing.json"),
               "--reward-out", str(out)])
    assert rc != 0
    rj = json.loads(out.read_text())
    assert rj["score"] == 0.0
    assert "error" in json.loads(out.with_name("reward_detail.json").read_text())


def test_main_empty_positive_weight_group_hard_fails(tmp_path, monkeypatch):
    """Positive-weight groups must carry at least one KPI."""
    kpis_path = _write_kpis(tmp_path,
        {"setup": {"weight": 0.1}, "numerical": {"weight": 0.15}, "outputs": {"weight": 0.75}},
        {"sim_completed": {"group": "setup", "gt_value": 1, "T_good": 0.5, "T_bad": 0.5},
         "gain": {"group": "outputs", "gt_value": 1.0, "T_good": 0.1, "T_bad": 0.5}})
    out = tmp_path / "out" / "reward.json"
    rc = main(["--kpis", str(kpis_path),
               "--result", str(tmp_path / "missing.json"),
               "--reward-out", str(out)])
    assert rc != 0
    assert json.loads(out.read_text())["score"] == 0.0
    detail = json.loads(out.with_name("reward_detail.json").read_text())
    assert "positive weight but no KPIs" in detail["error"]


def test_weights_sum_to_one():
    assert W_META + W_KPI == pytest.approx(1.0)
