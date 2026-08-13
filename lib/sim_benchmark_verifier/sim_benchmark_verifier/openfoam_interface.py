#!/usr/bin/env python3
"""The CFD track's shared evaluator: reproduce, then read the declared interface.

The contract is CLAUDE.md's "The output interface". A case's `instruction.md`
names a file and its columns; the submission's own `Allrun` writes it; this
evaluator re-runs `Allrun` from a clean copy and reads that file. It never opens
`system/`, `constant/` or a boundary keyword, so none of the agent's legal
choices can enter the score.

The module it replaces did the opposite -- `native_openfoam.evaluate` hands each
case an `extract_and_score` callback that goes and finds the number itself, which
means probing a mesh the task deliberately left free. Nine of nineteen cfd cases
encoded one of the oracle's arbitrary choices that way (#21): its `z`, its slab
thickness, its `TRef`, its spelling of `noSlip`. There is no seam here for that
to enter through, which is why the 100 generated cases sharing two evaluators
have never had one.

What differs between two cases is `tests/spec.json` and `tests/kpis.json` -- data,
not code. A case needing a line of code here means the interface is wrong.

**The rerun alone is not the whole gate, and the hole was measured.** `bash
./Allrun` is arbitrary shell, so an `Allrun` whose whole body is a `printf` of
the right number reproduces perfectly: in `sim-benchmark-cfd-fullstack:latest`
on `lid_driven_cavity_ghia_re100`, three empty directories plus that one-line
`Allrun` scored **1.0** (#196). What closes it is the same check
`calculix_interface` has had all along -- after the rerun, ask whether the
reproduced tree contains solver output -- and the reason it is admissible under
CLAUDE.md's rule is that it fails a submission the tolerance band passes,
which is exactly what that 1.0 was.

Two things about *where* it sits are the whole point. It runs against the
**evaluator's own** directory, not against what the submission handed over, so
a shipped `polyMesh/` proves nothing and forging it means making the rerun
actually mesh and solve. And it asks `has_mesh_and_solution`, not the
detector's permissive `has_solver_evidence`: the latter also accepts any
`log.*`, which `: > log.simpleFoam` would satisfy. Mesh plus a solved time
directory is what thirteen cfd `kpis.json` already claim about themselves, so
wiring this in is what makes that sentence true rather than aspirational.

**What the strict predicate reads is the serialisation, and that is a second
repair rather than the original one.** As landed in #211 it asked only whether
three files existed, and #361 priced that: `mkdir -p constant/polyMesh 1` plus
three `printf`s of the literal words `not a mesh` / `not a field` took
`lid_driven_cavity_ghia_re100` back to **1.000** through this very gate, while
a `bare` arm without them scored 0.000. It now reads what OpenFOAM's own writer
puts in those files — the object's class, and the records a list holds against
the count it declares — which is the same check `calculix._frd_holds_the_model`
has made all along and is where the ~5x asymmetry between the two live tracks
came from (#377). It is still a format check and touches nothing the agent
chose: not a scheme, not a boundary condition, not a dictionary entry.

Whether the check can zero a *correct* run was measured before it landed, not
argued: all nineteen cfd oracles were re-run in the real image and every one
left `constant/polyMesh` plus a non-zero time directory in the evaluator's copy
(#211). The `preserve` mechanism is what keeps the two task-supplied grids
honest here -- their mesh is an input, so it survives the strip, and the time
directory is still theirs to produce.

Reading the interface, deriving a KPI from its columns and scoring the result
are solver-neutral and live in `csv_interface`; they are re-exported here so a
case's `verify.py` keeps importing them from the track it belongs to. What stays
is the OpenFOAM-specific pair: which generated artifacts the rerun must be made
to produce again, and what the rerun command is.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .csv_interface import (  # noqa: F401 -- re-exported for cases and tests
    DERIVATIONS,
    derive,
    read_interface,
    score_kpis,
)
from .detectors import TrialContext
from .detectors.openfoam import (
    has_mesh_and_solution,
    has_solver_evidence,
    mesh_and_solution_files_present,
)
from .native_openfoam import (  # noqa: F401 -- is_case_root re-exported for cases and tests
    EvaluationFailure,
    every_directory,
    is_case_root,
    is_generated,
    openfoam_command,
    validate_submission,
    write_reward,
)

DEFAULT_REPRODUCTION_TIMEOUT_S = 1800


# ── stripping generated state ────────────────────────────────────────────────

def strip_generated(root: Path, interface_files: tuple[str, ...],
                    preserve: tuple[str, ...] = ()) -> list[str]:
    """Delete everything a run produces, so the rerun has to produce it again.

    Includes **the interface file itself**. Leaving it behind would let a
    submission ship a hand-written answer and never be asked to reproduce it,
    which is the whole gate this contract rests on.

    **The reach is the whole tree, and it is the whole tree because that is what
    the gate reads.** `detectors.openfoam.has_mesh_and_solution` globs
    `polyMesh` and numeric time directories with `rglob` from the submission
    root, so the invariant worth holding is not "walk the same directories the
    submission's cases are in" but the falsifiable one: *after this returns, the
    gate must be false and no interface file may remain anywhere.* The earlier
    form scanned only case roots and deleted `constant/polyMesh` under each,
    which left two things the gate can still see -- a `polyMesh` or a solved
    time directory parked in a directory with no `system/` in it
    (`solved/run_a/1000/U`), and, once `validate_submission` stopped pinning the
    case to the submission root, everything at the submission root itself, which
    is the one directory the entry point actually runs in.

    `0/` survives, because it is an input directory. That is a known hole: a
    steady case can ship its converged field as `0/U` with a `residualControl`
    one iteration satisfies, and the rerun then echoes the agent's own answer
    (CLAUDE.md, and the withheld `turbulent_channel_flow_retau395`). A KPI that
    is a *relation between runs* closes it by construction -- seeding every grid
    with the exact field drives the error to round-off on all of them, and the
    fitted order is then noise rather than the scheme's. Cases whose KPI is a
    value still need the case-level answer, which is to change the KPI.
    """
    removed: list[str] = []
    # `preserve` names paths the TASK supplied, which the submission must not
    # have to regenerate -- a published grid handed over in `environment/`,
    # typically `constant/polyMesh`. Stripping those breaks the rerun outright:
    # the mesh is an input to the case, not an artefact of it, and only the case
    # knows which. Nothing is preserved by default.
    kept = {Path(item) for item in preserve}

    for name in interface_files:
        # At any depth. A submission that ships `run_a/results.csv` and an
        # `Allrun` that copies it up is never asked to reproduce its number,
        # and the file name is the one thing the contract fixes.
        for target in sorted({root / name, *root.rglob(name)}):
            if target.exists():
                target.unlink()
                removed.append(str(target.relative_to(root)))

    for directory in every_directory(root):
        if not directory.is_dir():  # a previous iteration removed it
            continue
        for child in sorted(directory.iterdir()):
            # What counts as generated is one definition, in `native_openfoam`,
            # because the same answer has to hold for the other stripper and for
            # the detector this all has to agree with. #199 is the exemption
            # inside it worth remembering here: a numerically-named directory
            # that is ITSELF a case root is a refinement level, and deleting
            # those scored 0.0 for a submission that matched the oracle to ten
            # significant figures.
            drop = is_generated(child)
            if drop and child.relative_to(root) in kept:
                drop = False
            if drop:
                removed.append(str(child.relative_to(root)))
                shutil.rmtree(child) if child.is_dir() else child.unlink()

    return sorted(set(removed))


# ── entry point ──────────────────────────────────────────────────────────────

def main_from_case(tests_dir: Path) -> int:
    """The whole per-case evaluator. A case's `tests/test.sh` calls this and stops."""
    spec = json.loads((tests_dir / "spec.json").read_text(encoding="utf-8"))
    kpis = json.loads((tests_dir / "kpis.json").read_text(encoding="utf-8"))["kpis"]

    submission = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    reward_dir = Path(os.environ.get("SIM_BENCH_REWARD_DIR", "/logs/verifier"))
    interface = spec["interface"]
    budget = int(spec.get("reproduction_timeout_s", DEFAULT_REPRODUCTION_TIMEOUT_S))

    detail: dict[str, Any] = {
        "schema_version": "openfoam-interface-v1",
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
            detail["removed_prior_artifacts"] = strip_generated(
                work, (interface["file"],), tuple(spec.get("preserve") or ()))

            detail["stage"] = "reproduction"
            try:
                run = openfoam_command(
                    work, "bash ./Allrun",
                    timeout_s=budget,
                    log_path=reward_dir / "evaluator_Allrun.log",
                )
            except Exception as exc:
                category = ("reproduction_timeout" if "timed out after" in str(exc)
                            else "reproduction_failed")
                raise EvaluationFailure(category, str(exc)) from exc
            detail["reproduction"] = {**run, "timeout_s": budget}

            detail["stage"] = "solver_evidence"
            ctx = TrialContext(case_dir=work, solver_label="openfoam")
            # Three readings, and only the strict one gates. The other two are
            # worth keeping visible because they name *which* failure this is,
            # and a reward_detail.json that cannot tell them apart sends the
            # reader to the wrong layer: nothing ran at all, something ran and
            # logged but wrote no field, or files with the right names are
            # there and are not what OpenFOAM writes. The third is the one
            # #377 measured at 1.000 before the gate read the format.
            evidence = {
                "mesh_and_solution": has_mesh_and_solution(ctx),
                "mesh_and_solution_files_present": mesh_and_solution_files_present(ctx),
                "any_solver_artifact": has_solver_evidence(ctx),
            }
            detail["solver_evidence"] = evidence
            if not evidence["mesh_and_solution"]:
                if evidence["mesh_and_solution_files_present"]:
                    why = ("files named points/faces/<field> are there and do not "
                           "read as OpenFOAM output -- a wrong class, or a list "
                           "shorter than its own declared count")
                elif evidence["any_solver_artifact"]:
                    why = "a solver log is present, so something ran and wrote no field"
                else:
                    why = "nothing the solver writes is there at all"
                raise EvaluationFailure(
                    "invalid_physics_setup",
                    "the rerun left no OpenFOAM solution -- no serialised polyMesh/ "
                    "with a non-zero time directory holding a field "
                    f"({why}); {interface['file']} was not produced by solving",
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
            # `scoring_components`, not a tenth name for the same thing.
            # `run_oracle_into_store._find_value` already carries nine branches
            # because each native cfd grader invented its own shape, and a KPI it
            # cannot find ingests as null -- the score still lands, so the store
            # looks fine and every per-KPI view of it is empty. Speaking a shape
            # the reader already knows costs nothing and is checked by
            # tools/tests/test_store_reads_evaluator_output.py.
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
