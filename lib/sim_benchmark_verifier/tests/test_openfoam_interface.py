"""The CFD interface evaluator, exercised where it can be exercised without OpenFOAM.

Reproduction needs a solver, so that stage is covered on a host with the image.
Everything either side of it -- stripping generated state, reading the declared
interface, deriving a KPI from its columns, scoring -- is pure and is where the
defects that cost nine cases actually lived, so it is tested here.
"""
from __future__ import annotations

import gzip
import json
import struct

import pytest

import sim_benchmark_verifier.openfoam_interface as of_interface
from sim_benchmark_verifier.detectors import TrialContext
from sim_benchmark_verifier.detectors.openfoam import (
    has_mesh_and_solution,
    has_solver_evidence,
)
from sim_benchmark_verifier.native_openfoam import EvaluationFailure
from sim_benchmark_verifier.openfoam_interface import (
    derive,
    main_from_case,
    read_interface,
    score_kpis,
    strip_generated,
)


def _case(root, name="."):
    """A minimal OpenFOAM case tree with generated state in it."""
    case = root / name if name != "." else root
    for sub in ("system", "constant", "0"):
        (case / sub).mkdir(parents=True, exist_ok=True)
    (case / "system" / "controlDict").write_text("x", encoding="utf-8")
    (case / "0" / "U").write_text("input", encoding="utf-8")
    (case / "constant" / "polyMesh").mkdir(exist_ok=True)
    (case / "constant" / "polyMesh" / "points").write_text("m", encoding="utf-8")
    (case / "1000").mkdir(exist_ok=True)
    (case / "1000" / "U").write_text("solved", encoding="utf-8")
    (case / "postProcessing").mkdir(exist_ok=True)
    (case / "log.simpleFoam").write_text("l", encoding="utf-8")
    return case


# ── what OpenFOAM's writer actually emits ────────────────────────────────────
#
# Every helper below reproduces the shape read back out of
# `sim-benchmark-cfd-fullstack:latest` (OpenFOAM v2412) rather than a guess at
# it: header entries in the writer's order, the `arch` string it stamps, and a
# list whose declared count precedes its records. That fidelity is the point --
# the gate reads this format, so a fixture that only resembles it would test
# the fixture.

def _header(class_name, object_name, location, fmt="ascii"):
    return (
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        f"    format      {fmt};\n"
        '    arch        "LSB;label=32;scalar=64";\n'
        f"    class       {class_name};\n"
        f'    location    "{location}";\n'
        f"    object      {object_name};\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n"
    )


def _list_body(records):
    return "\n%d\n(\n%s)\n" % (len(records), "".join(f"{r}\n" for r in records))


def solved_mesh(mesh, n_points=8, n_faces=6):
    """A `polyMesh/` serialised the way blockMesh serialises one."""
    mesh.mkdir(parents=True, exist_ok=True)
    where = "constant/polyMesh"
    (mesh / "points").write_text(
        _header("vectorField", "points", where)
        + _list_body([f"({i} 0 0)" for i in range(n_points)]), encoding="utf-8")
    (mesh / "faces").write_text(
        _header("faceList", "faces", where)
        + _list_body(["4(0 1 2 3)"] * n_faces), encoding="utf-8")
    (mesh / "owner").write_text(
        _header("labelList", "owner", where)
        + _list_body(["0"] * n_faces), encoding="utf-8")
    return mesh


def _gzip_in_place(directory):
    """What `writeCompression on` leaves: every written object gzipped."""
    for path in list(directory.iterdir()):
        if path.is_file():
            (path.parent / f"{path.name}.gz").write_bytes(
                gzip.compress(path.read_bytes()))
            path.unlink()
    return directory


def solved_field(directory, name="U", n_cells=4, class_name="volVectorField"):
    """A time-directory field serialised the way a solver serialises one."""
    directory.mkdir(parents=True, exist_ok=True)
    record = "(0.1 0.2 0)" if "Vector" in class_name else "0.1"
    kind = "vector" if "Vector" in class_name else "scalar"
    (directory / name).write_text(
        _header(class_name, name, directory.name)
        + "\ndimensions      [0 1 -1 0 0 0 0];\n\n"
        + "internalField   nonuniform List<%s> \n%d\n(\n%s)\n;\n\n" % (
            kind, n_cells, "".join(f"{record}\n" for _ in range(n_cells)))
        + "boundaryField\n{\n    movingWall\n    {\n"
          "        type            noSlip;\n    }\n}\n",
        encoding="utf-8")
    return directory / name


