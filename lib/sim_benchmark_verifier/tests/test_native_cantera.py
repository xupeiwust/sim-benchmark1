"""Unit tests for the shared Cantera evaluator.

These cover the lifecycle and gating logic without requiring Cantera itself:
the equilibrium computation is the only part that needs the library, and the
tests that touch it are skipped when it is absent.
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_benchmark_verifier import native_cantera as nc  # noqa: E402


def _has_cantera() -> bool:
    try:
        import cantera  # noqa: F401
        return True
    except Exception:
        return False


def _spec(**kw):
    base = dict(
        case_id="unit", kind="idt", mechanism="gri30.yaml", fuel="CH4",
        phi=1.0, T0_K=1400.0, P0_atm=1.0,
    )
    base.update(kw)
    return nc.CanteraSpec(**base)


class ColumnParsingTests(unittest.TestCase):
    def _write(self, tmp: Path, text: str) -> Path:
        p = tmp / nc.RESULTS_NAME
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return p

    def test_reads_a_simple_table(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                time_s,T_K,P_Pa
                0.0,1400.0,101325.0
                1e-4,1500.0,110000.0
                2e-4,2800.0,300000.0
                """)
            cols = nc.read_results_csv(p)
            self.assertEqual(sorted(cols), ["P_Pa", "T_K", "time_s"])
            self.assertEqual(len(cols["time_s"]), 3)

    def test_rejects_a_table_with_no_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), "time_s,T_K\n")
            with self.assertRaises(RuntimeError):
                nc.read_results_csv(p)

    def test_column_lookup_tolerates_author_naming(self):
        """A submission is graded on physics, not on header spelling."""
        cols = {"Time (s)": [0.0, 1.0], "T (K)": [300.0, 400.0]}
        self.assertEqual(nc.pick_column(cols, "time_s", "time"), [0.0, 1.0])
        self.assertEqual(nc.pick_column(cols, "T_K", "T"), [300.0, 400.0])

    def test_column_lookup_reports_what_was_available(self):
        with self.assertRaises(RuntimeError) as ctx:
            nc.pick_column({"a": [1.0]}, "velocity_m_s")
        self.assertIn("a", str(ctx.exception))


class IgnitionExtractionTests(unittest.TestCase):
    def test_picks_the_time_of_maximum_dtdt(self):
        # Slow drift, then a sharp rise between samples 4 and 5. np.gradient
        # uses central differences, so the peak registers on either side of
        # the jump; the claim under test is that it lands on the jump and not
        # somewhere in the flat regions.
        t = [i * 1e-4 for i in range(20)]
        T = [1400.0 + i for i in range(5)] + [2600.0] * 15
        cols = {"time_s": t, "T_K": T}
        out = nc.extract_ignition_delay(cols, _spec())
        self.assertGreaterEqual(out["ignition_delay_ms"], t[4] * 1e3 - 1e-9)
        self.assertLessEqual(out["ignition_delay_ms"], t[5] * 1e3 + 1e-9)

    def test_rejects_a_run_that_never_ignited(self):
        cols = {"time_s": [i * 1e-4 for i in range(30)],
                "T_K": [1400.0 + 0.1 * i for i in range(30)]}
        with self.assertRaises(RuntimeError) as ctx:
            nc.extract_ignition_delay(cols, _spec())
        self.assertIn("no ignition", str(ctx.exception))

    def test_rejects_a_too_short_trajectory(self):
        cols = {"time_s": [0.0, 1.0], "T_K": [1400.0, 2800.0]}
        with self.assertRaises(RuntimeError):
            nc.extract_ignition_delay(cols, _spec())


class FlameExtractionTests(unittest.TestCase):
    def _profile(self, reverse=False):
        n = 40
        x = [i * 1e-3 for i in range(n)]
        T = [300.0 + (2000.0 * i / (n - 1)) for i in range(n)]
        u = [0.38 + 2.0 * i / (n - 1) for i in range(n)]
        if reverse:
            x, T, u = x, T[::-1], u[::-1]
        return {"grid_m": x, "T_K": T, "velocity_m_s": u}

    def test_takes_the_unburned_side_velocity(self):
        out = nc.extract_flame_speed(self._profile(), _spec(kind="flame_speed", T0_K=300.0))
        self.assertAlmostEqual(out["flame_speed_cm_s"], 38.0, places=6)

    def test_handles_a_profile_stored_burned_first(self):
        """Orientation is inferred from the temperature field, not assumed."""
        out = nc.extract_flame_speed(self._profile(reverse=True),
                                     _spec(kind="flame_speed", T0_K=300.0))
        self.assertAlmostEqual(out["flame_speed_cm_s"], 38.0, places=6)

    def test_rejects_a_profile_with_no_flame(self):
        flat = {"grid_m": [i * 1e-3 for i in range(40)],
                "T_K": [300.0] * 40, "velocity_m_s": [0.4] * 40}
        with self.assertRaises(RuntimeError):
            nc.extract_flame_speed(flat, _spec(kind="flame_speed"))


