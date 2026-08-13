"""Evaluator-owned reproduction + scoring for native Cantera submissions.

Design mirrors ``native_openfoam`` in spirit (the evaluator re-derives every
number from its own re-execution of the submission, never from what the agent
claims), but Cantera has no mesh and no ``log.<solver>`` artifact.

**What defends this track against a fabricated answer is the reproduction, not
any one check on the trace.** The submitted driver is copied into a clean
directory with every numeric artifact stripped and re-executed, so the
``results.csv`` the score is read off can only be the output of that run. A
hand-written CSV never reaches a physics check at all: it dies at
``clean_reproduction`` / ``artifact_produced``.

This docstring used to say something else. It claimed the equilibrium
end-state comparison was the content credential -- *"not something a
hand-written CSV can fake"* -- and that sentence was false in the same file
that contradicted it: the check reads a trace the evaluator itself produced,
so its contribution against forgery is zero. The claim was load-bearing
anyway, because anti-cheat is naturally a gate, and it kept
``equilibrium_consistent`` inside the gate product long after it had started
scoring correct submissions as zero (#125). It is now what it always was: a
diagnostic on the end state, recorded and not scored.

Two deliberate departures from the OpenFOAM evaluators:

1. **Dimensions are recorded independently and never short-circuit.** Every
   check is attempted inside its own try/except and lands in
   ``reward_detail.json`` with an explicit status (``pass`` / ``fail`` /
   ``not_attempted``), even when an earlier check already failed. A single
   raised exception no longer erases all downstream diagnostics, so a trial
   can be re-weighted offline without re-running the agent or the solver.

2. **A solver-specific case supplies only two callbacks** — a spec describing
   the physics and an extractor turning the reproduced raw output into KPI
   values. Lifecycle, gating, scoring math and reward I/O are shared.

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
# instruction states them as "write your results here", not as Cantera API.
DRIVER_NAME = "run_case.py"
RESULTS_NAME = "results.csv"
# The second interface file, written only by a case that declares
# `resolution_spec`. Overridable there; this is the default name.
LADDER_NAME = "grid_independence.csv"
# The second *profile*, written only by a case that declares `second_profile`.
# Same three columns as `results.csv` and read by the same parser, because it
# is the same interface applied twice rather than a new one.
SECOND_PROFILE_NAME = "results_unity_lewis.csv"
FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".svg")

# The submitted trace's own sample spacing is wider than the tolerance the KPI
# is scored against, so the trace could never have placed the answer inside the
# band. This is a defect of the *contract* — the output interface never asked
# for a resolution — not of the physics, and it is emitted purely so an
# aggregate can tell the two apart. It does NOT change any score: see
# `_output_grid_attribution`.
OUTPUT_GRID_TOO_COARSE = "output_grid_too_coarse"

# Optional key an extractor may return: {kpi_name: the finest step the reported
# value could move by, in that KPI's own unit}. Only extractors whose KPI is
# quantised by the submitted grid supply one; `extract_flame_speed` does not,
# because the flame speed is a boundary value rather than a located feature.
RESOLUTION_KEY = "kpi_resolution"

DIMENSIONS = (
    "artifact_produced",
    "figure_produced",
    "clean_reproduction",
    "initial_state_valid",
    "equilibrium_consistent",
    "extraction_succeeded",
    "kpi_accuracy",
)

# The dimensions that are PREREQUISITES OF MEASUREMENT: without them there is
# no number to compare, so partial credit would be credit for nothing. Every
# other dimension is recorded and left out of the scalar.
#
# The test is "is there something to measure", never "is the measurement
# accurate" -- which is why `equilibrium_consistent` is not here. A trace that
# ignited correctly and stopped at 1.2x the delay has a perfectly well-defined
# ignition delay whatever its end state does; #125 is the four correct
# submissions that gate scored zero.
GATES = (
    "artifact_produced",
    "clean_reproduction",
    "initial_state_valid",
    "extraction_succeeded",
)

# The dimensions a case opts INTO, each by declaring one block in its
# spec.json. They are absent from `DIMENSIONS` and from `GATES` on purpose: a
# dimension that exists for every case but is only ever attempted by one would
# sit at `not_attempted` on the other fifty, and `not_attempted` multiplies a
# gate product to zero. So each is added to both lists per case, and a case
# that declares neither block is byte-for-byte unaffected.
RESUME_DIMENSION = "given_state_preserved"
RESOLUTION_DIMENSION = "resolution_demonstrated"



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


class Recorder:
    """Collects dimensions; each check runs isolated so later ones still run."""

    def __init__(self, extra: tuple[str, ...] = ()) -> None:
        self.dims: dict[str, Dimension] = {
            name: Dimension() for name in (*DIMENSIONS, *extra)
        }

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
            # Keep whatever the check had measured before it gave up. Without
            # this a failed gate stores one sentence, and the two ways
            # `clean_reproduction` fails -- overran the budget, or the driver
            # crashed -- arrive as the same word (#88).
            dim.detail = {"traceback": traceback.format_exc(limit=3),
                          **getattr(exc, "detail", {})}
            return None

    def as_dict(self) -> dict[str, Any]:
        return {name: dim.as_dict() for name, dim in self.dims.items()}


# ── spec ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CanteraSpec:
    """Physics the submission must reproduce. Solver-agnostic values only."""

    case_id: str
    kind: str  # "idt" | "flame_speed"
    mechanism: str
    fuel: str
    phi: float
    T0_K: float
    P0_atm: float
    phase: str | None = None
    oxidizer: dict[str, float] = field(default_factory=lambda: {"O2": 1.0, "N2": 3.76})
    # Tolerance for the one structural gate that has one.
    initial_T_tol_K: float = 5.0
    initial_P_rel_tol: float = 0.02
    reproduction_timeout_s: int = 900
    # Extra KPIs the *case* declares, mapping a name onto a `csv_interface`
    # derivation spec. Additive rather than instead-of: the extractor named by
    # `kind` still runs and still re-derives its own quantity from the trace,
    # which is the defence that must not be traded away — an ignition delay the
    # evaluator computes itself cannot be asserted by the submission. What this
    # adds is the case whose *question* is something no extractor can compute
    # from one trace, because the submission had to run the solver more than
    # once to answer it: a sensitivity, a limit, a ratio between two runs.
    derivations: dict[str, Any] = field(default_factory=dict)
    # Set only by a case that hands the agent a run someone else started.
    #   given_dir      directory under tests/ holding the PRISTINE handover
    #   prefix_file    the interface file whose leading rows were handed over
    #   prefix_rel_tol how far a re-emitted handover row may drift
    # Absent on every other case, and absent means the resume machinery below
    # never runs.
    resume: dict[str, Any] | None = None
    # Set only by a case whose contract asks the run to SHOW that its answer has
    # stopped moving, rather than only to report it.
    #   file            the second output-interface file carrying the ladder
    #   level_columns   tolerant names for the resolution column (rows are
    #                   ordered by it; it is an OUTCOME of the run, never a
    #                   knob the task pins)
    #   value_columns   tolerant names for the reported quantity per level
    #   reported_kpi    which extracted KPI the finest level must agree with
    #   min_levels / min_span_ratio / max_rel_change / max_rel_gap_to_reported
    #                   the four numbers `instruction.md` states verbatim
    # Absent on every other case, and absent means the ladder machinery below
    # never runs.
    resolution_spec: dict[str, Any] | None = None
    # Set only by a case whose KPI is a RELATION between two runs of the same
    # operating point under two different model closures. The value is the file
    # name the second run writes; it carries the SAME three columns as
    # `results.csv` and is read by the same parser, so this adds a second
    # instance of the existing interface rather than a second interface.
    #
    # Why a relation at all: a laminar flame speed sits on a densely published
    # Su(phi, T, P) surface, so moving the operating point off the catalog --
    # this family's whole anti-recall design -- buys nothing against a model
    # that can interpolate the correlation (#98's antenna criterion; measured
    # on `ghia_*` in #266). The difference between two transport closures at
    # one operating point is on no such surface, and the recallable term
    # divides out of it.
    second_profile: str | None = None


def _equilibrium_state(spec: CanteraSpec) -> dict[str, float]:
    """Independently compute the expected end state. Evaluator-owned."""
    import cantera as ct

    gas = ct.Solution(spec.mechanism, spec.phase) if spec.phase else ct.Solution(spec.mechanism)
    gas.set_equivalence_ratio(spec.phi, fuel=spec.fuel, oxidizer=dict(spec.oxidizer))
    gas.TP = spec.T0_K, spec.P0_atm * ct.one_atm
    # Constant-volume (UV) for the 0-D reactor; constant-pressure (HP) for the
    # freely-propagating flame's burned side.
    gas.equilibrate("UV" if spec.kind == "idt" else "HP")
    return {"T_equilibrium_K": float(gas.T), "P_equilibrium_Pa": float(gas.P)}


# ── raw output parsing ──────────────────────────────────────────────────


# How far the end state may sit from the independently computed equilibrium,
# as a fraction of the temperature rise, in EITHER direction. One number for
# both systems and both signs, and the reason it can be one number is that this
# is no longer a gate: it is recorded, it decides no score, so buying agreement
# between two systems with a single band costs nothing that used to be paid for
# by four constants.
#
# 5% is what the measurements support, with the worst of them at 3.2%:
#
#   * **Ignition, stopping when the contract says to stop.** `instruction.md`
#     asks for integration until dT/dt has fallen below 0.1% of its peak. Run
#     over all 31 ignition operating points in `cases/combustion/kinetics/`
#     (Cantera 3.2.0, rtol 1e-9 / atol 1e-18, the oracle's settings), the end
#     state at that instant lands between -0.9% and +3.1% of the rise, worst
#     case `ch4_air_idt_phi0p55_1633k_9p2atm` at +3.12%. Integrating a decade
#     further (0.01% of peak) moves the worst point to +3.19%, so the residue
#     is the mechanism's own approach to equilibrium and not an early stop.
#     **1% of peak, the threshold the issue floated, would NOT do**: the worst
#     point there is -5.95% (`c2h2_air_idt_phi1p09_1284k_1p7atm`), outside this
#     band. The contract threshold and this number were chosen together.
#
#   * **Flames overshoot, and legitimately.** A freely-propagating flame's
#     burned side is fed by diffusion rather than by a conserved parcel of
#     enthalpy, so a converged, correctly-specified lean flame lands above the
#     constant-pressure equilibrium computed from the unburned state. Measured
#     on lean ethylene at phi 0.78, 2.1 atm, 321 K in GRI-Mech: +0.87% of the
#     rise on the oracle's own grid, +0.80% on a domain nearly three times
#     wider, +0.65% on a grid with 2.6x the points. Unity Lewis numbers halve
#     it to +0.44% rather than removing it, so differential diffusion explains
#     part of it and not all of it.
#
# The asymmetric predecessor (0.5% overshoot for ignition, 2% for flames, and a
# separate per-case shortfall tolerance of 1%/2%/5%) is gone with the gate. It
# existed to be tight enough to zero a submission, and nothing is zeroed here
# any more.
EQUILIBRIUM_REL_TOL = 0.05

# Keys a `spec.json` may still declare that this evaluator no longer reads.
# Named one by one rather than filtered by "anything the dataclass does not
# know", so a typo in a live key still raises instead of being ignored. The
# case tree and the image version each other's contents only loosely -- a host
# can hold an older `cases/` tree than the verifier baked into its image -- and
# an evaluator that crashes on a retired key turns that into a zero that looks
# like a capability result.
_RETIRED_SPEC_KEYS = frozenset({"equilibrium_rel_tol"})


def check_equilibrium_consistency(
    spec: CanteraSpec, T: list[float], eq: dict[str, float]
) -> tuple[float, dict[str, Any]]:
    """Compare the end state against independently computed equilibrium.

    **Diagnostic, not a gate.** A trajectory that ignited correctly and stopped
    shortly afterwards has a perfectly well-defined ignition delay, so this
    cannot fail a submission the tolerance band would pass -- which is exactly
    the test CLAUDE.md applies to any check. What it is good for is reading an
    aggregate: an end state far from equilibrium says the trace is not a
    solution of this mixture, and that is worth knowing beside a KPI that
    happened to land.

    Module-level rather than a closure inside `evaluate` so that both branches
    can be driven directly. As a closure it could only be reached by re-running
    a submission, and it shipped raising `UnboundLocalError` on every call.
    """
    if spec.kind == "idt":
        # The end state, not the peak: constant-volume ignition genuinely
        # overshoots equilibrium for a few tens of microseconds while the
        # radical pool burns down, then relaxes onto it. Reading max(T) would
        # flag a perfectly correct run.
        T_end = T[-1]
    else:
        # Burned side of the flame profile.
        T_end = T[-1] if T[-1] > T[0] else T[0]

    rise = abs(eq["T_equilibrium_K"] - spec.T0_K)
    err = abs(T_end - eq["T_equilibrium_K"])
    rel = err / rise if rise > 0 else float("inf")
    out = {
        "T_end_K": T_end,
        "T_peak_K": max(T),
        **eq,
        "abs_error_K": err,
        "rel_error_of_rise": rel,
        "tolerance_rel": EQUILIBRIUM_REL_TOL,
        "allowance_K": EQUILIBRIUM_REL_TOL * rise,
    }
    if rel > EQUILIBRIUM_REL_TOL:
        raise RuntimeError(
            f"end state {T_end:.1f} K differs from the independently computed "
            f"equilibrium {eq['T_equilibrium_K']:.1f} K by {err:.1f} K "
            f"({rel:.3%} of the {rise:.0f} K rise, tolerance "
            f"{EQUILIBRIUM_REL_TOL:.0%}). Recorded, not scored."
        )
    return 1.0, out


def read_results_csv(path: Path) -> dict[str, list[float]]:
    """Parse the submission's raw numeric output into columns.

    Column names are matched case-insensitively and by prefix so a submission
    is not failed for writing ``T (K)`` instead of ``T_K`` — the check is on
    the physics, not on one author's chosen header string.
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
    norm = {k.lower().replace(" ", "").replace("(", "").replace(")", "").replace("_", ""): k
            for k in cols}
    for cand in candidates:
        key = cand.lower().replace(" ", "").replace("(", "").replace(")", "").replace("_", "")
        if key in norm:
            return cols[norm[key]]
        for nk, orig in norm.items():
            if nk.startswith(key):
                return cols[orig]
    raise RuntimeError(
        f"no column matching {candidates!r}; available: {sorted(cols)}"
    )


