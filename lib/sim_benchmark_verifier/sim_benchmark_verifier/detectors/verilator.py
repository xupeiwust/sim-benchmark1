"""Verilator-specific solver-stage detector + evidence check.

Same shape as ``openfoam.py`` / ``ltspice.py`` / ``comsol.py`` /
``simulink.py``.

Two responsibilities:

1. **Solver-stage detection** — scan the agent's workspace for
   Verilator artifacts and emit ``L2_solver_crash`` when nothing
   real ran.

2. **Evidence check** (anti-cheat) — ``has_solver_evidence(ctx)``
   lets ``score.py`` hard-zero analytical-shortcut trials. A
   ripple-carry adder has a trivial Verilog one-liner equivalent
   that's tempting to hand-compute (`a+b+cin`); an agent that fills
   ``result.json`` without ever invoking Verilator trips this gate.

Evidence taxonomy:
    Primary   — ``obj_dir/`` directory with at least one ``V*.cpp``
                generated C++ source > 1 KB (Verilator's signature
                output that cannot be hand-faked without running
                ``verilator --binary``). The compiled binary
                ``obj_dir/sim`` is also a strong primary.
    Secondary — ``*.vcd`` waveform dump > 256 B (if the testbench
                used ``$dumpvars``).
    Tertiary  — ``*.log`` / ``*.txt`` containing the canonical
                Verilator banner (``- V e r i l a t o r -`` or
                ``Verilator``) in the first ~32 KB. Weakest because
                text can be hand-crafted.

Stage emitted:
    ``L2_solver_crash`` — no evidence at all (agent never invoked
                          Verilator or invoked it in a way that
                          produced no output).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


_VERILATOR_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"- V e r i l a t o r -"      # canonical spaced banner verilator prints
    r"|\bVerilator\s+\d"           # "Verilator 5.020" style version line
    r"|\bverilator\s+--binary"     # command echo
    r"|\bV[a-zA-Z_][a-zA-Z0-9_]*\.cpp" # generated C++ filename pattern
    r")"
)


# ── helpers ─────────────────────────────────────────────────────────────


def _scan_for_artifacts(case_dir: Path) -> dict:
    """Walk ``case_dir`` for Verilator evidence.

    Returns a dict with:
      ``obj_dir_present``   — bool
      ``cpp_kb``            — total size in KB of all V*.cpp under obj_dir/
      ``binary_present``    — bool, obj_dir/sim or similar > 0 bytes
      ``vcd_bytes``         — int, max .vcd size
      ``banner_present``    — bool
    """
    out = {
        "obj_dir_present": False,
        "cpp_kb":          0,
        "binary_present":  False,
        "vcd_bytes":       0,
        "banner_present":  False,
    }
    if case_dir is None or not case_dir.is_dir():
        return out

    for p in case_dir.rglob("obj_dir"):
        if p.is_dir():
            out["obj_dir_present"] = True
            for cpp in p.glob("V*.cpp"):
                try:
                    out["cpp_kb"] += cpp.stat().st_size // 1024
                except OSError:
                    continue
            # Compiled binary: by convention solve.sh uses `-o sim`.
            for cand in ("sim", "Vtb", "Vtop"):
                bin_path = p / cand
                if bin_path.is_file() and bin_path.stat().st_size > 0:
                    out["binary_present"] = True
                    break

    for vcd in case_dir.rglob("*.vcd"):
        try:
            sz = vcd.stat().st_size
        except OSError:
            continue
        if sz > out["vcd_bytes"]:
            out["vcd_bytes"] = sz

    # Banner scan — read first 32 KB of each log-shaped file.
    for log in list(case_dir.rglob("*.log")) + list(case_dir.rglob("*.txt")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")[:32768]
        except OSError:
            continue
        if _VERILATOR_BANNER_RE.search(text):
            out["banner_present"] = True
            break

    return out


# ── evidence check (anti-cheat) ─────────────────────────────────────────


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff the workspace contains real Verilator artifacts."""
    if ctx.case_dir is None:
        return False
    art = _scan_for_artifacts(Path(ctx.case_dir))
    # Primary: obj_dir with a non-trivial generated .cpp OR a compiled binary
    if art["obj_dir_present"] and (art["cpp_kb"] >= 1 or art["binary_present"]):
        return True
    # Secondary: VCD waveform (uncommon for combinational MVP but allowed)
    if art["vcd_bytes"] > 256:
        return True
    # Tertiary: a log file with the Verilator banner — weakest, allowed
    if art["banner_present"]:
        return True
    return False


# ── stage detector ──────────────────────────────────────────────────────


class VerilatorDetector:
    name = "verilator"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        label = (ctx.solver_label or "").lower()
        if label == "verilator":
            return True
        # Fall back to artifact-sniff for solver=neutral cases.
        if label in ("neutral", ""):
            if ctx.case_dir is None:
                return False
            return _scan_for_artifacts(Path(ctx.case_dir))["obj_dir_present"]
        return False

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        art = _scan_for_artifacts(Path(ctx.case_dir))
        # No evidence at all → L2 (solver didn't run / silently crashed)
        if not (art["obj_dir_present"] or art["banner_present"]
                or art["vcd_bytes"] > 0):
            return "L2_solver_crash"
        # Evidence present but binary missing → likely compile failed
        if art["obj_dir_present"] and not art["binary_present"]:
            return "L2_solver_crash"
        # Otherwise defer to universal for L5/L6.
        return None


register(VerilatorDetector())
