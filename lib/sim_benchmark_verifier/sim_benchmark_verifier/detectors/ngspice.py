"""ngspice-specific solver-stage detector + evidence check.

Mirrors ``ltspice.py`` / ``calculix.py``. ngspice is the open-source SPICE
engine on the eda-analog track. Evidence that ngspice actually ran:

    Primary   — a SPICE ``*.raw`` rawfile. Even binary rawfiles begin with an
                ASCII header ("Title:", "Plotname:", "No. Variables:") that a
                Bash agent can't fabricate without running a simulator.
    Secondary — a ``*.log`` / ``*.out`` / ``*.txt`` whose head carries the
                ngspice banner or a SPICE run signature ("ngspice",
                "Circuit:", ".control", "Total analysis time").

Stage emitted:
    ``L2_solver_crash`` — no rawfile and no ngspice log, OR a log with a
                          fatal marker.
Clean evidence → ``None`` (universal detector decides L5 / L6).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# A genuine SPICE rawfile header (works for binary and ascii raw).
_RAW_HEADER_RE = re.compile(r"(?i)(?:Plotname:|No\.\s*Variables:|Title:.*\n.*Date:)")

# ngspice run signature in a captured log / stdout.
_NGSPICE_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"ngspice"
    r"|Circuit:\s"
    r"|Total\s+analysis\s+time"
    r"|Doing\s+analysis\b"
    r")"
)

# Fatal-error markers — solver started but died.
_NGSPICE_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"fatal\s+error"
    r"|singular\s+matrix"
    r"|Timestep\s+too\s+small"
    r"|no\s+such\s+(?:vector|parameter)"
    r"|simulation\s+(?:aborted|interrupted)"
    r"|can't\s+find\s+init"
    r")"
)


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    """Walk ``case_dir`` for ngspice evidence: SPICE rawfiles + ngspice logs."""
    if case_dir is None or not case_dir.is_dir():
        return {"raw_files": [], "ng_logs": []}

    raw_files: list[Path] = []
    ng_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.endswith(".raw"):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:4096]
            except OSError:
                continue
            if _RAW_HEADER_RE.search(head):
                raw_files.append(p)
            continue
        if name_lower.endswith((".log", ".out", ".txt", ".lis")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _NGSPICE_BANNER_RE.search(head):
                ng_logs.append(p)

    return {"raw_files": raw_files, "ng_logs": ng_logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence ngspice was actually run."""
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(artifacts["raw_files"] or artifacts["ng_logs"])


def _has_fatal_error(ng_logs: list[Path]) -> bool:
    if not ng_logs:
        return False
    log = max(ng_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_NGSPICE_FATAL_RE.search(text))


class NgspiceDetector:
    name = "ngspice"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "ngspice":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)
        if not (artifacts["raw_files"] or artifacts["ng_logs"]):
            return "L2_solver_crash"
        if _has_fatal_error(artifacts["ng_logs"]):
            return "L2_solver_crash"
        return None


register(NgspiceDetector())
