"""Universal solver-stage detector — the cross-solver fallback layer.

Provides the 6 stages every solver shares:

  L0_input_syntax     not yet emitted (no input-parser hook here yet)
  L2_solver_crash     emitted when sim_records show all-failed runs
  L_solver_complete   not yet emitted (Phase 3b will use this for "ran
                      to end normally but didn't reach scoring criteria")
  L5_physics          value outside [physics_min, physics_max]
  L5_quantitative     in physics range, but outside the tolerance band
  L6_pass             nothing wrong on this axis

Doesn't read any artifacts; doesn't know about specific solvers.
Solver-specific detectors register before this one and contribute their
own stages on top (e.g. OpenFOAM adds L3_convergence / L4_conservation).
"""
from __future__ import annotations

from . import TrialContext, register


class UniversalDetector:
    name = "universal"
    STAGES: tuple[str, ...] = (
        "L0_input_syntax",
        "L2_solver_crash",
        "L_solver_complete",
        "L5_physics",
        "L5_quantitative",
        "L6_pass",
    )

    def applicable(self, ctx: TrialContext) -> bool:
        # Universal detector always applies — it's the fallback layer.
        return True

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        # Provenance passed → derive L5 / L6 from the verifier's own
        # per-KPI fields. These are the only stages we can emit purely
        # from the KPI scoring outcome.
        if kpi_result.get("source_verified") == 1.0:
            if kpi_result.get("kpi_score") == 1.0:
                return "L6_pass"
            if kpi_result.get("physics_pass") == 0.0:
                return "L5_physics"
            # In the physics window but outside the tolerance band: the
            # agent computed a wrong number. How wrong is carried beside
            # this as `gross_error` (|err| > gross_error_tol) rather than
            # as a second stage — one axis, one question.
            return "L5_quantitative"

        # Provenance failed → try sim_records for L2_solver_crash.
        # When every recorded sim invocation reports failure, the
        # downstream provenance failure is most likely a cascading
        # effect of the solver never having produced the expected
        # output.
        if ctx.sim_records:
            runs = [r for r in ctx.sim_records if r.get("kind", "run") == "run"]
            if runs:
                ok_runs = [
                    r for r in runs
                    if r.get("ok") is True or r.get("exit_code") == 0
                ]
                if not ok_runs:
                    return "L2_solver_crash"
        return None


register(UniversalDetector())
