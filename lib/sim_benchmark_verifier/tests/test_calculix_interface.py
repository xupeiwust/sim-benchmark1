"""The packaging evaluator, exercised where it can be exercised without CalculiX.

Reproduction needs a solver, so that stage is covered on a host with the image.
What is pure -- deciding which files are the run's output and which are its
inputs, and refusing a submission whose rerun solved nothing -- is here, because
both are the difference between a gate and a formality.

`TestResultDatabase` is #304 written as a test. The gate used to accept a
CalculiX banner in any text file, so the same printf submission scored 0.000
alone and 1.000 beside a two-line `notes.txt`. What is asserted below is the
class, not that one spelling: a string is not evidence at any suffix.
"""
from __future__ import annotations

import json

import pytest

from sim_benchmark_verifier import calculix_interface as cx
from sim_benchmark_verifier.calculix_interface import (
    ENTRY_POINT,
    GENERATED_SUFFIXES,
    strip_generated,
    validate_submission,
)
from sim_benchmark_verifier.detectors import TrialContext
from sim_benchmark_verifier.detectors.calculix import (
    RESULT_DATABASE_SUFFIXES,
    has_result_database,
    has_solver_evidence,
)
from sim_benchmark_verifier.native_openfoam import EvaluationFailure


# ── fixtures shaped like what ccx actually writes ───────────────────────────
#
# Trimmed from a real `pkg25d_thermal_*` oracle run on the domain image: the
# block headers, their declared counts and the record prefixes are that file's,
# with the mesh shrunk to one hex so a test can hold it.

def frd_text(*, nodes: int = 8, node_records: int | None = None,
             elements: int = 1, results: bool = False) -> str:
    """A CalculiX `.frd`. Defaults are a well-formed single-element model."""
    lines = [
        "    1C",
        "    1UPGM               CalculiX                                        ",
        "    1UVERSION           Version 2.17                             ",
        f"    2C                         {nodes:5d}                                     1",
    ]
    for i in range(nodes if node_records is None else node_records):
        lines.append(f" -1{i + 1:10d} {i:.5E} 0.00000E+00 0.00000E+00")
    lines.append(" -3")
    lines.append(f"    3C                         {elements:5d}                                     1")
    for e in range(elements):
        lines.append(f" -1{e + 1:10d}    1    0    1")
        lines.append(" -2" + "".join(f"{n:10d}" for n in range(1, 9)))
    lines.append(" -3")
    if results:
        lines += [
            "    1PSTEP                         1",
            "  100CL  101 1.000000000E+00" + f"{nodes:12d}",
            " -4  NDTEMP      1    1",
            " -5  T           1    1    0    0",
        ]
        for i in range(nodes):
            lines.append(f" -1{i + 1:10d} 3.00000E+02")
        lines.append(" -3")
    lines.append(" 9999")
    return "\n".join(lines) + "\n"


def dat_text() -> str:
    """A `*NODE PRINT` block, caption line and records as ccx spells them."""
    return (
        "\n temperatures for set NALL and time  0.1000000E+01\n\n"
        "         1  3.198326E+01\n         2  3.209583E+01\n"
    )


def _submission(root):
    """A submission holding both its inputs and a completed run's output."""
    (root / ENTRY_POINT).write_text("#!/usr/bin/env bash\nccx -i thermal\n", encoding="utf-8")
    (root / "build_deck.py").write_text("# writes thermal.inp", encoding="utf-8")
    (root / "package.msh").write_text("$MeshFormat", encoding="utf-8")
    run = root / "run"
    run.mkdir()
    (run / "thermal.inp").write_text("*HEADING", encoding="utf-8")
    (run / "thermal.dat").write_text(dat_text(), encoding="utf-8")
    (run / "thermal.frd").write_text(frd_text(), encoding="utf-8")
    (run / "thermal.sta").write_text("1 1", encoding="utf-8")
    (run / "thermal.log").write_text("CalculiX Version 2.17", encoding="utf-8")
    (root / "results.csv").write_text("t_asic_max_c\n112.1\n", encoding="utf-8")
    return root


def _ctx(root):
    return TrialContext(case_dir=root, solver_label="calculix")