# ── lifecycle ───────────────────────────────────────────────────────────


# Carried into the reproduction directory. Everything else in the submission
# is stripped: a driver that merely replays a frozen copy of an earlier solve
# would otherwise reproduce "successfully" and pass every physical check,
# since the replayed data is genuinely correct — it just was not computed by
# the run being graded. Only source and mechanism inputs survive.
_REPRODUCTION_KEEP_SUFFIXES = (".py", ".yaml", ".yml", ".cti", ".xml", ".inp", ".txt", ".cfg")

# ...but a suffix cannot decide it for YAML, because Cantera writes both its
# mechanisms and its SOLUTIONS in that format. `Sim1D.save()` defaults to
# YAML, so a submission that stored its flame the way Cantera's own
# documentation stores one shipped `flame_solution.yaml`, the copier read the
# suffix and carried it in as if it were a mechanism, and the re-run hit
#
#   CanteraError thrown by SolutionArray::writeHeader:
#   Field name 'soln' exists; use 'overwrite' argument to overwrite.
#
# — a hard failure, score 0.0, for using the documented idiom (#68). The
# instruction had already promised the opposite: "the evaluator copies only
# source files into a clean working copy and strips every numeric artifact
# before re-running, so nothing you leave can affect the score." So this is
# the code being brought back to the contract, not the contract moving.
#
# The two files are trivially distinguishable by content and not at all by
# name. A Cantera input declares `phases:` / `species:` / `reactions:` at the
# top level; a saved solution has exactly one top-level key, the name the
# solution was stored under (`soln:`, `flame:`, whatever the author passed).
# Reading the keys is deterministic, needs no YAML parser and no Cantera, and
# survives an author who names the mechanism `mech.yaml` or the solution
# `gri30_solution.yaml`.
#
# A YAML that is neither — a hand-written config the driver reads back — is
# stripped, and that is the same deal `.json`, `.npz` and every other
# non-source suffix already get: a reproduction starts from source, so
# anything the driver needs it has to write itself.
_CANTERA_INPUT_TOP_LEVEL_KEYS = frozenset({"phases", "species", "reactions"})
_YAML_CLASSIFY_SCAN_BYTES = 4 * 1024 * 1024


