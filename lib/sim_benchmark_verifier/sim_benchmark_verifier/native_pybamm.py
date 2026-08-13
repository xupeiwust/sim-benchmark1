"""Evaluator-owned reproduction + scoring for native PyBaMM submissions.

Structurally this is ``native_cantera``'s sibling — the evaluator re-derives
every number from its own re-execution of the submission and never from what
the agent claims — but the "did a real solve happen" evidence has to be built
differently, because a lithium-ion cell has no equilibrium end state to land
on. A cell discharged to its cut-off voltage is not at rest; it is at a
*loaded* operating point whose voltage depends on the whole transport
solution.

What replaces the equilibrium gate is the **OCV envelope**:

  * The evaluator computes, from the declared parameter set *alone* and
    without solving any cell model, the open-circuit voltage as a function of
    state of charge — the electrode stoichiometry limits give the SOC window,
    and the two half-cell OCP functions give the voltage at each point in it.
  * It then coulomb-counts the reproduced current column to get SOC at every
    sample, and evaluates OCV there.
  * Two properties must hold of the residual ``V - OCV(soc)``:

      **sign** — the cell must dissipate, never generate. Under discharge the
      terminal voltage sits *below* OCV, under charge *above* it. A trace that
      violates this is claiming free energy.

      **magnitude** — the residual is the total overpotential, and it is
      bounded. A trace whose voltage wanders far from the OCV curve is not a
      solution of this cell at this rate, whatever its endpoints look like.

This paragraph used to end *"not something a hand-written CSV can fake ...
which is what makes this a real anti-cheat gate rather than a file-existence
check"*, and that sentence was the same false claim `native_cantera` carried
about its equilibrium check (#125). A hand-written CSV never reaches the OCV
envelope: the submission is copied into a clean directory with every numeric
artifact stripped and its driver re-executed, so the trace this check reads is
one the *evaluator* produced. Against a shipped file its contribution is zero,
and it is the strip list plus the re-run — not this check — that defends the
track there.

What the envelope does defend against is the other forgery, and that one is
real: **a driver that fabricates instead of solving.** `run_case.py` is
arbitrary Python, so a driver whose whole body writes a plausible CSV
reproduces cleanly and produces an artifact. Measured on
`lgm50_nmc811_discharge_0p87c_296k` (#196): the `flat_voltage` control — right
current schedule, voltage replaced by its own mean — leaves
`discharge_capacity_Ah` **inside its tolerance band**, because that KPI only
integrates current. `kpi_accuracy` scores it 1.0. The sign test is what zeroes
it. So the check is admissible under CLAUDE.md's rule for assertions, and the
honest name for what it catches is a fabricating driver, not a hand-written
file.

That verdict is not uniform across the three tests, which is why #196 left the
dimension intact and opened the split as #212: the **magnitude** bound is
calibrated per case from the oracle's own residual, and `ocv_max_deviation_V`
is therefore the one test that can — and on `lgm50_thermal_rise_1p08c_298k`
does — reject a correct submission for choosing a particle mesh the
instruction never constrained (`cases/battery/README.md`). In the stored
trials its whole observed effect is 36 rejections the tolerance band had
already zeroed plus 11 correct submissions scored 0.0.

The two deliberate departures from the OpenFOAM evaluators that
``native_cantera`` documents apply here unchanged: dimensions are recorded
independently and never short-circuit, and a case supplies only a spec plus
an extractor while lifecycle, gating, scoring math and reward I/O are shared.

Scoring math is imported from ``score`` so there is exactly one
implementation of the tolerance band and the physics-range gate.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .reproduction import (
    DRIVER_MISSING,
    RESULTS_MISSING,
    ReproductionFailed,
    run_driver,
)
from .score import _physics_pass, band_score, gross_error_tol, pass_tol

# Relative paths inside a submission. Solver-neutral names on purpose: the
# instruction states them as "write your results here", not as PyBaMM API.
DRIVER_NAME = "run_case.py"
RESULTS_NAME = "results.csv"
FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".svg")

DIMENSIONS = (
    "artifact_produced",
    "figure_produced",
    "clean_reproduction",
    "initial_state_valid",
    "ocv_consistent",
    "extraction_succeeded",
    "kpi_accuracy",
)

# The dimensions that are prerequisites of measurement; see `native_cantera`.
# `ocv_consistent` is here and `equilibrium_consistent` is not, and that is a
# claim about the two checks rather than about the two tracks: a cell trace
# whose voltage does not track the open-circuit curve is not a solution of this
# cell, so there is nothing to measure.
#
# #196 measured that claim and it holds for two of the three tests this
# dimension bundles, not for the third. Sign and shape earn the gate: on a
# capacity KPI the `flat_voltage` control lands INSIDE the tolerance band and
# only the sign test zeroes it. The magnitude bound (`ocv_max_deviation_V`,
# calibrated per case from the oracle's own residual) does not: it is the test
# that rejects `lgm50_thermal_rise_1p08c_298k`'s correct default-mesh answer,
# and across the stored trials it never rejected anything the band had not
# already zeroed. Splitting it out changes scores, so it is #212, not this
# commit — the dimension stays whole here.
GATES = (
    "artifact_produced",
    "clean_reproduction",
    "initial_state_valid",
    "ocv_consistent",
    "extraction_succeeded",
)


@dataclass
class Dimension:
    """One independently-recorded check."""

    status: str = "not_attempted"  # pass | fail | not_attempted
    score: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
    why: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "score": round(self.score, 6)}
        if self.why:
            out["why"] = self.why
        if self.detail:
            out.update(self.detail)
        return out


def ocv_statistics(soc, ocv, resid, current, keep, spec) -> dict[str, Any]:
    """The numbers the open-circuit-voltage gate decides on, as a pure function.

    Lifted out of the closure so it can be tested by running it rather than by
    re-running a whole battery simulation -- the same move `faffbf8c` made for
    the equilibrium check, and for the same reason: a gate nobody can call is a
    gate nobody tests, and this one rejected every model on a case while every
    model got its KPI right.

    `keep` marks the samples inside the reference curve's valid span. The sign
    and magnitude tests then run on a narrower window still, because the
    reference is indexed by coulomb-counted AVERAGE state of charge while
    terminal voltage is set by SURFACE concentration: in the end-of-discharge
    knee those diverge and the curve is near-vertical, so a fraction of a
    percent of misalignment reads as hundreds of millivolts the cell never
    developed.
    """
    import numpy as np

    window = keep & (soc >= spec.ocv_sign_min_soc) & (soc <= spec.ocv_sign_max_soc)
    loaded = window & (np.abs(current) > spec.ocv_min_current_A)
    admissible = window if window.any() else keep

    sign_excess = 0.0
    if loaded.any():
        sign_excess = float(np.max(resid[loaded] * np.sign(current[loaded])))
    # Against the open-circuit curve, not against state of charge: the check is
    # "does the terminal voltage carry information beyond a constant", and the
    # curve is what it should be tracking.
    shape_corr = 0.0
    if np.std(resid[keep]) > 1e-12 and np.std(ocv[keep]) > 1e-12:
        shape_corr = float(np.corrcoef(resid[keep], ocv[keep])[0, 1])
    return {
        "n_samples_checked": int(keep.sum()),
        "soc_range": [float(soc[keep].min()), float(soc[keep].max())],
        "max_dissipation_violation_V": sign_excess,
        "sign_tolerance_V": spec.ocv_sign_tol_V,
        "n_samples_sign_checked": int(loaded.sum()),
        "sign_soc_window": [spec.ocv_sign_min_soc, spec.ocv_sign_max_soc],
        "max_abs_overpotential_V": float(np.max(np.abs(resid[admissible]))),
        "max_abs_overpotential_full_trace_V": float(np.max(np.abs(resid[keep]))),
        "admissibility_soc_window": [spec.ocv_sign_min_soc, spec.ocv_sign_max_soc],
        "n_samples_admissibility_checked": int(admissible.sum()),
        "max_deviation_tolerance_V": spec.ocv_max_deviation_V,
        "rms_overpotential_V": float(np.sqrt(np.mean(resid[keep] ** 2))),
        "residual_ocv_correlation": shape_corr,
        "shape_min_correlation": spec.ocv_shape_min_corr,
    }


class CheckFailed(RuntimeError):
    """A check that failed and knows why in numbers, not just in prose.

    A gate that raises loses everything it measured on the way, so the one
    record that could show whether the threshold or the submission was at fault
    keeps only a sentence. The battery OCV gate rejected all five models on one
    case while every one of them got the KPI right, and the stored evidence for
    that was a string -- diagnosing it needed the whole run repeating by hand.
    """

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.detail = detail


class Recorder:
    """Collects dimensions; each check runs isolated so later ones still run."""

    def __init__(self) -> None:
        self.dims: dict[str, Dimension] = {name: Dimension() for name in DIMENSIONS}

    def run(self, name: str, fn: Callable[[], tuple[float, dict[str, Any]]]) -> Any:
        dim = self.dims[name]
        try:
            score, detail = fn()
            dim.score = float(score)
            dim.status = "pass" if score > 0 else "fail"
            dim.detail = detail
            return detail
        except Exception as exc:  # noqa: BLE001 - per-dimension isolation is the point
            dim.status = "fail"
            dim.score = 0.0
            dim.why = f"{type(exc).__name__}: {exc}"
            # Keep whatever the check had measured before it gave up.
            dim.detail = {"traceback": traceback.format_exc(limit=3),
                          **getattr(exc, "detail", {})}
            return None


    def as_dict(self) -> dict[str, Any]:
        return {name: dim.as_dict() for name, dim in self.dims.items()}


# ── spec ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PyBaMMSpec:
    """Physics the submission must reproduce. Solver-agnostic values only."""

    case_id: str
    kind: str  # discharge | thermal | pulse | cccv | cycling | rate_capability
    parameter_set: str
    initial_soc: float
    # Structural gate: the trace must start at the declared state of charge.
    # The window is wide because a case that begins under load starts one
    # instantaneous IR drop below OCV; it still pins the trace to the right
    # OCV curve, which is the point.
    initial_V_tol_V: float = 0.5
    # OCV-envelope gate.
    ocv_check: bool = True
    # Dissipation tolerance. Non-zero because the reference curve is evaluated
    # at the parameter set's reference temperature while the cell runs at its
    # own; the resulting offset is tens of millivolts and must not be read as a
    # thermodynamic violation.
    ocv_sign_tol_V: float = 0.05
    # SOC window in which the *sign* test is applied. Narrower than the window
    # the magnitude test uses, and deliberately so: the reference curve is
    # indexed by coulomb-counted *average* SOC, while terminal voltage is set
    # by *surface* concentration. Near either end of the window those diverge —
    # at the bottom of a deep discharge the surface is far more depleted than
    # the average, so a perfectly ordinary charge step that begins there reads
    # 116 mV on the "generating" side of an average-SOC reference. That is
    # concentration polarisation, not free energy. Between these bounds the OCV
    # curve is gentle enough that the average-SOC reference holds, which is
    # where the sign test has its discriminating power anyway.
    ocv_sign_min_soc: float = 0.15
    ocv_sign_max_soc: float = 0.95
    # Maximum admissible overpotential, calibrated per case from the oracle's
    # own measured residual. Rate-dependent, hence not a global constant.
    ocv_max_deviation_V: float = 0.6
    # Samples below this SOC are excluded from the envelope: at the end of
    # discharge the knee makes the overpotential diverge, which is real physics
    # rather than evidence of a bad trace.
    ocv_min_soc: float = 0.05
    # Rest samples carry no dissipation direction, so the sign test is only
    # applied where the current is meaningfully non-zero.
    ocv_min_current_A: float = 1e-3
    # Shape test. If the residual is perfectly anti-correlated with the
    # reference curve, the terminal voltage carries no information beyond a
    # constant: residual = c - OCV(soc) is exactly what a fabricated flat
    # voltage column produces, and it scores corr = -1.000 on every case
    # measured. Real runs span -0.77 to +0.92, so -0.95 separates them with
    # room to spare. This is the check that catches a faked voltage on a KPI
    # that only integrates current (a capacity), where nothing else would:
    # the sign and magnitude tests can both be satisfied by a constant that
    # happens to sit inside the envelope.
    ocv_shape_min_corr: float = -0.95
    reproduction_timeout_s: int = 900
    # Declared derivations, for `kind = "declared"`. Maps a KPI name onto a
    # `csv_interface` derivation spec, so a case whose KPI is not one of the six
    # hard-coded extractors below is a data edit rather than a new function
    # here. Every extractor above answers one fixed question about a
    # discharge trace; a task whose answer is a quantity the *submission*
    # searched for -- a limit, a window edge, a design delta -- has no fixed
    # question, and adding one Python function per such task is how an
    # evaluator becomes a program instead of a contract.
    derivations: dict[str, Any] = field(default_factory=dict)


# ── evaluator-owned OCV curve (no cell model solved) ─────────────────────


def _ocv_curve(spec: PyBaMMSpec, n: int = 401) -> dict[str, Any]:
    """OCV(soc) and the SOC-window capacity, from the parameter set alone.

    Both electrodes' stoichiometry moves linearly with SOC between the limits
    the parameter set implies, so the whole curve follows from the two limit
    pairs plus the two half-cell OCP functions. Nothing here depends on which
    cell model the submission chose, which is what makes it an independent
    check rather than a restatement of the submission's own output.
    """
    import numpy as np
    import pybamm

    param = pybamm.ParameterValues(spec.parameter_set)
    x0, x100, y100, y0 = pybamm.lithium_ion.get_min_max_stoichiometries(param)
    socs = np.linspace(0.0, 1.0, n)
    xs = np.asarray(x0 + socs * (x100 - x0), dtype=float)
    ys = np.asarray(y0 + socs * (y100 - y0), dtype=float)

    def _eval(fn, sto):
        # Some parameter sets define an OCP in closed form over a pybamm
        # symbol; others as an Interpolant over published half-cell data. The
        # vector form serves the interpolants, the scalar loop the rest.
        try:
            out = param.evaluate(fn(pybamm.Vector(sto.reshape(-1, 1))))
            return np.asarray(out, dtype=float).flatten()
        except Exception:  # noqa: BLE001
            return np.array([float(param.evaluate(fn(pybamm.Scalar(s)))) for s in sto])

    ocv = _eval(param["Positive electrode OCP [V]"], ys) - _eval(
        param["Negative electrode OCP [V]"], xs
    )
    Q_span = float(param.evaluate(pybamm.LithiumIonParameters().n.Q_init)) * float(
        x100 - x0
    )
    return {"socs": socs, "ocv": ocv, "Q_span_Ah": Q_span}


# ── raw output parsing ──────────────────────────────────────────────────


def read_results_csv(path: Path) -> dict[str, list[float]]:
    """Parse the submission's raw numeric output into columns.

    Column names are matched case-insensitively and by prefix so a submission
    is not failed for writing ``V (V)`` instead of ``voltage_V`` — the check is
    on the physics, not on one author's chosen header string.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing or empty raw output: {path.name}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = [r for r in reader if r and not r[0].lstrip().startswith("#")]
    if len(rows) < 3:
        raise RuntimeError(f"{path.name} has fewer than 2 data rows")
    header = [c.strip() for c in rows[0]]
    cols: dict[str, list[float]] = {h: [] for h in header}
    for row in rows[1:]:
        if len(row) != len(header):
            continue
        for h, v in zip(header, row):
            try:
                cols[h].append(float(v))
            except ValueError:
                cols[h].append(math.nan)
    return cols


