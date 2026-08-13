"""PyBaMM-specific solver-stage detector + evidence check.

PyBaMM has the same structural problem as Cantera and MuJoCo — it is a
library, not a batch executable, so a run leaves no ``polyMesh``/``.frd``/
``.raw`` behind unless the driver script writes one. And as with Cantera, the
weak "a numeric file exists" gate is *not* what backs these cases: the
evaluator (``native_pybamm``) re-executes the submission's own driver in a
clean directory and then checks two *content* properties of the regenerated
trace:

  * it starts from the specified initial state of charge — the terminal
    voltage at t=0 must sit on the open-circuit voltage the evaluator
    independently computes from the declared parameter set, and
  * it is thermodynamically admissible throughout — the loaded terminal
    voltage must lie on the dissipative side of the evaluator's own OCV
    curve, i.e. below OCV while discharging and above it while charging,
    by an amount bounded by a physically plausible overpotential.

Neither of those is what stops a hand-written CSV, and this docstring used to
say it was (#196, the same false claim `native_cantera` carried until #125).
A shipped CSV dies in the strip-and-re-run before any physics check sees it.
What the two content checks catch is the *other* forgery — a `run_case.py`
that fabricates a trace instead of solving — and that one they do catch:
measured on a capacity KPI, a trace with the right current schedule and a
constant voltage lands inside its tolerance band and is zeroed by the
dissipation-sign test alone.

**This detector is not on the live path at all.** Its `has_solver_evidence` is
reached only through `score.py`, which no `cases/battery/**` case calls; every
one of them runs `native_pybamm` directly. Read what follows as the format
knowledge the detector encodes, not as a gate that fires.

Evidence accepted:
    Primary   — a state dump the integrator can only produce by solving:
                a multi-row numeric CSV/DAT/TSV (>= 3 numeric rows, >= 2
                numeric columns).
    Secondary — a log/text file carrying a PyBaMM banner or a PyBaMM
                solver-error traceback frame.

NOT evidence: the driver script (``*.py``) or a parameter/drive-cycle input
file (``*.json`` / an input ``*.csv`` the case shipped) — both are input,
writable without ever calling the solver (same reasoning as CalculiX ``.inp``
and MuJoCo's MJCF).

Stage emitted:
    ``L2_solver_crash`` — no numeric state dump at all, OR a log showing a
                          PyBaMM fatal error / failed convergence.
Clean runs return ``None`` so the universal detector decides L5 / L6.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


_PYBAMM_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"\bpybamm\b"
    r"|lithium_ion\.(?:DFN|SPMe?|MPM)"
    r"|ParameterValues|pybamm\.Simulation|pybamm\.Experiment"
    r"|Terminal voltage \[V\]"
    r")"
)

_PYBAMM_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"pybamm\.\w*(?:Solver|Model|Geometry|Option)Error"
    r"|SolverError"
    r"|IDA(?:S)?\s+error|IDA_(?:CONV|ERR|LINESEARCH)_FAIL"
    r"|CasADi.*(?:failure|error)"
    r"|maximum number of (?:steps|iterations)"
    r"|could not find consistent initial conditions"
    r"|did not converge|solver failed"
    r"|event.*terminated.*at t = 0"
    r")"
)


def _looks_like_state_dump(path: Path) -> bool:
    """True if a text file reads as a numeric state table: >= 3 rows carrying
    >= 2 numeric tokens each (header row tolerated). Head-only scan.
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
        return {"state_dumps": [], "pb_logs": []}

    state_dumps: list[Path] = []
    pb_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith((".csv", ".dat", ".tsv")):
            if _looks_like_state_dump(p):
                state_dumps.append(p)
            continue
        if name.endswith((".h5", ".hdf5", ".nc")):
            # pybamm.Solution.save() / xarray dumps; binary, trust the suffix.
            state_dumps.append(p)
            continue
        if name.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _PYBAMM_BANNER_RE.search(head):
                pb_logs.append(p)

    return {"state_dumps": state_dumps, "pb_logs": pb_logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """True iff there is artifact evidence the cell model actually ran.

    A driver ``.py`` or a shipped drive-cycle input alone is NOT evidence —
    those are inputs. The authoritative check for native PyBaMM cases is the
    OCV-consistency gate in ``native_pybamm``; this is the coarse filter for
    the generic scoring path.
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(artifacts["state_dumps"] or artifacts["pb_logs"])


def _has_fatal_error(pb_logs: list[Path]) -> bool:
    if not pb_logs:
        return False
    log = max(pb_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_PYBAMM_FATAL_RE.search(text))


class PyBaMMDetector:
    name = "pybamm"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "pybamm":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)
        if not (artifacts["state_dumps"] or artifacts["pb_logs"]):
            return "L2_solver_crash"
        if _has_fatal_error(artifacts["pb_logs"]):
            return "L2_solver_crash"
        return None


register(PyBaMMDetector())
