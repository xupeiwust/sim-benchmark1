"""Oracle: the largest constant charge current a CCCV protocol can use without
the cell exceeding its temperature ceiling.

What separates this from every other case on the track is that the answer is
not a property of one simulation. No single run knows the limit; the limit is
where a *constraint* starts to bind, so it has to be searched for. The search
is the task, and the evaluator's strip-and-re-run is what makes it earned: the
`results.csv` this writes is deleted before the re-run, so the row scored can
only be one this script's own bisection produced.

Monotonicity is what licenses a bisection here, and it is a fact about the
well-behaved part of the range rather than about the protocol. Above roughly
11 A the constant-voltage hold fails to converge, and a failed run reads as a
*cool* one -- the trace stops after a few seconds, so its peak temperature is
near ambient and a naive search would walk straight past the real limit. That
is a numerical artefact, not physics, which is why the search range the
instruction states stops at 10 A.
"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pybamm  # noqa: E402

PARAMETER_SET = "Chen2020"
INITIAL_SOC = 0.2
CEILING_K = 318.15
SEARCH_LO_A, SEARCH_HI_A = 1.0, 10.0
SEARCH_TOL_A = 1.0e-3


def simulate(current_a: float):
    """One CCCV charge at the given constant current."""
    model = pybamm.lithium_ion.SPMe(options={"thermal": "lumped"})
    experiment = pybamm.Experiment([
        f"Charge at {current_a:.6f} A until 4.2 V",
        "Hold at 4.2 V until 250 mA",
    ])
    sim = pybamm.Simulation(
        model,
        parameter_values=pybamm.ParameterValues(PARAMETER_SET),
        experiment=experiment,
    )
    return sim.solve(initial_soc=INITIAL_SOC)


def peak_temperature(sol) -> float:
    return float(np.asarray(
        sol["Volume-averaged cell temperature [K]"].data, dtype=float).max())


# ── the search ───────────────────────────────────────────────────────────────
# Bisection rather than a fitted curve: the temperature rise is set by ohmic
# and polarisation heat over a charge whose duration itself depends on the
# current, so there is no closed form to invert.
lo, hi = SEARCH_LO_A, SEARCH_HI_A
if peak_temperature(simulate(lo)) > CEILING_K:
    raise RuntimeError("ceiling is already exceeded at the bottom of the range")
if peak_temperature(simulate(hi)) <= CEILING_K:
    raise RuntimeError("ceiling is not reached at the top of the range")
while hi - lo > SEARCH_TOL_A:
    mid = 0.5 * (lo + hi)
    if peak_temperature(simulate(mid)) <= CEILING_K:
        lo = mid
    else:
        hi = mid
i_max = lo

# ── the reported run: the protocol at the limit ──────────────────────────────
sol = simulate(i_max)
t = np.asarray(sol["Time [s]"].data, dtype=float)
I = np.asarray(sol["Current [A]"].data, dtype=float)
V = np.asarray(sol["Voltage [V]"].data, dtype=float)
T = np.asarray(sol["Volume-averaged cell temperature [K]"].data, dtype=float)

with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["time_s", "current_A", "voltage_V", "temperature_K",
                "i_charge_max_a"])
    for row in zip(t, I, V, T):
        w.writerow(list(row) + [i_max])

t_h = t / 3600.0
fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.set_xlabel("time (h)")
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
axes[0].plot(t_h, V, color="#2a78d6", linewidth=2, zorder=3)
axes[0].set_ylabel("terminal voltage (V)")
axes[0].set_title("voltage response at the limiting current")
axes[1].plot(t_h, T, color="#c2452d", linewidth=2, zorder=3)
axes[1].axhline(CEILING_K, color="#6b6a66", linewidth=1.2, linestyle="--", zorder=2)
axes[1].set_ylabel("volume-averaged cell temperature (K)")
axes[1].set_title("temperature against the ceiling")
fig.suptitle(
    "largest constant charge current holding the cell under its ceiling",
    fontsize=11)
fig.tight_layout()
fig.savefig("result.png")

print(f"i_charge_max_a={i_max:.6g}")
print(f"charge_time_at_limit_s={t[-1]:.6g}")
print(f"peak_temperature_K={float(T.max()):.6g}")