class TestStripGenerated:
    def test_removes_the_run_and_keeps_what_built_it(self, tmp_path):
        """The deck, the mesh and the driver are inputs; deleting them would
        delete the case rather than force it to be re-solved."""
        _submission(tmp_path)
        strip_generated(tmp_path, ("results.csv",))

        run = tmp_path / "run"
        for gone in ("thermal.dat", "thermal.frd", "thermal.sta", "thermal.log"):
            assert not (run / gone).exists(), gone
        assert not (tmp_path / "results.csv").exists()

        assert (run / "thermal.inp").exists()
        assert (tmp_path / "package.msh").exists()
        assert (tmp_path / "build_deck.py").exists()
        assert (tmp_path / ENTRY_POINT).exists()

    def test_reports_what_it_removed(self, tmp_path):
        _submission(tmp_path)
        removed = strip_generated(tmp_path, ("results.csv",))
        assert "results.csv" in removed
        assert any(name.endswith("thermal.frd") for name in removed)

    def test_leaves_the_answer_nowhere_to_hide(self, tmp_path):
        """Nested however deep, a result file is still a result file. A
        submission that tucks its `.frd` under three directories would otherwise
        keep a solved state the rerun never has to reproduce."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "static.frd").write_text("solved", encoding="utf-8")
        strip_generated(tmp_path, ())
        assert not (deep / "static.frd").exists()

    def test_the_strip_deletes_everything_the_gate_can_accept(self, tmp_path):
        """The invariant #304 broke, driven as behaviour rather than as a
        set comparison between two tuples.

        A submission carrying a complete, genuine result database at every
        suffix the gate will open -- at the root, nested, and upper-cased --
        must satisfy the gate before the strip and fail it after. Whatever the
        accepted set grows to, the strip has to keep up or this goes red.
        """
        deep = tmp_path / "out" / "run"
        deep.mkdir(parents=True)
        for stem_dir in (tmp_path, deep):
            for suffix in RESULT_DATABASE_SUFFIXES:
                body = frd_text(results=True) if suffix == ".frd" else dat_text()
                (stem_dir / f"job{suffix}").write_text(body, encoding="utf-8")
                (stem_dir / f"upper{suffix.upper()}").write_text(body, encoding="utf-8")

        assert has_result_database(_ctx(tmp_path)), "the fixture is not evidence"
        strip_generated(tmp_path, ())
        assert not has_result_database(_ctx(tmp_path))

    def test_every_accepted_suffix_is_in_the_strip_list(self):
        """The same invariant read statically -- cheap, and it names the defect
        directly when the behavioural test above goes red for a subtler reason."""
        assert set(RESULT_DATABASE_SUFFIXES) <= set(GENERATED_SUFFIXES)


class TestValidateSubmission:
    def test_accepts_a_submission_with_the_entry_point(self, tmp_path):
        (tmp_path / ENTRY_POINT).write_text("#!/bin/sh\n", encoding="utf-8")
        validate_submission(tmp_path)

    @pytest.mark.parametrize("body", ["", None])
    def test_rejects_a_missing_or_empty_entry_point(self, tmp_path, body):
        if body is not None:
            (tmp_path / ENTRY_POINT).write_text(body, encoding="utf-8")
        with pytest.raises(EvaluationFailure) as raised:
            validate_submission(tmp_path)
        assert raised.value.category == "invalid_submission"


class TestResultDatabase:
    """The strict predicate -- the one that decides the score.

    Stripping alone cannot tell a rerun that solved from one that printed: a
    `run_case.sh` whose whole body is a `cat > results.csv` reproduces
    perfectly and would score 1.0.
    """

    def test_a_completed_run_passes(self, tmp_path):
        _submission(tmp_path)
        assert has_result_database(_ctx(tmp_path))

    def test_results_written_into_the_frd_pass_without_any_dat(self, tmp_path):
        """`*NODE FILE` instead of `*NODE PRINT` is an ordinary, legal choice
        and leaves the answer inside the `.frd`. Requiring a `.dat` would zero
        it."""
        (tmp_path / "model.frd").write_text(frd_text(results=True), encoding="utf-8")
        assert has_result_database(_ctx(tmp_path))

    def test_a_deck_without_a_run_does_not(self, tmp_path):
        """The `.inp` is what the answerer wrote, not what the solver produced."""
        (tmp_path / "thermal.inp").write_text("*HEADING", encoding="utf-8")
        (tmp_path / "results.csv").write_text("t_asic_max_c\n112.1\n", encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    def test_a_hand_written_answer_alone_does_not(self, tmp_path):
        (tmp_path / ENTRY_POINT).write_text("#!/bin/sh\necho 112.1\n", encoding="utf-8")
        (tmp_path / "results.csv").write_text("t_asic_max_c\n112.1\n", encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    # The measured hole, and every other spelling of it. `.txt` is the one that
    # was tried; the point of the list is that no member of it is special.
    @pytest.mark.parametrize("name", [
        "notes.txt", "NOTES.TXT", "notes.md", "solver_notes", "run/ccx.log",
        "spooles.out", "README", "log.ccx", "results.csv",
    ])
    def test_a_calculix_banner_is_not_evidence_whatever_it_is_written_into(
        self, tmp_path, name,
    ):
        """#304: `printf 'CalculiX Version 2.17\\nJob finished\\n' > notes.txt`
        beside a printf submission took it from 0.000 to 1.000.

        The repair is not that `.txt` joined a list. A banner is a string, a
        string is not a solver run, and the gate no longer reads text at all --
        so the file it is written into stops mattering, which is the only form
        of this fix that a tenth spelling cannot walk around.
        """
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("CalculiX Version 2.17\nJob finished\n", encoding="utf-8")
        (tmp_path / ENTRY_POINT).write_text("#!/bin/sh\nprintf 112.1\n", encoding="utf-8")

        assert not has_result_database(_ctx(tmp_path))
        # ...and the permissive predicate is *why* this test exists: it still
        # says yes for the two suffixes it scans, which is exactly the reading
        # an evaluator must not gate on.
        if name.lower().endswith((".txt", ".log", ".out")):
            assert has_solver_evidence(_ctx(tmp_path))

    def test_a_numeric_data_file_borrowed_from_the_image_is_not_evidence(self, tmp_path):
        """The domain image ships `.dat` files with exactly the shape of a print
        block -- scipy's `Norris.dat` is caption lines then numeric rows -- so a
        `run_case.sh` doing one `cp` would satisfy a `.dat`-only gate. It ships
        no `.frd`, and the `.frd` is the anchor."""
        (tmp_path / "model.dat").write_text(
            "               Calibration of Ozone Monitors.\n\n"
            "     y          x\n     0.1  0.2\n     0.3  0.4\n",
            encoding="utf-8",
        )
        assert not has_result_database(_ctx(tmp_path))

    def test_an_frd_that_is_only_a_name_is_not_evidence(self, tmp_path):
        (tmp_path / "model.frd").write_text("binary-ish\n", encoding="utf-8")
        (tmp_path / "model.dat").write_text(dat_text(), encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    def test_an_frd_whose_counts_do_not_match_its_records_is_not_evidence(self, tmp_path):
        """ccx's own header count always agrees with its own records, so a
        mismatch is a hand-written file rather than a coarse mesh. Checking the
        format instead of a size keeps this from ever failing a real run."""
        (tmp_path / "model.frd").write_text(
            frd_text(nodes=8, node_records=2), encoding="utf-8",
        )
        (tmp_path / "model.dat").write_text(dat_text(), encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    def test_an_empty_model_is_not_a_model(self, tmp_path):
        (tmp_path / "model.frd").write_text(
            frd_text(nodes=0, elements=0), encoding="utf-8",
        )
        (tmp_path / "model.dat").write_text(dat_text(), encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    def test_a_solve_that_died_leaves_the_model_and_no_values(self, tmp_path):
        """ccx writes the model into the `.frd` before the step results, so a
        crashed run leaves the first half without the second. That is a
        different failure from never starting, and it must not score."""
        (tmp_path / "model.frd").write_text(frd_text(), encoding="utf-8")
        (tmp_path / "model.log").write_text(
            "CalculiX Version 2.17\n *ERROR: singular matrix\n", encoding="utf-8",
        )
        assert not has_result_database(_ctx(tmp_path))

    def test_a_dat_from_another_job_does_not_answer_for_this_one(self, tmp_path):
        """ccx names the `.dat` after the job that wrote it. Pairing on the stem
        keeps a stray numeric file from standing in as one solve's output."""
        (tmp_path / "model.frd").write_text(frd_text(), encoding="utf-8")
        (tmp_path / "somethingelse.dat").write_text(dat_text(), encoding="utf-8")
        assert not has_result_database(_ctx(tmp_path))

    def test_a_run_in_a_subdirectory_still_counts(self, tmp_path):
        """Where the answerer puts its scratch directory is its business."""
        run = tmp_path / "a" / "b"
        run.mkdir(parents=True)
        (run / "thermal.frd").write_text(frd_text(), encoding="utf-8")
        (run / "thermal.dat").write_text(dat_text(), encoding="utf-8")
        assert has_result_database(_ctx(tmp_path))


