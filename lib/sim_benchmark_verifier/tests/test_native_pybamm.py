"""Unit tests for the shared PyBaMM evaluator.

These cover the parsing, extraction and cycle-segmentation logic without
requiring PyBaMM itself: the open-circuit-voltage curve is the only part that
needs the library, and the tests that touch it are skipped when it is absent.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_benchmark_verifier import native_pybamm as np_ev  # noqa: E402


def _spec(**kw):
    base = dict(case_id="unit", kind="discharge", parameter_set="Chen2020",
                initial_soc=1.0)
    base.update(kw)
    return np_ev.PyBaMMSpec(**base)


class ColumnParsingTests(unittest.TestCase):
    def _write(self, tmp: Path, text: str) -> Path:
        p = tmp / np_ev.RESULTS_NAME
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return p

    def test_reads_a_simple_table(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), """\
                time_s,current_A,voltage_V
                0.0,5.0,4.0
                1.0,5.0,3.9
                2.0,5.0,3.8
                """)
            cols = np_ev.read_results_csv(p)
            self.assertEqual(sorted(cols), ["current_A", "time_s", "voltage_V"])
            self.assertEqual(len(cols["time_s"]), 3)

    def test_rejects_a_table_with_no_data(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(Path(td), "time_s,voltage_V\n")
            with self.assertRaises(RuntimeError):
                np_ev.read_results_csv(p)

    def test_column_lookup_tolerates_author_naming(self):
        """A submission is graded on physics, not on header spelling."""
        cols = {"Time [s]": [0.0, 1.0], "Current (A)": [5.0, 5.0],
                "Terminal voltage [V]": [4.0, 3.9]}
        self.assertEqual(np_ev.pick_column(cols, "time_s", "time"), [0.0, 1.0])
        self.assertEqual(np_ev.pick_column(cols, "current_A", "current"), [5.0, 5.0])
        self.assertEqual(
            np_ev.pick_column(cols, "voltage_V", "voltage", "terminal_voltage"),
            [4.0, 3.9],
        )

    def test_missing_column_names_what_it_wanted(self):
        with self.assertRaises(RuntimeError) as cm:
            np_ev.pick_column({"time_s": [0.0]}, "temperature_K")
        self.assertIn("temperature_K", str(cm.exception))


class DischargeExtractionTests(unittest.TestCase):
    def _cols(self, n=100, current=5.0, v0=4.0, v1=3.0):
        t = [float(i) for i in range(n)]
        return {
            "time_s": t,
            "current_A": [current] * n,
            "voltage_V": [v0 + (v1 - v0) * i / (n - 1) for i in range(n)],
        }

    def test_capacity_is_the_current_integral(self):
        # 5 A held for 99 s -> 5 * 99 / 3600 A.h
        out = np_ev.extract_discharge(self._cols(), _spec())
        self.assertAlmostEqual(out["discharge_capacity_Ah"], 5.0 * 99 / 3600.0, places=9)

    def test_mean_voltage_is_energy_over_charge(self):
        out = np_ev.extract_discharge(self._cols(), _spec())
        self.assertAlmostEqual(
            out["mean_discharge_voltage_V"],
            out["discharge_energy_Wh"] / out["discharge_capacity_Ah"], places=9,
        )
        # A linear ramp from 4.0 to 3.0 V averages 3.5 V.
        self.assertAlmostEqual(out["mean_discharge_voltage_V"], 3.5, places=3)

    def test_a_charge_only_trace_is_not_a_discharge(self):
        """Sign convention is part of the contract, so it is enforced."""
        cols = self._cols(current=-5.0)
        with self.assertRaises(RuntimeError) as cm:
            np_ev.extract_discharge(cols, _spec())
        self.assertIn("no discharge", str(cm.exception))

    def test_non_finite_values_are_rejected(self):
        cols = self._cols()
        cols["voltage_V"][10] = float("nan")
        with self.assertRaises(RuntimeError):
            np_ev.extract_discharge(cols, _spec())

    def test_a_stub_trace_is_rejected(self):
        with self.assertRaises(RuntimeError):
            np_ev.extract_discharge(self._cols(n=5), _spec())


class ThermalExtractionTests(unittest.TestCase):
    def _cols(self, n=100, peak=330.0):
        base = DischargeExtractionTests()._cols(n=n)
        base["temperature_K"] = [
            298.15 + (peak - 298.15) * min(i, n - 1 - i) / (n / 2) for i in range(n)
        ]
        return base

    def test_rise_is_measured_from_the_first_sample(self):
        cols = self._cols()
        out = np_ev.extract_thermal(cols, _spec(kind="thermal"))
        self.assertAlmostEqual(
            out["max_temperature_rise_K"],
            max(cols["temperature_K"]) - cols["temperature_K"][0], places=9,
        )

    def test_celsius_is_rejected_as_not_kelvin(self):
        cols = self._cols()
        cols["temperature_K"] = [25.0 + i * 0.1 for i in range(len(cols["time_s"]))]
        with self.assertRaises(RuntimeError) as cm:
            np_ev.extract_thermal(cols, _spec(kind="thermal"))
        self.assertIn("kelvin", str(cm.exception))


class PulseExtractionTests(unittest.TestCase):
    def test_resistance_is_read_across_the_largest_current_step(self):
        # rest, then a 5 A pulse that drops the voltage by 0.12 V.
        t = [float(i) for i in range(60)]
        I = [0.0] * 30 + [5.0] * 30
        V = [4.0] * 30 + [3.88] * 30
        out = np_ev.extract_pulse(
            {"time_s": t, "current_A": I, "voltage_V": V}, _spec(kind="pulse")
        )
        self.assertAlmostEqual(out["pulse_resistance_ohm"], 0.12 / 5.0, places=9)
        self.assertAlmostEqual(out["step_time_s"], 30.0, places=9)

    def test_a_trace_with_no_step_cannot_yield_a_resistance(self):
        t = [float(i) for i in range(60)]
        with self.assertRaises(RuntimeError):
            np_ev.extract_pulse(
                {"time_s": t, "current_A": [5.0] * 60, "voltage_V": [3.9] * 60},
                _spec(kind="pulse"),
            )


class CyclingSegmentationTests(unittest.TestCase):
    """The index arithmetic that splits a trace into cycles.

    Worth testing directly: an off-by-one here silently reports the wrong
    cycle's capacity rather than failing, which is the kind of bug a score
    alone would not reveal.
    """

    def _build(self, cycles: list[tuple[float, int]]):
        """cycles: (discharge_current, n_samples) then an equal charge leg."""
        t, I = [], []
        clock = 0.0
        for cur, n in cycles:
            for _ in range(n):
                t.append(clock); I.append(cur); clock += 1.0
            for _ in range(n):
                t.append(clock); I.append(-cur); clock += 1.0
        return t, I

    def test_counts_each_discharge_leg_once(self):
        import numpy as np

        t, I = self._build([(5.0, 40)] * 4)
        caps = np_ev._per_cycle_discharge_Ah(np.asarray(t), np.asarray(I))
        self.assertEqual(len(caps), 4)
        for c in caps:
            self.assertAlmostEqual(c, caps[0], places=12)

    def test_fade_compares_last_complete_cycle_against_the_first(self):

        # Four cycles whose discharge current falls 5%, so capacity does too.
        t, I = self._build([(5.0, 40), (4.9, 40), (4.8, 40), (4.75, 40)])
        cols = {"time_s": t, "current_A": I, "voltage_V": [3.7] * len(t)}
        out = np_ev.extract_cycling(cols, _spec(kind="cycling"))
        self.assertEqual(out["n_cycles_detected"], 4)
        expected = (5.0 - 4.75) / 5.0 * 100.0
        self.assertAlmostEqual(out["capacity_fade_pct"], expected, places=6)

    def test_a_single_cycle_cannot_measure_fade(self):
        t, I = self._build([(5.0, 40)])
        cols = {"time_s": t, "current_A": I, "voltage_V": [3.7] * len(t)}
        with self.assertRaises(RuntimeError) as cm:
            np_ev.extract_cycling(cols, _spec(kind="cycling"))
        self.assertIn("at least two cycles", str(cm.exception))


class CccvExtractionTests(unittest.TestCase):
    def test_charge_time_spans_the_charging_samples(self):
        t = [float(i) for i in range(120)]
        I = [0.0] * 10 + [-5.0] * 60 + [-0.05] * 40 + [0.0] * 10
        V = [3.5] * 110 + [4.2] * 10
        out = np_ev.extract_cccv(
            {"time_s": t, "current_A": I, "voltage_V": V}, _spec(kind="cccv")
        )
        self.assertAlmostEqual(out["charge_time_s"], 109.0 - 10.0, places=9)
        self.assertGreater(out["charge_capacity_Ah"], 0.0)

    def test_a_discharge_only_trace_is_not_a_charge(self):
        t = [float(i) for i in range(60)]
        with self.assertRaises(RuntimeError):
            np_ev.extract_cccv(
                {"time_s": t, "current_A": [5.0] * 60, "voltage_V": [3.9] * 60},
                _spec(kind="cccv"),
            )


class ReproductionStripTests(unittest.TestCase):
    """A replayed result must not survive into the graded run."""

    def test_numeric_artifacts_are_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "submission"
            sub.mkdir()
            (sub / "run_case.py").write_text("print('hi')\n", encoding="utf-8")
            (sub / "results.csv").write_text("time_s,voltage_V\n0,4\n", encoding="utf-8")
            (sub / "result.png").write_bytes(b"\x89PNG")
            work = Path(td) / "work"
            log = Path(td) / "log"
            # The driver writes nothing, so reproduction must fail on the
            # missing output rather than pick up the shipped copy.
            with self.assertRaises(RuntimeError) as cm:
                np_ev._reproduce(sub, work, _spec(), log)
            self.assertIn("did not produce", str(cm.exception))
            self.assertFalse((work / "results.csv").exists())
            self.assertFalse((work / "result.png").exists())

    def test_a_results_csv_disguised_as_source_is_still_stripped(self):
        """`.csv` is not a kept suffix, but the name is checked regardless."""
        self.assertNotIn(".csv", np_ev._REPRODUCTION_KEEP_SUFFIXES)


class SignWindowTests(unittest.TestCase):
    """The sign test's SOC window is load-bearing, not a tunable.

    The reference curve is indexed by coulomb-counted *average* SOC while
    terminal voltage is set by *surface* concentration. Those diverge at the
    ends of the window: a charge step beginning at the bottom of a deep
    discharge reads ~116 mV on the "generating" side of an average-SOC
    reference, which is concentration polarisation rather than free energy.
    Widening this window back to the full range re-introduces that false
    positive, so the bounds are asserted here.
    """

    def test_sign_window_excludes_both_extremes(self):
        spec = _spec()
        self.assertGreater(spec.ocv_sign_min_soc, spec.ocv_min_soc)
        self.assertLess(spec.ocv_sign_max_soc, 1.0)

    def test_sign_window_is_narrower_than_the_magnitude_window(self):
        """Magnitude still policies the ends; only the sign test steps back."""
        spec = _spec()
        self.assertLess(spec.ocv_min_soc, spec.ocv_sign_min_soc)
        self.assertGreater(1.0 + spec.ocv_min_soc, spec.ocv_sign_max_soc)


class ShapeTestTests(unittest.TestCase):
    """The residual-shape threshold separates real runs from a flat voltage.

    Measured across eight cases spanning every kind, a fabricated constant
    voltage column scores exactly -1.000 while real runs span -0.77 to +0.92.
    The threshold has to sit between those, and loosening it past the real-run
    floor would stop catching the fake — which on a capacity KPI is the only
    check that does, since integrating current is indifferent to the voltage
    column.
    """

    def test_threshold_separates_measured_populations(self):
        spec = _spec()
        worst_real, fake = -0.773, -1.0
        self.assertGreater(spec.ocv_shape_min_corr, fake)
        self.assertLess(spec.ocv_shape_min_corr, worst_real)

    def test_a_constant_voltage_is_perfectly_anti_correlated(self):
        """The property the threshold keys on, stated as arithmetic."""
        import numpy as np

        ocv = np.linspace(4.1, 3.2, 200)
        resid = 3.6 - ocv  # what a constant voltage column produces
        self.assertAlmostEqual(float(np.corrcoef(resid, ocv)[0, 1]), -1.0, places=9)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("pybamm"), "PyBaMM not installed"
)
class OcvCurveTests(unittest.TestCase):
    """The evaluator-owned reference curve — the anti-cheat gate's foundation."""

    def test_curve_is_monotonic_and_spans_the_cell_window(self):
        curve = np_ev._ocv_curve(_spec(), n=51)
        ocv = curve["ocv"]
        self.assertEqual(len(ocv), 51)
        # OCV rises with state of charge, over the full window.
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(ocv, ocv[1:])))
        self.assertGreater(curve["Q_span_Ah"], 0.0)

    def test_curve_needs_no_cell_model(self):
        """Independence is the point: it must not depend on the submission."""
        import inspect
        src = inspect.getsource(np_ev._ocv_curve)
        for forbidden in ("Simulation", "Experiment", ".solve("):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()


