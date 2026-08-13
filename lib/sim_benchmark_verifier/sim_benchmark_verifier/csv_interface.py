#!/usr/bin/env python3
"""The half of the output-interface contract that has nothing to do with a solver.

CLAUDE.md's "The output interface" says a case's `instruction.md` names a file
and its columns, the submission's own run writes it, and the evaluator reads
only that. Everything in *that* sentence is solver-neutral: reading a CSV,
deriving a KPI from its columns, and scoring the derived value against a band.

What is not neutral is the pair either side of it -- which generated artifacts
have to be stripped before the rerun, and what command the rerun is. Those stay
in the per-track evaluators (`openfoam_interface`, `calculix_interface`), which
are otherwise the same twenty lines. Splitting here rather than copying is what
keeps a fix to the header-row recovery below from having to be made twice.
"""
from __future__ import annotations

import csv
import math
import os
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .native_openfoam import EvaluationFailure, band_verdict, shell_quote


# ── reading the declared interface ───────────────────────────────────────────

def _is_number(field: str) -> bool:
    try:
        float(field)
    except ValueError:
        return False
    return True


def read_interface(
    path: Path,
    columns: list[str],
    min_rows: int,
    labels: Sequence[str] = (),
) -> dict[str, Any]:
    """Read the named columns out of the named file. Nothing else is consulted.

    Every failure here is `extraction_failed` and says which column was missing
    or which cell would not parse, because "the agent's file was not what the
    prompt asked for" and "the agent could not do the physics" are different
    findings and an aggregate cannot tell them apart afterwards.

    `labels` names columns that carry *text* rather than a measurement -- which
    configuration each row is, for a KPI defined between two of them. They come
    back as strings in the same dict, and nothing declared as one reaches an
    arithmetic derivation (`_numeric` below is where that is refused). The
    interface stays one file and one reader: a label column is a column, not a
    second format.
    """
    if not path.is_file():
        raise EvaluationFailure(
            "extraction_failed",
            f"the run produced no {path.name}; the task requires it in the submission root",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise EvaluationFailure("extraction_failed", f"{path.name} is empty")

    # A missing header row is a formatting slip, not a wrong answer, and it must
    # not cost a correct one. Measured: a submission whose three refinement
    # levels agreed with the reference to eight figures scored zero because its
    # first line was `20,0.05,0.00371611432368` instead of the column names --
    # `DictReader` then read the data as the header. Recovering it is
    # unambiguous only under both of these, so both are required: every field on
    # the first line parses as a number, and the count matches the declared
    # columns exactly. Anything else still fails, loudly, by name.
    #
    # A declared label column needs no extra guard here and deliberately does
    # not get one. The header this recovers is `columns` alone, so it can never
    # name a label column, so a labelled interface whose file went through
    # recovery fails the missing-column check below either way -- measured
    # across every shape where the numeric test can fire. A branch that cannot
    # change an outcome is the kind this repo deletes rather than keeps.
    first = [f.strip() for f in lines[0].split(",")]
    if len(first) == len(columns) and all(_is_number(f) for f in first):
        lines.insert(0, ",".join(columns))

    rows = list(csv.DictReader(lines))
    if not rows:
        raise EvaluationFailure("extraction_failed", f"{path.name} has a header but no data rows")

    header = [h.strip() for h in (rows[0].keys() or []) if h]
    missing = [c for c in [*columns, *labels] if c not in header]
    if missing:
        raise EvaluationFailure(
            "extraction_failed",
            f"{path.name} is missing required column(s) {missing}; it has {header}",
        )
    if len(rows) < min_rows:
        raise EvaluationFailure(
            "extraction_failed",
            f"{path.name} has {len(rows)} data row(s); the task requires at least {min_rows}",
        )

    out: dict[str, list[float]] = {}
    for column in columns:
        values = []
        for index, row in enumerate(rows):
            raw = (row.get(column) or "").strip()
            try:
                value = float(raw)
            except ValueError:
                raise EvaluationFailure(
                    "extraction_failed",
                    f"{path.name} row {index + 1}, column {column!r}: {raw!r} is not a number",
                ) from None
            if not math.isfinite(value):
                raise EvaluationFailure(
                    "extraction_failed",
                    f"{path.name} row {index + 1}, column {column!r} is {raw!r}, not finite",
                )
            values.append(value)
        out[column] = values
    for label in labels:
        out[label] = [(row.get(label) or "").strip() for row in rows]
    return out


# ── derivations: how a KPI is computed from the interface's columns ──────────

def _log_log_slope(cols: dict[str, list[float]], spec: dict) -> float:
    """Least-squares slope of log(y) against log(x) -- an observed order.

    This is the derivation that makes a closed-form problem scorable. An order
    is not a property of the operating point, so there is nothing to recall, and
    it cannot be produced without actually solving every refinement level.
    """
    xs, ys = cols[spec["x"]], cols[spec["y"]]
    pairs = [(x, y) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pairs) < 2:
        raise EvaluationFailure(
            "extraction_failed",
            f"need >= 2 rows with positive {spec['x']} and {spec['y']} to fit a slope; "
            f"got {len(pairs)} of {len(xs)}",
        )
    lx = [math.log(x) for x, _ in pairs]
    ly = [math.log(y) for _, y in pairs]
    n = len(pairs)
    mx, my = sum(lx) / n, sum(ly) / n
    denominator = sum((x - mx) ** 2 for x in lx)
    if denominator == 0.0:
        raise EvaluationFailure(
            "extraction_failed",
            f"every row reports the same {spec['x']}; a refinement study needs distinct levels",
        )
    return sum((x - mx) * (y - my) for x, y in zip(lx, ly)) / denominator


def _value_at_extreme(cols: dict[str, list[float]], spec: dict, want_min: bool) -> float:
    key, value = cols[spec["key"]], cols[spec["value"]]
    index = min(range(len(key)), key=lambda i: key[i] if want_min else -key[i])
    return value[index]


# ── a KPI defined between two configurations the prompt pins ─────────────────
#
# CLAUDE.md makes a relation between runs the default shape for a new KPI: it
# cannot be recalled, it cannot be produced without solving twice, and the two
# runs share a mesh and a discretisation so their common-mode error cancels.
# The two constraints that come with it are both enforced here rather than
# trusted. Both endpoints are named in `spec.json`, never chosen by the
# submission -- a relation whose second endpoint the agent picks has no
# `gt_value` to score against. And every way the two rows can fail to be there
# is a *scored zero* with a named category, never an exception: an evaluator
# that raises reads downstream as infrastructure having broken.

def _fold(label: Any) -> str:
    """The spelling-insensitive form of a row label.

    Whitespace and capitalisation are not physics. A submission that solved
    both configurations correctly and wrote `Baseline` where the prompt wrote
    `baseline` is a right answer, and zeroing it is the defect class that cost
    nine CFD cases -- an evaluator reaching for a coordinate only the oracle
    had. What is *not* forgiven is a different word: the label is the identity
    of a configuration the prompt fixed.
    """
    return " ".join(str(label).split()).casefold()


def _numeric(cols: dict, name: Any, role: str) -> list[float]:
    """Fetch a column the spec named, insisting the interface declared it numeric.

    A spec pointing a derivation at a missing or textual column is *our* error
    and has to stay distinguishable from the submission's: `evaluator_error`
    sends the reader to `spec.json`, `extraction_failed` sends them to the
    agent's file.
    """
    if not isinstance(name, str) or not name:
        raise EvaluationFailure(
            "evaluator_error", f"spec.json declares no {role} column for this derivation")
    values = cols.get(name)
    if values is None:
        raise EvaluationFailure(
            "evaluator_error",
            f"spec.json names {name!r} as the {role} column and the interface does not declare it",
        )
    if values and isinstance(values[0], str):
        raise EvaluationFailure(
            "evaluator_error",
            f"spec.json names {name!r} as the {role} column while the interface declares it "
            f"under `labels`, so it holds text; a label column cannot be arithmetic",
        )
    return values


def _row_of(labels: list[str], wanted: Any, key_name: str, role: str) -> int:
    """The one row carrying `wanted` in the key column -- or a scored zero."""
    hits = [i for i, got in enumerate(labels) if _fold(got) == _fold(wanted)]
    if len(hits) == 1:
        return hits[0]
    seen: list[str] = []
    for got in labels:
        if got not in seen:
            seen.append(got)
    shown = seen[:12] + (["..."] if len(seen) > 12 else [])
    if not hits:
        raise EvaluationFailure(
            "extraction_failed",
            f"no row has {key_name}={wanted!r}, which the task names as configuration {role}; "
            f"the file's {key_name} values are {shown}",
        )
    raise EvaluationFailure(
        "extraction_failed",
        f"{len(hits)} rows have {key_name}={wanted!r} (configuration {role}); the task requires "
        f"exactly one, because which of them is the reported configuration is otherwise undefined",
    )


def _pair(cols: dict, spec: dict, ratio: bool) -> float:
    """Combine the two named rows: `b / a` for a ratio, `b - a` for a delta.

    `a` is the reference configuration and `b` the changed one, so the number
    reads as *what the change did* -- the direction an engineer asks the
    question in, and the direction `unity_lewis_speed_ratio` already uses
    (alternative closure over reference closure).
    """
    key_name = spec.get("key")
    if not isinstance(key_name, str) or not key_name:
        raise EvaluationFailure(
            "evaluator_error", "spec.json declares no `key` column for this derivation")
    labels = cols.get(key_name)
    if labels is None or (labels and not isinstance(labels[0], str)):
        raise EvaluationFailure(
            "evaluator_error",
            f"spec.json names {key_name!r} as the key column; it must be declared in the "
            f"interface's `labels` so it is read as text rather than parsed as a number",
        )
    a_wanted, b_wanted = spec.get("a"), spec.get("b")
    if a_wanted is None or b_wanted is None:
        raise EvaluationFailure(
            "evaluator_error", "spec.json must name both endpoints, `a` and `b`, for this derivation")
    if _fold(a_wanted) == _fold(b_wanted):
        raise EvaluationFailure(
            "evaluator_error",
            f"spec.json names the same configuration {a_wanted!r} as both endpoints; the relation "
            f"is then the constant {1.0 if ratio else 0.0}, which measures nothing",
        )

    values = _numeric(cols, spec.get("value"), "value")
    a = values[_row_of(labels, a_wanted, key_name, "a")]
    b = values[_row_of(labels, b_wanted, key_name, "b")]
    if not ratio:
        return b - a
    if a == 0.0:
        raise EvaluationFailure(
            "extraction_failed",
            f"the reference configuration {a_wanted!r} reports {spec['value']} = 0, so a ratio "
            f"against it is undefined",
        )
    out = b / a
    if not math.isfinite(out):
        # Reached when |a| is small enough that the quotient overflows. There is
        # deliberately no epsilon below which a denominator is "too small": an
        # invented one is a threshold that can zero a correct answer, and where
        # a ratio stops being physical is what the KPI's own physics window
        # already says. This branch only refuses a number arithmetic cannot
        # represent.
        raise EvaluationFailure(
            "extraction_failed",
            f"{spec['value']} = {b!r} over {a!r} does not evaluate to a finite ratio",
        )
    return out


DERIVATIONS = {
    "log_log_slope": _log_log_slope,
    "value_at_min": lambda c, s: _value_at_extreme(c, s, True),
    "value_at_max": lambda c, s: _value_at_extreme(c, s, False),
    "single_row": lambda c, s: c[s["value"]][0],
    "pair_ratio": lambda c, s: _pair(c, s, True),
    "pair_delta": lambda c, s: _pair(c, s, False),
}

# What each relation returns when the submission reports the same thing for both
# configurations -- "nothing changed", produced without solving the second one.
NULL_ANSWER = {"pair_ratio": 1.0, "pair_delta": 0.0}


def null_answer_margin(derivation: dict, kpi: dict) -> float | None:
    """How far a KPI's `gt_value` sits from "nothing changed", in band widths.

    **A relation's anti-recall property is not free, and this is the number that
    prices it.** #406 built one, reported the reference twice so the ratio was
    exactly 1.000, and it scored **1.0** on two flames whose closures differ by
    less than the band. #410 (2) then hit the same wall on a different track, a
    different solver and a different KPI: a `kOmegaSST / kOmega` ratio of 1.0144
    is settled to 0.0108 of its threshold -- eleven times steadier than either
    scalar -- and 1.0 is inside its band, so the unrepaired case scores full
    marks with no solve. Two independent instances make it a property of the
    shape rather than a quirk of a family.

    Both readings are the same knob: **the more completely a relation cancels
    common mode, the closer it sits to its own null answer.** So the quantity a
    case author needs is one number -- how many band widths separate `gt_value`
    from what typing the null costs nothing to produce -- and it is reported
    beside every relation KPI rather than left to each case to rediscover.

    Under the flat 5% band of `docs/acceptance.md` it has a closed form worth
    knowing before a case is written: a `pair_delta` sits at exactly 20 band
    widths whatever its `gt`, while a `pair_ratio` sits at `20 * |1/gt - 1|`,
    which drops below 1 -- the null answer scores -- for any `gt` inside
    [1/1.05, 1/0.95] = [0.9524, 1.0526]. Measured instances on both sides: a
    packaging TIM change of 15% gives 3.58 band widths and a change of 4.6%
    gives 0.95, and only the second is a case whose answer can be typed.

    Returns `None` for a derivation with no null answer, which is every
    derivation that is not a relation.
    """
    from .score import pass_tol

    null = NULL_ANSWER.get(derivation.get("derive"))
    if null is None:
        return None
    tol = pass_tol(kpi)
    if not tol > 0:
        return None
    return abs(null - float(kpi["gt_value"])) / tol


def derive(cols: dict[str, list[float]], spec: dict) -> float:
    kind = spec.get("derive")
    if kind not in DERIVATIONS:
        raise EvaluationFailure(
            "evaluator_error",
            f"unknown derivation {kind!r}; spec.json must use one of {sorted(DERIVATIONS)}",
        )
    return float(DERIVATIONS[kind](cols, spec))


# ── scoring ──────────────────────────────────────────────────────────────────

def score_kpis(cols: dict[str, list[float]], derivations: dict, kpis: dict) -> tuple[float, dict]:
    """Per-KPI `physics_pass * band_pass`, then the group-weighted mean.

    Same shape as every other track, and binary in both factors: a value
    outside its physics window and a value outside its tolerance band are
    both simply wrong, and neither earns partial credit.
    """
    per_kpi: dict[str, Any] = {}
    for name, derivation in derivations.items():
        kpi = kpis.get(name)
        if kpi is None:
            raise EvaluationFailure("evaluator_error", f"spec.json derives {name!r}, kpis.json has no such KPI")
        value = derive(cols, derivation)
        gt = float(kpi["gt_value"])
        error = abs(value - gt)
        low, high = float(kpi["physics_min"]), float(kpi["physics_max"])
        if not (low <= value <= high):
            score, reason = 0.0, f"outside the physics window [{low}, {high}]"
        else:
            score, reason = band_verdict(error, kpi)
        per_kpi[name] = {
            "value": value,
            "gt_value": gt,
            "absolute_error": error,
            "score": round(score, 4),
            "reason": reason,
            "group": kpi.get("group", "outputs"),
        }
        # Diagnostic, never a gate: it is a property of the contract, identical
        # for every submission, so it can neither help nor hurt one. What it is
        # for is the moment a case is authored -- the oracle run the case-PR bar
        # already requires writes it into `reward_detail.json`, which is where
        # #406 and #410 (2) each had to go and measure it by hand instead.
        # One number, not a number plus a verdict on it: `<= 1` is the whole
        # rule and spelling it as a second field would invite reading it as a
        # gate, which it must not become -- it is a property of the contract,
        # identical for every submission, so gating on it would refuse a case
        # rather than a submission.
        margin = null_answer_margin(derivation, kpi)
        if margin is not None:
            per_kpi[name]["null_answer_margin_band_widths"] = round(margin, 4)

    groups: dict[str, list[float]] = {}
    for entry in per_kpi.values():
        groups.setdefault(entry["group"], []).append(entry["score"])
    weights = {g: 1.0 / len(groups) for g in groups}
    total = sum(weights[g] * (sum(s) / len(s)) for g, s in groups.items())
    return total, per_kpi


# ── running the submission's own entry point ─────────────────────────────────

def run_entry_point(
    case: Path,
    command: str,
    *,
    timeout_s: int,
    log_path: Path,
    env_prefix: str = "",
) -> dict[str, Any]:
    """Run the rerun command in `case`, capturing its output under a deadline.

    The process group, not the parent shell, is what gets signalled on timeout.
    A solver is a child of the entry-point script; killing only bash leaves the
    solver holding the output pipes, which made a configured deadline read tens
    of seconds long on the CFD track before it was fixed there.
    """
    script = f"{env_prefix}cd {shell_quote(str(case))} && {command}"
    started = time.monotonic()
    proc = subprocess.Popen(
        ["bash", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _signal_group(proc, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_group(proc, getattr(signal, "SIGKILL", 9))
            stdout, stderr = proc.communicate()
        _write_log(log_path, (stdout or "") + (stderr or ""))
        raise RuntimeError(f"command timed out after {timeout_s}s: {command}") from exc

    output = (stdout or "") + (stderr or "")
    _write_log(log_path, output)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {proc.returncode}: {command}; {output[-800:]}"
        )
    return {
        "command": command,
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": proc.returncode,
        "log": log_path.name,
    }


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, sig)
        elif sig == signal.SIGTERM:
            proc.terminate()
        else:
            proc.kill()
    except ProcessLookupError:
        pass


def _write_log(log_path: Path, output: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