class TestStripGenerated:
    def test_removes_solved_state_and_keeps_inputs(self, tmp_path):
        case = _case(tmp_path)
        strip_generated(tmp_path, ())
        assert not (case / "1000").exists()
        assert not (case / "constant" / "polyMesh").exists()
        assert not (case / "postProcessing").exists()
        assert not (case / "log.simpleFoam").exists()
        # `0/` is an input directory and survives -- documented, and the reason
        # a value KPI is exposed to seeding while a relation KPI is not.
        assert (case / "0" / "U").read_text(encoding="utf-8") == "input"
        assert (case / "system" / "controlDict").exists()

    def test_removes_the_interface_file(self, tmp_path):
        _case(tmp_path)
        (tmp_path / "grid_convergence.csv").write_text("h,e\n1,1\n", encoding="utf-8")
        removed = strip_generated(tmp_path, ("grid_convergence.csv",))
        assert not (tmp_path / "grid_convergence.csv").exists()
        assert "grid_convergence.csv" in removed

    def test_descends_into_every_sub_case(self, tmp_path):
        """A refinement study is several cases; stripping only the root would let
        the finer grids keep their solved fields and never re-solve."""
        (tmp_path / "system").mkdir()
        (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
        for level in ("grid20", "grid40", "grid80"):
            _case(tmp_path, level)
        strip_generated(tmp_path, ())
        for level in ("grid20", "grid40", "grid80"):
            assert not (tmp_path / level / "1000").exists()
            assert not (tmp_path / level / "constant" / "polyMesh").exists()
            assert (tmp_path / level / "0" / "U").exists()

    def test_leaves_a_numeric_directory_that_is_not_a_case(self, tmp_path):
        """`20/` beside a driver script is an input, not a time directory. The
        discriminator is the sibling `system/`, not the name."""
        (tmp_path / "system").mkdir()
        (tmp_path / "meshes" / "20").mkdir(parents=True)
        (tmp_path / "meshes" / "20" / "blockMeshDict").write_text("g", encoding="utf-8")
        strip_generated(tmp_path, ())
        assert (tmp_path / "meshes" / "20" / "blockMeshDict").exists()

    def test_a_numeric_input_directory_holding_a_field_name_is_still_stripped(
        self, tmp_path,
    ):
        """The exemption above is for inputs, and a file called `U` is not one.

        `meshes/20/blockMeshDict` survives because nothing in it is output. The
        moment such a directory holds a field name, the detector's `rglob` will
        accept it as a solution, so the strip has to take it -- otherwise the
        exemption is the hole."""
        (tmp_path / "system").mkdir()
        (tmp_path / "spare" / "20").mkdir(parents=True)
        (tmp_path / "spare" / "20" / "U").write_text("solved", encoding="utf-8")
        strip_generated(tmp_path, ())
        assert not (tmp_path / "spare" / "20").exists()


class TestStripReachesTheWholeSubmission:
    """A relation KPI's submission has no case at its root, and the strip has to
    follow it there.

    Two configurations means one `system/` per configuration and nothing at the
    submission root, so the root stops being a case root -- and the root is the
    one directory the rerun's entry point actually runs in.
    """

    def _two_configurations(self, root):
        (root / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("slow_floor", "fast_floor"):
            _case(root, name)
        return root

    def test_the_submission_root_is_stripped_even_when_it_is_not_a_case(self, tmp_path):
        self._two_configurations(tmp_path)
        (tmp_path / "log.driver").write_text("l", encoding="utf-8")
        (tmp_path / "postProcessing").mkdir()
        strip_generated(tmp_path, ())
        assert not (tmp_path / "log.driver").exists()
        assert not (tmp_path / "postProcessing").exists()
        for name in ("slow_floor", "fast_floor"):
            assert not (tmp_path / name / "1000").exists()
            assert not (tmp_path / name / "constant" / "polyMesh").exists()
            assert (tmp_path / name / "0" / "U").exists()

    def test_the_interface_file_goes_at_any_depth(self, tmp_path):
        """Otherwise `cp slow_floor/results.csv .` is a complete submission."""
        self._two_configurations(tmp_path)
        for where in (tmp_path, tmp_path / "slow_floor", tmp_path / "fast_floor"):
            (where / "results.csv").write_text("config,u\na,1\n", encoding="utf-8")
        removed = strip_generated(tmp_path, ("results.csv",))
        assert not list(tmp_path.rglob("results.csv"))
        assert "results.csv" in removed

    def test_a_solution_parked_outside_a_case_survives_nothing(self, tmp_path):
        """The falsifiable form: the strip's reach has to equal the gate's.

        `detectors.openfoam` globs `polyMesh` and numeric time directories from
        the submission root, so a real prior run copied into a directory with no
        `system/` in it is a solution the gate accepts and an entry point can put
        back. That is the forgery the layout relaxation would otherwise buy.
        """
        self._two_configurations(tmp_path)
        solved_mesh(tmp_path / "solved" / "slow_floor" / "constant" / "polyMesh")
        solved_field(tmp_path / "solved" / "slow_floor" / "1000")
        (tmp_path / "solved" / "results.csv").write_text(
            "config,u\nslow_floor,-0.39\n", encoding="utf-8")

        before = TrialContext(case_dir=tmp_path, solver_label="openfoam")
        assert has_mesh_and_solution(before), "fixture must be a solution the gate accepts"

        strip_generated(tmp_path, ("results.csv",))

        after = TrialContext(case_dir=tmp_path, solver_label="openfoam")
        assert not has_mesh_and_solution(after)
        assert not list(tmp_path.rglob("results.csv"))

    def test_a_preserved_mesh_still_survives_under_the_wider_reach(self, tmp_path):
        case = _case(tmp_path)
        strip_generated(tmp_path, (), preserve=("constant/polyMesh",))
        assert (case / "constant" / "polyMesh" / "points").exists()
        assert not (case / "1000").exists()


class TestValidateSubmission:
    """What the handover has to contain, and what it no longer has to be shaped like.

    The check used to demand `0/ constant/ system/` at the submission root, which
    refused every multi-configuration submission at `submission_validation`
    before any physics was read -- a check on the submission's *layout*, which
    the output-interface contract explicitly leaves free.
    """

    def test_a_two_configuration_submission_is_valid(self, tmp_path):
        (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("runA", "runB"):
            _case(tmp_path, name)
        of_interface.validate_submission(tmp_path)  # no raise

    def test_a_single_configuration_submission_is_still_valid(self, tmp_path):
        _case(tmp_path)
        (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
        of_interface.validate_submission(tmp_path)  # no raise

    def test_a_submission_with_no_case_anywhere_is_refused(self, tmp_path):
        (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / "notes").mkdir()
        with pytest.raises(EvaluationFailure) as excinfo:
            of_interface.validate_submission(tmp_path)
        assert excinfo.value.category == "invalid_submission"
        assert "system/" in str(excinfo.value)

    def test_a_case_without_the_entry_point_is_refused(self, tmp_path):
        _case(tmp_path)
        with pytest.raises(EvaluationFailure) as excinfo:
            of_interface.validate_submission(tmp_path)
        assert "Allrun" in str(excinfo.value)

    def test_an_empty_entry_point_is_refused(self, tmp_path):
        _case(tmp_path)
        (tmp_path / "Allrun").write_text("", encoding="utf-8")
        with pytest.raises(EvaluationFailure):
            of_interface.validate_submission(tmp_path)


class TestReadInterface:
    def _write(self, tmp_path, text):
        path = tmp_path / "grid_convergence.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_named_columns(self, tmp_path):
        path = self._write(tmp_path, "n,h,l2\n20,0.05,4e-3\n40,0.025,1e-3\n80,0.0125,2.5e-4\n")
        cols = read_interface(path, ["h", "l2"], 3)
        assert cols["h"] == [0.05, 0.025, 0.0125]
        assert cols["l2"][-1] == pytest.approx(2.5e-4)

    def test_missing_file_names_the_file(self, tmp_path):
        with pytest.raises(EvaluationFailure) as e:
            read_interface(tmp_path / "grid_convergence.csv", ["h"], 1)
        assert e.value.category == "extraction_failed"
        assert "grid_convergence.csv" in str(e.value)

    def test_missing_column_reports_what_was_there(self, tmp_path):
        path = self._write(tmp_path, "n,h\n20,0.05\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["h", "l2"], 1)
        assert "'l2'" in str(e.value) and "['n', 'h']" in str(e.value)

    def test_too_few_rows(self, tmp_path):
        path = self._write(tmp_path, "h,l2\n0.05,4e-3\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["h", "l2"], 3)
        assert "at least 3" in str(e.value)

    def test_non_numeric_cell_names_the_row_and_column(self, tmp_path):
        path = self._write(tmp_path, "h,l2\n0.05,diverged\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["h", "l2"], 1)
        assert "row 1" in str(e.value) and "'l2'" in str(e.value)

    def test_nan_is_rejected(self, tmp_path):
        """A diverged run that writes `nan` must not reach the scorer, where it
        would compare false against every bound and score a silent zero."""
        path = self._write(tmp_path, "h,l2\n0.05,nan\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["h", "l2"], 1)
        assert "not finite" in str(e.value)

    def test_a_label_column_comes_back_as_text(self, tmp_path):
        """The one column a relation KPI needs and arithmetic must never touch."""
        path = self._write(tmp_path, "config,t\nbaseline,92.5\nmodified,78.625\n")
        cols = read_interface(path, ["t"], 2, ["config"])
        assert cols["config"] == ["baseline", "modified"]
        assert cols["t"] == [92.5, 78.625]

    def test_a_declared_label_column_that_is_absent_is_named(self, tmp_path):
        path = self._write(tmp_path, "case,t\nbaseline,92.5\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["t"], 1, ["config"])
        assert e.value.category == "extraction_failed"
        assert "'config'" in str(e.value)

    @pytest.mark.parametrize("text,columns", [
        ("92.5\n78.625\n", ["t"]),
        ("1,92.5\n2,78.625\n", ["t"]),
        ("1,92.5\n2,78.625\n", ["t", "p"]),
    ])
    def test_a_headerless_file_cannot_be_recovered_into_a_label_column(
        self, tmp_path, text, columns,
    ):
        """Recovery rebuilds the header out of `columns`, so it never names a
        label -- which is why the recovery needs no extra guard for one. Every
        shape where its numeric test can fire while a label is declared is
        asserted here, because a guard that changes no outcome is a branch this
        repo deletes and the way to know which it is, is to run it."""
        path = self._write(tmp_path, text)
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, columns, 1, ["config"])
        assert e.value.category == "extraction_failed"
        assert "'config'" in str(e.value)

    def test_recovery_still_works_when_no_label_is_declared(self, tmp_path):
        path = self._write(tmp_path, "0.05,4e-3\n0.025,1e-3\n")
        cols = read_interface(path, ["h", "l2"], 2)
        assert cols["h"] == [0.05, 0.025]


class TestDerive:
    def test_recovers_a_known_order(self):
        h = [0.05, 0.025, 0.0125]
        cols = {"h": h, "l2": [1e-2 * x**2 for x in h]}
        got = derive(cols, {"derive": "log_log_slope", "x": "h", "y": "l2"})
        assert got == pytest.approx(2.0, abs=1e-9)

    def test_first_order_is_not_second(self):
        h = [0.05, 0.025, 0.0125]
        cols = {"h": h, "l2": [1e-2 * x for x in h]}
        assert derive(cols, {"derive": "log_log_slope", "x": "h", "y": "l2"}) == pytest.approx(1.0)

    def test_value_at_min(self):
        cols = {"h": [0.05, 0.0125, 0.025], "l2": [4e-3, 2.5e-4, 1e-3]}
        got = derive(cols, {"derive": "value_at_min", "key": "h", "value": "l2"})
        assert got == pytest.approx(2.5e-4)

    def test_identical_levels_is_not_a_study(self):
        cols = {"h": [0.05, 0.05], "l2": [1e-3, 1e-3]}
        with pytest.raises(EvaluationFailure) as e:
            derive(cols, {"derive": "log_log_slope", "x": "h", "y": "l2"})
        assert "distinct levels" in str(e.value)

    def test_zero_error_rows_are_dropped_and_reported(self):
        """Seeding the exact field gives error 0, which has no logarithm. It must
        fail loudly rather than silently fitting the rows that remain."""
        cols = {"h": [0.05, 0.025, 0.0125], "l2": [0.0, 0.0, 1e-9]}
        with pytest.raises(EvaluationFailure) as e:
            derive(cols, {"derive": "log_log_slope", "x": "h", "y": "l2"})
        assert ">= 2 rows" in str(e.value)

    def test_unknown_derivation_is_an_evaluator_error(self):
        with pytest.raises(EvaluationFailure) as e:
            derive({"h": [1.0]}, {"derive": "vibes"})
        assert e.value.category == "evaluator_error"


class TestPairDerivation:
    """A KPI defined between two configurations the prompt pins by name.

    The shape is track-neutral -- it is read off the same `results.csv` as the
    other four, and both interface evaluators reach it -- so it is tested here
    against `csv_interface` directly rather than through either track.

    Two properties are what the branches below are about. **Which two rows are
    compared is decided by `spec.json` and never by the submission**, because a
    relation whose second endpoint the agent picks has no `gt_value` to score
    against. And **every way the two rows can fail to be there is a scored zero
    with a named category, never an exception** -- an evaluator that raises has
    historically been read as infrastructure having broken rather than as a
    submission having failed.
    """

    SWEEP = {
        "config": ["baseline", "trial_1", "modified", "trial_2"],
        "t_asic_max_c": [92.5, 88.0, 78.625, 81.0],
    }

    def _derive(self, kind, cols=None, **over):
        spec = {"derive": kind, "key": "config", "a": "baseline",
                "b": "modified", "value": "t_asic_max_c"}
        spec.update(over)
        return derive(dict(cols if cols is not None else self.SWEEP), spec)

    # ── the number itself ────────────────────────────────────────────────

    def test_ratio_is_the_changed_configuration_over_the_reference(self):
        assert self._derive("pair_ratio") == pytest.approx(78.625 / 92.5)

    def test_delta_is_the_changed_configuration_minus_the_reference(self):
        assert self._derive("pair_delta") == pytest.approx(78.625 - 92.5)

    def test_the_direction_is_b_against_a_and_not_the_other_way_round(self):
        """`b/a` and `a/b` are both plausible and only one has a `gt_value`.

        Getting this backwards is invisible in a symmetric fixture, so the
        assertion is that swapping the endpoints changes the answer.
        """
        assert self._derive("pair_ratio", a="modified", b="baseline") == pytest.approx(
            92.5 / 78.625)
        assert self._derive("pair_delta", a="modified", b="baseline") == pytest.approx(
            92.5 - 78.625)

    def test_rows_the_spec_does_not_name_are_ignored(self):
        """A design sweep is mostly rows the KPI is not about.

        The submission is free to explore as widely as it likes; what the KPI
        reads is the two rows the prompt pinned, so adding sweep points can
        neither help nor hurt.
        """
        wide = {
            "config": ["s%d" % i for i in range(9)] + ["baseline", "modified"],
            "t_asic_max_c": [float(i) for i in range(9)] + [92.5, 78.625],
        }
        assert self._derive("pair_ratio", cols=wide) == pytest.approx(78.625 / 92.5)

    # ── locating the rows: what the submission can get wrong ─────────────

    def test_a_missing_endpoint_scores_zero_and_names_what_was_there(self):
        cols = {"config": ["baseline", "trial_1"], "t_asic_max_c": [92.5, 88.0]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", cols=cols)
        assert e.value.category == "extraction_failed"
        assert "'modified'" in str(e.value) and "baseline" in str(e.value)

    def test_a_missing_reference_endpoint_scores_zero_too(self):
        cols = {"config": ["modified", "trial_1"], "t_asic_max_c": [78.625, 88.0]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_delta", cols=cols)
        assert e.value.category == "extraction_failed"
        assert "'baseline'" in str(e.value)

    def test_a_repeated_key_scores_zero_rather_than_picking_one(self):
        """Two rows claiming to be the same configuration have no tie-break that
        is not the evaluator inventing one, and inventing one is how a
        submission's own choice enters the score."""
        cols = {"config": ["baseline", "modified", "modified"],
                "t_asic_max_c": [92.5, 78.625, 60.0]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", cols=cols)
        assert e.value.category == "extraction_failed"
        assert "2 rows" in str(e.value)

    def test_a_single_row_file_cannot_carry_a_relation(self):
        cols = {"config": ["baseline"], "t_asic_max_c": [92.5]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_delta", cols=cols)
        assert e.value.category == "extraction_failed"

    def test_spelling_of_the_label_is_not_part_of_the_physics(self):
        """Capitalisation and stray whitespace must not zero a right answer.

        This is the mirror of the admissibility rule: a check that fails a
        submission the tolerance band would pass is inadmissible, and `Baseline`
        for `baseline` is exactly that -- both configurations solved, both
        numbers right, one capital letter.

        What is asserted is that the two files derive the *same* number, not
        what that number is: written the other way this test also fails when
        the ratio's direction is wrong, and a test two unrelated mutations
        redden is guarding neither of them by itself.
        """
        plain = {"config": ["baseline", "modified"], "t_asic_max_c": [92.5, 78.625]}
        spelled = {"config": ["  Baseline ", "MODIFIED"], "t_asic_max_c": [92.5, 78.625]}
        assert self._derive("pair_ratio", cols=spelled) == pytest.approx(
            self._derive("pair_ratio", cols=plain))

    def test_a_different_word_is_still_a_different_configuration(self):
        cols = {"config": ["base", "modified"], "t_asic_max_c": [92.5, 78.625]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", cols=cols)
        assert e.value.category == "extraction_failed"

    def test_two_rows_that_differ_only_in_case_are_a_repeated_key(self):
        """The forgiveness above and the duplicate check are the same comparison,
        so a file that exploits one has to trip the other."""
        cols = {"config": ["baseline", "Baseline", "modified"],
                "t_asic_max_c": [92.5, 90.0, 78.625]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_delta", cols=cols)
        assert e.value.category == "extraction_failed"
        assert "2 rows" in str(e.value)

    # ── arithmetic that has no answer ────────────────────────────────────

    def test_a_zero_reference_makes_a_ratio_undefined(self):
        cols = {"config": ["baseline", "modified"], "t_asic_max_c": [0.0, 78.625]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", cols=cols)
        assert e.value.category == "extraction_failed"
        assert "undefined" in str(e.value)

    def test_a_zero_reference_is_fine_for_a_delta(self):
        cols = {"config": ["baseline", "modified"], "t_asic_max_c": [0.0, 78.625]}
        assert self._derive("pair_delta", cols=cols) == pytest.approx(78.625)

    def test_a_ratio_that_overflows_is_refused_rather_than_scored(self):
        """There is deliberately no epsilon below which a denominator is "too
        small" -- an invented threshold can zero a correct answer, and where a
        ratio stops being physical is what the KPI's physics window says. What
        is refused here is only a quotient arithmetic cannot represent, and it
        is refused by name rather than left to arrive at the band as `inf`.

        Asserted as "one ordering overflows and the other does not" rather than
        against a fixed ordering: the two are reciprocals, so a test naming one
        of them also goes red when the derivation's *direction* is wrong, and
        the direction is guarded elsewhere.
        """
        cols = {"config": ["baseline", "modified"], "t_asic_max_c": [5e-324, 1e308]}
        outcomes = []
        for a, b in (("baseline", "modified"), ("modified", "baseline")):
            try:
                outcomes.append(("value", self._derive("pair_ratio", cols=cols, a=a, b=b)))
            except EvaluationFailure as exc:
                outcomes.append(("failed", exc.category, "finite" in str(exc)))
        assert sorted(o[0] for o in outcomes) == ["failed", "value"]
        assert ("failed", "extraction_failed", True) in outcomes

    # ── specs that are our fault, not the submission's ───────────────────

    def test_naming_one_configuration_as_both_endpoints_is_refused(self):
        """The null answer written into `spec.json` instead of into the data:
        a relation to itself is the constant 1 (or 0) and measures nothing."""
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", b="baseline")
        assert e.value.category == "evaluator_error"

    def test_the_same_configuration_spelled_two_ways_is_still_one_endpoint(self):
        """The forgiveness in the row lookup and this refusal are one comparison,
        so a spec cannot slip a degenerate relation past by changing the case."""
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_delta", b="Baseline")
        assert e.value.category == "evaluator_error"

    def test_an_endpoint_the_spec_omits_is_an_evaluator_error(self):
        for missing in ("a", "b"):
            with pytest.raises(EvaluationFailure) as e:
                self._derive("pair_delta", **{missing: None})
            assert e.value.category == "evaluator_error"

    def test_a_key_column_that_is_not_a_label_is_an_evaluator_error(self):
        """Matching a configuration by float equality is a coin toss on the
        last bit, so the key column has to be declared under `labels`."""
        cols = {"config": [1.0, 2.0], "t_asic_max_c": [92.5, 78.625]}
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", cols=cols, a=1.0, b=2.0)
        assert e.value.category == "evaluator_error"
        assert "labels" in str(e.value)

    def test_a_value_column_that_is_a_label_is_an_evaluator_error(self):
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_ratio", value="config")
        assert e.value.category == "evaluator_error"

    def test_a_value_column_the_interface_does_not_declare_is_an_evaluator_error(self):
        with pytest.raises(EvaluationFailure) as e:
            self._derive("pair_delta", value="t_hbm_w_max_c")
        assert e.value.category == "evaluator_error"

    def test_no_failure_needs_a_category_that_does_not_exist(self):
        """#453 asked whether this shape forces a new public failure category.

        It does not, and that is worth an assertion rather than a sentence:
        every branch above lands on one of the closed vocabulary's existing
        entries, split the way triage reads them -- the submission's file
        (`extraction_failed`) against `spec.json` (`evaluator_error`).
        """
        from sim_benchmark_verifier.native_openfoam import FAILURE_CATEGORIES

        assert {"extraction_failed", "evaluator_error"} <= set(FAILURE_CATEGORIES)


class TestScoreKpis:
    KPIS = {
        "observed_order_u": {
            "group": "outputs", "gt_value": 2.0,
            "physics_min": 0.5, "physics_max": 3.5,
            "T_good": 0.25, "T_bad": 0.75,
        },
        "l2_error_finest_u": {
            "group": "outputs", "gt_value": 1.0e-3,
            "physics_min": 0.0, "physics_max": 1.0,
            "T_good": 5.0e-4, "T_bad": 2.0e-3,
        },
    }
    DERIVATIONS = {
        "observed_order_u": {"derive": "log_log_slope", "x": "h", "y": "l2"},
        "l2_error_finest_u": {"derive": "value_at_min", "key": "h", "value": "l2"},
    }

    def _cols(self, order, finest):
        h = [0.05, 0.025, 0.0125]
        scale = finest / (h[-1] ** order)
        return {"h": h, "l2": [scale * x**order for x in h]}

    def test_a_clean_second_order_study_scores_one(self):
        score, per = score_kpis(self._cols(2.0, 1.0e-3), self.DERIVATIONS, self.KPIS)
        assert score == pytest.approx(1.0)
        assert per["observed_order_u"]["value"] == pytest.approx(2.0)

    def test_a_first_order_scheme_is_penalised(self):
        score, per = score_kpis(self._cols(1.0, 1.0e-3), self.DERIVATIONS, self.KPIS)
        assert per["observed_order_u"]["score"] == 0.0   # |1-2| = 1.0 > pass_tol
        assert per["l2_error_finest_u"]["score"] == pytest.approx(1.0)
        assert score == pytest.approx(0.5)

    def test_there_is_no_partial_credit(self):
        # |1.5 - 2.0| = 0.5, outside pass_tol 0.25 and inside the old
        # gross_error_tol 0.75 — the window that used to score 0.5. Under
        # #188 a scheme that is not second order is not two-thirds second
        # order; it scores nothing.
        _, per = score_kpis(self._cols(1.5, 1.0e-3), self.DERIVATIONS, self.KPIS)
        assert per["observed_order_u"]["score"] == 0.0

    def test_a_value_outside_the_physics_window_scores_zero_not_a_near_miss(self):
        _, per = score_kpis(self._cols(-1.0, 1.0e-3), self.DERIVATIONS, self.KPIS)
        assert per["observed_order_u"]["score"] == 0.0
        assert "physics window" in per["observed_order_u"]["reason"]

    def test_a_clean_slope_on_absurd_errors_does_not_score(self):
        """The magnitude KPI is why a fabricated but self-consistent table fails:
        a perfect slope of 2 with errors 100x the reference still loses half."""
        score, per = score_kpis(self._cols(2.0, 1.0e-1), self.DERIVATIONS, self.KPIS)
        assert per["observed_order_u"]["score"] == pytest.approx(1.0)
        assert per["l2_error_finest_u"]["score"] == 0.0
        assert score == pytest.approx(0.5)

    def test_a_kpi_the_spec_derives_but_kpis_json_lacks_is_an_evaluator_error(self):
        with pytest.raises(EvaluationFailure) as e:
            score_kpis(self._cols(2.0, 1e-3), self.DERIVATIONS, {"observed_order_u": self.KPIS["observed_order_u"]})
        assert e.value.category == "evaluator_error"


def test_no_setup_inspection_anywhere_in_the_module():
    """The rule this module exists to enforce, asserted against its own source.

    Every one of these names reads the submission's *setup*. Nine cases used them
    to harden one of the oracle's arbitrary choices into a requirement, so their
    absence here is the property worth pinning -- a future edit that reintroduces
    one is the defect coming back.
    """
    from pathlib import Path

    import sim_benchmark_verifier.openfoam_interface as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]  # skip the module docstring, which names them
    for banned in ("dictionary_text", "boundary_field_types", "sole_patch",
                   "dictionary_block", "install_sample_dict", "poly_mesh_bounds"):
        assert banned not in body, f"{banned} inspects the submission's setup"


class TestHeaderlessFile:
    """A missing header row must not cost a correct answer.

    Measured on a real trial: a submission whose three refinement levels matched
    the reference to eight figures scored zero because its first line was the
    data. Recovery is allowed only where it is unambiguous.
    """

    def _write(self, tmp_path, text):
        path = tmp_path / "grid_convergence.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_headerless_is_recovered_when_the_shape_matches(self, tmp_path):
        path = self._write(tmp_path, "20,0.05,4e-3\n40,0.025,1e-3\n80,0.0125,2.5e-4\n")
        cols = read_interface(path, ["n_cells_per_side", "h", "l2_error_u"], 3)
        assert cols["h"] == [0.05, 0.025, 0.0125]
        assert cols["l2_error_u"][-1] == pytest.approx(2.5e-4)

    def test_a_header_is_still_preferred_when_present(self, tmp_path):
        path = self._write(tmp_path, "l2_error_u,h\n4e-3,0.05\n")
        cols = read_interface(path, ["h", "l2_error_u"], 1)
        # Named columns win over position: this file has them in the other order.
        assert cols["h"] == [0.05]
        assert cols["l2_error_u"] == [4e-3]

    def test_wrong_field_count_still_fails_by_name(self, tmp_path):
        """Two fields where three are declared is not a recoverable slip: which
        two, in which order, is a guess, so it fails as a naming mismatch."""
        path = self._write(tmp_path, "20,0.05\n40,0.025\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["n_cells_per_side", "h", "l2_error_u"], 1)
        assert "missing required column" in str(e.value)

    def test_a_misspelled_header_is_not_silently_recovered(self, tmp_path):
        """Text in the first row means it was meant as a header; if it is the
        wrong header the case author has a naming bug and must hear about it."""
        path = self._write(tmp_path, "n_cells,h,l2\n20,0.05,4e-3\n")
        with pytest.raises(EvaluationFailure) as e:
            read_interface(path, ["n_cells_per_side", "h", "l2_error_u"], 1)
        assert "missing required column" in str(e.value)


class TestPreservedInputs:
    """A grid the TASK supplied is an input, not an artefact.

    Two cases hand the agent a published mesh in `environment/`. Stripping it
    before the rerun leaves the submission with nothing to solve on, and the
    failure looks like the agent shipping a broken case.
    """

    def test_a_declared_mesh_survives_the_strip(self, tmp_path):
        case = _case(tmp_path)
        strip_generated(tmp_path, (), preserve=("constant/polyMesh",))
        assert (case / "constant" / "polyMesh" / "points").exists()
        # everything else the run produced is still gone
        assert not (case / "1000").exists()
        assert not (case / "postProcessing").exists()

    def test_nothing_is_preserved_by_default(self, tmp_path):
        case = _case(tmp_path)
        strip_generated(tmp_path, ())
        assert not (case / "constant" / "polyMesh").exists()


class TestSolverEvidencePredicate:
    """Which of the two detector predicates the evaluator may gate on.

    `has_solver_evidence` also accepts any `log.*`, which is whatever a shell
    redirected into a name. That is the right reading when the question is
    "did this workspace ever see a solver?"; it is the wrong one when the
    answer decides a score, and the third test is the difference.
    """

    def _ctx(self, root):
        return TrialContext(case_dir=root, solver_label="openfoam")

    def test_a_solved_tree_passes_both(self, tmp_path):
        _case(tmp_path)
        solved_mesh(tmp_path / "constant" / "polyMesh")
        solved_field(tmp_path / "1000")
        assert has_mesh_and_solution(self._ctx(tmp_path))
        assert has_solver_evidence(self._ctx(tmp_path))

    def test_an_answer_with_no_run_passes_neither(self, tmp_path):
        for sub in ("0", "constant", "system"):
            (tmp_path / sub).mkdir()
        (tmp_path / "Allrun").write_text("#!/bin/sh\nprintf 'cd\\n0.53\\n' > results.csv\n",
                                         encoding="utf-8")
        (tmp_path / "results.csv").write_text("cd\n0.53\n", encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))
        assert not has_solver_evidence(self._ctx(tmp_path))

    def test_an_empty_log_file_is_not_a_solve(self, tmp_path):
        """`: > log.simpleFoam` is one more line in a fabricated `Allrun`."""
        (tmp_path / "system").mkdir()
        (tmp_path / "log.simpleFoam").touch()
        assert has_solver_evidence(self._ctx(tmp_path))       # permissive: yes
        assert not has_mesh_and_solution(self._ctx(tmp_path))  # what we gate on

    def test_a_compressed_mesh_and_field_still_count(self, tmp_path):
        """`writeCompression on` is a setting, not a missing solve.

        Both task-supplied grids in the cfd track ship as `points.gz`, so a
        gate that matched only the bare name would zero two full-mark oracles
        -- measured on `bump_in_channel_2d` before this was fixed. Reading the
        format instead of the name does not change that: the header is inside
        the gzip member, so it is un-gzipped and read.
        """
        _gzip_in_place(solved_mesh(tmp_path / "constant" / "polyMesh"))
        _gzip_in_place(solved_field(tmp_path / "1206").parent)
        (tmp_path / "system").mkdir()
        assert has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_compressed_mesh_without_a_solved_time_does_not(self, tmp_path):
        """The grid is a task input on those two cases; producing the fields
        is still the submission's job."""
        _gzip_in_place(solved_mesh(tmp_path / "constant" / "polyMesh"))
        (tmp_path / "system").mkdir()
        assert not has_mesh_and_solution(self._ctx(tmp_path))


class TestTheStrictPredicateReadsTheFormat:
    """#377: the strict predicate used to ask only whether files existed.

    `_written` was `is_file()`, so `mkdir -p constant/polyMesh 1` plus three
    `printf`s of the literal words `not a mesh` / `not a field` satisfied it,
    and that took `lid_driven_cavity_ghia_re100` to **1.000** in the shipped
    image (#361). The parallel predicate on the other live track,
    `calculix.has_result_database`, cost a **21-line heredoc** to satisfy
    because it reads an FRD's declared counts against its records -- about 5x,
    guarding the same thing, from the same repair. This class is the openfoam
    side brought to that tier: every arm here is one the format check has to
    tell apart, and each is written the way a submission would actually
    produce it.

    Each negative is also the reverted check's positive: run any of them
    against `_written`-style existence and they pass, which is why they are
    the tests rather than a paragraph.
    """

    def _ctx(self, root):
        return TrialContext(case_dir=root, solver_label="openfoam")

    def _solved(self, root):
        solved_mesh(root / "constant" / "polyMesh")
        solved_field(root / "1")
        return root

    def test_the_measured_four_line_forgery_is_refused(self, tmp_path):
        mesh = tmp_path / "constant" / "polyMesh"
        mesh.mkdir(parents=True)
        (mesh / "points").write_text("not a mesh\n", encoding="utf-8")
        (mesh / "faces").write_text("not a mesh\n", encoding="utf-8")
        (tmp_path / "1").mkdir()
        (tmp_path / "1" / "U").write_text("not a field\n", encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_header_with_no_payload_is_refused(self, tmp_path):
        """The next forgery up: copy the header, skip the list."""
        self._solved(tmp_path)
        mesh = tmp_path / "constant" / "polyMesh"
        header = _header("vectorField", "points", "constant/polyMesh")
        (mesh / "points").write_text(header, encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_list_shorter_than_its_own_declared_count_is_refused(self, tmp_path):
        """The FRD check, transposed: a count that disagrees with its records.

        This is the one that makes the check a *format* check rather than a
        shape check -- OpenFOAM's writer always agrees with itself, so no run
        that solved can land here.
        """
        self._solved(tmp_path)
        mesh = tmp_path / "constant" / "polyMesh"
        (mesh / "points").write_text(
            _header("vectorField", "points", "constant/polyMesh")
            + "\n900\n(\n(0 0 0)\n(1 0 0)\n)\n", encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_face_count_the_owner_list_contradicts_is_refused(self, tmp_path):
        """Every face has exactly one owner. Two files, one number."""
        self._solved(tmp_path)
        mesh = tmp_path / "constant" / "polyMesh"
        (mesh / "owner").write_text(
            _header("labelList", "owner", "constant/polyMesh")
            + _list_body(["0"] * 99), encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_polymesh_with_no_owner_is_refused(self, tmp_path):
        """A `polyMesh/` OpenFOAM could not read back is not one it wrote."""
        self._solved(tmp_path)
        (tmp_path / "constant" / "polyMesh" / "owner").unlink()
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_the_wrong_class_under_the_right_name_is_refused(self, tmp_path):
        self._solved(tmp_path)
        mesh = tmp_path / "constant" / "polyMesh"
        (mesh / "points").write_text(
            _header("labelList", "points", "constant/polyMesh")
            + _list_body(["0"] * 8), encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_real_mesh_with_a_uniform_hand_written_field_is_refused(self, tmp_path):
        """The cheapest route left once the mesh has to be real: mesh for
        real, then hand-write one `internalField uniform` line.

        `uniform` is the one spelling with nothing to count, so it is not
        counted. A solved time directory whose every field came out uniform is
        one where nothing happened.
        """
        solved_mesh(tmp_path / "constant" / "polyMesh")
        (tmp_path / "1").mkdir()
        (tmp_path / "1" / "U").write_text(
            _header("volVectorField", "U", "1")
            + "\ndimensions      [0 1 -1 0 0 0 0];\n"
              "internalField   uniform (0 0 0);\n"
              "boundaryField\n{\n}\n", encoding="utf-8")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_field_naming_a_different_object_is_refused(self, tmp_path):
        """`cp 0/U 1/U` after editing is not a solve; the object entry says so."""
        solved_mesh(tmp_path / "constant" / "polyMesh")
        solved_field(tmp_path / "1", "p", class_name="volScalarField")
        text = (tmp_path / "1" / "p").read_text(encoding="utf-8")
        (tmp_path / "1" / "U").write_text(text, encoding="utf-8")
        (tmp_path / "1" / "p").unlink()
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_binary_write_format_is_read_as_what_it_is(self, tmp_path):
        """`writeFormat binary` is an ordinary setting, and the reason the
        payload check is not a line count.

        Produced in the shipped image before this landed: binary `points` is a
        `vectorField` of `scalar=64` triples, and binary `faces` becomes a
        `faceCompactList` whose first list is nFaces+1 offsets. Both are read
        here, and a payload one record short of its declared count is not.
        """
        mesh = tmp_path / "constant" / "polyMesh"
        mesh.mkdir(parents=True)
        n_points, n_faces = 8, 6
        (mesh / "points").write_bytes(
            _header("vectorField", "points", "constant/polyMesh", "binary").encode()
            + b"\n%d\n(" % n_points
            + struct.pack("<%dd" % (3 * n_points), *([0.0] * 3 * n_points))
            + b")\n")
        (mesh / "faces").write_bytes(
            _header("faceCompactList", "faces", "constant/polyMesh", "binary").encode()
            + b"\n%d\n(" % (n_faces + 1)
            + struct.pack("<%di" % (n_faces + 1), *range(n_faces + 1))
            + b")\n")
        (mesh / "owner").write_bytes(
            _header("labelList", "owner", "constant/polyMesh", "binary").encode()
            + b"\n%d\n(" % n_faces
            + struct.pack("<%di" % n_faces, *([0] * n_faces))
            + b")\n")
        solved_field(tmp_path / "1")
        assert has_mesh_and_solution(self._ctx(tmp_path))

        (mesh / "points").write_bytes(
            _header("vectorField", "points", "constant/polyMesh", "binary").encode()
            + b"\n%d\n(" % n_points
            + struct.pack("<%dd" % (3 * n_points - 3), *([0.0] * (3 * n_points - 3)))
            + b")\n")
        assert not has_mesh_and_solution(self._ctx(tmp_path))

    def test_a_serialised_tree_passes_whatever_the_case_was_configured_as(
            self, tmp_path):
        """The mirror. Nothing the check reads is a choice the task left free.

        Not the scheme, not a boundary condition, not a dictionary entry --
        only the object's class and whether a list holds what it declares. So
        this passes with a `system/` that says nothing at all.
        """
        self._solved(tmp_path)
        (tmp_path / "system").mkdir()
        assert has_mesh_and_solution(self._ctx(tmp_path))


class TestReproducedRunMustHaveSolved:
    """#211: the rerun is not the whole gate, because `Allrun` is arbitrary shell.

    Measured in the real image before this landed: three empty directories plus
    `printf 'u_min_vertical_centerline\\n-0.2109\\n' > results.csv` scored **1.0**
    on `lid_driven_cavity_ghia_re100`, while thirteen cfd `kpis.json` asserted
    that exact submission scores 0. Both halves are pinned here -- the fabricated
    rerun fails, and a rerun that really meshes and solves is untouched.

    `openfoam_command` is the seam: everything the gate reads is what the rerun
    left on disk, so a fake rerun that writes those files exercises the real
    path without needing OpenFOAM.
    """

    KPIS = {"cd": {"group": "outputs", "gt_value": 0.53, "physics_min": 0.0,
                   "physics_max": 2.0, "pass_tol": 0.05}}
    SPEC = {"case_id": "fake_case",
            "interface": {"file": "results.csv", "columns": ["cd"], "min_rows": 1},
            "kpis": {"cd": {"derive": "single_row", "value": "cd"}}}

    def _tests_dir(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "spec.json").write_text(json.dumps(self.SPEC), encoding="utf-8")
        (tests / "kpis.json").write_text(json.dumps({"kpis": self.KPIS}), encoding="utf-8")
        return tests

    def _submission(self, tmp_path):
        sub = tmp_path / "submission"
        for name in ("0", "constant", "system"):
            (sub / name).mkdir(parents=True)
        (sub / "Allrun").write_text("#!/bin/sh\n# whatever the fake rerun does\n",
                                    encoding="utf-8")
        return sub

    def _run(self, tmp_path, monkeypatch, rerun):
        tests = self._tests_dir(tmp_path)
        sub = self._submission(tmp_path)
        reward = tmp_path / "reward"
        monkeypatch.setenv("SIM_BENCH_SUBMISSION", str(sub))
        monkeypatch.setenv("SIM_BENCH_REWARD_DIR", str(reward))

        def fake(case, command, *, timeout_s, log_path, check=True):
            rerun(case)
            return {"command": command, "exit_code": 0, "duration_s": 0.0}

        monkeypatch.setattr(of_interface, "openfoam_command", fake)
        assert main_from_case(tests) == 0
        return (json.loads((reward / "reward.json").read_text(encoding="utf-8")),
                json.loads((reward / "reward_detail.json").read_text(encoding="utf-8")))

    @staticmethod
    def _printf_rerun(case):
        (case / "results.csv").write_text("cd\n0.53\n", encoding="utf-8")

    @staticmethod
    def _solving_rerun(case):
        solved_mesh(case / "constant" / "polyMesh")
        solved_field(case / "500", "U")
        solved_field(case / "500", "p", class_name="volScalarField")
        (case / "log.simpleFoam").write_text("End\n", encoding="utf-8")
        (case / "results.csv").write_text("cd\n0.53\n", encoding="utf-8")

    @staticmethod
    def _forging_rerun(case):
        """#361's four lines of shell, transcribed.

        `mkdir -p constant/polyMesh 1` and three `printf`s. This reached
        **1.000** on `lid_driven_cavity_ghia_re100` in the shipped image
        against the predicate as #211 left it, which is what #377 priced.
        """
        mesh = case / "constant" / "polyMesh"
        mesh.mkdir(parents=True, exist_ok=True)
        (mesh / "points").write_text("not a mesh\n", encoding="utf-8")
        (mesh / "faces").write_text("not a mesh\n", encoding="utf-8")
        (case / "1").mkdir(exist_ok=True)
        (case / "1" / "U").write_text("not a field\n", encoding="utf-8")
        (case / "results.csv").write_text("cd\n0.53\n", encoding="utf-8")

    def test_a_fabricated_rerun_scores_zero(self, tmp_path, monkeypatch):
        reward, detail = self._run(tmp_path, monkeypatch, self._printf_rerun)
        assert reward["score"] == 0.0
        assert detail["failure_category"] == "invalid_physics_setup"
        assert detail["stage"] == "solver_evidence"
        assert detail["solver_evidence"] == {
            "mesh_and_solution": False,
            "mesh_and_solution_files_present": False,
            "any_solver_artifact": False}

    def test_a_fabricated_rerun_that_also_touches_a_log_scores_zero(
            self, tmp_path, monkeypatch):
        """The one extra line that defeats the permissive predicate."""
        def rerun(case):
            self._printf_rerun(case)
            (case / "log.simpleFoam").touch()

        reward, detail = self._run(tmp_path, monkeypatch, rerun)
        assert reward["score"] == 0.0
        assert detail["solver_evidence"] == {
            "mesh_and_solution": False,
            "mesh_and_solution_files_present": False,
            "any_solver_artifact": True}

    def test_a_rerun_that_forges_the_artifacts_scores_zero(self, tmp_path, monkeypatch):
        """#377's `forged` arm, end to end through the evaluator.

        Same submission, same rerun seam, one difference from the arm above:
        the four lines that used to satisfy the gate. `mesh_and_solution` is
        False while `mesh_and_solution_files_present` is True, which is the
        pair a reader needs -- something was written, and OpenFOAM did not
        write it.
        """
        reward, detail = self._run(tmp_path, monkeypatch, self._forging_rerun)
        assert reward["score"] == 0.0
        assert detail["stage"] == "solver_evidence"
        assert detail["solver_evidence"] == {
            "mesh_and_solution": False,
            "mesh_and_solution_files_present": True,
            "any_solver_artifact": True}
        assert "do not read as OpenFOAM output" in detail["error"]

    def test_a_rerun_that_meshed_and_solved_is_untouched(self, tmp_path, monkeypatch):
        """The other side. All nineteen cfd oracles land here -- measured, #211."""
        reward, detail = self._run(tmp_path, monkeypatch, self._solving_rerun)
        assert reward["score"] == pytest.approx(1.0)
        assert detail["checks"]["solver_evidence"] == "passed"
        assert detail["solver_evidence"]["mesh_and_solution"] is True

    def _relation_run(self, tmp_path, monkeypatch):
        """The whole evaluator over a two-row `results.csv` and a relation KPI."""
        monkeypatch.setattr(type(self), "SPEC", {
            "case_id": "fake_relation_case",
            "interface": {"file": "results.csv", "columns": ["cd"],
                          "labels": ["config"], "min_rows": 2},
            "kpis": {"cd_ratio": {"derive": "pair_ratio", "key": "config",
                                  "a": "baseline", "b": "modified", "value": "cd"}},
        })
        monkeypatch.setattr(type(self), "KPIS", {
            "cd_ratio": {"group": "outputs", "gt_value": 0.8, "physics_min": 0.0,
                         "physics_max": 2.0, "pass_tol": 0.04}})

        def rerun(case):
            self._solving_rerun(case)
            (case / "results.csv").write_text(
                "config,cd\nbaseline,0.53\nmodified,0.424\n", encoding="utf-8")

        return self._run(tmp_path, monkeypatch, rerun)

    def test_the_declared_label_column_reaches_the_reader(self, tmp_path, monkeypatch):
        """The one line of wiring the derivation's own tests cannot see.

        `spec.json`'s `labels` has to reach `read_interface` from *this*
        module; a typo there leaves every derivation test green while every
        relation case fails on a correct answer. That is the shape of #211 --
        a predicate can be perfect and score nothing if nobody calls it.

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
            self, tmp_path, monkeypatch):
        reward, detail = self._relation_run(tmp_path, monkeypatch)

        assert reward["score"] == pytest.approx(1.0)
        assert detail["scoring_components"]["cd_ratio"]["value"] == pytest.approx(0.8)

    def test_the_gate_reads_the_evaluators_copy_not_the_submission(
            self, tmp_path, monkeypatch):
        """A shipped mesh proves nothing: `strip_generated` deletes it first.

        This is why the check is worth having at all. Put a full solved tree in
        the submission, have the rerun produce only the answer, and the score is
        still zero -- forging the evidence means making the rerun solve.
        """
        tests = self._tests_dir(tmp_path)
        sub = self._submission(tmp_path)
        mesh = sub / "constant" / "polyMesh"
        mesh.mkdir(parents=True)
        (mesh / "points").write_text("(0 0 0)", encoding="utf-8")
        (mesh / "faces").write_text("(0 1 2 3)", encoding="utf-8")
        (sub / "500").mkdir()
        (sub / "500" / "U").write_text("internalField", encoding="utf-8")
        reward = tmp_path / "reward"
        monkeypatch.setenv("SIM_BENCH_SUBMISSION", str(sub))
        monkeypatch.setenv("SIM_BENCH_REWARD_DIR", str(reward))

        def fake(case, command, *, timeout_s, log_path, check=True):
            self._printf_rerun(case)
            return {"command": command, "exit_code": 0, "duration_s": 0.0}

        monkeypatch.setattr(of_interface, "openfoam_command", fake)
        assert main_from_case(tests) == 0
        assert json.loads((reward / "reward.json").read_text(encoding="utf-8"))["score"] == 0.0