def looks_like_a_cantera_input(path: Path) -> bool:
    """True when a YAML file declares a Cantera phase/species/reaction set.

    Only the top-level (column-0) keys are read: a saved solution nests
    everything one level under its own name, so nothing inside it can be
    mistaken for a mechanism declaration.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_YAML_CLASSIFY_SCAN_BYTES)
    except OSError:
        return False
    for line in head.splitlines():
        if not line or line[:1].isspace() or ":" not in line:
            continue
        if line.split(":", 1)[0].strip().strip("'\"") in _CANTERA_INPUT_TOP_LEVEL_KEYS:
            return True
    return False


def is_reproduction_input(path: Path) -> bool:
    """Decide whether one submitted file is an INPUT the re-run may start from."""
    suffix = path.suffix.lower()
    if suffix not in _REPRODUCTION_KEEP_SUFFIXES:
        return False
    if suffix in (".yaml", ".yml"):
        return looks_like_a_cantera_input(path)
    return True


def _reproduce(submission: Path, workdir: Path, spec: CanteraSpec,
               log_dir: Path, given: Path | None = None) -> dict[str, Any]:
    """Re-execute the submission's own driver in a clean copy of the case.

    The copy carries only inputs (source + mechanism files); every numeric
    artifact the submission shipped is left behind, so the reproduced
    ``results.csv`` can only come from this run.

    `given` names a directory of files the TASK handed the agent -- the partial
    output and checkpoint of a run that was interrupted. They are numeric, so
    the strip above removes the submission's copies, and then the **evaluator's
    own pristine copies are planted in their place**. Restoring the
    submission's would defeat the whole contract: a submission could ship a
    handover it had rewritten, or one already carrying the answer, and the
    rerun would faithfully reproduce it. Planting the evaluator's makes the
    handover a fixed input of the measurement rather than something the thing
    being measured supplies.
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
    removed = bool(stripped)
    stripping = {
        "stripped_submitted_artifacts": removed,
        "stripped_files": sorted(stripped)[:20],
    }
    if given is not None:
        planted = []
        for src in sorted(p for p in given.rglob("*") if p.is_file()):
            dst = workdir / src.relative_to(given)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            planted.append(str(src.relative_to(given)))
        stripping["planted_given_files"] = planted
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


