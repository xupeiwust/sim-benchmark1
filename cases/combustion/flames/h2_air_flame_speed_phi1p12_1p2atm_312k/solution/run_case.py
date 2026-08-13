"""Reference solution: 1-D freely-propagating premixed laminar flame."""
import matplotlib
matplotlib.use("Agg")
import csv
import warnings
warnings.filterwarnings("ignore")
import cantera as ct
import numpy as np
import matplotlib.pyplot as plt

MECHANISM = 'h2o2.yaml'
PHASE = None
FUEL = 'H2'
PHI = 1.12
T_UNBURNED_K = 312.0
P_ATM = 1.2
WIDTH_M = 0.03
TRANSPORT = "mixture-averaged"
RATIO, SLOPE, CURVE = 3, 0.06, 0.12


gas = ct.Solution(MECHANISM, PHASE) if PHASE else ct.Solution(MECHANISM)
gas.set_equivalence_ratio(PHI, fuel=FUEL, oxidizer={"O2": 1.0, "N2": 3.76})
gas.TP = T_UNBURNED_K, P_ATM * ct.one_atm

flame = ct.FreeFlame(gas, width=WIDTH_M)
flame.transport_model = TRANSPORT
flame.set_refine_criteria(ratio=RATIO, slope=SLOPE, curve=CURVE)
flame.solve(loglevel=0, auto=True)

with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["grid_m", "T_K", "velocity_m_s"])
    for row in zip(flame.grid, flame.T, flame.velocity):
        w.writerow(row)

su_cm_s = flame.velocity[0] * 100.0

# Two panels: the temperature profile, and the velocity profile whose
# unburned-side value IS the reported flame speed -- so the number can be
# read straight off the plot rather than taken on trust.
x_mm = np.asarray(flame.grid) * 1e3
u_cm_s = np.asarray(flame.velocity) * 100.0

fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.set_xlabel("distance (mm)")
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

axes[0].plot(x_mm, flame.T, color="#2a78d6", linewidth=2, zorder=3)
axes[0].set_ylabel("temperature (K)")
axes[0].set_title("temperature profile")

axes[1].plot(x_mm, u_cm_s, color="#1baf7a", linewidth=2, zorder=3)
axes[1].axhline(su_cm_s, color="#eb6834", linewidth=1.5, linestyle="--", zorder=2)
axes[1].set_ylabel("axial velocity (cm/s)")
axes[1].set_title("velocity — inlet value is the flame speed")
axes[1].annotate(f"Su = {su_cm_s:.4g} cm/s", xy=(x_mm[-1], su_cm_s),
                 xytext=(-8, 8), textcoords="offset points", ha="right",
                 color="#eb6834", fontsize=10, fontweight="bold")

fig.suptitle(f"hydrogen/air flame, phi={PHI}, {T_UNBURNED_K:.0f} K, {P_ATM:g} atm",
             fontsize=11)
fig.tight_layout(); fig.savefig("flame_profile.png")
print(f"flame_speed_cm_s={su_cm_s:.6g}")