def pick_column(cols: dict[str, list[float]], *candidates: str) -> list[float]:
    """Find a column by any of several tolerant name forms."""
    def _norm(s: str) -> str:
        return (s.lower().replace(" ", "").replace("(", "").replace(")", "")
                .replace("[", "").replace("]", "").replace("_", "").replace(".", ""))

    norm = {_norm(k): k for k in cols}
    for cand in candidates:
        key = _norm(cand)
        if key in norm:
            return cols[norm[key]]
        for nk, orig in norm.items():
            if nk.startswith(key):
                return cols[orig]
    raise RuntimeError(f"no column matching {candidates!r}; available: {sorted(cols)}")


def _trace(cols: dict[str, list[float]]) -> tuple[Any, Any, Any]:
    """(t, I, V) as sorted numpy arrays. Positive current = discharge."""
    import numpy as np

    t = np.asarray(pick_column(cols, "time_s", "time", "t"), dtype=float)
    I = np.asarray(pick_column(cols, "current_A", "current", "i"), dtype=float)
    V = np.asarray(pick_column(cols, "voltage_V", "voltage", "v", "terminal_voltage"),
                   dtype=float)
    order = np.argsort(t)
    return t[order], I[order], V[order]


def _cumulative_Ah(t: Any, I: Any) -> Any:
    """Trapezoidal charge throughput in A.h, cumulative, starting at 0."""
    import numpy as np

    if len(t) < 2:
        return np.zeros_like(t)
    inc = np.diff(t) * (I[1:] + I[:-1]) / 2.0
    return np.concatenate([[0.0], np.cumsum(inc)]) / 3600.0


