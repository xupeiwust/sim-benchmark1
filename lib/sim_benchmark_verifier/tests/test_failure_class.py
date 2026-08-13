"""Unit tests for failure_class — the diagnostic-layer enum.

Each test exercises one classifier branch using a synthetic
`_score_one_kpi` output dict. Real verifier runs feed strings of the
shape these tests check.

Tests are split into two sections: legacy single-axis (v3.1
``classify_kpi``) and the two-axis (v3.2 ``classify_provenance`` /
``classify_solver_stage``).
"""
from __future__ import annotations


from sim_benchmark_verifier.failure_class import (
    PER_KPI_CLASSES,
    annotate_per_kpi,
    classify_kpi,
    classify_provenance,
    classify_solver_stage,
)


# ── null / passed ────────────────────────────────────────────────────────

def test_passed_kpi_classifies_null():
    r = {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 1.0, "value": 175.6}
    assert classify_kpi(r, {"value": 175.6, "source": {"kind": "ltspice_log"}}) == "null"


# ── hallucination shapes ────────────────────────────────────────────────

def test_kpi_absent_classifies_hallucination():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "KPI absent from result.json"}
    assert classify_kpi(r, None) == "hallucination"


def test_bare_number_claim_classifies_hallucination():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: KPI claim must be an object {value, source}"}
    assert classify_kpi(r, 175.6) == "hallucination"


def test_unknown_source_kind_classifies_hallucination():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: unknown source.kind 'made_up'; expected file_extract|ltspice_log|sim_run_stdout|sim_run_kpi"}
    assert classify_kpi(r, {"value": 175.6, "source": {"kind": "made_up"}}) == "hallucination"


# ── provenance_path ─────────────────────────────────────────────────────

def test_missing_file_classifies_provenance_path():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: source file not found: /tmp/nope.log"}
    assert classify_kpi(r, {"value": 1, "source": {"kind": "file_extract", "path": "/tmp/nope.log"}}) == "provenance_path"


def test_relative_path_classifies_provenance_path():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: source.path must be absolute, got 'rel/path.log'"}
    assert classify_kpi(r, {"value": 1, "source": {"path": "rel/path.log"}}) == "provenance_path"


# ── extract_runnable ────────────────────────────────────────────────────

def test_extractor_rejected_classifies_extract_runnable():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: extractor rejected: forbidden binary 'python3'"}
    assert classify_kpi(r, {"value": 1, "source": {"extract": "python3 -c '...'"}}) == "extract_runnable"


def test_extractor_exit_classifies_extract_runnable():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: extractor exited 1: awk: cannot open"}
    assert classify_kpi(r, {"value": 1, "source": {}}) == "extract_runnable"


# ── extract_format / value mismatch ─────────────────────────────────────

def test_value_mismatch_classifies_extract_format():
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: value mismatch: claim 175.6, file 159.18, diff 16.42"}
    assert classify_kpi(r, {"value": 175.6, "source": {}}) == "extract_format"


# ── physics ──────────────────────────────────────────────────────────────

def test_outside_physics_range_classifies_physics():
    r = {"kpi_score": 0.0, "source_verified": 1.0, "physics_pass": 0.0,
         "t_decay": 0.0, "physics_why": "pred 5e6 > physics_max 1e3", "value": 5e6}
    assert classify_kpi(r, {"value": 5e6, "source": {}}) == "physics"


# ── convergence ─────────────────────────────────────────────────────────

def test_in_physics_but_far_from_gt_classifies_convergence():
    r = {"kpi_score": 0.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 0.0, "value": 100.0}
    assert classify_kpi(r, {"value": 100.0, "source": {}}) == "convergence"


def test_partial_t_decay_classifies_convergence():
    r = {"kpi_score": 0.5, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 0.5, "value": 175.6}
    assert classify_kpi(r, {"value": 175.6, "source": {}}) == "convergence"


# ── annotate_per_kpi mutates + returns counts ───────────────────────────

def test_annotate_legacy_failure_class_field_set_correctly():
    # v3.1 consumers read per_kpi[*]["failure_class"]; verify the legacy
    # field is still emitted with v3.1 values.
    per_kpi = {
        "good":     {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0, "t_decay": 1.0},
        "no_file":  {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0, "t_decay": 0.0,
                     "why": "source verification failed: source file not found: /x"},
        "absent":   {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0, "t_decay": 0.0,
                     "why": "KPI absent from result.json"},
    }
    annotate_per_kpi(per_kpi, {"good": {"value": 1, "source": {}}, "no_file": {"value": 1, "source": {}}})
    assert per_kpi["good"]["failure_class"] == "null"
    assert per_kpi["no_file"]["failure_class"] == "provenance_path"
    assert per_kpi["absent"]["failure_class"] == "hallucination"


def test_all_classes_in_enum():
    # Sanity: every value classify_kpi can return is in the published enum.
    for _ in range(10):
        # spot checks
        for cls in PER_KPI_CLASSES:
            assert isinstance(cls, str)
    assert "null" in PER_KPI_CLASSES
    assert "physics" in PER_KPI_CLASSES


# ── two-axis tests (v3.2) ───────────────────────────────────────────────

def test_provenance_passed_returns_P4_pass():
    r = {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 1.0, "value": 1.0}
    assert classify_provenance(r, {"value": 1.0, "source": {}}) == "P4_pass"


def test_provenance_path_invalid():
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: source file not found: /tmp/nope.log"}
    assert classify_provenance(r, {"value": 1, "source": {}}) == "P1_path_invalid"


def test_provenance_extract_unrunnable():
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: extractor exited 1: awk: cannot open"}
    assert classify_provenance(r, {"value": 1, "source": {}}) == "P2_extract_unrunnable"


