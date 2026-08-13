#!/usr/bin/env python3
"""The packaging track's shared evaluator: reproduce, then read the declared interface.

Same contract as `openfoam_interface`, and deliberately the same twenty lines
around a different pair of solver facts:

* **what to strip** -- CalculiX writes its answer into `.frd` / `.dat` / `.sta`
  / `.cvg` beside the deck. Those go, together with the interface file itself,
  so the rerun has to solve rather than echo. The `.inp` deck, any `.msh` or
  `.geo`, and the driver scripts stay: they are the submission's *inputs*, and
  a case that pre-generates its mesh has done nothing wrong.
* **what the rerun is** -- `bash ./run_case.sh` at the submission root. The
  prompt names that file and nothing else about how the analysis is driven.

After the rerun, the reproduced tree must contain a CalculiX result database.
Without it a submission could ship a `run_case.sh` whose whole body is `printf`
of the right numbers, reproduce perfectly, and score 1.0. It is admissible
under CLAUDE.md's rule for assertions -- it fails a submission the tolerance
band would otherwise pass, and it traces to the sentence in `instruction.md`
requiring the deliverable to regenerate the result by solving. It never opens
the deck.

**It asks `has_result_database`, not the detector's permissive
`has_solver_evidence`**, and that distinction is the whole of #304. The
permissive predicate also accepts a CalculiX banner inside any `.log` / `.txt`
/ `.out`, and `printf 'CalculiX Version 2.17' > notes.txt` satisfies it: the
same submission scored 0.000 without that file and **1.000** with it. The
repair is not to add `.txt` to the strip list -- a string is not evidence a
solver ran at any suffix, so the branch is gone from the gate entirely and
`.md`, an extension-less name and a comment line in `results.csv` all die with
it. What remains admissible is the solver's own serialisation, and the two
lists that have to agree now agree by construction: `GENERATED_SUFFIXES` is
*built from* the suffixes the strict predicate will open, so nothing the gate
accepts can survive the strip.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .csv_interface import EvaluationFailure, read_interface, run_entry_point, score_kpis
from .detectors import TrialContext
from .detectors.calculix import (
    RESULT_DATABASE_SUFFIXES,
    has_result_database,
    has_solver_evidence,
)
from .native_openfoam import write_reward

DEFAULT_REPRODUCTION_TIMEOUT_S = 2400
ENTRY_POINT = "run_case.sh"

# Every extension CalculiX writes on a run. `.inp` is absent on purpose -- it is
# the deck, which the agent authors, and deleting it would delete the case.
#
# The evidence suffixes lead, and they are imported rather than retyped: the
# invariant this list exists to hold is *everything the gate can accept is
# deleted before the rerun*, and #304 is what it cost to maintain the two ends
# of that sentence separately. `test_the_strip_deletes_everything_the_gate_can_
# accept` drives it as behaviour, so adding an accepted suffix without adding
# it here fails rather than reopening the hole.
GENERATED_SUFFIXES = RESULT_DATABASE_SUFFIXES + (
    ".sta", ".cvg", ".12d", ".out", ".log", ".eig", ".rout", ".rin",
)


def strip_generated(root: Path, interface_files: tuple[str, ...]) -> list[str]:
    """Delete everything a run produces, so the rerun has to produce it again."""
    removed: list[str] = []
    for name in interface_files:
        target = root / name
        if target.exists():
            target.unlink()
            removed.append(name)
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name.lower().endswith(GENERATED_SUFFIXES):
            removed.append(str(path.relative_to(root)))
            path.unlink()
    return removed


def validate_submission(case: Path) -> None:
    entry = case / ENTRY_POINT
    if not entry.is_file() or entry.stat().st_size == 0:
        raise EvaluationFailure(
            "invalid_submission",
            f"missing reproducible case inputs: {ENTRY_POINT} at the submission root",
        )


def main_from_case(tests_dir: Path) -> int:
    """The whole per-case evaluator. A case's `tests/test.sh` calls this and stops."""
    spec = json.loads((tests_dir / "spec.json").read_text(encoding="utf-8"))
    kpis = json.loads((tests_dir / "kpis.json").read_text(encoding="utf-8"))["kpis"]

    submission = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    reward_dir = Path(os.environ.get("SIM_BENCH_REWARD_DIR", "/logs/verifier"))
    interface = spec["interface"]
    budget = int(spec.get("reproduction_timeout_s", DEFAULT_REPRODUCTION_TIMEOUT_S))

    detail: dict[str, Any] = {
        "schema_version": "calculix-interface-v1",
        "case_id": spec["case_id"],
        "evaluator_owned_reproduction": True,
        "evaluator_owned_extraction": False,
        "interface": interface,
        "status": "running",
        "stage": "submission_validation",
        "checks": {},
    }
    try:
        validate_submission(submission)
        detail["checks"]["reproducible_case_inputs"] = "passed"

        with tempfile.TemporaryDirectory(prefix=f"{spec['case_id']}-evaluator-") as temp:
            work = Path(temp) / "case"
            shutil.copytree(submission, work)
            detail["removed_prior_artifacts"] = strip_generated(work, (interface["file"],))

            detail["stage"] = "reproduction"
            try:
                run = run_entry_point(
                    work, f"bash ./{ENTRY_POINT}",
                    timeout_s=budget,
                    log_path=reward_dir / "evaluator_run_case.log",
                )
            except Exception as exc:
                category = ("reproduction_timeout" if "timed out after" in str(exc)
                            else "reproduction_failed")
                raise EvaluationFailure(category, str(exc)) from exc
            detail["reproduction"] = {**run, "timeout_s": budget}

            detail["stage"] = "solver_evidence"
            ctx = TrialContext(case_dir=work, solver_label="calculix")
            # Both readings are recorded and only the strict one gates. Keeping
            # the permissive one visible costs nothing and separates two
            # different failures in `reward_detail.json`: a rerun that wrote a
            # banner and no results is a solver that died, while one that wrote
            # nothing at all never started a solver. A detail file that cannot
            # tell them apart sends the reader to the wrong layer.
            evidence = {
                "result_database": has_result_database(ctx),
                "any_solver_artifact": has_solver_evidence(ctx),
            }
            detail["solver_evidence"] = evidence
            if not evidence["result_database"]:
                raise EvaluationFailure(
                    "invalid_physics_setup",
                    "the rerun left no CalculiX result database -- no .frd holding "
                    "the model ccx assembled together with solved values (its own "
                    "result blocks, or the .dat printed beside it)"
                    + (" (a CalculiX banner is present, so something wrote text "
                       "and no results)" if evidence["any_solver_artifact"] else "")
                    + f"; {interface['file']} was not produced by solving",
                )
            detail["checks"]["solver_evidence"] = "passed"

            detail["stage"] = "extraction"
            cols = read_interface(
                work / interface["file"],
                list(interface["columns"]),
                int(interface.get("min_rows", 1)),
                list(interface.get("labels") or ()),
            )
            detail["interface_rows"] = len(next(iter(cols.values())))

            detail["stage"] = "scoring"
            score, per_kpi = score_kpis(cols, spec["kpis"], kpis)
            detail["scoring_components"] = per_kpi
            detail["status"] = "completed"
            detail["stage"] = "complete"
            write_reward(reward_dir, score, detail)
            return 0

    except EvaluationFailure as exc:
        detail["status"] = "failed"
        detail["failure_category"] = exc.category
        detail["error"] = str(exc)
        write_reward(reward_dir, 0.0, detail)
        return 0
    except Exception as exc:  # an evaluator bug must stay distinguishable from a bad submission
        detail["status"] = "failed"
        detail["failure_category"] = "evaluator_error"
        detail["error"] = f"{type(exc).__name__}: {exc}"
        write_reward(reward_dir, 0.0, detail)
        return 0