class OCVAdmissibilityTests(unittest.TestCase):
    """The open-circuit-voltage gate, exercised by calling it.

    It had no test at all, and it rejected all five models on one case while
    every one of them got that case's KPI right. These pin the two properties
    that matter: an excursion confined to the end-of-discharge knee is not a
    physical violation, and a real one still is.
    """

    def _arrays(self, n=400):
        import numpy as np
        soc = np.linspace(1.0, 0.02, n)
        ocv = 3.0 + 1.2 * soc          # monotone stand-in for the real curve
        current = np.full(n, 5.0)
        keep = np.ones(n, dtype=bool)
        return soc, ocv, current, keep

    def _spec(self):
        return _spec(ocv_max_deviation_V=0.45, ocv_sign_tol_V=0.05,
                     ocv_sign_min_soc=0.15, ocv_sign_max_soc=0.95)

    def test_a_knee_only_excursion_is_not_a_violation(self):
        import numpy as np
        soc, ocv, current, keep = self._arrays()
        resid = np.full_like(soc, -0.25)          # ordinary overpotential
        resid[soc < 0.10] = -0.65                 # the knee, outside the window
        out = np_ev.ocv_statistics(soc, ocv, resid, current, keep, self._spec())
        self.assertAlmostEqual(out["max_abs_overpotential_full_trace_V"], 0.65, places=6)
        self.assertAlmostEqual(out["max_abs_overpotential_V"], 0.25, places=6)
        self.assertLess(out["max_abs_overpotential_V"], out["max_deviation_tolerance_V"])

    def test_a_real_overpotential_violation_still_fails(self):
        import numpy as np
        soc, ocv, current, keep = self._arrays()
        resid = np.full_like(soc, -0.25)
        resid[(soc > 0.40) & (soc < 0.60)] = -0.70   # mid-discharge, inside the window
        out = np_ev.ocv_statistics(soc, ocv, resid, current, keep, self._spec())
        self.assertAlmostEqual(out["max_abs_overpotential_V"], 0.70, places=6)
        self.assertGreater(out["max_abs_overpotential_V"], out["max_deviation_tolerance_V"])

    def test_a_cell_generating_under_load_is_caught(self):
        import numpy as np
        soc, ocv, current, keep = self._arrays()
        resid = np.full_like(soc, -0.25)
        resid[(soc > 0.40) & (soc < 0.60)] = +0.20   # above OCV while discharging
        out = np_ev.ocv_statistics(soc, ocv, resid, current, keep, self._spec())
        self.assertGreater(out["max_dissipation_violation_V"], out["sign_tolerance_V"])

    def test_the_window_never_empties_the_sample(self):
        """A trace living entirely outside the window falls back to the full one,
        rather than reporting a maximum over nothing."""
        import numpy as np
        soc = np.linspace(0.12, 0.02, 50)
        ocv = 3.0 + 1.2 * soc
        current, keep = np.full(50, 5.0), np.ones(50, dtype=bool)
        resid = np.full_like(soc, -0.30)
        out = np_ev.ocv_statistics(soc, ocv, resid, current, keep, self._spec())
        self.assertEqual(out["n_samples_admissibility_checked"], 50)
        self.assertAlmostEqual(out["max_abs_overpotential_V"], 0.30, places=6)


