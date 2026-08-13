"""OpenROAD / ORFS-specific solver-stage detector + evidence check.

Mirrors ``calculix.py``. Two responsibilities:

1. **Solver-stage detection**: scan the agent's workspace for RTL→GDS flow
   output artifacts and emit a stage label.

2. **Evidence check** (anti-cheat): expose ``has_solver_evidence(ctx)`` so the
   grader can hard-zero reported PPA numbers (Fmax / area / power) that were
   never actually produced by a flow run. An agent can quote a plausible
   frequency or a "WNS = 0" from memory; this gate forces a real
   OpenROAD/ORFS run that leaves a layout + reports on disk.

Evidence taxonomy (flow **outputs**, not the ``.v`` / ``.sdc`` inputs — those
are writable without ever running synthesis or P&R):
    Primary   — a non-empty final layout: ``*.gds`` (esp. ``*6_final.gds``) or
                ``*.def`` (placed+routed), > 1 KiB.
    Secondary — OpenROAD reports ``*.rpt`` (STA / DRC / power) and any
                ``*.log`` carrying the OpenROAD banner within the first ~32 KiB.

Stage emitted:
    ``L2_solver_crash`` — no flow output at all, OR a log present with a fatal
                          marker (``[ERROR``, "Fatal", routing failed, …).
When evidence is clean, returns ``None`` — the universal detector decides
L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# OpenROAD / ORFS banner — what the flow writes to stdout / captured logs.
_OPENROAD_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"OpenROAD\s+v?\d"
    r"|This\s+is\s+OpenROAD"
    r"|Starting\s+\"?(?:floorplan|placement|routing|cts|detailed_route)"
    r"|\[INFO\s+(?:ORD|FLW|RSZ|GRT|DRT|STA)"
    r"|OpenROAD-flow-scripts"
    r")"
)

# Fatal-error markers — flow started but died (L2 even if a stub file exists).
_OPENROAD_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"\[ERROR"
    r"|\bfatal\b"
    r"|cannot\s+open"
    r"|no\s+liberty"
    r"|routing\s+(?:failed|congestion\s+unrecoverable)"
    r"|placement\s+failed"
    r"|unable\s+to\s+route"
    r"|design\s+is\s+not\s+legal"
    r"|out\s+of\s+memory"
    r")"
)

_GDS_MIN_BYTES = 1024  # a 0-byte / touched .gds is not evidence


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    """Walk ``case_dir`` for OpenROAD/ORFS evidence. Returns a dict with:

        gds_files  — list of non-empty *.gds layout paths (> 1 KiB)
        def_files  — list of *.def placed+routed paths
        rpt_files  — list of *.rpt report paths (STA / DRC / power)
        or_logs    — list of log/txt/out paths whose head has the OpenROAD banner
    """
    if case_dir is None or not case_dir.is_dir():
        return {"gds_files": [], "def_files": [], "rpt_files": [], "or_logs": []}

    gds_files: list[Path] = []
    def_files: list[Path] = []
    rpt_files: list[Path] = []
    or_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.endswith(".gds") or name_lower.endswith(".gds2"):
            try:
                if p.stat().st_size >= _GDS_MIN_BYTES:
                    gds_files.append(p)
            except OSError:
                pass
            continue
        if name_lower.endswith(".def"):
            def_files.append(p)
            continue
        if name_lower.endswith(".rpt"):
            rpt_files.append(p)
            continue
        if name_lower.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _OPENROAD_BANNER_RE.search(head):
                or_logs.append(p)

    return {
        "gds_files": gds_files,
        "def_files": def_files,
        "rpt_files": rpt_files,
        "or_logs":   or_logs,
    }


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence an OpenROAD/ORFS flow was run.

    A non-empty ``*.gds`` / ``*.def`` layout, an OpenROAD ``*.rpt`` report, or an
    OpenROAD-banner log must exist — the ``.v`` netlist and ``.sdc`` constraints
    alone are not evidence (they are inputs, writable without running the flow).
    """
    if ctx.case_dir is None:
        return False
    a = _scan_for_artifacts(ctx.case_dir)
    return bool(a["gds_files"] or a["def_files"] or a["rpt_files"] or a["or_logs"])


def _has_fatal_error(or_logs: list[Path]) -> bool:
    """Check the most-recently-modified OpenROAD log for a fatal marker."""
    if not or_logs:
        return False
    log = max(or_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_OPENROAD_FATAL_RE.search(text))


class OpenroadDetector:
    name = "openroad"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "openroad":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        a = _scan_for_artifacts(ctx.case_dir)

        # No flow output at all → synthesis/P&R never ran → L2.
        if not (a["gds_files"] or a["def_files"] or a["rpt_files"] or a["or_logs"]):
            return "L2_solver_crash"

        # Output present but log shows a fatal error → L2.
        if _has_fatal_error(a["or_logs"]):
            return "L2_solver_crash"

        # Clean — let universal decide L5 / L6.
        return None


register(OpenroadDetector())
