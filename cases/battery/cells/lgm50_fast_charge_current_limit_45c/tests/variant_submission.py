"""Acceptance bar (e): a correct submission written differently from the oracle.

Legal differences, chosen to disturb the scoring chain without changing the
answer:
  * a bracketing root-find on (peak temperature - ceiling) instead of the
    oracle's bisection, so the search converges from a different sequence of
    currents and lands on a slightly different last iterate;
  * columns written in a different order, and the constant answer column first;
  * float formatting through an explicit format string rather than csv's
    default repr;
  * the figure saved under a different name, in a subdirectory.
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pybamm  # noqa: E402
from scipy.optimize import brentq  # noqa: E402

CEILING = 318.15


def solve_at(amps):
    model = pybamm.lithium_ion.SPMe(options={"thermal": "lumped"})
    steps = [f"Charge at {amps:.6f} A until 4.2 V", "Hold at 4.2 V until 250 mA"]
    sim = pybamm.Simulation(
        model,
        parameter_values=pybamm.ParameterValues("Chen2020"),
        experiment=pybamm.Experiment(steps),
    )
    return sim.solve(initial_soc=0.2)


def excess(amps):
    s = solve_at(amps)
    peak = np.asarray(s["Volume-averaged cell temperature [K]"].data, dtype=float).max()
    return float(peak) - CEILING


limit = brentq(excess, 1.0, 10.0, xtol=5.0e-4)

sol = solve_at(limit)
time_s = np.asarray(sol["Time [s]"].data, dtype=float)
amps = np.asarray(sol["Current [A]"].data, dtype=float)
volts = np.asarray(sol["Voltage [V]"].data, dtype=float)
temp = np.asarray(sol["Volume-averaged cell temperature [K]"].data, dtype=float)

with open("results.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["i_charge_max_a", "temperature_K", "voltage_V",
                     "current_A", "time_s"])
    for k in range(len(time_s)):
        writer.writerow([f"{limit:.8f}", f"{temp[k]:.8f}", f"{volts[k]:.8f}",
                         f"{amps[k]:.8f}", f"{time_s[k]:.8f}"])

os.makedirs("figures", exist_ok=True)
plt.figure(figsize=(6, 4), dpi=120)
plt.plot(time_s / 60.0, temp)
plt.axhline(CEILING, linestyle=":")
plt.xlabel("time (min)")
plt.ylabel("cell temperature (K)")
plt.title("charge at the limiting current")
plt.tight_layout()
plt.savefig(os.path.join("figures", "temperature.png"))

print(f"limit {limit:.6f} A over {time_s[-1]:.1f} s")