# ── lifecycle ───────────────────────────────────────────────────────────


# Carried into the reproduction directory. Everything else in the submission
# is stripped: a driver that merely replays a frozen copy of an earlier solve
# would otherwise reproduce "successfully" and pass every physical check,
# since the replayed data is genuinely correct — it just was not computed by
# the run being graded. Only source survives.
#
# `.json` used to be on this list, and it is the one suffix PyBaMM itself
# writes a *solved trace* to. `Solution.save_data` takes `to_format` in
# {pickle, matlab, csv, json}; the first three land on `.pkl` / `.mat` /
# `.csv` and were stripped, the fourth was carried straight through. On the
# pinned 26.7.1.0 the json export is a flat object keyed by PyBaMM's own
# variable names, each value the full solve-time list —
#
#   {"Time [s]": [0.0, 0.0023, ...], "Current [A]": [5.0, ...],
#    "Voltage [V]": [4.0363, ...]}
#
# — so a driver that exported its solve that way and read it back reproduced
# without solving, and the strip that exists to stop exactly that was the code
# being bypassed. Which of the four documented idioms the agent happened to
# pick decided whether the gate applied to it (#138). This is the anti-cheat
# end of the hole #127 closed at the false-zero end in `native_cantera`.
#
# `.yaml` / `.yml` went with it: PyBaMM has no YAML route in either direction,
# so they protected nothing and were open for the same reason.
#
# What is NOT lost by dropping them, and why this is not the Cantera problem
# over again: Cantera had to keep `.yaml` because a *mechanism* is YAML — a
# genuine run input sharing a suffix with the artefact, which is what forced
# `looks_like_a_cantera_input` to read content instead of names. PyBaMM has no
# such input. Parameter sets ship inside the wheel as Python modules, the
# battery image installs no `bpx` package so the one JSON input format PyBaMM
# can read (`ParameterValues.create_from_bpx`) raises `ModuleNotFoundError`
# in-container, and no case's oracle reads a data file at all — `solve.sh`
# copies `run_case.py` and nothing else. A content classifier here would have
# one class, so the keep-list is the whole answer.
#
# `.txt` / `.cfg` stay, matching `native_cantera`: neither is a PyBaMM route
# in either direction, and a data file only becomes a replay vector when
# reading it back is cheaper than solving — one `json.load` is, a hand-rolled
# text parser is not.
#
# The cost is the same deal #127 booked for combustion, and every battery
# `instruction.md` had already promised it: "the evaluator copies only source
# files into a clean working copy and strips every numeric artifact before
# re-running, so nothing you leave can affect the score." A reproduction
# starts from source; whatever the driver needs, it writes itself. No case
# text changed.
_REPRODUCTION_KEEP_SUFFIXES = (".py", ".txt", ".cfg")