def complete_rows(path: Path) -> tuple[list[str], list[tuple[float, ...]]]:
    """Rows of a CSV that are whole and numeric, plus its header.

    A run that was killed mid-write leaves a partial final record, so "whole"
    is a property of the data and not an error to raise on: the last line of
    the handover this reads is deliberately half a row. Rows that do not carry
    every declared field, or do not parse, are skipped -- which is what a
    submission has to do too.
    """
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        try:
            header = [c.strip() for c in next(reader)]
        except StopIteration:
            return [], []
        rows: list[tuple[float, ...]] = []
        for row in reader:
            if len(row) != len(header):
                continue
            try:
                rows.append(tuple(float(v) for v in row))
            except ValueError:
                continue
    return header, rows


def check_given_prefix(produced: Path, given: Path,
                       rel_tol: float) -> tuple[float, dict[str, Any]]:
    """The handed-over rows must come back unchanged, at the front, in order.

    This is the second thing a resume task scores, and it is exact rather than
    banded: "the finished part survived" has no tolerance to argue about. It
    reads the OUTPUT INTERFACE only -- the same file the KPI is read from --
    and never the submission's source, so it cannot learn what the run was
    configured with, which is the rule the rest of this repo's evaluators keep.

    It compares parsed values rather than bytes on purpose. A submission that
    re-emits the handover through its own writer, with a different float
    spelling, has not lost anything and must not be zeroed for it -- that is
    exactly the class of defect acceptance criterion (e) exists to catch, and
    the variant that writes every carried-over row through ``"%.17g"`` instead
    of ``repr`` is in this evaluator's tests for that reason.

    **What this does NOT check is that the finished interval was not
    recomputed, and that is a property of the world rather than a gap to be
    closed.** Measured while the case was being built: a driver that ignores
    the checkpoint entirely and re-integrates from t = 0, at the same
    tolerances on the same mechanism, lands on *bit-identical* adaptive steps
    and reproduces all 505 handover rows exactly. The integrator is
    deterministic, so "reused" and "recomputed identically" are the same
    output, and no evaluator restricted to the output interface can tell them
    apart. An `instruction.md` demanding "do not recompute" would therefore be
    stating a rule nothing enforces -- the false-contract-clause failure
    CLAUDE.md names -- so the contract asks for what is checkable: the rows
    come back, whole, unaltered, at the front.
    """
    _, want = complete_rows(given)
    _, got = complete_rows(produced)
    if not want:
        raise RuntimeError(f"the handover at {given.name} carries no complete rows")
    if len(got) < len(want):
        raise RuntimeError(
            f"the completed {produced.name} has {len(got)} rows, fewer than the "
            f"{len(want)} the interrupted run had already written; the handover "
            "has to come back whole"
        )
    for index, (a, b) in enumerate(zip(want, got)):
        for column, (x, y) in enumerate(zip(a, b)):
            if abs(x - y) > rel_tol * max(abs(x), abs(y), 1e-300):
                raise RuntimeError(
                    f"row {index + 1} column {column + 1} of the completed "
                    f"{produced.name} reads {y!r} where the interrupted run had "
                    f"written {x!r}; the rows it had already completed have to "
                    "come back unaltered, at the front of the file"
                )
    return 1.0, {
        "handover_rows": len(want),
        "produced_rows": len(got),
        "rows_added": len(got) - len(want),
        "rel_tol": rel_tol,
        "source": "evaluator's own pristine copy of the handover",
    }


