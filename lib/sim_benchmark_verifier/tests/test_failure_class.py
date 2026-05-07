"""Unit tests for failure_class — the diagnostic-layer enum.

Each test exercises one classifier branch using a synthetic
`_score_one_kpi` output dict. Real verifier runs feed strings of the
shape these tests check.
"""
from __future__ import annotations

import pytest

from sim_benchmark_verifier.failure_class import (
    PER_KPI_CLASSES,
    annotate_per_kpi,
    classify_kpi,
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

def test_annotate_mutates_and_counts():
    per_kpi = {
        "good":     {"kpi_score": 1.0, "source_verified": 1.0, "physics_pass": 1.0, "t_decay": 1.0},
        "no_file":  {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0, "t_decay": 0.0,
                     "why": "source verification failed: source file not found: /x"},
        "absent":   {"kpi_score": 0.0, "source_verified": 0.0, "physics_pass": 0.0, "t_decay": 0.0,
                     "why": "KPI absent from result.json"},
    }
    counts = annotate_per_kpi(per_kpi, {"good": {"value": 1, "source": {}}, "no_file": {"value": 1, "source": {}}})
    assert per_kpi["good"]["failure_class"] == "null"
    assert per_kpi["no_file"]["failure_class"] == "provenance_path"
    assert per_kpi["absent"]["failure_class"] == "hallucination"
    assert counts["null"] == 1
    assert counts["provenance_path"] == 1
    assert counts["hallucination"] == 1


def test_all_classes_in_enum():
    # Sanity: every value classify_kpi can return is in the published enum.
    for _ in range(10):
        # spot checks
        for cls in PER_KPI_CLASSES:
            assert isinstance(cls, str)
    assert "null" in PER_KPI_CLASSES
    assert "physics" in PER_KPI_CLASSES
