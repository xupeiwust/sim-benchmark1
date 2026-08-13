"""Cantera-specific solver-stage detector + evidence check.

Cantera shares MuJoCo's structural problem — it is a library, not a batch
executable, so a run leaves no ``polyMesh``/``.frd``/``.raw`` behind unless
the driver script writes one. But unlike MuJoCo, Cantera cases here are
**not** limited to the weak "a numeric file exists" gate, because the
evaluator (``native_cantera``) re-executes the submission's own driver in a
clean directory and then checks two *content* properties of the regenerated
output:

  * it starts at the specified initial thermodynamic state, and
  * its burned/final temperature lands on the independently-computed
    chemical-equilibrium state for that same mixture.

The second of those two is no longer a gate and no longer a credential: #125
measured that the equilibrium comparison reads a trace the evaluator itself
re-ran, and it had been scoring correct submissions zero. What actually
defends the track is the strip-and-re-run — a hand-written CSV never reaches a
physics check — plus the off-catalog operating point, which is where CLAUDE.md
puts the defence against recall.

**This detector is not on the live path at all.** Its ``has_solver_evidence``
is reached only through ``score.py``, which no ``cases/combustion/**`` case
calls; every one of them runs ``native_cantera`` directly (#196). Read what
follows as the format knowledge the detector encodes, not as a gate that
fires.

Evidence accepted:
    Primary   — a state dump the integrator can only produce by solving:
                a multi-row numeric CSV/DAT/TSV (≥3 numeric rows, ≥2
                numeric columns).
    Secondary — a log/text file carrying a Cantera banner or a
                CanteraError traceback frame.

NOT evidence: the mechanism file (``*.yaml`` / ``*.cti`` / ``*.xml``) or the
driver script (``*.py``) — both are input, writable without ever calling the
integrator (same reasoning as CalculiX ``.inp`` and MuJoCo's MJCF).

Stage emitted:
    ``L2_solver_crash`` — no numeric state dump at all, OR a log showing a
                          Cantera fatal error / failed convergence.
Clean runs return ``None`` so the universal detector decides L5 / L6.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


_CANTERA_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"\bcantera\b"
    r"|ct\.Solution|IdealGasReactor|ReactorNet|FreeFlame"
    r"|set_equivalence_ratio"
    r")"
)

_CANTERA_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"CanteraError"
    r"|Flow1D::|ChemEquil::.*(?:failed|no convergence)"
    r"|ReactorNet::advance.*fail"
    r"|CVodes?\s+error|CV_(?:CONV|ERR)_FAILURE"
    r"|did not converge|solution failed"
    r"|unknown species"
    r")"
)


def _looks_like_state_dump(path: Path) -> bool:
    """True if a text file reads as a numeric state table: ≥3 rows carrying
    ≥2 numeric tokens each (header row tolerated). Head-only scan.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            rows = [fh.readline() for _ in range(64)]
    except OSError:
        return False

    num_tok = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
    numeric_rows = 0
    for line in rows:
        if not line:
            break
        toks = re.split(r"[,\s;\t]+", line.strip())
        nums = [t for t in toks if t and num_tok.fullmatch(t)]
        if len(nums) >= 2:
            numeric_rows += 1
    return numeric_rows >= 3


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    if case_dir is None or not case_dir.is_dir():
        return {"state_dumps": [], "ct_logs": []}

    state_dumps: list[Path] = []
    ct_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith((".csv", ".dat", ".tsv")):
            if _looks_like_state_dump(p):
                state_dumps.append(p)
            continue
        if name.endswith((".h5", ".hdf5")):
            # Cantera's SolutionArray.save() target; binary, trust the suffix.
            state_dumps.append(p)
            continue
        if name.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _CANTERA_BANNER_RE.search(head):
                ct_logs.append(p)

    return {"state_dumps": state_dumps, "ct_logs": ct_logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """True iff there is artifact evidence the integrator actually ran.

    A mechanism YAML or a driver ``.py`` alone is NOT evidence — those are
    inputs. The authoritative check for native Cantera cases is the
    equilibrium-consistency gate in ``native_cantera``; this is the coarse
    filter for the generic scoring path.
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(artifacts["state_dumps"] or artifacts["ct_logs"])


def _has_fatal_error(ct_logs: list[Path]) -> bool:
    if not ct_logs:
        return False
    log = max(ct_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_CANTERA_FATAL_RE.search(text))


class CanteraDetector:
    name = "cantera"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "cantera":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)
        if not (artifacts["state_dumps"] or artifacts["ct_logs"]):
            return "L2_solver_crash"
        if _has_fatal_error(artifacts["ct_logs"]):
            return "L2_solver_crash"
        return None


register(CanteraDetector())