def check_resolution_ladder(
    produced: Path, block: dict[str, Any], reported: float | None
) -> tuple[float, dict[str, Any]]:
    """The run has to SHOW that its answer stopped moving, not just report it.

    A second file on the same output interface, written by the same re-run:
    one row per resolution level, each row the level actually reached and the
    quantity read off it. Four predicates, all four stated verbatim in
    `instruction.md` so nothing here can ambush a submission that read the
    contract:

      1. at least `min_levels` rows at distinct levels;
      2. the finest level is at least `min_span_ratio` times the coarsest --
         levels that barely differ are not a refinement study;
      3. **the last two steps** each move the value by no more than
         `max_rel_change`;
      4. the reported answer agrees with the finest level to
         `max_rel_gap_to_reported`, which is what ties the ladder to the number
         being scored instead of leaving it a decorative side file.

    Predicate 3 asks for two consecutive small steps rather than one, and that
    is not belt-and-braces -- it was put there by a measurement. On this
    operating point the answer *plateaus* between 47 and 54 grid points
    (40.4546 then 40.4852, a step of 0.07%) while still being 4.2% high, so a
    single small step is satisfied by an answer that has not converged at all;
    it has merely stopped moving for one step. Two consecutive steps costs the
    submission one more solve and costs this check nothing.

    **This is admissible under the rule that a check must be able to fail a
    submission the band would pass**, and that is measured rather than argued.
    On this case's operating point the ladder 32 -> 47 -> 54 -> 74 grid points
    reads 43.4615 -> 40.4546 -> 40.4852 -> 39.5390 cm/s, and its finest value
    sits +1.87% from a `gt_value` of 38.8149 against a 5% band -- scored 1.0 by
    the band. Its last step is 2.39%, so predicate 3 zeroes it. The band cannot
    see an unconverged answer; this can. It also runs the other way --
    unity-Lewis transport converges cleanly (a ladder that passes all four) and
    lands 28.7% out, which the band catches and this does not. The two are
    checking different things, which is why both are kept.

    Like `check_given_prefix` it reads the OUTPUT INTERFACE only. It never
    learns what refinement criteria, domain width or transport model produced
    the rows, so none of those can enter the score -- the level column is an
    *outcome* of whatever the submission chose to do, which is what keeps the
    free choice free while giving it a consequence.

    **What it does not do is prove the rows were solved rather than printed.**
    The strip-and-re-run makes them come out of the evaluator's own execution,
    so they cannot be shipped as data; a driver that prints four invented pairs
    still passes. That hole is the whole track's and is not closed here: what
    keeps it shut is that the invented pairs have to bracket an answer the
    agent does not have, since the band is scored off the same re-run.
    """
    level_names = tuple(block.get("level_columns") or ("n_grid_points",))
    value_names = tuple(block.get("value_columns") or ("flame_speed_cm_s",))
    min_levels = int(block.get("min_levels", 3))
    min_span = float(block.get("min_span_ratio", 2.0))
    max_change = float(block.get("max_rel_change", 0.02))
    max_gap = float(block.get("max_rel_gap_to_reported", 0.02))

    if not produced.is_file() or produced.stat().st_size == 0:
        raise RuntimeError(
            f"the reproduced run wrote no {produced.name}; the contract asks for "
            "the resolution ladder as well as the result"
        )
    cols = read_results_csv(produced)
    levels = pick_column(cols, *level_names)
    values = pick_column(cols, *value_names)

    # One row per level, later rows winning, so a submission that re-emits a
    # level is not failed for it.
    by_level: dict[float, float] = {}
    for lev, val in zip(levels, values):
        if math.isfinite(lev) and math.isfinite(val):
            by_level[float(lev)] = float(val)
    ladder = sorted(by_level.items())
    out: dict[str, Any] = {
        "file": produced.name,
        "levels": [lev for lev, _ in ladder],
        "values": [val for _, val in ladder],
        "min_levels": min_levels,
        "min_span_ratio": min_span,
        "max_rel_change": max_change,
        "max_rel_gap_to_reported": max_gap,
        "source": "evaluator reproduction",
    }
    if len(ladder) < min_levels:
        raise RuntimeError(
            f"{produced.name} carries {len(ladder)} distinct levels, fewer than "
            f"the {min_levels} the contract asks for"
        )
    coarsest, finest = ladder[0][0], ladder[-1][0]
    span = finest / coarsest if coarsest > 0 else float("inf")
    out["span_ratio"] = span
    if span < min_span:
        raise RuntimeError(
            f"the finest level in {produced.name} ({finest:g}) is only {span:.2f}x "
            f"the coarsest ({coarsest:g}); the contract asks for at least "
            f"{min_span:g}x, because levels that barely differ demonstrate nothing"
        )
    v_fine = ladder[-1][1]
    scale = max(abs(v_fine), 1e-300)
    steps = [abs(ladder[i + 1][1] - ladder[i][1]) / max(abs(ladder[i + 1][1]), 1e-300)
             for i in range(len(ladder) - 1)]
    last_two = steps[-2:]
    out.update({"finest_value": v_fine, "rel_change_per_step": steps,
                "rel_change_last_two_steps": last_two})
    for offset, change in zip(range(len(ladder) - len(last_two) - 1, len(ladder) - 1),
                              last_two):
        if change > max_change:
            raise RuntimeError(
                f"in {produced.name} the step from level {ladder[offset][0]:g} to "
                f"{ladder[offset + 1][0]:g} moves the value by {change:.3%} "
                f"({ladder[offset][1]!r} then {ladder[offset + 1][1]!r}), more than "
                f"the {max_change:.1%} the contract asks for of each of the last two "
                "steps; the answer has not stopped moving"
            )
    if reported is None or not math.isfinite(float(reported)):
        raise RuntimeError(
            "no reported value to compare the ladder against (extraction did "
            "not produce one)"
        )
    gap = abs(float(reported) - v_fine) / scale
    out.update({"reported_value": float(reported), "rel_gap_to_reported": gap})
    if gap > max_gap:
        raise RuntimeError(
            f"the reported answer {float(reported)!r} is {gap:.3%} from the finest "
            f"level in {produced.name} ({v_fine!r}), more than the {max_gap:.1%} "
            "the contract asks for; the ladder has to be about the run being scored"
        )
    return 1.0, out


def _output_grid_attribution(rec: Recorder) -> dict[str, Any] | None:
    """Name the defect when the submitted trace could not resolve the KPI.

    **This changes no score, by design.** A trace too coarse to place the
    ignition peak keeps exactly the score `band_pass` gave it; what this adds
    is a line in `reward_detail.json` saying *why* that zero happened, so an
    aggregate can separate "the output interface never asked for a resolution"
    from "the model could not do the physics". Those two look identical in the
    score — a correct H2 submission reporting on a 1 us grid scores the same
    zero as a wrong mechanism, and `gross_error: false` beside it reads as a
    near miss (#189).

    Whether such a cell should also leave the leaderboard's denominator is a
    scoring-contract question and is deliberately NOT decided here: the answer
    would move published numbers, so it needs its own decision. Attribution
    first, because attribution is what makes that decision arguable at all.
    """
    kpis: dict[str, Any] = {}
    per_kpi = (rec.dims["kpi_accuracy"].detail or {}).get("per_kpi") or {}
    for name, k in per_kpi.items():
        if k.get("resolves_pass_tol") is False:
            kpis[name] = {
                "output_grid_spacing": k.get("output_grid_spacing"),
                "pass_tol": k.get("pass_tol"),
                "band_pass": k.get("band_pass"),
            }
    # The same defect written a second way: a fixed-decimal time column, which
    # collapses samples onto one timestamp and stops the extractor before any
    # KPI exists to annotate.
    extraction = rec.dims["extraction_succeeded"].detail or {}
    quantum = (extraction.get("time_column_quantum_s")
               if extraction.get("failure_kind") == OUTPUT_GRID_TOO_COARSE else None)
    if not kpis and quantum is None:
        return None
    out: dict[str, Any] = {
        "failure_kind": OUTPUT_GRID_TOO_COARSE,
        "score_effect": "none — this is attribution only",
    }
    if kpis:
        out["kpis"] = kpis
        out["why"] = (
            "the reported value can only land on a sample of the submitted "
            "trace, and the samples around it are further apart than the whole "
            "tolerance the KPI is scored to, so this trace cannot resolve the "
            "KPI however correct the physics behind it is"
        )
    if quantum is not None:
        out["time_column_quantum_s"] = quantum
        out.setdefault("why", "")
        out["why"] = (out["why"] + "; " if out["why"] else "") + (
            f"the time column is rounded onto multiples of {quantum:.6g} s, "
            "which is a formatting choice rather than a property of the run"
        )
    return out