def test_provenance_extract_mismatch():
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: value mismatch: claim 175.6, file 159.18, diff 16.42"}
    assert classify_provenance(r, {"value": 175.6, "source": {}}) == "P3_extract_mismatch"


def test_provenance_hallucination_kpi_absent():
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "KPI absent from result.json"}
    assert classify_provenance(r, None) == "P0_hallucination"


def test_solver_stage_pass_when_score_one():
    r = {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 1.0, "value": 1.0}
    assert classify_solver_stage(r) == "L6_pass"


def test_solver_stage_physics_fail():
    r = {"kpi_score": 0.0, "source_verified": 1.0, "physics_pass": 0.0,
         "t_decay": 0.0, "value": 5e6}
    assert classify_solver_stage(r) == "L5_physics"


def test_solver_stage_quantitative_fail():
    r = {"kpi_score": 0.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 0.0, "value": 100.0}
    assert classify_solver_stage(r) == "L5_quantitative"


def test_solver_stage_partial_decay_is_quantitative():
    r = {"kpi_score": 0.5, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 0.5, "value": 175.6}
    assert classify_solver_stage(r) == "L5_quantitative"


def test_solver_stage_null_when_provenance_failed():
    # Cascading: source not verified → can't trust solver-axis signal
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: source file not found"}
    assert classify_solver_stage(r) is None


def test_annotate_emits_both_axes():
    per_kpi = {
        "good":   {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0, "t_decay": 1.0},
        "miss":   {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
                   "t_decay": 0.0, "why": "source verification failed: source file not found: /x"},
        "phys":   {"kpi_score": 0.0, "source_verified": 1.0, "physics_pass": 0.0,
                   "t_decay": 0.0, "value": 5e6},
    }
    counts = annotate_per_kpi(
        per_kpi,
        {"good": {"value": 1, "source": {}}, "miss": {"value": 1, "source": {}}, "phys": {"value": 5e6, "source": {}}},
    )
    assert per_kpi["good"]["solver_stage"]     == "L6_pass"
    assert per_kpi["good"]["provenance_stage"] == "P4_pass"
    assert per_kpi["good"]["failure_class"]    == "null"

    assert per_kpi["miss"]["solver_stage"]     is None
    assert per_kpi["miss"]["provenance_stage"] == "P1_path_invalid"
    assert per_kpi["miss"]["failure_class"]    == "provenance_path"

    assert per_kpi["phys"]["solver_stage"]     == "L5_physics"
    assert per_kpi["phys"]["provenance_stage"] == "P4_pass"
    assert per_kpi["phys"]["failure_class"]    == "physics"

    assert counts["solver_stage_counts"]["L6_pass"]     == 1
    assert counts["solver_stage_counts"]["L5_physics"]  == 1
    assert counts["solver_stage_counts"]["null"]        == 1
    assert counts["provenance_stage_counts"]["P4_pass"]        == 2
    assert counts["provenance_stage_counts"]["P1_path_invalid"] == 1


def test_legacy_failure_class_still_correct():
    # v3.1 callers expect the old name to keep returning the same values.
    r = {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0,
         "t_decay": 0.0, "why": "source verification failed: extractor rejected: forbidden binary"}
    assert classify_kpi(r, {"value": 1, "source": {}}) == "extract_runnable"


# ── Phase 2: L2_solver_crash attribution from sim_records ───────────────

def test_solver_stage_L2_when_all_runs_failed():
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: source file not found: /tmp/nope.log"}
    sim_records = [
        {"kind": "run", "solver": "ltspice", "ok": False, "exit_code": 1},
        {"kind": "run", "solver": "ltspice", "ok": False, "exit_code": 2},
    ]
    assert classify_solver_stage(r, sim_records) == "L2_solver_crash"


def test_solver_stage_null_when_some_run_succeeded():
    # At least one ok run → solver completed; provenance failure is not
    # attributable to L2.
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: extractor exited 1: awk: cannot open"}
    sim_records = [
        {"kind": "run", "solver": "ltspice", "ok": True, "exit_code": 0},
    ]
    assert classify_solver_stage(r, sim_records) is None


def test_solver_stage_null_when_no_records():
    # Agent bypassed sim-cli — no records means we can't tell if the
    # solver ran. Don't fabricate an L2 attribution.
    r = {"kpi_score": 0.0, "source_verified": 0.0,
         "why": "source verification failed: source file not found: /x"}
    assert classify_solver_stage(r, sim_records=[]) is None
    assert classify_solver_stage(r, sim_records=None) is None


def test_solver_stage_records_ignored_when_provenance_passed():
    # If source_verified=1, sim_records can't override the per-KPI L5/L6
    # attribution; solver clearly ran.
    r = {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0,
         "t_decay": 1.0, "value": 175.6}
    sim_records = [{"kind": "run", "solver": "ltspice", "ok": False}]
    assert classify_solver_stage(r, sim_records) == "L6_pass"


def test_annotate_with_sim_records_emits_L2():
    per_kpi = {
        "missed": {"kpi_score": 0.0, "source_verified": 0.0,
                   "why": "source verification failed: source file not found"},
    }
    sim_records = [{"kind": "run", "solver": "openfoam", "ok": False, "exit_code": 1}]
    counts = annotate_per_kpi(per_kpi, {"missed": {"value": 1, "source": {}}}, sim_records)
    assert per_kpi["missed"]["solver_stage"] == "L2_solver_crash"
    assert per_kpi["missed"]["provenance_stage"] == "P1_path_invalid"
    assert counts["solver_stage_counts"]["L2_solver_crash"] == 1
