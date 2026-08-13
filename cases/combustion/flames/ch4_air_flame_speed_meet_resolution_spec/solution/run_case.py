"""Reference solution: a burning velocity carried to the stated resolution spec.

Four refinement levels rather than the three the contract requires, and the
coarsest is the setting the handed-over script arrived at -- so the table shows
the whole approach rather than only its converged end. The reported profile is
the finest level.
"""
import matplotlib
matplotlib.use("Agg")
import csv
import warnings
warnings.filterwarnings("ignore")
import cantera as ct
import numpy as np
import matplotlib.pyplot as plt

MECHANISM = 'gri30.yaml'
PHASE = None
FUEL = 'CH4'
PHI = 1.07
T_UNBURNED_K = 312.0
P_ATM = 1.2
WIDTH_M = 0.03
TRANSPORT = "mixture-averaged"

# ratio, slope, curve. Coarsest first; the last one is the level the reported
# profile comes from.
LEVELS = [
    (10, 0.8, 0.8),
    (5, 0.2, 0.4),
    (4, 0.1, 0.2),
    (3, 0.06, 0.12),
]


def solve(ratio, slope, curve):
    gas = ct.Solution(MECHANISM, PHASE) if PHASE else ct.Solution(MECHANISM)
    gas.set_equivalence_ratio(PHI, fuel=FUEL, oxidizer={"O2": 1.0, "N2": 3.76})
    gas.TP = T_UNBURNED_K, P_ATM * ct.one_atm
    flame = ct.FreeFlame(gas, width=WIDTH_M)
    flame.transport_model = TRANSPORT
    flame.set_refine_criteria(ratio=ratio, slope=slope, curve=curve)
    flame.solve(loglevel=0, auto=True)
    return flame


ladder = []
flame = None
for ratio, slope, curve in LEVELS:
    flame = solve(ratio, slope, curve)
    ladder.append((int(flame.grid.size), float(flame.velocity[0]) * 100.0))
    print(f"n_grid_points={ladder[-1][0]} flame_speed_cm_s={ladder[-1][1]:.6g}")

with open("grid_independence.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["n_grid_points", "flame_speed_cm_s"])
    for n, su in ladder:
        w.writerow([n, su])

with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["grid_m", "T_K", "velocity_m_s"])
    for row in zip(flame.grid, flame.T, flame.velocity):
        w.writerow(row)

su_cm_s = flame.velocity[0] * 100.0

# Two panels: the reported profile, and the ladder the requirement is judged
# on -- so both halves of what was asked for can be read off the figure.
x_mm = np.asarray(flame.grid) * 1e3
u_cm_s = np.asarray(flame.velocity) * 100.0

fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

axes[0].plot(x_mm, u_cm_s, color="#1baf7a", linewidth=2, zorder=3)
axes[0].axhline(su_cm_s, color="#eb6834", linewidth=1.5, linestyle="--", zorder=2)
axes[0].set_xlabel("distance (mm)")
axes[0].set_ylabel("axial velocity (cm/s)")
axes[0].set_title("velocity — inlet value is the burning velocity")

axes[1].plot([n for n, _ in ladder], [s for _, s in ladder], "o-",
             color="#2a78d6", linewidth=2, zorder=3)
axes[1].set_xscale("log")
axes[1].set_xlabel("grid points")
axes[1].set_ylabel("burning velocity (cm/s)")
axes[1].set_title("resolution ladder")

fig.suptitle(f"methane/air flame, phi={PHI}, {T_UNBURNED_K:.0f} K, {P_ATM:g} atm",
             fontsize=11)
fig.tight_layout(); fig.savefig("flame_profile.png")
print(f"flame_speed_cm_s={su_cm_s:.6g}")