def evaluate(
    spec: CanteraSpec,
    extract: Callable[..., dict[str, Any]],
    *,
    submission: Path,
    kpis: dict[str, Any],
    reward_dir: Path,
    given_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the full lifecycle, recording every dimension independently."""
    resuming = spec.resume is not None and given_dir is not None
    resolving = spec.resolution_spec is not None
    extra = ((RESUME_DIMENSION,) if resuming else ()) + (
        (RESOLUTION_DIMENSION,) if resolving else ())
    rec = Recorder(extra=extra)
    gates = (*GATES, *extra)
    detail: dict[str, Any] = {
        "schema_version": "native-cantera-v1",
        "case_id": spec.case_id,
        "kind": spec.kind,
        "submission": str(submission),
        "evaluator_owned_reproduction": True,
        "spec": {
            "mechanism": spec.mechanism, "fuel": spec.fuel, "phi": spec.phi,
            "T0_K": spec.T0_K, "P0_atm": spec.P0_atm, "phase": spec.phase,
        },
    }

    # Everything below needs the evaluator's own re-execution, including the two
    # artifact dimensions: they ask whether RUNNING the submitted driver produces
    # a raw trace and a figure, and the evaluator is the one that runs it.
    with tempfile.TemporaryDirectory(prefix=f"{spec.case_id}-eval-") as tmp:
        workdir = Path(tmp) / "case"
        repro = rec.run(
            "clean_reproduction",
            lambda: (1.0, _reproduce(submission, workdir, spec, reward_dir,
                                     given_dir if resuming else None)),
        )

        if resuming:
            resume_spec = spec.resume or {}
            prefix_file = resume_spec.get("prefix_file", RESULTS_NAME)
            rec.run(RESUME_DIMENSION, lambda: check_given_prefix(
                workdir / prefix_file,
                (given_dir or Path()) / prefix_file,
                float(resume_spec.get("prefix_rel_tol", 1e-9)),
            ))

        # 1. Raw trace, as produced by the re-run.
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
        aux: dict[str, list[float]] | None = None
        if repro is not None:
            try:
                cols = read_results_csv(workdir / RESULTS_NAME)
            except Exception as exc:  # noqa: BLE001
                detail["reproduced_output_error"] = f"{type(exc).__name__}: {exc}"
            # The second profile, if the case declares one. A failure to read it
            # is left to `extraction_succeeded` rather than raised here, so the
            # submission gets the same per-dimension isolation as everything
            # else and the reason lands in `reward_detail.json`.
            if spec.second_profile:
                try:
                    aux = read_results_csv(workdir / spec.second_profile)
                except Exception as exc:  # noqa: BLE001
                    detail["second_profile_error"] = f"{type(exc).__name__}: {exc}"

        if cols is not None:
            def _initial() -> tuple[float, dict[str, Any]]:

                if spec.kind == "idt":
                    T = pick_column(cols, "T_K", "T", "temperature")
                    T_start = T[0]
                else:
                    T = pick_column(cols, "T_K", "T", "temperature")
                    T_start = min(T[0], T[-1])  # unburned side
                dT = abs(T_start - spec.T0_K)
                ok = dT <= spec.initial_T_tol_K
                out = {
                    "T_start_K": T_start,
                    "T_expected_K": spec.T0_K,
                    "abs_error_K": dT,
                    "tolerance_K": spec.initial_T_tol_K,
                }
                if not ok:
                    raise RuntimeError(
                        f"initial temperature {T_start:.2f} K differs from the "
                        f"specified {spec.T0_K} K by {dT:.2f} K"
                    )
                return 1.0, out

            rec.run("initial_state_valid", _initial)

            def _equilibrium() -> tuple[float, dict[str, Any]]:
                T = pick_column(cols, "T_K", "T", "temperature")
                return check_equilibrium_consistency(
                    spec, T, _equilibrium_state(spec))

            rec.run("equilibrium_consistent", _equilibrium)

            extracted = rec.run(
                "extraction_succeeded", lambda: (1.0, extract(cols, spec, aux))
            )

            # After extraction, because predicate 4 compares the ladder's
            # finest level against the number actually being scored.
            if resolving:
                block = spec.resolution_spec or {}
                rec.run(RESOLUTION_DIMENSION, lambda: check_resolution_ladder(
                    workdir / block.get("file", LADDER_NAME),
                    block,
                    None if extracted is None
                    else extracted.get(block.get("reported_kpi", "")),
                ))

        else:
            extracted = None

    # 7. Accuracy of the evaluator-derived KPI values.
    kpi_specs: dict[str, Any] = kpis.get("kpis", {})

    def _accuracy() -> tuple[float, dict[str, Any]]:
        if extracted is None:
            raise RuntimeError("no extracted values (extraction did not succeed)")
        per_kpi: dict[str, Any] = {}
        scores: list[float] = []
        resolutions = extracted.get(RESOLUTION_KEY) or {}
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
            # Can this submission's own output grid express an answer inside
            # the band at all? The score does not consult the answer — a
            # too-coarse trace keeps whatever `band_pass` gave it. What this
            # adds is the ability to read, in an aggregate, that a zero came
            # from an output interface that never stated a resolution rather
            # than from a model that could not do the physics.
            resolution = resolutions.get(name)
            if resolution is not None:
                resolves = float(resolution) <= tol
                per_kpi[name]["output_grid_spacing"] = float(resolution)
                per_kpi[name]["resolves_pass_tol"] = resolves
                if not resolves:
                    per_kpi[name]["failure_kind"] = OUTPUT_GRID_TOO_COARSE
            scores.append(s)
        mean = sum(scores) / len(scores) if scores else 0.0
        return mean, {"per_kpi": per_kpi}

    rec.run("kpi_accuracy", _accuracy)

    # ── aggregate ───────────────────────────────────────────────────────
    #
    #     final_score = gate_product x accuracy
    #
    # and nothing else. The gates multiply because they are prerequisites of
    # measurement rather than dimensions of quality: a run that produced no
    # trace, or started from the wrong state, has no accuracy to be partly
    # right about.
    #
    # **There is no per-case weighting.** There used to be
    # `0.9 x accuracy + 0.1 x figure`, which after #188 made a wrong answer
    # with a plot worth 0.1 -- a visible floor under every failure, and a
    # weight nobody had chosen for a reason. Composing dimensions is an
    # AGGREGATE-layer decision: only the aggregate has the global view needed
    # to say what a figure is worth, and only there can it be revised without
    # re-running anything. Harbor's contract forces one scalar per task
    # (`reward.json` has a single `score` key), so the collapse has to happen
    # in this container -- but every dimension is written to
    # `reward_detail.json` beside it, which is what keeps a later re-weighting
    # a read of the store rather than a re-run of the sweep (#195).
    #
    # `figure_produced` is checked and recorded exactly as before. It is not in
    # this scalar and it is not a gate.
    gate_product = 1.0
    for g in gates:
        gate_product *= 1.0 if rec.dims[g].status == "pass" else 0.0
    accuracy = rec.dims["kpi_accuracy"].score
    final = gate_product * accuracy

    attribution = _output_grid_attribution(rec)

    detail.update({
        "dimensions": rec.as_dict(),
        "gates": list(gates),
        "gate_product": gate_product,
        "score_composition": "gate_product * kpi_accuracy",
        **({"attribution": attribution} if attribution else {}),
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


# ── the two standard extractors ─────────────────────────────────────────


def _time_quantum(t) -> float | None:
    """The lattice step a rounded time column sits on, or None if it is not on one.

    `f"{t:.6f}"` is an ordinary way to write a CSV and it snaps every timestamp
    onto multiples of 1e-6 s. Naming the step is what turns the resulting
    "the time column does not advance" into a statement the author can act on.
    """
    import numpy as np

    gaps = np.diff(t)
    positive = gaps[gaps > 0.0]
    if positive.size == 0:
        return None
    q = float(positive.min())
    if q <= 0.0 or not math.isfinite(q):
        return None
    # Every sample has to be a multiple of the candidate step, to within the
    # float noise of having been parsed back from decimal text.
    ratios = np.asarray(t, dtype=float) / q
    if np.max(np.abs(ratios - np.round(ratios))) > 1e-6:
        return None
    return q


def extract_ignition_delay(cols: dict[str, list[float]], spec: CanteraSpec,
                           aux: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """IDT = time of the maximum dT/dt, re-derived from the reproduced trace."""
    import numpy as np

    t = np.asarray(pick_column(cols, "time_s", "time", "t"), dtype=float)
    T = np.asarray(pick_column(cols, "T_K", "T", "temperature"), dtype=float)
    order = np.argsort(t)
    t, T = t[order], T[order]
    if np.any(~np.isfinite(t)) or np.any(~np.isfinite(T)):
        raise RuntimeError("trajectory contains non-finite values")
    if len(t) < 20:
        raise RuntimeError(f"trajectory has only {len(t)} points")
    # A repeated timestamp is a zero-width interval, and `np.gradient` divides
    # by it. The NaN that comes back then WINS `np.argmax`, so this function
    # used to return the time of the first degenerate sample dressed as an
    # ignition delay, sitting next to `max_dTdt_K_per_s = nan`. Observed on a
    # real trial: the evaluator's own reproduction printed 19.75 us on its
    # stdout while the extraction beside it reported 0.060 ms, and the case
    # scored 0.1 — a number wrong by a factor of three, from a run that was
    # right (#68). Only the inputs were ever checked for finiteness; the
    # derivative this function computes itself never was.
    #
    # There is no honest repair. Two temperatures at one instant do not say
    # when the rise between them happened, and the band this KPI is scored
    # against is a couple of per cent wide. Refusing puts a named failure in
    # `reward_detail.json` that a human can triage; returning a number puts a
    # silent wrong answer on the leaderboard, which is the more expensive of
    # the two by far.
    gaps = np.diff(t)
    bad = np.flatnonzero(gaps <= 0.0)
    if bad.size:
        # A time column written with a fixed number of decimals collapses onto
        # a lattice, and the collision shows up here as a repeated timestamp.
        # Saying which lattice turns "your trace is broken" into the actionable
        # "your time column is rounded", and it is the same defect the
        # resolution check below attributes on traces that stay monotone.
        quantum = _time_quantum(t)
        message = (
            f"the time column does not advance at t = {t[int(bad[0])]:.6g} s "
            f"({bad.size} of {gaps.size} intervals are not positive); dT/dt is "
            "undefined there, so no ignition delay can be read off this trace"
        )
        detail: dict[str, Any] = {}
        if quantum is not None:
            message += (
                f". Every timestamp in the column is a multiple of {quantum:.6g} s, "
                "so the column has been rounded to a fixed number of decimals "
                "rather than written at the precision the run computed it to"
            )
            detail = {"failure_kind": OUTPUT_GRID_TOO_COARSE,
                      "time_column_quantum_s": float(quantum)}
        err = RuntimeError(message)
        err.detail = detail  # type: ignore[attr-defined]
        raise err
    if T.max() - T[0] < 200.0:
        raise RuntimeError(
            f"no ignition: temperature rose only {T.max() - T[0]:.1f} K"
        )
    dTdt = np.gradient(T, t)
    if not np.all(np.isfinite(dTdt)):
        raise RuntimeError(
            f"dT/dt is not finite at {int(np.count_nonzero(~np.isfinite(dTdt)))} "
            f"of {dTdt.size} samples; no ignition delay can be read off this trace"
        )
    i = int(np.argmax(dTdt))
    # The delay is one of the submitted samples — there is no interpolation and
    # no peak refinement here, deliberately (adding either would change what
    # this KPI means and move every stored `gt_value`). So the answer can only
    # move in steps of the local grid spacing, and that spacing is the
    # measurement's own quantum. Reporting it lets the scorer say whether the
    # trace could have resolved the KPI at all; see `RESOLUTION_KEY`.
    #
    # The *smaller* of the two adjacent steps is deliberate: it is a lower
    # bound on the quantum, so "this is bigger than the tolerance" is a
    # statement that holds however the peak sits between the samples. Taking
    # the larger one would flag traces that are in fact resolved.
    neighbours = [t[i] - t[i - 1] if i > 0 else None,
                  t[i + 1] - t[i] if i + 1 < len(t) else None]
    peak_spacing_s = float(min(g for g in neighbours if g is not None))
    return {
        "ignition_delay_ms": float(t[i] * 1e3),
        "max_dTdt_K_per_s": float(dTdt[i]),
        "n_points": int(len(t)),
        "peak_spacing_ms": peak_spacing_s * 1e3,
        RESOLUTION_KEY: {"ignition_delay_ms": peak_spacing_s * 1e3},
    }


def _flame_speed_from_profile(cols: dict[str, list[float]],
                              what: str = "flame profile") -> dict[str, Any]:
    """Laminar flame speed = inlet (unburned-side) axial velocity."""
    import numpy as np

    x = np.asarray(pick_column(cols, "grid_m", "grid", "x_m", "x", "z"), dtype=float)
    u = np.asarray(pick_column(cols, "velocity_m_s", "velocity", "u"), dtype=float)
    T = np.asarray(pick_column(cols, "T_K", "T", "temperature"), dtype=float)
    order = np.argsort(x)
    x, u, T = x[order], u[order], T[order]
    if len(x) < 20:
        raise RuntimeError(f"{what} has only {len(x)} points")
    if T[-1] < T[0]:  # profile stored burned-first; flip so index 0 is unburned
        u, T = u[::-1], T[::-1]
    if T.max() - T.min() < 200.0:
        raise RuntimeError(f"{what} shows no flame (temperature nearly uniform)")
    return {
        "flame_speed_cm_s": float(u[0] * 100.0),
        "adiabatic_flame_temperature_K": float(T.max()),
        "n_points": int(len(x)),
    }


def extract_flame_speed(cols: dict[str, list[float]], spec: CanteraSpec,
                        aux: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """Laminar flame speed = inlet (unburned-side) axial velocity."""
    return _flame_speed_from_profile(cols)


def extract_transport_ratio(cols: dict[str, list[float]], spec: CanteraSpec,
                            aux: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """The ratio of two flame speeds computed under two transport closures.

    Both numbers are read off a profile the evaluator's own re-run wrote, by
    the same function and through the same three columns, so nothing here is a
    claim the submission makes about itself. What the ratio buys is stated on
    `CanteraSpec.second_profile`: the leading term -- the flame speed itself,
    which sits on a published Su(phi, T, P) surface -- divides out, and what
    remains is how much differential diffusion is worth in this mixture, which
    is not tabulated anywhere and cannot be produced without solving twice.
    """
    base = _flame_speed_from_profile(cols)
    if aux is None:
        raise RuntimeError(
            f"the second profile ({spec.second_profile or SECOND_PROFILE_NAME}) "
            f"was not produced by the re-run, so the two closures cannot be "
            f"compared"
        )
    other = _flame_speed_from_profile(aux, what="second flame profile")
    su_ref = base["flame_speed_cm_s"]
    su_alt = other["flame_speed_cm_s"]
    if not su_ref > 0:
        raise RuntimeError(
            f"the reference profile's inlet velocity is {su_ref:.6g} cm/s, so a "
            f"ratio against it is undefined"
        )
    return {
        "unity_lewis_speed_ratio": float(su_alt / su_ref),
        "flame_speed_cm_s": su_ref,
        "unity_lewis_speed_cm_s": su_alt,
        "adiabatic_flame_temperature_K": base["adiabatic_flame_temperature_K"],
        "n_points": base["n_points"],
        "n_points_second_profile": other["n_points"],
    }


def with_declared(base: Callable[..., dict[str, Any]],
                  spec: CanteraSpec) -> Callable[..., dict[str, Any]]:
    """Wrap an extractor so the case's declared derivations run beside it.

    Returns `base` untouched when the case declares none, so every existing
    case takes exactly the path it took before.

    The composition is the point. `base` answers the question that *is* a
    property of the trace, and it answers it from the trace rather than from
    anything the submission claims — that is what the track's whole design
    rests on. The declared derivations answer the question that is not: a
    quantity the submission could only produce by running the solver several
    times and combining the results, which no single trace contains. Both are
    scored the same way afterwards, and what keeps the second honest is the
    same strip-and-re-run that keeps the first honest: the column is deleted
    before the submission's own entry point is re-executed.
    """
    if not spec.derivations:
        return base

    from .csv_interface import derive as _derive

    def _extract(cols: dict[str, list[float]], *args: Any, **kw: Any) -> dict[str, Any]:
        out = dict(base(cols, *args, **kw))
        for name, dspec in spec.derivations.items():
            if name in out:
                raise RuntimeError(
                    f"declared derivation {name!r} collides with a name the "
                    f"{spec.kind!r} extractor already produces; the evaluator's "
                    "own value must not be shadowed by a reported one"
                )
            out[name] = _derive(cols, dspec)
        return out

    return _extract


EXTRACTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "idt": extract_ignition_delay,
    "flame_speed": extract_flame_speed,
    "transport_ratio": extract_transport_ratio,
}


def main_from_case(case_tests_dir: Path) -> int:
    """Entry point used by every case's ``tests/verify_native.py``.

    The case supplies only ``spec.json`` + ``kpis.json``; all behaviour above
    is shared, which is the whole point of the standardisation.
    """
    spec_data = json.loads((case_tests_dir / "spec.json").read_text(encoding="utf-8"))
    kpis = json.loads((case_tests_dir / "kpis.json").read_text(encoding="utf-8"))
    spec = CanteraSpec(**{k: v for k, v in spec_data.items()
                          if k not in _RETIRED_SPEC_KEYS})
    submission = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    reward_dir = Path(os.environ.get("SIM_BENCH_REWARD_DIR", "/logs/verifier"))
    given_dir = (case_tests_dir / spec.resume["given_dir"]) if spec.resume else None
    detail = evaluate(
        spec, with_declared(EXTRACTORS[spec.kind], spec),
        submission=submission, kpis=kpis, reward_dir=reward_dir,
        given_dir=given_dir,
    )
    print(json.dumps({"score": detail["final_score"],
                      "dimensions": {k: v["status"] for k, v in detail["dimensions"].items()}},
                     indent=2))
    return 0
