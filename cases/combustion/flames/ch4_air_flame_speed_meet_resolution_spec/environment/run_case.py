"""Laminar burning velocity of a premixed methane/air flame."""
import csv
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

warnings.filterwarnings("ignore")
import cantera as ct

MECH = "gri30.yaml"
FUEL = "CH4"
OXIDIZER = {"O2": 1.0, "N2": 3.76}
PHI = 1.07
T_UNBURNED = 312.0
P_ATM = 1.2

DOMAIN_WIDTH_M = 0.03
TRANSPORT = "mixture-averaged"
REFINE_RATIO = 10.0
REFINE_SLOPE = 0.8
REFINE_CURVE = 0.8


def solve_flame():
    gas = ct.Solution(MECH)
    gas.set_equivalence_ratio(PHI, fuel=FUEL, oxidizer=OXIDIZER)
    gas.TP = T_UNBURNED, P_ATM * ct.one_atm

    flame = ct.FreeFlame(gas, width=DOMAIN_WIDTH_M)
    flame.transport_model = TRANSPORT
    flame.set_refine_criteria(ratio=REFINE_RATIO, slope=REFINE_SLOPE,
                              curve=REFINE_CURVE)
    flame.solve(loglevel=0, auto=True)
    return flame


def write_profile(flame, path="results.csv"):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["grid_m", "T_K", "velocity_m_s"])
        for row in zip(flame.grid, flame.T, flame.velocity):
            writer.writerow(row)


def plot_profile(flame, path="flame_profile.png"):
    x_mm = np.asarray(flame.grid) * 1e3
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.0, 3.8), dpi=140)
    left.plot(x_mm, flame.T, color="#c0392b", linewidth=1.8)
    left.set_xlabel("distance (mm)")
    left.set_ylabel("temperature (K)")
    right.plot(x_mm, np.asarray(flame.velocity) * 100.0, color="#2c3e50",
               linewidth=1.8)
    right.set_xlabel("distance (mm)")
    right.set_ylabel("axial velocity (cm/s)")
    fig.suptitle("premixed methane/air flame, phi=%g, %g K, %g atm"
                 % (PHI, T_UNBURNED, P_ATM), fontsize=10)
    fig.tight_layout()
    fig.savefig(path)


def main():
    flame = solve_flame()
    write_profile(flame)
    plot_profile(flame)
    print("burning velocity (cm/s):", flame.velocity[0] * 100.0)
    print("grid points:", flame.grid.size)


if __name__ == "__main__":
    main()