class TestTheGateInTheScoringChain:
    """The same thing again, but through `main_from_case`, because that is what
    a mutation has to break.

    A predicate can be perfect and score nothing if nobody calls it: that is
    exactly the state `openfoam_interface` was in when a wholly empty case
    measured 1.0 (#211). So these drive the evaluator end to end and assert the
    number. The rerun itself is stubbed -- CalculiX is not on this host, and
    what is under test is the verdict, not the shell.
    """

    GT = 99.42533

    def _case(self, tmp_path, rerun):
        """A tests/ dir, a submission, and a stubbed rerun that populates the
        evaluator's own working copy the way `run_case.sh` would."""
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "spec.json").write_text(json.dumps({
            "case_id": "variant",
            "interface": {"file": "results.csv", "columns": ["t_asic_max_c"],
                          "min_rows": 1},
            "kpis": {"t_asic_max_c": {"derive": "single_row",
                                      "value": "t_asic_max_c"}},
            "reproduction_timeout_s": 60,
        }), encoding="utf-8")
        (tests / "kpis.json").write_text(json.dumps({
            "kpis": {"t_asic_max_c": {
                "group": "outputs", "shape": "scalar", "unit": "degC",
                "physics_min": 30.0, "physics_max": 400.0, "weight": 1.0,
                "gt_value": self.GT, "pass_tol": 3.72, "gross_error_tol": 14.9,
            }},
        }), encoding="utf-8")

        submission = tmp_path / "submission"
        submission.mkdir()
        (submission / ENTRY_POINT).write_text("#!/bin/sh\n:\n", encoding="utf-8")

        def stub(work, command, **_):
            rerun(work)
            return {"command": command, "exit_code": 0, "duration_s": 0.01}

        return tests, submission, stub

    def _score(self, tmp_path, monkeypatch, rerun):
        tests, submission, stub = self._case(tmp_path, rerun)
        rewards = tmp_path / "logs"
        rewards.mkdir()
        monkeypatch.setattr(cx, "run_entry_point", stub)
        monkeypatch.setenv("SIM_BENCH_SUBMISSION", str(submission))
        monkeypatch.setenv("SIM_BENCH_REWARD_DIR", str(rewards))
        assert cx.main_from_case(tests) == 0
        return (json.loads((rewards / "reward.json").read_text(encoding="utf-8"))["score"],
                json.loads((rewards / "reward_detail.json").read_text(encoding="utf-8")))

    def _answer(self, work):
        (work / "results.csv").write_text(
            f"t_asic_max_c\n{self.GT}\n", encoding="utf-8")

    def test_a_rerun_that_printed_the_right_answer_scores_zero(
        self, tmp_path, monkeypatch,
    ):
        score, detail = self._score(tmp_path, monkeypatch, self._answer)
        assert score == 0.0
        assert detail["failure_category"] == "invalid_physics_setup"
        assert detail["stage"] == "solver_evidence"

    @pytest.mark.parametrize("name", ["notes.txt", "run.log", "notes.md", "banner"])
    def test_a_rerun_that_printed_the_answer_and_a_banner_still_scores_zero(
        self, tmp_path, monkeypatch, name,
    ):
        """#304 measured on the real image: variant B shipped the banner in the
        submission, and the strip list was blamed. But variants C, D and E
        wrote theirs *during* the rerun, where no strip list can reach them,
        and all four scored 1.000. That is why the fix is the predicate and not
        the list -- so this writes the banner where the strip cannot help.
        """
        def rerun(work):
            self._answer(work)
            (work / name).write_text("CalculiX Version 2.17\nJob finished\n",
                                     encoding="utf-8")

        score, detail = self._score(tmp_path, monkeypatch, rerun)
        assert score == 0.0
        assert detail["solver_evidence"]["result_database"] is False

    def test_a_rerun_that_touched_empty_result_files_still_scores_zero(
        self, tmp_path, monkeypatch,
    ):
        """`: > model.frd` is two characters and scored 1.000 before #304."""
        def rerun(work):
            self._answer(work)
            (work / "model.frd").write_text("", encoding="utf-8")
            (work / "model.dat").write_text("", encoding="utf-8")

        score, _ = self._score(tmp_path, monkeypatch, rerun)
        assert score == 0.0

    def test_a_rerun_that_solved_scores(self, tmp_path, monkeypatch):
        def rerun(work):
            self._answer(work)
            run = work / "run"
            run.mkdir()
            (run / "thermal.frd").write_text(frd_text(), encoding="utf-8")
            (run / "thermal.dat").write_text(dat_text(), encoding="utf-8")

        score, detail = self._score(tmp_path, monkeypatch, rerun)
        assert score == 1.0
        assert detail["checks"]["solver_evidence"] == "passed"

    def test_a_solve_that_only_filed_its_results_scores(self, tmp_path, monkeypatch):
        """Verification (e), at the shape the oracle never takes.

        Every packaging oracle uses `*NODE PRINT`, so its answers arrive in a
        `.dat` and its `.frd` carries no result block at all -- measured on all
        eight. A submission using `*NODE FILE` instead is equally correct and
        arrives the other way round, with an **empty** `.dat` beside a `.frd`
        that holds the values. A gate written against the eight oracles would
        have demanded the `.dat` and looked right on every one of them.

        Not hypothetical: run for real on the domain image at a 0.85 mm grid,
        this route left a 0-byte `pkg.dat` next to a 6 MB `pkg.frd` and scored
        1.000 on all three KPIs (#304).
        """
        def rerun(work):
            self._answer(work)
            (work / "analysis").mkdir()
            (work / "analysis" / "pkg.frd").write_text(
                frd_text(results=True), encoding="utf-8")
            (work / "analysis" / "pkg.dat").write_text("", encoding="utf-8")

        score, detail = self._score(tmp_path, monkeypatch, rerun)
        assert score == 1.0
        assert detail["solver_evidence"]["result_database"] is True

    def _relation_run(self, tmp_path, monkeypatch):
        """The whole evaluator over a two-row `results.csv` and a relation KPI."""
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "spec.json").write_text(json.dumps({
            "case_id": "variant_relation",
            "interface": {"file": "results.csv", "columns": ["t_asic_max_c"],
                          "labels": ["config"], "min_rows": 2},
            "kpis": {"delta_t_asic_ab_c": {
                "derive": "pair_delta", "key": "config",
                "a": "baseline", "b": "modified", "value": "t_asic_max_c"}},
            "reproduction_timeout_s": 60,
        }), encoding="utf-8")
        (tests / "kpis.json").write_text(json.dumps({"kpis": {
            "delta_t_asic_ab_c": {
                "group": "outputs", "shape": "scalar", "unit": "K",
                "physics_min": -300.0, "physics_max": 0.0, "weight": 1.0,
                "gt_value": -15.108930, "pass_tol": 0.755, "gross_error_tol": 2.27,
            }}}), encoding="utf-8")

        submission = tmp_path / "submission"
        submission.mkdir()
        (submission / ENTRY_POINT).write_text("#!/bin/sh\n:\n", encoding="utf-8")

        def stub(work, command, **_):
            (work / "results.csv").write_text(
                "config,t_asic_max_c\nbaseline,99.42533\nmodified,84.33802\n",
                encoding="utf-8")
            run = work / "run"
            run.mkdir()
            (run / "thermal.frd").write_text(frd_text(), encoding="utf-8")
            (run / "thermal.dat").write_text(dat_text(), encoding="utf-8")
            return {"command": command, "exit_code": 0, "duration_s": 0.01}

        rewards = tmp_path / "logs"
        rewards.mkdir()
        monkeypatch.setattr(cx, "run_entry_point", stub)
        monkeypatch.setenv("SIM_BENCH_SUBMISSION", str(submission))
        monkeypatch.setenv("SIM_BENCH_REWARD_DIR", str(rewards))
        assert cx.main_from_case(tests) == 0

        return (json.loads((rewards / "reward.json").read_text(encoding="utf-8"))["score"],
                json.loads((rewards / "reward_detail.json").read_text(encoding="utf-8")))

    def test_the_declared_label_column_reaches_the_reader(self, tmp_path, monkeypatch):
        """The one line of wiring the derivation's own tests cannot see.

        `spec.json`'s `labels` has to reach `read_interface` from *this*
        module; a typo there leaves every derivation test green while every
        relation case fails on a correct answer. Same shape as #211 -- a
        predicate can be perfect and score nothing if nobody calls it.

        Asserted as *the evaluation completed and read two rows*, not as the
        number: a test that asserts the number also goes red when the
        derivation's direction is wrong, and then neither of the two is
        guarded by a test of its own.
        """
        _, detail = self._relation_run(tmp_path, monkeypatch)

        assert detail["status"] == "completed"
        assert "failure_category" not in detail
        assert detail["interface_rows"] == 2

    def test_a_relation_kpi_reaches_the_score_through_the_whole_evaluator(
        self, tmp_path, monkeypatch,
    ):
        score, detail = self._relation_run(tmp_path, monkeypatch)

        assert score == 1.0
        assert detail["scoring_components"]["delta_t_asic_ab_c"]["value"] == pytest.approx(
            84.33802 - 99.42533)
