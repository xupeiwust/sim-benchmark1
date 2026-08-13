"""Behavioural tests for the PyBaMM artifact detector.

The point of this detector is the line it draws between *input* and
*evidence*: a driver script and a parameter file are things an agent can write
without ever solving anything, so neither may count. These tests pin that line
down, because a detector that answers "yes" without the solver having run
means the benchmark cannot tell a real run from a hallucination.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_benchmark_verifier.detectors import TrialContext, has_solver_evidence  # noqa: E402
from sim_benchmark_verifier.detectors import pybamm as det  # noqa: E402


class Case:
    """A throwaway case directory."""

    def __init__(self, td: str):
        self.dir = Path(td)

    def write(self, name: str, text: str) -> Case:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return self

    def ctx(self, label: str | None = "pybamm") -> TrialContext:
        return TrialContext(case_dir=self.dir, solver_label=label)


STATE_DUMP = (
    "time_s,current_A,voltage_V\n"
    "0.0,5.0,4.0377\n"
    "10.0,5.0,4.0102\n"
    "20.0,5.0,3.9944\n"
    "30.0,5.0,3.9821\n"
)


class EvidenceTests(unittest.TestCase):
    def test_a_numeric_state_dump_is_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("results.csv", STATE_DUMP)
            self.assertTrue(det.has_solver_evidence(c.ctx()))

    def test_a_driver_script_alone_is_not_evidence(self):
        """The `.py` is input — writable without calling the solver."""
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write(
                "run_case.py",
                "import pybamm\nsim = pybamm.Simulation(pybamm.lithium_ion.DFN())\n",
            )
            self.assertFalse(det.has_solver_evidence(c.ctx()))

    def test_a_parameter_input_file_alone_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("inputs.json", '{"C_rate": 0.87}')
            self.assertFalse(det.has_solver_evidence(c.ctx()))

    def test_an_empty_case_directory_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(det.has_solver_evidence(Case(td).ctx()))

    def test_a_missing_case_directory_is_not_evidence(self):
        self.assertFalse(
            det.has_solver_evidence(TrialContext(case_dir=None, solver_label="pybamm"))
        )

    def test_a_one_column_table_is_not_a_state_dump(self):
        """Two numeric columns minimum: a bare list of times proves nothing."""
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("times.csv", "time_s\n0.0\n1.0\n2.0\n3.0\n")
            self.assertFalse(det.has_solver_evidence(c.ctx()))

    def test_a_log_carrying_a_pybamm_banner_is_secondary_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write(
                "solve.log", "building pybamm.lithium_ion.DFN\nTerminal voltage [V]\n"
            )
            self.assertTrue(det.has_solver_evidence(c.ctx()))

    def test_registry_dispatch_reaches_this_detector(self):
        """The cross-solver entry point must know the `pybamm` label."""
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("results.csv", STATE_DUMP)
            self.assertTrue(has_solver_evidence(c.ctx()))
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("run_case.py", "import pybamm\n")
            self.assertFalse(has_solver_evidence(c.ctx()))


class StageTests(unittest.TestCase):
    def _detector(self):
        return det.PyBaMMDetector()

    def test_no_artifacts_is_a_solver_crash(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("run_case.py", "import pybamm\n")
            self.assertEqual(
                self._detector().detect({}, c.ctx()), "L2_solver_crash"
            )

    def test_a_fatal_solver_error_in_the_log_is_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write(
                "solve.log",
                "pybamm.Simulation starting\n"
                "pybamm.SolverError: could not find consistent initial conditions\n",
            )
            self.assertEqual(
                self._detector().detect({}, c.ctx()), "L2_solver_crash"
            )

    def test_a_clean_run_attributes_nothing(self):
        """Clean runs defer to the universal detector for L5 / L6."""
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("results.csv", STATE_DUMP)
            self.assertIsNone(self._detector().detect({}, c.ctx()))

    def test_applicable_on_the_label_even_before_any_artifact_exists(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self._detector().applicable(Case(td).ctx()))

    def test_not_applicable_to_an_unrelated_solver_with_no_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            c = Case(td).write("run.inp", "*NODE\n")
            self.assertFalse(self._detector().applicable(c.ctx(label="calculix")))


if __name__ == "__main__":
    unittest.main()
