"""Reference solution: one flame, two transport closures, and the ratio.

The reported quantity is a RELATION between two runs of the same operating
point, so the flame speed itself -- which sits on a densely published
Su(phi, T, P) surface -- divides out and only the differential-diffusion
content of this mixture is left. Both profiles are written on the same
three-column interface; the evaluator reads each with the same code.
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
FUEL = 'C2H6'
PHI = 1.09
T_UNBURNED_K = 316.0
P_ATM = 1.3
WIDTH_M = 0.03
RATIO, SLOPE, CURVE = 3, 0.06, 0.12
REFERENCE_TRANSPORT = "mixture-averaged"
COMPARISON_TRANSPORT = "unity-Lewis-number"


def solve(transport):
    gas = ct.Solution(MECHANISM, PHASE) if PHASE else ct.Solution(MECHANISM)
    gas.set_equivalence_ratio(PHI, fuel=FUEL, oxidizer={"O2": 1.0, "N2": 3.76})
    gas.TP = T_UNBURNED_K, P_ATM * ct.one_atm
    flame = ct.FreeFlame(gas, width=WIDTH_M)
    flame.transport_model = transport
    flame.set_refine_criteria(ratio=RATIO, slope=SLOPE, curve=CURVE)
    flame.solve(loglevel=0, auto=True)
    return flame


def write_profile(path, flame):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["grid_m", "T_K", "velocity_m_s"])
        for row in zip(flame.grid, flame.T, flame.velocity):
            w.writerow(row)


reference = solve(REFERENCE_TRANSPORT)
comparison = solve(COMPARISON_TRANSPORT)
write_profile("results.csv", reference)
write_profile("results_unity_lewis.csv", comparison)

su_ref = reference.velocity[0] * 100.0
su_alt = comparison.velocity[0] * 100.0
ratio = su_alt / su_ref

# Both velocity profiles on one axis, so the two inlet values the ratio is
# built from can be read off the figure rather than taken on trust.
fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.set_xlabel("distance (mm)")
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

for flame, colour, label in ((reference, "#1baf7a", REFERENCE_TRANSPORT),
                             (comparison, "#2a78d6", COMPARISON_TRANSPORT)):
    x_mm = np.asarray(flame.grid) * 1e3
    axes[0].plot(x_mm, np.asarray(flame.T), color=colour, linewidth=2,
                 zorder=3, label=label)
    axes[1].plot(x_mm, np.asarray(flame.velocity) * 100.0, color=colour,
                 linewidth=2, zorder=3, label=label)
axes[0].set_ylabel("temperature (K)")
axes[0].set_title("temperature profiles")
axes[1].set_ylabel("axial velocity (cm/s)")
axes[1].set_title("velocity — inlet values give the ratio")
axes[1].legend(frameon=False, fontsize=9)
axes[1].annotate(f"ratio = {ratio:.4g}", xy=(0.98, 0.05),
                 xycoords="axes fraction", ha="right",
                 color="#eb6834", fontsize=10, fontweight="bold")

fig.suptitle(f"ethane/air flame, phi={PHI}, {T_UNBURNED_K:.0f} K, {P_ATM:g} atm",
             fontsize=11)
fig.tight_layout(); fig.savefig("flame_profile.png")
print(f"flame_speed_cm_s={su_ref:.6g}")
print(f"unity_lewis_speed_cm_s={su_alt:.6g}")
print(f"unity_lewis_speed_ratio={ratio:.6g}")