class DeclaredDerivationTests(unittest.TestCase):
    """`kind = "declared"` — the seam that lets a case whose KPI is a searched-for
    quantity be a data edit rather than a new extractor function.

    The six hard-coded extractors each answer one fixed question about a
    discharge trace. A limit, a window edge or a design delta is not a property
    of the trace at all; it is a column the submission wrote after searching for
    it, and the evaluator's strip-and-re-run is what makes that column earned
    rather than typed.
    """

    COLS = {
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "current_A": [2.0, 2.0, 2.0, 2.0],
        "voltage_V": [4.1, 4.0, 3.9, 3.8],
        "temperature_K": [298.0, 301.0, 305.0, 309.0],
        "i_charge_max_a": [7.42, 7.42, 7.42, 7.42],
    }

    def test_declared_is_registered_and_leaves_the_existing_kinds_alone(self):
        self.assertIn("declared", np_ev.EXTRACTORS)
        self.assertEqual(
            sorted(k for k in np_ev.EXTRACTORS if k != "declared"),
            ["cccv", "cycling", "discharge", "pulse", "rate_capability", "thermal"],
        )

    def test_derives_each_declared_kpi_through_the_shared_table(self):
        spec = _spec(kind="declared", derivations={
            "i_charge_max_a": {"derive": "single_row", "value": "i_charge_max_a"},
            "t_max_at_limit_k": {"derive": "value_at_max",
                                 "value": "temperature_K", "key": "temperature_K"},
        })
        self.assertEqual(
            np_ev.extract_declared(self.COLS, spec),
            {"i_charge_max_a": 7.42, "t_max_at_limit_k": 309.0},
        )

    def test_an_empty_derivations_block_fails_rather_than_scoring_nothing(self):
        """A case that forgets the block must not quietly produce zero KPIs —
        `evaluate` would then score an empty set, which is indistinguishable
        from a case with nothing wrong."""
        with self.assertRaises(RuntimeError):
            np_ev.extract_declared(self.COLS, _spec(kind="declared"))

    def test_an_unknown_derivation_name_fails(self):
        spec = _spec(kind="declared",
                     derivations={"q": {"derive": "not_a_derivation", "value": "time_s"}})
        with self.assertRaises(Exception) as caught:
            np_ev.extract_declared(self.COLS, spec)
        self.assertIn("unknown derivation", str(caught.exception))

    def test_a_declared_kpi_naming_a_missing_column_fails(self):
        """The column has to be one the re-run actually wrote."""
        spec = _spec(kind="declared",
                     derivations={"q": {"derive": "single_row", "value": "never_written"}})
        # Named types rather than blind `Exception` (ruff B017), and the
        # pair is what the code actually does rather than what it should:
        # a missing column reaches `DERIVATIONS['single_row']`, which is a
        # bare `c[s['value']][0]`, so it comes out as a KeyError carrying
        # only the column name -- where every other extraction failure in
        # this module raises `EvaluationFailure` naming the file and the
        # columns that WERE present. Filed as #585; asserted here
        # as-is so this test does not quietly pass on the wrong exception.
        with self.assertRaises((RuntimeError, KeyError)):
            np_ev.extract_declared(self.COLS, spec)
