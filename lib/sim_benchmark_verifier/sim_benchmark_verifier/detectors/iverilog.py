"""Icarus Verilog (iverilog/vvp) solver-stage detector + evidence check.

Mirrors ``calculix.py``. The digital side of a mixed-signal co-sim case.

Evidence taxonomy (Icarus **outputs**, not the ``.v`` source — Verilog can
be written without ever simulating):
    Primary   — ``*.vcd`` (value-change dump: the canonical waveform output
                of a run, via ``$dumpvars``) and ``*.vvp`` (the compiled
                simulation object ``iverilog`` emits).
    Secondary — any ``*.log`` / ``*.txt`` carrying the Icarus banner
                (``VCD info`` / ``iverilog`` / ``$finish``).

Stage emitted:
    ``L2_solver_crash`` — no simulation artifact at all, OR a log with a
                          fatal Verilog/elaboration error.
When evidence is clean, returns ``None`` — the universal detector decides
L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# Icarus-SPECIFIC banner only. Loose tokens (bare "vvp" / "finish") collide
# with other tools' logs (e.g. ngspice's sim.log) and would let an analog-only
# run masquerade as a digital one — keep this tight.
_IVERILOG_BANNER_RE = re.compile(
    r"(?:VCD\s+info:|Icarus\s+Verilog|iverilog\s+version|vvp\s+\(Icarus)"
)
_IVERILOG_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"error:|syntax\s+error|cannot\s+open|elaboration\s+fail"
    r"|unable\s+to\s+(?:bind|elaborate)|giving\s+up"
    r")"
)


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    if case_dir is None or not case_dir.is_dir():
        return {"vcd": [], "vvp": [], "logs": []}
    vcd: list[Path] = []
    vvp: list[Path] = []
    logs: list[Path] = []
    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith(".vcd"):
            vcd.append(p)
        elif name.endswith(".vvp"):
            vvp.append(p)
        elif name.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _IVERILOG_BANNER_RE.search(head):
                logs.append(p)
    return {"vcd": vcd, "vvp": vvp, "logs": logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """True iff there's artifact evidence Icarus actually simulated — a
    ``.vcd`` waveform dump, a compiled ``.vvp``, or an Icarus-banner log.
    A bare ``.v`` source is not evidence (input, writable without running).
    Evidence is the concrete Icarus output (``.vcd``/``.vvp``); a banner log
    alone is intentionally NOT sufficient here — loose log tokens collide
    with other tools' logs and would let an analog-only run fake the digital
    half of a mixed-signal chain.
    """
    if ctx.case_dir is None:
        return False
    a = _scan_for_artifacts(ctx.case_dir)
    return bool(a["vcd"] or a["vvp"])


def _has_fatal_error(logs: list[Path]) -> bool:
    if not logs:
        return False
    log = max(logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_IVERILOG_FATAL_RE.search(text))


class IcarusDetector:
    name = "iverilog"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label is not None and "iverilog" in ctx.solver_label:
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        a = _scan_for_artifacts(ctx.case_dir)
        if not (a["vcd"] or a["vvp"] or a["logs"]):
            return "L2_solver_crash"
        if _has_fatal_error(a["logs"]):
            return "L2_solver_crash"
        return None


register(IcarusDetector())