class RecorderTests(unittest.TestCase):
    def test_a_failing_check_does_not_stop_later_checks(self):
        """The whole point of the dimension recorder: no short-circuiting."""
        rec = nc.Recorder()

        def boom():
            raise ValueError("nope")

        rec.run("artifact_produced", boom)
        rec.run("figure_produced", lambda: (1.0, {"figures": ["a.png"]}))

        dims = rec.as_dict()
        self.assertEqual(dims["artifact_produced"]["status"], "fail")
        self.assertIn("ValueError", dims["artifact_produced"]["why"])
        self.assertEqual(dims["figure_produced"]["status"], "pass")

    def test_unrun_checks_are_marked_not_attempted(self):
        dims = nc.Recorder().as_dict()
        self.assertTrue(all(d["status"] == "not_attempted" for d in dims.values()))
        self.assertEqual(set(dims), set(nc.DIMENSIONS))


class ReproductionStrippingTests(unittest.TestCase):
    def test_only_source_and_mechanism_files_are_carried_over(self):
        """A frozen results file must not survive into the graded run."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "submission"
            sub.mkdir()
            (sub / "run_case.py").write_text("open('results.csv','w').write('x')")
            (sub / "results.csv").write_text("stale")
            (sub / "results_frozen.csv").write_text("frozen")
            (sub / "plot.png").write_bytes(b"\x89PNG")
            (sub / "mech.yaml").write_text("phases: []")

            work = Path(td) / "work"
            try:
                nc._reproduce(sub, work, _spec(), Path(td) / "logs")
            except RuntimeError:
                pass  # the toy driver may fail; we only care what was copied

            self.assertTrue((work / "run_case.py").is_file())
            self.assertTrue((work / "mech.yaml").is_file())
            self.assertFalse((work / "results_frozen.csv").exists())
            self.assertFalse((work / "plot.png").exists())


class EquilibriumTests(unittest.TestCase):
    def setUp(self):
        try:
            import cantera  # noqa: F401
        except ImportError:
            self.skipTest("cantera not installed")

    def test_constant_volume_equilibrium_is_reproducible(self):
        a = nc._equilibrium_state(_spec())
        b = nc._equilibrium_state(_spec())
        self.assertAlmostEqual(a["T_equilibrium_K"], b["T_equilibrium_K"], places=6)
        self.assertGreater(a["T_equilibrium_K"], 1400.0)

    def _gate(self, *, kind, T0_K, T_end_K, P0_atm=1.0, fuel="CH4", phi=1.0):
        """Drive the real check over a synthetic profile.

        The first version of these tests asserted that a line of source existed.
        It passed against code that raised UnboundLocalError on every call,
        because the variable it looked for was read one line above where it was
        assigned. Behaviour, not text.
        """
        spec = _spec(kind=kind, T0_K=T0_K, P0_atm=P0_atm, fuel=fuel, phi=phi)
        eq = nc._equilibrium_state(spec)
        T = [T0_K + (T_end_K - T0_K) * k / 39 for k in range(40)]
        return spec, eq, T

    @unittest.skipUnless(_has_cantera(), "cantera not installed")
    def test_a_lean_flame_above_equilibrium_by_the_measured_amount_passes(self):
        """The three oracle runs the bound was widened for -- lean ethylene,
        ethane and propane -- settle 0.65%-0.87% of the rise above equilibrium,
        and the original 0.5% bound rejected them."""
        spec, eq, _ = self._gate(kind="flame_speed", T0_K=321.0, P0_atm=2.1,
                                 fuel="C2H4", phi=0.78, T_end_K=0.0)
        rise = eq["T_equilibrium_K"] - 321.0
        for measured in (0.0065, 0.0080, 0.0087):
            T = [321.0 + (eq["T_equilibrium_K"] + measured * rise - 321.0) * k / 39
                 for k in range(40)]
            score, out = nc.check_equilibrium_consistency(spec, T, eq)
            self.assertEqual(score, 1.0)
            self.assertEqual(out["tolerance_rel"], nc.EQUILIBRIUM_REL_TOL)

    @unittest.skipUnless(_has_cantera(), "cantera not installed")
    def test_an_end_state_far_from_equilibrium_is_still_recorded_as_a_failure(self):
        """The diagnostic still has to fire -- both ways, and on both systems.

        `equilibrium_consistent` came out of the gate product (#125), which is
        a statement about what the score reads, not a licence for the check to
        stop discriminating. A trace that ends 10% of the rise away from
        equilibrium in either direction is not a solution of this mixture and
        `reward_detail.json` has to say so.
        """
        for kind, T0_K, kw in (("flame_speed", 321.0,
                                dict(P0_atm=2.1, fuel="C2H4", phi=0.78)),
                               ("idt", 1400.0, {})):
            spec, eq, _ = self._gate(kind=kind, T0_K=T0_K, T_end_K=0.0, **kw)
            rise = eq["T_equilibrium_K"] - T0_K
            for signed in (+0.10, -0.10):
                T = [T0_K + (eq["T_equilibrium_K"] + signed * rise - T0_K) * k / 39
                     for k in range(40)]
                with self.assertRaisesRegex(RuntimeError, "differs from the"):
                    nc.check_equilibrium_consistency(spec, T, eq)

    @unittest.skipUnless(_has_cantera(), "cantera not installed")
    def test_the_band_is_one_number_for_both_systems_and_both_signs(self):
        """The asymmetric predecessor is what zeroed correct submissions.

        0.5% overshoot for ignition, 2% for flames, and a separate per-case
        shortfall tolerance underneath: four constants tuned to be tight enough
        to zero a submission, on a check that no longer zeroes anything. What
        replaced them is one band, and the measurement behind it says an
        ignition trace stopped where `instruction.md` tells it to stop lands
        within 3.2% of the rise (worst of all 31 operating points).
        """
        self.assertEqual(nc.EQUILIBRIUM_REL_TOL, 0.05)
        self.assertFalse(hasattr(nc, "OVERSHOOT_ALLOWANCE_REL"))
        for kind, T0_K, kw in (("flame_speed", 321.0,
                                dict(P0_atm=2.1, fuel="C2H4", phi=0.78)),
                               ("idt", 1400.0, {})):
            spec, eq, _ = self._gate(kind=kind, T0_K=T0_K, T_end_K=0.0, **kw)
            rise = eq["T_equilibrium_K"] - T0_K
            for signed in (+0.032, -0.032):
                T = [T0_K + (eq["T_equilibrium_K"] + signed * rise - T0_K) * k / 39
                     for k in range(40)]
                score, _out = nc.check_equilibrium_consistency(spec, T, eq)
                self.assertEqual(score, 1.0, f"{kind} {signed:+.3f}")

    def test_flame_uses_constant_pressure_equilibrium(self):
        """UV and HP equilibria differ; the kind must select the right one."""
        uv = nc._equilibrium_state(_spec(kind="idt", T0_K=300.0))
        hp = nc._equilibrium_state(_spec(kind="flame_speed", T0_K=300.0))
        self.assertNotAlmostEqual(uv["T_equilibrium_K"], hp["T_equilibrium_K"], places=1)


class ResumeHandoverTests(unittest.TestCase):
    """The interrupted-run contract: what the handover check does and does not do.

    Every assertion here was written after running the real thing in the domain
    image (#266); two of them exist because the run contradicted what the code
    had been written to claim.
    """

    HANDOVER = "time_s,T_K,P_Pa\n0.0,1418.0,131722.5\n1e-05,1418.4,131740.0\n2e-05,141"

    def _write(self, tmp: Path, name: str, text: str) -> Path:
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_partial_final_record_is_not_a_row(self):
        """A process killed mid-write leaves half a line. That is data, not an error."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), "given.csv", self.HANDOVER)
            header, rows = nc.complete_rows(p)
            self.assertEqual(header, ["time_s", "T_K", "P_Pa"])
            self.assertEqual(len(rows), 2)

    def test_continuation_that_keeps_the_handover_passes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            given = self._write(tmp, "given.csv", self.HANDOVER)
            done = self._write(tmp, "results.csv", (
                "time_s,T_K,P_Pa\n0.0,1418.0,131722.5\n1e-05,1418.4,131740.0\n"
                "3e-05,1419.0,131800.0\n"))
            score, out = nc.check_given_prefix(done, given, 1e-9)
            self.assertEqual(score, 1.0)
            self.assertEqual(out["handover_rows"], 2)
            self.assertEqual(out["rows_added"], 1)

    def test_a_different_float_spelling_is_not_a_loss(self):
        """Acceptance (e): re-emitting the handover through another writer is legal."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            given = self._write(tmp, "given.csv", self.HANDOVER)
            done = self._write(tmp, "results.csv", (
                "time_s,T_K,P_Pa\n"
                "0.00000000000000000,1418.0000000000000,131722.50000000000\n"
                "1.0000000000000001e-05,1418.4000000000001,131740.00000000000\n"
                "3e-05,1419.0,131800.0\n"))
            self.assertEqual(nc.check_given_prefix(done, given, 1e-9)[0], 1.0)

    def test_dropping_the_handover_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            given = self._write(tmp, "given.csv", self.HANDOVER)
            done = self._write(tmp, "results.csv",
                               "time_s,T_K,P_Pa\n3e-05,1419.0,131800.0\n")
            with self.assertRaises(RuntimeError):
                nc.check_given_prefix(done, given, 1e-9)

    def test_rounding_the_handover_fails(self):
        """The interface asks for full precision; a re-rounded carry-over lost some."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            given = self._write(tmp, "given.csv", self.HANDOVER)
            done = self._write(tmp, "results.csv", (
                "time_s,T_K,P_Pa\n0.0,1418.0,131722.5\n1e-05,1418.0,131740.0\n"
                "3e-05,1419.0,131800.0\n"))
            with self.assertRaises(RuntimeError):
                nc.check_given_prefix(done, given, 1e-9)

    def test_the_check_cannot_see_recomputation_and_does_not_claim_to(self):
        """Measured (#266), not argued, and it is why the prompt does not ask for it.

        A driver that ignores the checkpoint and re-integrates from t = 0 at the
        same tolerances on the same mechanism reproduced all 505 handover rows
        bit-identically and scored 1.0 in the domain image. The integrator is
        deterministic, so reuse and deterministic recomputation are the same
        bytes at the output interface -- the only surface an evaluator here may
        read. Anything in the contract that demanded "do not recompute" would
        enforce nothing, so this asserts the honest wording instead of a check
        that cannot exist.
        """
        import inspect
        text = inspect.getsource(nc.check_given_prefix)
        self.assertIn("does NOT check", text)
        for word in ("unaltered", "at the front"):
            self.assertIn(word, text)

    def test_a_case_without_resume_is_untouched(self):
        """The other fifty cases in this family must not grow a gate they can never pass."""
        self.assertNotIn(nc.RESUME_DIMENSION, nc.DIMENSIONS)
        self.assertNotIn(nc.RESUME_DIMENSION, nc.GATES)
        self.assertIsNone(_spec().resume)
        self.assertEqual(set(nc.Recorder().dims), set(nc.DIMENSIONS))
        self.assertEqual(
            set(nc.Recorder(extra=(nc.RESUME_DIMENSION,)).dims),
            set(nc.DIMENSIONS) | {nc.RESUME_DIMENSION},
        )


class ResolutionLadderTests(unittest.TestCase):
    """`resolution_spec` -- the contract asking the run to SHOW it converged.

    Every number below is a measurement from the domain image at the operating
    point of `ch4_air_flame_speed_meet_resolution_spec` (phi 1.07, 312 K,
    1.2 atm, gri30, mixture-averaged), so these are the real ladders rather
    than invented ones.
    """

    BLOCK = {
        "file": "grid_independence.csv",
        "level_columns": ["n_grid_points", "n_points", "grid_points"],
        "value_columns": ["flame_speed_cm_s", "flame_speed", "su_cm_s"],
        "reported_kpi": "flame_speed_cm_s",
        "min_levels": 3,
        "min_span_ratio": 2.0,
        "max_rel_change": 0.02,
        "max_rel_gap_to_reported": 0.02,
    }

    def _write(self, tmp: Path, text: str, name: str = "grid_independence.csv") -> Path:
        p = tmp / name
        p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return p

    ORACLE = """\
        n_grid_points,flame_speed_cm_s
        32,43.4614671471582
        74,39.538963919448946
        128,39.02034483744651
        195,38.814880153691824
        """

    def test_the_oracle_ladder_passes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), self.ORACLE)
            score, out = nc.check_resolution_ladder(
                p, self.BLOCK, 38.814880153691824)
            self.assertEqual(score, 1.0)
            self.assertAlmostEqual(out["span_ratio"], 195 / 32)
            self.assertLess(max(out["rel_change_last_two_steps"]), 0.02)
            self.assertEqual(out["rel_gap_to_reported"], 0.0)

    def test_a_submission_the_band_would_pass_can_fail_here(self):
        """The admissibility test CLAUDE.md applies to every check, measured.

        This ladder's finest value is 39.5390 cm/s against `gt_value` 38.8149
        and a 5% band: `kpi_accuracy` scores it 1.0. Its last step is 2.39%, so
        the answer has not stopped moving and this gate zeroes it. Run
        end-to-end in the domain image the check was written against, the same
        submission comes back `kpi_accuracy` 1.0 / `final_score` 0.0.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                n_grid_points,flame_speed_cm_s
                32,43.4614671471582
                47,40.45460267971187
                54,40.485150497632596
                74,39.538963919448946
                """)
            with self.assertRaises(RuntimeError) as caught:
                nc.check_resolution_ladder(p, self.BLOCK, 39.538963919448946)
            self.assertIn("2.393%", str(caught.exception))

    def test_one_small_step_is_not_enough(self):
        """Why the contract asks for the last TWO steps and not the last one.

        Measured: this mixture plateaus between 47 and 54 grid points -- the
        step is 0.07% -- while the answer is still 4.2% high. A rule reading
        only the final step would call that converged.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                n_grid_points,flame_speed_cm_s
                23,43.4614671471582
                47,40.45460267971187
                54,40.485150497632596
                """)
            with self.assertRaises(RuntimeError):
                nc.check_resolution_ladder(p, self.BLOCK, 40.485150497632596)

    def test_levels_that_barely_differ_are_not_a_study(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                n_grid_points,flame_speed_cm_s
                190,38.82
                193,38.818
                195,38.814880153691824
                """)
            with self.assertRaises(RuntimeError) as caught:
                nc.check_resolution_ladder(p, self.BLOCK, 38.814880153691824)
            self.assertIn("coarsest", str(caught.exception))

    def test_a_ladder_about_some_other_run_fails(self):
        """Predicate 4: the table has to be about the number being scored."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), self.ORACLE)
            with self.assertRaises(RuntimeError) as caught:
                nc.check_resolution_ladder(p, self.BLOCK, 31.0)
            self.assertIn("finest level", str(caught.exception))

    def test_written_differently_still_passes(self):
        """Acceptance (e): alias headers, descending rows, an extra column.

        Same ladder as the end-to-end (e) probe, which scored 1.0 in the image:
        three levels rather than four, refined by a different route, ending
        FINER than the reference level so the reported answer is -0.98% from
        `gt_value` instead of on it.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                n_points,flame_speed,T_burned
                366,38.43476569615332,2237.1
                195,38.814880153691824,2237.0
                128,39.02034483744651,2236.9
                """)
            score, out = nc.check_resolution_ladder(
                p, self.BLOCK, 38.43476569615332)
            self.assertEqual(score, 1.0)
            self.assertEqual(out["levels"], [128.0, 195.0, 366.0])

    def test_a_missing_ladder_is_a_failure_not_a_crash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError) as caught:
                nc.check_resolution_ladder(
                    Path(td) / "grid_independence.csv", self.BLOCK, 38.8149)
            self.assertIn("wrote no", str(caught.exception))

    def test_a_case_without_resolution_spec_is_untouched(self):
        """The other fifty-one cases in this family must not grow this gate."""
        self.assertNotIn(nc.RESOLUTION_DIMENSION, nc.DIMENSIONS)
        self.assertNotIn(nc.RESOLUTION_DIMENSION, nc.GATES)
        self.assertIsNone(_spec().resolution_spec)
        self.assertEqual(set(nc.Recorder().dims), set(nc.DIMENSIONS))
        self.assertEqual(
            set(nc.Recorder(extra=(nc.RESOLUTION_DIMENSION,)).dims),
            set(nc.DIMENSIONS) | {nc.RESOLUTION_DIMENSION},
        )

    def test_the_check_reads_the_output_interface_and_says_so(self):
        """It may not learn what SETTING produced a row -- only the outcome.

        The level column is the grid the solver ended on. If this ever grew a
        `ratio`/`slope`/`domain width` reader it would be scoring the
        submission's setup, which is the failure that cost the CFD track nine
        cases.
        """
        import inspect
        text = inspect.getsource(nc.check_resolution_ladder)
        self.assertIn("OUTPUT INTERFACE", text)
        # And it must keep saying what it cannot do: the rows come out of the
        # evaluator's own re-run, which stops them being SHIPPED, not PRINTED.
        self.assertIn("does not do", text)


if __name__ == "__main__":
    unittest.main()
