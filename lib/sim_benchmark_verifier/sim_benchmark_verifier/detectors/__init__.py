"""Plugin detector framework for solver-stage classification.

Per RFC sim-proj#125 amendment. Each detector contributes stages from
its own ``STAGES`` set; the union of all registered detectors' stages
forms the open ``solver_stage`` enum. Detectors are dispatched in
registration order; first non-``None`` stage wins.

Conventions:
- Solver-specific detectors register **before** ``universal`` so they
  get first crack at attributing solver-specific failures (L3 / L4 /
  domain stages). The universal detector is the fallback layer for
  L0 / L2 / L5 / L6.
- Each detector reads artifacts directly (``log.<solver>``, ``*.cas``,
  …); it must NOT depend on sim-cli having been called. ``sim_records``
  is a corroborating signal, not a primary one.
- Detectors are pure: same input → same output. No LLM judgment in
  this layer (per ccl-evaluator pattern, soft judgment lives in a
  separate optional skill, sim-proj#125 phase 5).

Adding a new solver:
    1. Drop a file in ``detectors/<solver>.py``
    2. Define a class with ``name`` / ``STAGES`` / ``applicable`` /
       ``detect``
    3. Call ``register(MyDetector())`` at module bottom
    4. Add ``from . import <solver>`` at the bottom of this file
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class TrialContext:
    """Aggregates everything detectors might need to inspect a trial.

    Built by the verifier at scoring time. Detectors should treat it as
    read-only.
    """
    sim_records: list[dict] = field(default_factory=list)
    case_dir: Path | None = None        # workspace where agent left artifacts
    solver_label: str | None = None     # task.toml.metadata.sim.solver


@runtime_checkable
class SolverStageDetector(Protocol):
    """Pluggable detector for solver-stage classification."""

    name: str
    STAGES: tuple[str, ...]

    def applicable(self, ctx: TrialContext) -> bool:
        """Return True iff this detector should run on this trial."""
        ...

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        """Return one of ``self.STAGES`` (or ``None`` if can't attribute)."""
        ...


# ── Registry ─────────────────────────────────────────────────────────────

_REGISTRY: list[SolverStageDetector] = []


def register(detector: SolverStageDetector) -> None:
    """Register a detector. Earlier registrations get higher dispatch
    priority — solver-specific detectors should register before the
    universal fallback.
    """
    _REGISTRY.append(detector)


def registered() -> tuple[SolverStageDetector, ...]:
    """Snapshot of the registry — primarily for tests."""
    return tuple(_REGISTRY)


def all_known_stages() -> set[str]:
    """Union of every registered detector's STAGES. The full open enum
    at runtime — count-dict initialisers + leaderboard tooling read this.
    """
    stages: set[str] = set()
    for d in _REGISTRY:
        stages.update(d.STAGES)
    return stages


def dispatch(kpi_result: dict, ctx: TrialContext) -> str | None:
    """Run applicable detectors in registration order; return the first
    non-``None`` stage. Returns ``None`` when nothing attributed.
    """
    for d in _REGISTRY:
        if not d.applicable(ctx):
            continue
        stage = d.detect(kpi_result, ctx)
        if stage is not None:
            return stage
    return None


# ── Auto-register builtin detectors ──────────────────────────────────────
# Solver-specific detectors first (so they get first crack at attributing),
# universal detector last (fallback for L0/L2/L5/L6).
from . import openfoam   # noqa: F401, E402
from . import universal  # noqa: F401, E402
