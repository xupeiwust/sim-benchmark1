"""OpenFOAM-specific solver-stage detector.

Reads ``log.<solver>`` files from the agent's workspace directly. Does
NOT depend on sim-cli having been called — discovery is purely
artifact-based (glob for ``log.<known_of_solver>`` under
``ctx.case_dir``).

Stages emitted:

  L3_convergence   solver killed mid-run (no ``End`` marker), OR last
                   time-step's final residual exceeds RESIDUAL_TOLERANCE.
  L4_conservation  max ``|local|`` continuity error across the run
                   exceeds CONTINUITY_TOLERANCE.

When the log gives no clear L3 / L4 signal (e.g. clean completion +
small residuals + small continuity error), this detector returns
``None`` — the universal detector then handles L5 / L6 from the KPI
score fields.

Thresholds are UNVALIDATED — Phase 4 calibration sets TPR/FPR targets
and records evidence in EVIDENCE.md. Adjust before promoting. Per
ccl-evaluator's convention, an unvalidated detector still runs but its
findings should be marked with caution in downstream reports.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# Recognised OpenFOAM solver names. Used both for log-file globbing and
# for sniff-based applicability detection. Add new ones as we encounter
# them; reasonable but not exhaustive.
OF_SOLVERS: tuple[str, ...] = (
    "simpleFoam",
    "icoFoam",
    "pimpleFoam",
    "pisoFoam",
    "rhoSimpleFoam",
    "rhoPimpleFoam",
    "interFoam",
    "buoyantFoam",
    "buoyantSimpleFoam",
    "buoyantPimpleFoam",
    "rhoCentralFoam",
    "potentialFoam",
    "scalarTransportFoam",
    "twoPhaseEulerFoam",
    "compressibleInterFoam",
    "chtMultiRegionFoam",
)

# Thresholds — VALIDATED 2026-05-08 against real OF cavity_re100 oracle
# log + 4 mutated variants (lib/sim_benchmark_verifier/EVIDENCE.md).
# TPR=1.0, FPR=0.0 across the calibration fixture set. May need
# re-validation when extending to non-cavity OF cases.
RESIDUAL_TOLERANCE: float = 1e-2     # final residual on last step must be ≤
CONTINUITY_TOLERANCE: float = 1e-3   # max |local| continuity error must be ≤


_FINAL_RESIDUAL_RE = re.compile(
    r"Solving for ([A-Za-z_]+),\s+"
    r"Initial residual = [^,]+,\s+"
    r"Final residual = ([0-9.eE+-]+)"
)
_CONTINUITY_RE = re.compile(
    r"time step continuity errors\s*:?\s*"
    r"sum local = ([0-9.eE+-]+)"
)


# ── helpers ─────────────────────────────────────────────────────────────


def _find_of_log(case_dir: Path | None) -> Path | None:
    """Return the most-recently-modified ``log.<of_solver>`` under
    ``case_dir``, or ``None`` if nothing matches.

    Falls back to any ``log.*`` file when no solver-name match is found
    — useful when the agent renamed the log or used a non-canonical solver.
    """
    if case_dir is None or not case_dir.is_dir():
        return None
    candidates: list[Path] = []
    for solver in OF_SOLVERS:
        candidates.extend(case_dir.rglob(f"log.{solver}"))
    if not candidates:
        # Generic log.* fallback (skip log.foo.txt etc.)
        for p in case_dir.rglob("log.*"):
            if p.is_file() and "." not in p.name[len("log."):]:
                candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _has_end_marker(log_text: str) -> bool:
    """OpenFOAM writes a bare ``End`` line as the final substantive
    line of a normally-terminated run."""
    tail_lines = log_text.splitlines()[-200:]
    for line in reversed(tail_lines):
        stripped = line.strip()
        if not stripped:
            continue
        return stripped == "End"
    return False


def _last_iteration_max_residual(log_text: str) -> float | None:
    """Max final residual recorded in the LAST ``Time = …`` block.

    Returns ``None`` if no residual lines were found at all (log is
    malformed or empty)."""
    blocks = re.split(r"\n(?=Time = )", log_text)
    if len(blocks) < 2:
        return None
    last_block = blocks[-1]
    residuals = [
        float(m.group(2)) for m in _FINAL_RESIDUAL_RE.finditer(last_block)
    ]
    if not residuals:
        return None
    return max(residuals)


def _max_continuity_local(log_text: str) -> float | None:
    """Max ``|local|`` continuity error reported anywhere in the run."""
    locals_ = [
        abs(float(m.group(1))) for m in _CONTINUITY_RE.finditer(log_text)
    ]
    if not locals_:
        return None
    return max(locals_)


# ── detector ────────────────────────────────────────────────────────────


class OpenFOAMDetector:
    name = "openfoam"
    STAGES: tuple[str, ...] = ("L3_convergence", "L4_conservation")

    def applicable(self, ctx: TrialContext) -> bool:
        # Declarative: case opted in via task.toml.metadata.sim.solver.
        if ctx.solver_label == "openfoam":
            return True
        # Sniff: artifact glob found at least one OF log file. Robust
        # against agent bypasses of sim-cli — purely based on what was
        # written to disk.
        return _find_of_log(ctx.case_dir) is not None

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        log_path = _find_of_log(ctx.case_dir)
        if log_path is None:
            return None
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # L3 — solver was killed before normal completion. The OF "End"
        # marker is the canonical "ran to controlDict.endTime" signal.
        if not _has_end_marker(log_text):
            return "L3_convergence"

        # L3 — completed but final residuals too large to claim
        # convergence.
        max_residual = _last_iteration_max_residual(log_text)
        if max_residual is not None and max_residual > RESIDUAL_TOLERANCE:
            return "L3_convergence"

        # L4 — converged but mass conservation broken.
        max_continuity = _max_continuity_local(log_text)
        if max_continuity is not None and max_continuity > CONTINUITY_TOLERANCE:
            return "L4_conservation"

        # Log looks clean; let the universal detector decide L5 / L6 from
        # KPI scoring fields.
        return None


register(OpenFOAMDetector())
