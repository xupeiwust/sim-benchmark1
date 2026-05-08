"""Plugin-layer contract tests — verifies the detector framework
itself (Protocol shape, registration order, dispatch semantics).

The behavioural fixtures still live in test_failure_class +
test_calibration; this file is just the wiring."""
from __future__ import annotations

from sim_benchmark_verifier.detectors import (
    SolverStageDetector,
    TrialContext,
    all_known_stages,
    dispatch,
    register,
    registered,
)
from sim_benchmark_verifier.detectors.universal import UniversalDetector


def test_universal_detector_is_registered():
    names = {d.name for d in registered()}
    assert "universal" in names


def test_universal_detector_satisfies_protocol():
    d = UniversalDetector()
    assert isinstance(d, SolverStageDetector)
    assert d.name == "universal"
    assert "L6_pass" in d.STAGES
    assert "L2_solver_crash" in d.STAGES


def test_all_known_stages_includes_universal():
    stages = all_known_stages()
    assert "L6_pass" in stages
    assert "L5_physics" in stages
    assert "L2_solver_crash" in stages


def test_dispatch_returns_first_non_none(monkeypatch):
    """Earlier-registered detector wins over later-registered one."""

    class FirstDetector:
        name = "test_first"
        STAGES = ("X_first",)

        def applicable(self, ctx):
            return True

        def detect(self, kpi_result, ctx):
            return "X_first"

    class SecondDetector:
        name = "test_second"
        STAGES = ("X_second",)

        def applicable(self, ctx):
            return True

        def detect(self, kpi_result, ctx):
            return "X_second"

    from sim_benchmark_verifier import detectors as dmod
    saved = list(dmod._REGISTRY)
    try:
        dmod._REGISTRY.clear()
        register(FirstDetector())
        register(SecondDetector())
        result = dispatch({}, TrialContext())
        assert result == "X_first"
    finally:
        dmod._REGISTRY.clear()
        dmod._REGISTRY.extend(saved)


def test_dispatch_skips_inapplicable(monkeypatch):
    """An applicable=False detector is skipped, dispatch falls through."""

    class NotApplicable:
        name = "not_applicable"
        STAGES = ("X_skip",)

        def applicable(self, ctx):
            return False

        def detect(self, kpi_result, ctx):
            return "X_skip"  # would be wrong — but applicable=False

    class Applicable:
        name = "applicable"
        STAGES = ("X_use",)

        def applicable(self, ctx):
            return True

        def detect(self, kpi_result, ctx):
            return "X_use"

    from sim_benchmark_verifier import detectors as dmod
    saved = list(dmod._REGISTRY)
    try:
        dmod._REGISTRY.clear()
        register(NotApplicable())
        register(Applicable())
        result = dispatch({}, TrialContext())
        assert result == "X_use"
    finally:
        dmod._REGISTRY.clear()
        dmod._REGISTRY.extend(saved)


def test_dispatch_returns_none_when_nothing_attributes(monkeypatch):
    class AlwaysNone:
        name = "always_none"
        STAGES = ()

        def applicable(self, ctx):
            return True

        def detect(self, kpi_result, ctx):
            return None

    from sim_benchmark_verifier import detectors as dmod
    saved = list(dmod._REGISTRY)
    try:
        dmod._REGISTRY.clear()
        register(AlwaysNone())
        result = dispatch({}, TrialContext())
        assert result is None
    finally:
        dmod._REGISTRY.clear()
        dmod._REGISTRY.extend(saved)


def test_trial_context_defaults():
    ctx = TrialContext()
    assert ctx.sim_records == []
    assert ctx.case_dir is None
    assert ctx.solver_label is None


def test_trial_context_carries_fields():
    ctx = TrialContext(
        sim_records=[{"kind": "run", "ok": True}],
        solver_label="openfoam",
    )
    assert ctx.sim_records == [{"kind": "run", "ok": True}]
    assert ctx.solver_label == "openfoam"
