"""Acceptance bar (e): a correct submission written differently from the oracle.

Legal differences, chosen to disturb the scoring chain without changing the
answer:
  * the derivative is extrapolated to zero perturbation by Richardson from a
    different pair of step sizes, rather than read off the smallest one;
  * the integration runs to a fixed end time well past ignition instead of
    stopping on the dT/dt decay rule, so the trace has a different length and
    a different tail;
  * a coarser output grid -- every other accepted step is written, which is a
    real hazard for a delay read off a dT/dt maximum;
  * columns in a different order, floats through an explicit format string,
    and the figure under a different name in a subdirectory.
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import cantera as ct  # noqa: E402

TARGET = "CH3 + HO2 <=> CH3O + OH"
END_TIME_S = 0.02


def run(multiplier=None):
    gas = ct.Solution("gri30.yaml")
    gas.set_equivalence_ratio(0.87, "CH4", "O2:1, N2:3.76")
    gas.TP = 1390.0, 2.4 * ct.one_atm
    if multiplier is not None:
        target = [i for i, eq in enumerate(gas.reaction_equations())
                  if eq.replace(" ", "") == TARGET.replace(" ", "")][0]
        gas.set_multiplier(multiplier, target)
    reactor = ct.IdealGasReactor(gas, clone=False)
    net = ct.ReactorNet([reactor])
    rows = []
    while net.time < END_TIME_S:
        net.step()
        rows.append((net.time, reactor.T, reactor.thermo.P))
    arr = np.asarray(rows)
    return arr[:, 0], arr[:, 1], arr[:, 2]


def tau(multiplier=None):
    t, T, _ = run(multiplier)
    return float(t[np.argmax(np.gradient(T, t))])


def central(step):
    return ((np.log(tau(1.0 + step)) - np.log(tau(1.0 - step)))
            / (np.log(1.0 + step) - np.log(1.0 - step)))


# Richardson: the central difference carries an O(h^2) error, so two step
# sizes in a 2:1 ratio combine into an estimate with that term removed.
coarse, fine = central(0.08), central(0.04)
answer = float((4.0 * fine - coarse) / 3.0)

t, T, P = run()
keep = slice(None, None, 2)
t, T, P = t[keep], T[keep], P[keep]

with open("results.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["s_ch3_ho2", "P_Pa", "T_K", "time_s"])
    for k in range(len(t)):
        writer.writerow([f"{answer:.9f}", f"{P[k]:.9f}",
                         f"{T[k]:.9f}", f"{t[k]:.12f}"])

os.makedirs("plots", exist_ok=True)
plt.figure(figsize=(6, 4), dpi=120)
plt.plot(t * 1e3, T)
plt.xlabel("time (ms)")
plt.ylabel("T (K)")
plt.title("constant-volume ignition")
plt.tight_layout()
plt.savefig(os.path.join("plots", "ignition.png"))

print(f"sensitivity {answer:.6f}")
