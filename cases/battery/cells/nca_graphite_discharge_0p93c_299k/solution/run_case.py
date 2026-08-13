"""Reference solution: constant-current discharge."""
import matplotlib
matplotlib.use("Agg")
import csv
import numpy as np
import pybamm
import matplotlib.pyplot as plt

PARAMETER_SET = 'NCA_Kim2011'
MODEL = 'SPMe'
OPTIONS = {}
INITIAL_SOC = 1.0
AMBIENT_K = 299.15
EXPERIMENT = ['Discharge at 0.93C until 2.7V']
RTOL, ATOL = 1e-06, 1e-06
WITH_TEMPERATURE = False

# Discretisation and solver follow PyBaMM's own published examples rather than
# anything derived here: the particle mesh is refined toward the surface the
# way the O'Regan 2022 example does, because these parameter sets carry steep
# surface concentration gradients that a uniform particle mesh does not
# resolve -- on a uniform mesh the reported temperature rise keeps drifting as
# the mesh is refined instead of converging.
VAR_PTS = {'x_n': 30, 'x_s': 30, 'x_p': 30, 'r_n': 40, 'r_p': 40}


param = pybamm.ParameterValues(PARAMETER_SET)
param.update({"Ambient temperature [K]": AMBIENT_K,
              "Initial temperature [K]": AMBIENT_K})

model = getattr(pybamm.lithium_ion, MODEL)(OPTIONS)

submesh_types = model.default_submesh_types
for _particle in ("negative particle", "positive particle"):
    submesh_types[_particle] = pybamm.MeshGenerator(
        pybamm.Exponential1DSubMesh, submesh_params={"side": "right"}
    )

solver = pybamm.IDAKLUSolver(rtol=RTOL, atol=ATOL)
sim = pybamm.Simulation(
    model, parameter_values=param, solver=solver,
    var_pts=VAR_PTS, submesh_types=submesh_types,
    experiment=pybamm.Experiment([tuple(s) if isinstance(s, list) else s
                                  for s in EXPERIMENT]),
)
sol = sim.solve(initial_soc=INITIAL_SOC)

t = np.asarray(sol["Time [s]"].data, dtype=float)
I = np.asarray(sol["Current [A]"].data, dtype=float)
V = np.asarray(sol["Voltage [V]"].data, dtype=float)
T = (np.asarray(sol["Volume-averaged cell temperature [K]"].data, dtype=float)
     if WITH_TEMPERATURE else None)

header = ["time_s", "current_A", "voltage_V"] + (["temperature_K"] if WITH_TEMPERATURE else [])
with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(header)
    for row in (zip(t, I, V, T) if WITH_TEMPERATURE else zip(t, I, V)):
        w.writerow(row)

disch = I > 0
value = float(np.trapezoid(np.where(disch, I, 0.0), t) / 3600.0)

# Two panels so the reported number is auditable: the voltage trace shows the
# protocol actually ran to its stopping condition, and the second panel shows
# the quantity the number is read off, rather than asking the reader to take
# the printed value on trust.
t_h = t / 3600.0
fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.set_xlabel("time (h)")
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

axes[0].plot(t_h, V, color="#2a78d6", linewidth=2, zorder=3)
axes[0].set_ylabel("terminal voltage (V)")
axes[0].set_title("voltage response")

Ah_cum = np.concatenate([[0.0], np.cumsum(np.diff(t) * (I[1:] + I[:-1]) / 2)]) / 3600.0
axes[1].plot(t_h, Ah_cum, color="#eb6834", linewidth=2, zorder=3)
axes[1].set_ylabel("cumulative charge throughput (A.h)")
axes[1].set_title("charge throughput")

fig.suptitle('NCA_Kim2011 cell, constant-current discharge', fontsize=11)
fig.tight_layout(); fig.savefig("result.png")
print(f"discharge_capacity_Ah={value:.6g}")
