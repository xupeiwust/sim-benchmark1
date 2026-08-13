"""COMSOL-specific solver-stage detector + evidence check.

Two responsibilities:

1. **Solver-stage detection** (same role as ``openfoam.py``): scan the
   agent's workspace for COMSOL artifacts and emit a stage label.

2. **Evidence check** (anti-cheat): expose ``has_solver_evidence(ctx)``
   so the grader can hard-zero analytical shortcuts. A trial that didn't
   produce **any** COMSOL artifact (no ``.mph``, no compiled ``.class``,
   no ``comsolbatch`` log) is presumed to have skipped the solver and
   returned a hand-calculated value.

Evidence taxonomy:
    Primary — ``*.mph`` files (COMSOL model archive; binary; cannot be
              hand-faked by a Bash agent without running COMSOL).
    Secondary — ``*.class`` from ``comsolcompile`` (Java bytecode).
    Tertiary — any ``*.log`` containing the canonical COMSOL banner
              ("COMSOL Multiphysics" or "comsolbatch") within the first
              few KB.

Stage emitted:
    ``L2_solver_crash`` — no evidence at all OR evidence present but
                          banner indicates a fatal error.

When evidence is clean and no L2 trigger fires, returns ``None`` — the
universal detector decides L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# COMSOL banner regexes — match the canonical signatures the solver
# writes to log files (both comsolbatch stdout/log and the .mph
# self-description). Matched anywhere in the first ~32 KB of the file.
_COMSOL_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"COMSOL\s+Multiphysics"
    r"|comsolbatch"
    r"|Build:\s*COMSOL"
    r"|Licensed\s+to:\s.+COMSOL"
    r")"
)

# Fatal-error markers. Presence of these in a COMSOL log = solver
# started but died (L2_solver_crash even when artifacts are present).
_COMSOL_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"Out\s+of\s+memory"
    r"|License\s+error"
    r"|License\s+not\s+available"
    r"|Failed\s+to\s+find\s+a\s+solution"
    r"|Could\s+not\s+find\s+a\s+solution"
    r"|Exception\s+in\s+thread\b"
    r"|java\.lang\.OutOfMemoryError"
    r"|Geometry\s+error"
    r"|Singular\s+matrix"
    r"|Failed\s+at\s+step\b"
    r")"
)


def _scan_for_artifacts(case_dir: Path) -> dict:
    """Walk ``case_dir`` looking for COMSOL evidence. Returns a dict with:

        mph_files     — list of *.mph paths
        class_files   — list of *.class paths (from comsolcompile)
        comsol_logs   — list of log/txt paths whose head contains the
                        COMSOL banner
    """
    if case_dir is None or not case_dir.is_dir():
        return {"mph_files": [], "class_files": [], "comsol_logs": []}

    mph_files: list[Path] = []
    class_files: list[Path] = []
    comsol_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        # Primary signal — any .mph is conclusive.
        if name_lower.endswith(".mph"):
            mph_files.append(p)
            continue
        # Secondary — compiled .class from comsolcompile.
        if name_lower.endswith(".class"):
            class_files.append(p)
            continue
        # Tertiary — log/txt with COMSOL banner. Skip Python tracebacks,
        # claude.log, etc. by content-sniffing the first 32 KB.
        if name_lower.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _COMSOL_BANNER_RE.search(head):
                comsol_logs.append(p)

    return {
        "mph_files":   mph_files,
        "class_files": class_files,
        "comsol_logs": comsol_logs,
    }


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence COMSOL was actually run.

    Used by ``score.py`` to hard-zero analytical shortcuts. If the agent
    hand-calculated values and wrote them to ``kpis.txt`` (passing the
    per-KPI provenance check), this still fails because no .mph or
    COMSOL log exists.
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(
        artifacts["mph_files"]
        or artifacts["class_files"]
        or artifacts["comsol_logs"]
    )


def _has_fatal_error(comsol_logs: list[Path]) -> bool:
    """Check the most-recently-modified COMSOL log for a fatal marker."""
    if not comsol_logs:
        return False
    log = max(comsol_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_COMSOL_FATAL_RE.search(text))


class ComsolDetector:
    name = "comsol"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        # Declarative: case opted in via task.toml.metadata.sim.solver.
        if ctx.solver_label == "comsol":
            return True
        # Sniff: at least one COMSOL artifact found.
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)

        # No artifacts at all → analytical-shortcut OR runner never
        # invoked the solver. Either way, COMSOL didn't run → L2.
        if not (artifacts["mph_files"] or artifacts["class_files"]
                or artifacts["comsol_logs"]):
            return "L2_solver_crash"

        # Artifacts present but log shows a fatal error → L2.
        if _has_fatal_error(artifacts["comsol_logs"]):
            return "L2_solver_crash"

        # Artifact-clean — let universal decide L5 / L6.
        return None


register(ComsolDetector())
