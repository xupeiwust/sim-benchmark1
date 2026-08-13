from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sim_benchmark_verifier import native_openfoam as native


class NativeOpenFOAMRuntimeTests(unittest.TestCase):
    def test_dictionary_block_uses_balanced_braces(self) -> None:
        text = "boundaryField { inlet { type fixedValue; nested { x 1; } } outlet { type zeroGradient; } }"
        self.assertIn("nested { x 1; }", native.dictionary_block(text, "inlet"))
        self.assertIn("type zeroGradient", native.dictionary_block(text, "outlet"))

    def test_sample_dict_moves_only_the_spanwise_coordinate(self) -> None:
        text = (
            "sets\n(\n    centerPoint\n    {\n        type cloud;\n"
            "        points ((0.5 0 0.05));\n    }\n"
            "    profile\n    {\n        type uniform;\n"
            "        start (20 -0.49375 0.05);\n        end (20 0.49375 0.05);\n    }\n);\n"
        )
        moved = native.sample_dict_on_mid_plane(text, -0.005, 0.005)
        self.assertIn("points ((0.5 0 0.0))", moved)
        self.assertIn("start (20 -0.49375 0.0)", moved)
        self.assertIn("end (20 0.49375 0.0)", moved)

    def test_sample_dict_is_a_no_op_on_the_slab_it_was_written_for(self) -> None:
        """The fix must not move any submission that already scored."""
        text = "points ((0.5 0 0.05));\nstart (0.5 0.00125 0.05);\n"
        self.assertEqual(native.sample_dict_on_mid_plane(text, 0.0, 0.1), text)

    def test_install_sample_dict_places_the_plane_from_the_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir) / "case"
            (case / "system").mkdir(parents=True)
            source = Path(temp_dir) / "evaluatorSample"
            source.write_text("points ((0.5 0 0.05));\n", encoding="utf-8")
            with mock.patch.object(
                native, "reproduced_mesh_bounds", return_value=(0, 1, -0.5, 0.5, 0, 0.0099)
            ):
                detail = native.install_sample_dict(
                    case, source, "system/evaluatorSample", Path(temp_dir)
                )
            self.assertAlmostEqual(detail["sample_plane"], 0.00495)
            self.assertIn(
                "0.00495", (case / "system/evaluatorSample").read_text(encoding="utf-8")
            )

    def test_install_sample_dict_rejects_an_unknown_axis(self) -> None:
        with self.assertRaises(ValueError):
            native.sample_dict_on_mid_plane("points ((0 0 0));", 0, 1, axis="w")

    def test_a_reproduction_timeout_is_its_own_category(self) -> None:
        """A budget the evaluator ran out of is not a defect it found.

        Folded into `reproduction_failed`, a timeout looked exactly like a mesh
        that will never build -- which is how a case whose rows sorted by
        wall-clock, its own oracle among the failures, stayed invisible.
        """
        for message, expected in (
            ("command timed out after 600s: bash ./Allrun", "reproduction_timeout"),
            ("command failed with exit 1: bash ./Allrun", "reproduction_failed"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                submission = self.make_submission(root)
                rewards = root / "rewards"
                with mock.patch.dict(
                    os.environ,
                    {"SIM_BENCH_SUBMISSION": str(submission), "SIM_BENCH_REWARD_DIR": str(rewards)},
                ), mock.patch.object(
                    native, "openfoam_command", side_effect=RuntimeError(message)
                ):
                    native.evaluate(native.NativeOpenFOAMTask(
                        "unit", ("U", "p"), lambda *_: native.EvaluationResult(1, {})))
                self.assertEqual(self.read_detail(rewards)["failure_category"], expected)

    def test_poly_mesh_bounds_reads_native_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            points = case / "constant/polyMesh/points"
            points.parent.mkdir(parents=True)
            points.write_text(
                "8\n(\n(0 0 0)\n(2 0 0)\n(2 1 0)\n(0 1 0)\n"
                "(0 0 1)\n(2 0 1)\n(2 1 1)\n(0 1 1)\n)\n",
                encoding="utf-8",
            )
            self.assertEqual(native.poly_mesh_bounds(case), (0, 2, 0, 1, 0, 1))

    def test_bounds_from_check_mesh_output(self) -> None:
        output = "Bounding box (0 -1e-3 0) (9 3.035 1)\nMesh OK.\n"
        self.assertEqual(
            native.bounds_from_check_mesh_output(output),
            (0, 9, -0.001, 3.035, 0, 1),
        )
    @staticmethod
    def make_submission(root: Path) -> Path:
        submission = root / "submission"
        for name in ("0", "constant", "system"):
            (submission / name).mkdir(parents=True, exist_ok=True)
        (submission / "Allrun").write_text("#!/bin/bash\n", encoding="utf-8")
        return submission

    @staticmethod
    def reproduce_with_fields(case: Path, command: str, *, log_path: Path, **_kwargs):
        if command == "bash ./Allrun":
            solved = case / "10"
            solved.mkdir()
            for field in ("U", "p"):
                (solved / field).write_text("field", encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        return {"command": command, "duration_s": 0.01, "exit_code": 0, "log": log_path.name}

    @staticmethod
    def read_detail(reward_dir: Path) -> dict:
        return json.loads((reward_dir / "reward_detail.json").read_text(encoding="utf-8"))

    def test_cleanup_preserves_inputs_and_removes_generated_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            for name in ("0", "constant", "system", "10", "postProcessing", "processor0"):
                (case / name).mkdir()
            (case / "constant/polyMesh").mkdir()
            (case / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
            (case / "log.solver").write_text("old", encoding="utf-8")
            (case / "pipe.step").write_text("generated", encoding="utf-8")
            removed = native.clean_generated_artifacts(case, ("pipe.step",))
            self.assertEqual(
                removed,
                ["10", "constant/polyMesh", "log.solver", "pipe.step", "postProcessing", "processor0"],
            )
            self.assertTrue((case / "0").is_dir())
            self.assertTrue((case / "Allrun").is_file())

    def test_cleanup_reaches_generated_state_at_any_depth(self) -> None:
        """The strip has to reach as far as the check it feeds.

        `detectors.openfoam` globs `polyMesh` and numeric time directories with
        `rglob` from the submission root, so a one-level strip left
        `solved/run_a/constant/polyMesh` and `solved/run_a/1000/U` for an entry
        point to copy back into place. Reachable by nesting alone, once
        `validate_submission` stopped pinning the case to the root (#648).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            (case / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
            for config in ("run_a", "run_b"):
                for name in ("0", "constant", "system", "1000", "postProcessing"):
                    (case / config / name).mkdir(parents=True)
                (case / config / "constant" / "polyMesh").mkdir()
                (case / config / "log.solver").write_text("old", encoding="utf-8")
            solved = case / "solved" / "run_a"
            (solved / "constant" / "polyMesh").mkdir(parents=True)
            (solved / "1000").mkdir(parents=True)
            (solved / "1000" / "U").write_text("solved", encoding="utf-8")

            removed = native.clean_generated_artifacts(case)

            self.assertEqual(list(case.rglob("polyMesh")), [])
            self.assertFalse((solved / "1000").exists())
            self.assertIn("solved/run_a/1000", removed)
            self.assertIn("run_b/constant/polyMesh", removed)
            for config in ("run_a", "run_b"):
                self.assertTrue((case / config / "0").is_dir())
                self.assertTrue((case / config / "system").is_dir())

    def test_cleanup_resolves_an_extra_path_at_any_depth(self) -> None:
        """An author names a generated file, not the one level they pictured it at."""
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            for name in ("0", "constant", "system"):
                (case / name).mkdir()
            (case / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
            (case / "pipe.step").write_text("generated", encoding="utf-8")
            (case / "spare").mkdir()
            (case / "spare" / "pipe.step").write_text("generated", encoding="utf-8")
            removed = native.clean_generated_artifacts(case, ("pipe.step",))
            self.assertEqual(list(case.rglob("pipe.step")), [])
            self.assertIn("spare/pipe.step", removed)

    def test_a_numeric_input_directory_is_not_a_time_directory(self) -> None:
        """#199's exemption, and the one thing that bounds it.

        `20/` beside a driver script is a refinement level when it is a case in
        its own right, and an input when it holds no field. It stops being
        either the moment it holds a name the detector reads as a solution.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            (case / "meshes" / "20").mkdir(parents=True)
            (case / "meshes" / "20" / "blockMeshDict").write_text("g", encoding="utf-8")
            (case / "levels" / "40" / "system").mkdir(parents=True)
            (case / "spare" / "80").mkdir(parents=True)
            (case / "spare" / "80" / "U").write_text("solved", encoding="utf-8")
            native.clean_generated_artifacts(case)
            self.assertTrue((case / "meshes" / "20" / "blockMeshDict").is_file())
            self.assertTrue((case / "levels" / "40" / "system").is_dir())
            self.assertFalse((case / "spare" / "80").exists())

    def test_a_multi_configuration_submission_is_valid(self) -> None:
        """The layout is the submission's to choose; the entry point is not.

        A relation KPI needs two configurations solved and compared, so its
        submission has one `system/` per configuration and no case at the root.
        The old check read that as a missing case and refused it at
        `submission_validation`, before any physics was read.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            (case / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
            for config in ("slow_floor", "fast_floor"):
                for name in ("0", "constant", "system"):
                    (case / config / name).mkdir(parents=True)
            native.validate_submission(case)  # no raise

    def test_an_entry_point_with_no_case_under_it_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            (case / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
            (case / "notes").mkdir()
            with self.assertRaises(native.EvaluationFailure) as caught:
                native.validate_submission(case)
            self.assertEqual(caught.exception.category, "invalid_submission")

    def test_a_case_at_any_depth_still_needs_the_entry_point(self) -> None:
        """`Allrun` stays pinned to the root: the rerun is `bash ./Allrun` there."""
        with tempfile.TemporaryDirectory() as temp_dir:
            case = Path(temp_dir)
            for name in ("0", "constant", "system"):
                (case / "run_a" / name).mkdir(parents=True)
            with self.assertRaises(native.EvaluationFailure) as caught:
                native.validate_submission(case)
            self.assertIn("Allrun", str(caught.exception))

    def test_cleanup_rejects_unsafe_extra_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsafe generated path"):
                native.clean_generated_artifacts(Path(temp_dir), ("../outside",))

    def test_missing_submission_has_stable_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(native.EvaluationFailure) as caught:
                native.validate_submission(Path(temp_dir))
            self.assertEqual(caught.exception.category, "invalid_submission")

    def test_extended_geometry_warning_does_not_override_basic_mesh_ok(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rewards = root / "rewards"

            def fake_command(_case, command, *, log_path, **_kwargs):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                if "allGeometry" in command:
                    log_path.write_text("Failed 1 mesh checks.\n", encoding="utf-8")
                else:
                    log_path.write_text("Mesh OK.\n", encoding="utf-8")
                return {"command": command, "exit_code": 0, "log": log_path.name}

            with mock.patch.object(native, "openfoam_command", side_effect=fake_command):
                result = native.check_mesh(root, rewards, 30)
            self.assertTrue(result["mesh_ok"])
            self.assertEqual(result["all_geometry_diagnostic"]["failed_check_count"], 1)
            self.assertFalse(result["all_geometry_diagnostic"]["hard_gate"])

    def test_basic_high_aspect_ratio_only_is_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rewards = root / "rewards"
            valid = "\n".join(
                (
                    "Boundary definition OK.",
                    "Cell to face addressing OK.",
                    "Point usage OK.",
                    "Face vertices OK.",
                    "Number of regions: 1 (OK).",
                    "***High aspect ratio cells found, Max aspect ratio: 10208",
                    "Cell volumes OK.",
                    "Non-orthogonality check OK.",
                    "Face pyramids OK.",
                    "Max skewness = 1e-14 OK.",
                    "Failed 1 mesh checks.",
                )
            )

            def fake_command(_case, command, *, log_path, **_kwargs):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(
                    "Mesh OK.\n" if "allGeometry" in command else valid,
                    encoding="utf-8",
                )
                return {"command": command, "exit_code": 0, "log": log_path.name}

            with mock.patch.object(native, "openfoam_command", side_effect=fake_command):
                result = native.check_mesh(root, rewards, 30)
            self.assertTrue(result["mesh_ok"])
            self.assertEqual(result["accepted_diagnostic"], "high_aspect_ratio_only")
            self.assertEqual(result["failed_check_count"], 1)

    def test_basic_high_aspect_ratio_does_not_hide_another_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rewards = root / "rewards"

            def fake_command(_case, command, *, log_path, **_kwargs):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(
                    "***High aspect ratio cells found\nFailed 2 mesh checks.\n",
                    encoding="utf-8",
                )
                return {"command": command, "exit_code": 0, "log": log_path.name}

            with mock.patch.object(native, "openfoam_command", side_effect=fake_command):
                with self.assertRaisesRegex(RuntimeError, "valid mesh"):
                    native.check_mesh(root, rewards, 30)

    def test_command_nonzero_is_error_by_default(self) -> None:
        process = mock.Mock(pid=123, returncode=4)
        process.communicate.return_value = ("", "bad")
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            native, "discover_openfoam_bashrc", return_value=None
        ), mock.patch.object(native.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "exit 4"):
                native.openfoam_command(
                    Path(temp_dir),
                    "false",
                    timeout_s=1,
                    log_path=Path(temp_dir) / "log",
                )

    def test_command_timeout_is_reported_and_logged(self) -> None:
        expired = subprocess.TimeoutExpired("slow", 1, output="partial", stderr="tail")
        process = mock.Mock(pid=123, returncode=-15)
        process.communicate.side_effect = [expired, ("partial", "tail")]
        # killpg must be patched: the implementation prefers it over
        # proc.terminate() wherever it exists, so leaving it real would send
        # SIGTERM to whatever process group happens to own the mocked pid on
        # this machine. `terminate()` is only the Windows fallback path.
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            native, "discover_openfoam_bashrc", return_value=None
        ), mock.patch.object(native.subprocess, "Popen", return_value=process), mock.patch.object(
            native.os, "killpg", create=True
        ) as killpg:
            log = Path(temp_dir) / "timeout.log"
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                native.openfoam_command(Path(temp_dir), "slow", timeout_s=1, log_path=log)
            self.assertEqual(log.read_text(encoding="utf-8"), "partialtail")
            killpg.assert_called_once_with(123, signal.SIGTERM)

    def test_command_timeout_escalates_from_term_to_kill_for_process_group(self) -> None:
        first_timeout = subprocess.TimeoutExpired("slow", 1)
        grace_timeout = subprocess.TimeoutExpired("slow", 5)
        process = mock.Mock(pid=456, returncode=-9)
        process.communicate.side_effect = [
            first_timeout,
            grace_timeout,
            ("partial", "tail"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            native, "discover_openfoam_bashrc", return_value=None
        ), mock.patch.object(native.subprocess, "Popen", return_value=process), mock.patch.object(
            native.os, "killpg", create=True
        ) as killpg:
            log = Path(temp_dir) / "timeout.log"
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                native.openfoam_command(Path(temp_dir), "slow", timeout_s=1, log_path=log)
            self.assertEqual(log.read_text(encoding="utf-8"), "partialtail")
            self.assertEqual(
                killpg.call_args_list,
                [mock.call(456, signal.SIGTERM), mock.call(456, 9)],
            )

    def test_evaluate_success_uses_completed_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submission = self.make_submission(root)
            rewards = root / "rewards"
            task = native.NativeOpenFOAMTask(
                case_id="unit",
                solved_fields=("U", "p"),
                validate_setup=lambda _case: {"nu": 1.0},
                extract_and_score=lambda _case, solved: native.EvaluationResult(
                    0.75, {"extraction": {"solved_time": solved.name}}
                ),
            )
            with mock.patch.dict(
                os.environ,
                {"SIM_BENCH_SUBMISSION": str(submission), "SIM_BENCH_REWARD_DIR": str(rewards)},
            ), mock.patch.object(
                native, "openfoam_command", side_effect=self.reproduce_with_fields
            ), mock.patch.object(native, "check_mesh", return_value={"mesh_ok": True}):
                self.assertEqual(native.evaluate(task), 0)
            detail = self.read_detail(rewards)
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(detail["extraction"]["solved_time"], "10")
            self.assertEqual(json.loads((rewards / "reward.json").read_text())["score"], 0.75)

    def test_evaluate_nonzero_allrun_is_reproduction_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submission = self.make_submission(root)
            rewards = root / "rewards"
            task = native.NativeOpenFOAMTask("unit", ("U",), lambda *_: native.EvaluationResult(1, {}))
            with mock.patch.dict(
                os.environ,
                {"SIM_BENCH_SUBMISSION": str(submission), "SIM_BENCH_REWARD_DIR": str(rewards)},
            ), mock.patch.object(native, "openfoam_command", side_effect=RuntimeError("exit 2")):
                native.evaluate(task)
            self.assertEqual(self.read_detail(rewards)["failure_category"], "reproduction_failed")

    def test_evaluate_missing_final_fields_is_reproduction_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submission = self.make_submission(root)
            rewards = root / "rewards"
            task = native.NativeOpenFOAMTask("unit", ("U",), lambda *_: native.EvaluationResult(1, {}))

            def no_fields(_case, command, *, log_path, **_kwargs):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("ok", encoding="utf-8")
                return {"command": command, "exit_code": 0, "log": log_path.name}

            with mock.patch.dict(
                os.environ,
                {"SIM_BENCH_SUBMISSION": str(submission), "SIM_BENCH_REWARD_DIR": str(rewards)},
            ), mock.patch.object(native, "openfoam_command", side_effect=no_fields):
                native.evaluate(task)
            self.assertEqual(self.read_detail(rewards)["failure_category"], "reproduction_failed")

    def test_evaluate_preserves_setup_mesh_extraction_and_resolution_categories(self) -> None:
        scenarios = (
            ("invalid_physics_setup", lambda: native.NativeOpenFOAMTask(
                "unit", ("U", "p"), lambda *_: native.EvaluationResult(1, {}),
                validate_setup=lambda _case: (_ for _ in ()).throw(RuntimeError("wrong nu")),
            ), None),
            ("invalid_mesh", lambda: native.NativeOpenFOAMTask(
                "unit", ("U", "p"), lambda *_: native.EvaluationResult(1, {}),
            ), RuntimeError("bad mesh")),
            ("extraction_failed", lambda: native.NativeOpenFOAMTask(
                "unit", ("U", "p"), lambda *_: (_ for _ in ()).throw(RuntimeError("bad sample")),
            ), None),
            ("under_resolved_mesh", lambda: native.NativeOpenFOAMTask(
                "unit", ("U", "p"), lambda *_: (_ for _ in ()).throw(
                    native.EvaluationFailure("under_resolved_mesh", "y+ too high")
                ),
            ), None),
        )
        for expected, task_factory, mesh_error in scenarios:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                submission = self.make_submission(root)
                rewards = root / "rewards"
                mesh_effect = mesh_error if mesh_error else {"mesh_ok": True}
                with mock.patch.dict(
                    os.environ,
                    {"SIM_BENCH_SUBMISSION": str(submission), "SIM_BENCH_REWARD_DIR": str(rewards)},
                ), mock.patch.object(
                    native, "openfoam_command", side_effect=self.reproduce_with_fields
                ), mock.patch.object(native, "check_mesh", side_effect=mesh_error) if mesh_error else mock.patch.object(
                    native, "check_mesh", return_value=mesh_effect
                ):
                    native.evaluate(task_factory())
                self.assertEqual(self.read_detail(rewards)["failure_category"], expected)


if __name__ == "__main__":
    unittest.main()