def is_reproduction_input(path: Path) -> bool:
    """Decide whether one submitted file is an INPUT the re-run may start from.

    Named to match `native_cantera.is_reproduction_input` so the two shared
    evaluators answer the same question through the same door; PyBaMM's answer
    needs no content read, for the reason written above the list.
    """
    return path.suffix.lower() in _REPRODUCTION_KEEP_SUFFIXES


def _reproduce(submission: Path, workdir: Path, spec: PyBaMMSpec,
               log_dir: Path) -> dict[str, Any]:
    """Re-execute the submission's own driver in a clean copy of the case.

    The copy carries only source; every numeric artifact the submission
    shipped is left behind, so the reproduced ``results.csv`` can only come
    from this run.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    stripped: list[str] = []
    for src in submission.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(submission)
        if not is_reproduction_input(src):
            stripped.append(str(rel))
            continue
        dst = workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # A results.csv smuggled in under an allowed suffix would defeat the strip,
    # so the output name itself is never carried across regardless of suffix.
    for leftover in workdir.rglob("*"):
        if leftover.is_file() and leftover.name == RESULTS_NAME:
            stripped.append(str(leftover.relative_to(workdir)))
            leftover.unlink()
    removed = bool(stripped)
    stripping = {
        "stripped_submitted_artifacts": removed,
        "stripped_files": sorted(stripped)[:20],
    }
    driver = workdir / DRIVER_NAME
    if not driver.is_file():
        raise ReproductionFailed(
            f"submission has no {DRIVER_NAME} to reproduce",
            failure_kind=DRIVER_MISSING,
            **stripping,
        )
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        run = run_driver(
            [sys.executable, DRIVER_NAME],
            cwd=workdir,
            timeout_s=spec.reproduction_timeout_s,
            log_path=log_dir / "evaluator_reproduction.log",
        )
    except ReproductionFailed as exc:
        exc.detail.update(stripping)
        raise
    if not (workdir / RESULTS_NAME).is_file():
        raise ReproductionFailed(
            f"{DRIVER_NAME} did not produce {RESULTS_NAME}",
            failure_kind=RESULTS_MISSING,
            **{k: v for k, v in run.items() if k not in ("stdout", "stderr")},
            **stripping,
        )
    return {
        "exit_code": run["exit_code"],
        "reproduction_wall_sec": run["reproduction_wall_sec"],
        "reproduction_timeout_s": run["reproduction_timeout_s"],
        "reproduction_budget_used": run["reproduction_budget_used"],
        **stripping,
        "stdout_tail": run["stdout"].strip()[-400:],
    }


def evaluate(
    spec: PyBaMMSpec,
    extract: Callable[[dict[str, list[float]], PyBaMMSpec], dict[str, Any]],
    *,
    submission: Path,
    kpis: dict[str, Any],
    reward_dir: Path,
) -> dict[str, Any]:
    """Run the full lifecycle, recording every dimension independently."""
    import numpy as np

    rec = Recorder()
    detail: dict[str, Any] = {
        "schema_version": "native-pybamm-v1",
        "case_id": spec.case_id,
        "kind": spec.kind,
        "submission": str(submission),
        "evaluator_owned_reproduction": True,
        "spec": {
            "parameter_set": spec.parameter_set,
            "initial_soc": spec.initial_soc,
            "kind": spec.kind,
        },
    }

    # Everything below needs the evaluator's own re-execution, including the
    # two artifact dimensions: they ask whether RUNNING the submitted driver
    # produces a raw trace and a figure, and the evaluator is the one that runs
    # it. Asking the agent's directory instead scored housekeeping — a driver
    # that had been verified in a scratch copy, and whose outputs the agent was
    # then refused permission to move back, failed a check its own re-run passes.
    with tempfile.TemporaryDirectory(prefix=f"{spec.case_id}-eval-") as tmp:
        workdir = Path(tmp) / "case"
        repro = rec.run(
            "clean_reproduction",
            lambda: (1.0, _reproduce(submission, workdir, spec, reward_dir)),
        )

        # 1. Raw trace, as produced by the re-run. `_reproduce` already refuses
        #    to return without it, so this reports the columns rather than
        #    re-deciding whether the file exists.
        def _artifacts() -> tuple[float, dict[str, Any]]:
            cols = read_results_csv(workdir / RESULTS_NAME)
            return 1.0, {"columns": sorted(cols),
                         "n_rows": len(next(iter(cols.values()))),
                         "source": "evaluator reproduction"}

        rec.run("artifact_produced", _artifacts)

        # 2. Figure: existence only. Automatically judging a plot's content is
        #    out of scope; we require that the run produces one, so the workflow
        #    matches how an engineer actually reports this result.
        def _figure() -> tuple[float, dict[str, Any]]:
            figs = [q.name for q in workdir.rglob("*")
                    if q.is_file() and q.suffix.lower() in FIGURE_SUFFIXES]
            if not figs:
                raise RuntimeError(
                    f"the reproduced run produced no figure "
                    f"(expected one of {FIGURE_SUFFIXES})")
            return 1.0, {"figures": sorted(figs), "source": "evaluator reproduction"}

        rec.run("figure_produced", _figure)

        cols: dict[str, list[float]] | None = None
        if repro is not None:
            try:
                cols = read_results_csv(workdir / RESULTS_NAME)
            except Exception as exc:  # noqa: BLE001
                detail["reproduced_output_error"] = f"{type(exc).__name__}: {exc}"

        if cols is not None:
            curve = _ocv_curve(spec)
            detail["ocv_reference"] = {
                "Q_span_Ah": curve["Q_span_Ah"],
                # The OCV at the case's *initial* state of charge, not at SOC = 0.
                # The old name said `ocv_at_soc0_V`, which read as "SOC zero" and
                # made a correct diagnostic look broken: on a 100%-SOC case it
                # reports ~4.24 V, which is impossible at an empty cell and sends
                # anyone debugging a failed OCV gate looking for a reversed
                # reference curve that was never reversed.
                "ocv_at_initial_soc_V": float(np.interp(spec.initial_soc,
                                                        curve["socs"], curve["ocv"])),
                "initial_soc": spec.initial_soc,
                "source": "parameter-set stoichiometry limits + half-cell OCPs, "
                          "computed by the evaluator without solving a cell model",
            }

            def _initial() -> tuple[float, dict[str, Any]]:
                t, I, V = _trace(cols)
                ocv0 = float(np.interp(spec.initial_soc, curve["socs"], curve["ocv"]))
                dV = abs(float(V[0]) - ocv0)
                out = {
                    "V_start_V": float(V[0]),
                    "ocv_at_initial_soc_V": ocv0,
                    "abs_error_V": dV,
                    "tolerance_V": spec.initial_V_tol_V,
                }
                if dV > spec.initial_V_tol_V:
                    raise RuntimeError(
                        f"initial terminal voltage {V[0]:.4f} V is {dV:.4f} V away "
                        f"from the open-circuit voltage {ocv0:.4f} V that this "
                        f"parameter set has at the specified state of charge "
                        f"{spec.initial_soc:g}"
                    )
                return 1.0, out

            rec.run("initial_state_valid", _initial)

            def _ocv() -> tuple[float, dict[str, Any]]:
                if not spec.ocv_check:
                    return 1.0, {"skipped": "case declares ocv_check = false"}
                t, I, V = _trace(cols)
                Q = _cumulative_Ah(t, I)
                soc = spec.initial_soc - Q / curve["Q_span_Ah"]
                ocv = np.interp(soc, curve["socs"], curve["ocv"])
                resid = V - ocv

                # Restrict to the first equivalent full cycle: beyond that,
                # coulomb-counted SOC drifts against the reference curve for
                # any case that degrades, which is real physics rather than a
                # bad trace. The end-of-discharge knee is excluded for the
                # same reason.
                throughput = np.concatenate(
                    [[0.0], np.cumsum(np.abs(np.diff(t) * (I[1:] + I[:-1]) / 2.0))]
                ) / 3600.0
                keep = (
                    (soc > spec.ocv_min_soc)
                    & (soc < 1.0 + spec.ocv_min_soc)
                    & (throughput <= curve["Q_span_Ah"])
                )
                n_keep = int(keep.sum())
                if n_keep < 5:
                    raise RuntimeError(
                        f"only {n_keep} samples fall inside the OCV envelope "
                        f"window; the trace does not span a usable state-of-charge "
                        f"range"
                    )

                stats = ocv_statistics(soc, ocv, resid, I, keep, spec)
                out = stats
                sign_excess = stats["max_dissipation_violation_V"]
                worst = stats["max_abs_overpotential_V"]
                shape_corr = stats["residual_ocv_correlation"]

                if sign_excess > spec.ocv_sign_tol_V:
                    raise CheckFailed(
                        f"terminal voltage sits {sign_excess:.4f} V on the "
                        f"generating side of the independently computed "
                        f"open-circuit voltage; a cell under load dissipates, so "
                        f"this trace is not physically admissible",
                        **out,
                    )
                # Shape: the voltage must carry information beyond a constant.
                shape_corr = 0.0
                if np.std(resid[keep]) > 1e-12 and np.std(ocv[keep]) > 1e-12:
                    shape_corr = float(np.corrcoef(resid[keep], ocv[keep])[0, 1])
                out["residual_ocv_correlation"] = shape_corr
                out["shape_min_correlation"] = spec.ocv_shape_min_corr
                if shape_corr < spec.ocv_shape_min_corr:
                    raise CheckFailed(
                        f"the residual against the open-circuit curve is "
                        f"{shape_corr:.3f}-correlated with that curve, meaning the "
                        f"terminal voltage does not vary with state of charge at "
                        f"all — it carries no information beyond a constant, so it "
                        f"was not produced by solving the cell",
                        **out,
                    )
                if worst > spec.ocv_max_deviation_V:
                    raise CheckFailed(
                        f"terminal voltage departs from the independently "
                        f"computed open-circuit curve by up to {worst:.4f} V, "
                        f"beyond the {spec.ocv_max_deviation_V:.4f} V overpotential "
                        f"this cell can develop at this rate",
                        **out,
                    )
                return 1.0, out

            rec.run("ocv_consistent", _ocv)

            extracted = rec.run("extraction_succeeded", lambda: (1.0, extract(cols, spec)))
        else:
            extracted = None

    # 7. Accuracy of the evaluator-derived KPI values.
    kpi_specs: dict[str, Any] = kpis.get("kpis", {})

    def _accuracy() -> tuple[float, dict[str, Any]]:
        if extracted is None:
            raise RuntimeError("no extracted values (extraction did not succeed)")
        per_kpi: dict[str, Any] = {}
        scores: list[float] = []
        for name, kspec in kpi_specs.items():
            value = extracted.get(name)
            if value is None or not math.isfinite(float(value)):
                per_kpi[name] = {"value": value, "score": 0.0, "why": "absent or non-finite"}
                scores.append(0.0)
                continue
            value = float(value)
            phys, phys_why = _physics_pass(kspec, value)
            err = abs(value - float(kspec["gt_value"]))
            tol = pass_tol(kspec)
            band = band_score(err, tol)
            s = phys * band
            gross = gross_error_tol(kspec)
            per_kpi[name] = {
                "value": value,
                "gt_value": float(kspec["gt_value"]),
                # The continuous error stays in the detail whatever the score
                # is — reward shaping reads this, the leaderboard does not.
                "absolute_error": err,
                "pass_tol": tol,
                "physics_pass": phys,
                "physics_why": phys_why,
                "band_pass": round(band, 6),
                "gross_error_tol": gross,
                "gross_error": None if gross is None else bool(err > gross),
                "score": round(s, 6),
            }
            scores.append(s)
        mean = sum(scores) / len(scores) if scores else 0.0
        return mean, {"per_kpi": per_kpi}

    rec.run("kpi_accuracy", _accuracy)

    # ── aggregate ───────────────────────────────────────────────────────
    #
    #     final_score = gate_product x accuracy
    #
    # Structural dimensions are hard gates: a trace that started from the wrong
    # state of charge, or that is not thermodynamically admissible, has no
    # meaningful "accuracy". They multiply rather than average so partial
    # credit cannot be earned for a physically invalid run.
    #
    # **There is no per-case weighting**, for the reason `native_cantera`'s
    # aggregate block spells out: composing dimensions is an aggregate-layer
    # decision, and `0.9 x accuracy + 0.1 x figure` put a 0.1 floor under every
    # wrong answer that had drawn a plot (#195). `figure_produced` is checked
    # and recorded exactly as before; it is not in this scalar and not a gate.
    gate_product = 1.0
    for g in GATES:
        gate_product *= 1.0 if rec.dims[g].status == "pass" else 0.0
    accuracy = rec.dims["kpi_accuracy"].score
    final = gate_product * accuracy

    detail.update({
        "dimensions": rec.as_dict(),
        "gates": list(GATES),
        "gate_product": gate_product,
        "score_composition": "gate_product * kpi_accuracy",
        "final_score": round(final, 6),
        "status": "completed",
    })

    reward_dir.mkdir(parents=True, exist_ok=True)
    (reward_dir / "reward.json").write_text(
        json.dumps({"score": round(final, 6)}, indent=2), encoding="utf-8"
    )
    (reward_dir / "reward_detail.json").write_text(
        json.dumps(detail, indent=2), encoding="utf-8"
    )
    return detail


# ── the standard extractors ─────────────────────────────────────────────


def _require_span(t: Any, name: str, n_min: int = 20) -> None:
    if len(t) < n_min:
        raise RuntimeError(f"{name} has only {len(t)} points")


def extract_discharge(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Delivered charge and energy, re-derived from the reproduced trace."""
    import numpy as np

    t, I, V = _trace(cols)
    _require_span(t, "trace")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(I)) and np.all(np.isfinite(V))):
        raise RuntimeError("trace contains non-finite values")
    disch = I > 0
    if disch.sum() < 5:
        raise RuntimeError(
            "trace shows no discharge (positive current is the discharge direction)"
        )
    Ah = float(np.trapezoid(np.where(disch, I, 0.0), t) / 3600.0)
    Wh = float(np.trapezoid(np.where(disch, I * V, 0.0), t) / 3600.0)
    if Ah <= 0:
        raise RuntimeError("integrated discharge capacity is not positive")
    return {
        "discharge_capacity_Ah": Ah,
        "discharge_energy_Wh": Wh,
        "mean_discharge_voltage_V": Wh / Ah,
        "final_voltage_V": float(V[-1]),
        "n_points": int(len(t)),
    }


