"""The reproduction budget: what a failure says, and what a pass costs.

Both native evaluators re-run the agent's own driver under
`tests/spec.json`'s `reproduction_timeout_s`, and that deadline is a gate a
correct answer can lose to: a submission whose numbers sit inside the tolerance
band scores 0.0 if its driver overruns. The budget itself is not in dispute
here -- every live case states it in `instruction.md`, `lint_case.py` enforces
both that statement and a floor against the case's own oracle, and CLAUDE.md's
"What the budget is" makes finishing inside a stated budget part of the task.
What was in dispute is that nothing downstream could tell which of two very
different things had happened, and nothing at all recorded how close a passing
run came (#88).

Both halves are visible in the stored trials. Across the surviving
`reward_detail.json` files, `clean_reproduction: fail` appears 120 times and
splits -- by string-matching an exception class name inside a free-text `why`
-- into 118 "no run_case.py", one driver crash and one overrun. The store
itself keeps only the word `fail` for all 120, which is why #88 could not
answer its own first question about the 19 failures it was filed on. And across
333 passing records the keys are `exit_code`, `stdout_tail`, `stripped_files`,
`stripped_submitted_artifacts`: not one of them says how many of its 600 or 900
seconds the run used.

So these tests assert the two things that were missing, on both tracks:

  * a failed reproduction names its kind in a field, not in a sentence;
  * a passing one records what it cost.

Against the code before this file existed, every assertion below fails --
`ReproductionFailed` did not exist, `subprocess.TimeoutExpired` and
`RuntimeError` reached `Recorder.run` as bare exceptions, and the cost keys
were never written on any path.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_benchmark_verifier import native_cantera as nc  # noqa: E402
from sim_benchmark_verifier import native_pybamm as nb  # noqa: E402
from sim_benchmark_verifier import reproduction as rp  # noqa: E402

_WRITES_RESULTS = """\
    import pathlib
    pathlib.Path("results.csv").write_text("time_s,T_K,P_Pa\\n0,300,101325\\n")
    """

_SLEEPS_PAST_THE_BUDGET = """\
    import time
    time.sleep(30)
    """

_CRASHES = """\
    raise RuntimeError("the solve diverged")
    """

_NEVER_WRITES_RESULTS = """\
    print("done")
    """


def _cantera_spec(**kw):
    base = dict(case_id="unit", kind="idt", mechanism="gri30.yaml", fuel="CH4",
                phi=1.0, T0_K=1400.0, P0_atm=1.0)
    base.update(kw)
    return nc.CanteraSpec(**base)


def _pybamm_spec(**kw):
    base = dict(case_id="unit", kind="discharge", parameter_set="Chen2020",
                initial_soc=1.0)
    base.update(kw)
    return nb.PyBaMMSpec(**base)


class _ReproductionCase(unittest.TestCase):
    """Drives one evaluator's `_reproduce` over a toy submission."""

    module = nc
    spec_factory = staticmethod(_cantera_spec)

    def _reproduce(self, driver_source: str, *, timeout_s: int = 2):
        """Return (result, exception, workdir, log_path). Exactly one of the
        first two is None."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sub = root / "submission"
        sub.mkdir()
        (sub / self.module.DRIVER_NAME).write_text(
            textwrap.dedent(driver_source), encoding="utf-8")
        work, logs = root / "work", root / "logs"
        spec = self.spec_factory(reproduction_timeout_s=timeout_s)
        try:
            return (self.module._reproduce(sub, work, spec, logs), None, work,
                    logs / "evaluator_reproduction.log")
        except Exception as exc:  # noqa: BLE001 - the exception IS the subject
            return None, exc, work, logs / "evaluator_reproduction.log"


class CanteraReproductionBudgetTests(_ReproductionCase):
    module = nc
    spec_factory = staticmethod(_cantera_spec)

    def test_an_overrun_and_a_crash_are_different_failure_kinds(self):
        """The distinction the 19 stored zeros could not be asked for.

        Before this, one arrived as `TimeoutExpired` and the other as
        `RuntimeError`, both flattened by the store into the single word
        `fail`. Only the class name told them apart, and only inside a
        free-text sentence.
        """
        _, slow, _, _ = self._reproduce(_SLEEPS_PAST_THE_BUDGET, timeout_s=1)
        _, broken, _, _ = self._reproduce(_CRASHES)

        self.assertIsInstance(slow, rp.ReproductionFailed)
        self.assertIsInstance(broken, rp.ReproductionFailed)
        self.assertEqual(slow.detail["failure_kind"], rp.TIMEOUT)
        self.assertEqual(broken.detail["failure_kind"], rp.DRIVER_ERROR)
        self.assertNotEqual(slow.detail["failure_kind"], broken.detail["failure_kind"])

    def test_the_two_ways_the_output_can_be_absent_are_also_distinct(self):
        """A missing driver and a driver that wrote nothing are not one thing.

        118 of the 120 stored reproduction failures are the first kind -- an
        agent that ran out of wall-clock before shipping `run_case.py` -- and
        reading them as solver failures would misattribute nearly every one.
        """
        _, absent, _, _ = self._reproduce(_WRITES_RESULTS)
        absent_driver = self._missing_driver()
        _, silent, _, _ = self._reproduce(_NEVER_WRITES_RESULTS)

        self.assertIsNone(absent)  # the control: this one succeeds
        self.assertEqual(absent_driver.detail["failure_kind"], rp.DRIVER_MISSING)
        self.assertEqual(silent.detail["failure_kind"], rp.RESULTS_MISSING)

    def _missing_driver(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sub = root / "submission"
        sub.mkdir()
        (sub / "notes.txt").write_text("I ran out of time", encoding="utf-8")
        with self.assertRaises(rp.ReproductionFailed) as caught:
            self.module._reproduce(sub, root / "work",
                                   self.spec_factory(reproduction_timeout_s=2),
                                   root / "logs")
        return caught.exception

    def test_a_passing_reproduction_records_what_it_cost(self):
        """`余量是运气` stops being an anecdote once every pass carries a number.

        The one measurement anyone had of this gate's headroom -- 728 s of a
        900 s budget -- was read out of a container log by hand. A budget can
        only be sized from what real submissions cost, so the cost travels with
        every record, not only with the failures.
        """
        ok, exc, _, _ = self._reproduce(_WRITES_RESULTS, timeout_s=30)
        self.assertIsNone(exc)
        self.assertEqual(ok["reproduction_timeout_s"], 30)
        self.assertGreater(ok["reproduction_wall_sec"], 0.0)
        self.assertLess(ok["reproduction_wall_sec"], 30.0)
        self.assertAlmostEqual(
            ok["reproduction_budget_used"],
            ok["reproduction_wall_sec"] / 30, places=2)

    def test_an_overrun_also_reports_the_budget_it_overran(self):
        """A gate that raises must not throw away what it measured.

        `native_pybamm.CheckFailed` already says this about the OCV gate; the
        reproduction gate was the one that still lost everything.
        """
        _, exc, _, _ = self._reproduce(_SLEEPS_PAST_THE_BUDGET, timeout_s=1)
        self.assertEqual(exc.detail["reproduction_timeout_s"], 1)
        self.assertGreaterEqual(exc.detail["reproduction_wall_sec"], 1.0)

    def test_a_failed_reproduction_reaches_the_dimension_as_a_field(self):
        """End to end: `reward_detail.json` carries the kind, not just a word.

        This is the assertion that answers #88's first acceptance criterion for
        every future trial -- `clean_reproduction` is no longer one value
        covering two unrelated failures.
        """
        rec = self.module.Recorder()
        _, exc, _, _ = self._reproduce(_SLEEPS_PAST_THE_BUDGET, timeout_s=1)

        def _raise():
            raise exc

        rec.run("clean_reproduction", _raise)
        dim = rec.as_dict()["clean_reproduction"]
        self.assertEqual(dim["status"], "fail")
        self.assertEqual(dim["failure_kind"], rp.TIMEOUT)
        self.assertEqual(dim["reproduction_timeout_s"], 1)

    def test_an_overrun_still_writes_the_evaluator_log(self):
        """The one failure with nothing else to look at used to leave no log.

        The log write sat after the call that raised, so a timeout discarded
        the driver's partial output as well as its cause.
        """
        _, exc, _, log = self._reproduce(
            'import sys\nprint("step 1", flush=True)\nimport time\ntime.sleep(30)\n',
            timeout_s=1)
        self.assertIsInstance(exc, rp.ReproductionFailed)
        self.assertTrue(log.is_file(), "a timed-out reproduction wrote no log")
        self.assertIn("step 1", log.read_text(encoding="utf-8"))


class PyBaMMReproductionBudgetTests(CanteraReproductionBudgetTests):
    """The same contract on the other native track.

    Both evaluators produced stored reproduction failures, and the surviving
    overrun is a battery case (`ecker_graphite_energy_1p12c_298k`, 600 s), so
    covering only combustion would leave the half that has the one real
    example.
    """

    module = nb
    spec_factory = staticmethod(_pybamm_spec)


class ProcessGroupTests(unittest.TestCase):
    """The declared budget has to bind the driver's children too.

    A grid-refinement sweep fanned out over `multiprocessing` leaves workers
    running when only the direct child is signalled. They then compete for the
    verifier container's remaining seconds -- 120 of them, on a combustion case
    whose `[verifier].timeout_sec` is 1020 against a 900 s budget -- with the
    scoring that has to finish inside them, and a verifier that does not finish
    stores as `unmeasured` rather than as a score.

    POSIX-only because process groups are: on Windows the runner is not what
    this benchmark scores on, and `run_driver` falls back to killing the direct
    child there.
    """

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX")
    def test_a_grandchild_does_not_outlive_the_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "run_case.py").write_text(textwrap.dedent("""\
                import subprocess, sys, time
                subprocess.Popen([sys.executable, "-c",
                                  "import time, pathlib; time.sleep(2); "
                                  "pathlib.Path('MARKER').write_text('x')"])
                time.sleep(30)
                """), encoding="utf-8")
            with self.assertRaises(rp.ReproductionFailed):
                rp.run_driver([sys.executable, "run_case.py"], cwd=work,
                              timeout_s=1, log_path=work / "log.txt")
            time.sleep(4)
            self.assertFalse(
                (work / "MARKER").is_file(),
                "a child of the driver kept running past the reproduction budget")


if __name__ == "__main__":
    unittest.main()