def extract_thermal(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Peak temperature rise over the run, plus the discharge quantities."""
    import numpy as np

    out = extract_discharge(cols, spec)
    T = np.asarray(
        pick_column(cols, "temperature_K", "temperature", "T_K", "T"), dtype=float
    )
    if len(T) < 20 or not np.all(np.isfinite(T)):
        raise RuntimeError("temperature column is too short or contains non-finite values")
    if T.max() < 200.0:
        raise RuntimeError(
            f"temperature peaks at {T.max():.2f}, which is not a value in kelvin"
        )
    out["max_temperature_rise_K"] = float(T.max() - T[0])
    out["max_temperature_K"] = float(T.max())
    return out


def extract_pulse(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Pulse resistance from the largest current step in the trace.

    R = |dV / dI| across the step. Taken at the step rather than over the whole
    pulse so it is the instantaneous resistance, which is what a hybrid
    pulse-power characterisation reports.
    """
    import numpy as np

    t, I, V = _trace(cols)
    _require_span(t, "trace")
    dI = np.diff(I)
    j = int(np.argmax(np.abs(dI))) + 1
    step_I = float(I[j] - I[j - 1])
    step_V = float(V[j] - V[j - 1])
    if abs(step_I) < 1e-6:
        raise RuntimeError("trace contains no current step to measure a resistance across")
    R = abs(step_V / step_I)
    return {
        "pulse_resistance_ohm": R,
        "step_current_A": step_I,
        "step_voltage_V": step_V,
        "step_time_s": float(t[j]),
        "n_points": int(len(t)),
    }


def extract_cccv(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Charge time and delivered charge for a constant-current/constant-voltage
    charge. Negative current is the charge direction."""
    import numpy as np

    t, I, V = _trace(cols)
    _require_span(t, "trace")
    chg = I < 0
    if chg.sum() < 5:
        raise RuntimeError(
            "trace shows no charge (negative current is the charge direction)"
        )
    Ah = float(-np.trapezoid(np.where(chg, I, 0.0), t) / 3600.0)
    idx = np.flatnonzero(chg)
    return {
        "charge_time_s": float(t[idx[-1]] - t[idx[0]]),
        "charge_capacity_Ah": Ah,
        "final_voltage_V": float(V[-1]),
        "n_points": int(len(t)),
    }


def _per_cycle_discharge_Ah(t: Any, I: Any) -> list[float]:
    """Discharge capacity of each contiguous positive-current segment."""
    import numpy as np

    disch = I > 1e-9
    caps: list[float] = []
    if not disch.any():
        return caps
    edges = np.flatnonzero(np.diff(disch.astype(int)))
    starts = ([0] if disch[0] else []) + list(edges[disch[edges + 1]] + 1)
    ends = list(edges[disch[edges]] + 1) + ([len(t)] if disch[-1] else [])
    for a, b in zip(starts, ends):
        if b - a < 3:
            continue
        caps.append(float(np.trapezoid(I[a:b], t[a:b]) / 3600.0))
    return caps


def extract_cycling(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Capacity fade across the cycled trace.

    Segments the trace on the sign of the current and compares the last
    complete discharge against the first, which is how a cycle-life test
    reports retention.
    """

    t, I, V = _trace(cols)
    _require_span(t, "trace", n_min=50)
    caps = _per_cycle_discharge_Ah(t, I)
    if len(caps) < 2:
        raise RuntimeError(
            f"trace contains {len(caps)} discharge segment(s); a capacity-fade "
            f"measurement needs at least two cycles"
        )
    first, last = caps[0], caps[-1]
    if first <= 0:
        raise RuntimeError("first-cycle discharge capacity is not positive")
    return {
        "capacity_fade_pct": float((first - last) / first * 100.0),
        "first_cycle_capacity_Ah": first,
        "last_cycle_capacity_Ah": last,
        "n_cycles_detected": len(caps),
        "n_points": int(len(t)),
    }


def extract_rate_capability(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """Capacity lost between two pinned discharge rates, from one trace.

    The trace holds the same cell discharged twice at two different rates with
    a recharge between, so both capacities come out of one coulomb count of one
    run. **The cell's nominal capacity cancels exactly**, and that is the whole
    point of the KPI rather than a convenience: the nominal capacity is the one
    number about a commercial cell that is printed on its datasheet and is
    therefore recallable, while how much of it a given rate costs is a property
    of this parameterisation's transport solution and is tabulated nowhere.

    The arithmetic is `extract_cycling`'s and the two are deliberately not
    merged. `capacity_fade_pct` names an ageing quantity, and on a case with no
    degradation model in it that name would be a false statement about what was
    measured -- the same objection this repository raises against a
    `kpi_quality_note` that claims a gate the code does not run.
    """
    t, I, V = _trace(cols)
    _require_span(t, "trace", n_min=50)
    caps = _per_cycle_discharge_Ah(t, I)
    if len(caps) < 2:
        raise RuntimeError(
            f"trace contains {len(caps)} discharge segment(s); a rate-capability "
            f"measurement needs the cell discharged at both of the stated rates"
        )
    q_low, q_high = caps[0], caps[-1]
    if q_low <= 0:
        raise RuntimeError("the first discharge segment delivered no charge")
    return {
        "rate_capacity_loss_pct": float((q_low - q_high) / q_low * 100.0),
        "low_rate_capacity_Ah": q_low,
        "high_rate_capacity_Ah": q_high,
        "n_discharge_segments": len(caps),
        "n_points": int(len(t)),
    }


def extract_declared(cols: dict[str, list[float]], spec: PyBaMMSpec) -> dict[str, Any]:
    """KPIs the *case* declares, derived by `csv_interface`'s shared table.

    The six extractors above each answer a question fixed in Python: how much
    charge came out, how far the temperature rose. That works while the KPI is
    a property of the trace. It stops working the moment the answer is
    something the submission had to *search* for -- the largest charge current
    holding the cell under a temperature ceiling, the edge of a design window,
    the change between two configurations -- because there is no fixed question
    to hard-code, only a column the submission wrote.

    So those cases declare their derivation instead, in the same schema the CFD
    and packaging tracks already use, and the reading of it is shared code. The
    anti-cheat position is unchanged and is worth being explicit about, because
    "the agent reports its own answer" reads like a hole: the evaluator strips
    the submission's numeric artifacts -- `results.csv` included -- and re-runs
    its entry point, so the row scored here can only be one the re-run
    produced. A submission that prints a limit it did not search for reproduces
    nothing.
    """
    from .csv_interface import derive as _derive

    if not spec.derivations:
        raise RuntimeError(
            "kind = 'declared' requires a non-empty `derivations` block in spec.json"
        )
    return {name: _derive(cols, dspec) for name, dspec in spec.derivations.items()}


EXTRACTORS: dict[str, Callable[[dict[str, list[float]], PyBaMMSpec], dict[str, Any]]] = {
    "declared": extract_declared,
    "discharge": extract_discharge,
    "thermal": extract_thermal,
    "pulse": extract_pulse,
    "cccv": extract_cccv,
    "cycling": extract_cycling,
    "rate_capability": extract_rate_capability,
}


def main_from_case(case_tests_dir: Path) -> int:
    """Entry point used by every case's ``tests/verify_native.py``.

    The case supplies only ``spec.json`` + ``kpis.json``; all behaviour above
    is shared, which is the whole point of the standardisation.
    """
    spec_data = json.loads((case_tests_dir / "spec.json").read_text(encoding="utf-8"))
    kpis = json.loads((case_tests_dir / "kpis.json").read_text(encoding="utf-8"))
    spec = PyBaMMSpec(**spec_data)
    submission = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    reward_dir = Path(os.environ.get("SIM_BENCH_REWARD_DIR", "/logs/verifier"))
    detail = evaluate(
        spec, EXTRACTORS[spec.kind],
        submission=submission, kpis=kpis, reward_dir=reward_dir,
    )
    print(json.dumps({"score": detail["final_score"],
                      "dimensions": {k: v["status"] for k, v in detail["dimensions"].items()}},
                     indent=2))
    return 0
