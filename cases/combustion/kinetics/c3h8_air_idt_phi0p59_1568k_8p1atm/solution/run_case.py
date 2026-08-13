"""Reference solution: 0-D constant-volume adiabatic ignition delay."""
import matplotlib
matplotlib.use("Agg")
import csv
import cantera as ct
import numpy as np
import matplotlib.pyplot as plt

MECHANISM = 'gri30.yaml'
PHASE = None
FUEL = 'C3H8'
PHI = 0.59
T0_K = 1568.0
P0_ATM = 8.1
MAX_TIME_S = 2.0
RTOL, ATOL = 1e-09, 1e-18


gas = ct.Solution(MECHANISM, PHASE) if PHASE else ct.Solution(MECHANISM)
gas.set_equivalence_ratio(PHI, fuel=FUEL, oxidizer={"O2": 1.0, "N2": 3.76})
gas.TP = T0_K, P0_ATM * ct.one_atm

reactor = ct.IdealGasReactor(gas)
net = ct.ReactorNet([reactor])
net.rtol, net.atol = RTOL, ATOL

t_hist, T_hist, P_hist = [0.0], [reactor.T], [reactor.thermo.P]
while t_hist[-1] < MAX_TIME_S and len(t_hist) < 400_000:
    t_hist.append(net.step())
    T_hist.append(reactor.T)
    P_hist.append(reactor.thermo.P)

with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["time_s", "T_K", "P_Pa"])
    for row in zip(t_hist, T_hist, P_hist):
        w.writerow(row)

t = np.array(t_hist); T = np.array(T_hist)
idt_ms = t[int(np.argmax(np.gradient(T, t)))] * 1e3

# Two panels so the reported number is auditable: the history shows the
# induction period and the jump, and dT/dt shows that the marker really sits
# on the maximum. The window is scaled to the event rather than to the
# integrator's adaptive step range, which spans a meaningless 16 decades.
dTdt = np.gradient(T, t)
t_ms = t * 1e3
window = idt_ms * 1.5 if idt_ms > 0 else t_ms[-1]
sel = t_ms <= window

fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.axvline(idt_ms, color="#eb6834", linewidth=1.5, linestyle="--", zorder=2)
    ax.set_xlabel("time (ms)")
    ax.set_xlim(0, window)
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

axes[0].plot(t_ms[sel], T[sel], color="#2a78d6", linewidth=2, zorder=3)
axes[0].set_ylabel("temperature (K)")
axes[0].set_title("temperature history")
axes[0].annotate(f"IDT = {idt_ms:.4g} ms",
                 xy=(idt_ms, T[sel].min() + 0.45 * (T[sel].max() - T[sel].min())),
                 xytext=(-8, 0), textcoords="offset points",
                 ha="right", color="#eb6834", fontsize=10, fontweight="bold")

axes[1].plot(t_ms[sel], dTdt[sel], color="#1baf7a", linewidth=2, zorder=3)
axes[1].set_ylabel("dT/dt (K/s)")
axes[1].set_title("dT/dt — the maximum defines the delay")

fig.suptitle(f"propane/air ignition, phi={PHI}, {T0_K:.0f} K, {P0_ATM:g} atm",
             fontsize=11)
fig.tight_layout(); fig.savefig("ignition_history.png")
print(f"ignition_delay_ms={idt_ms:.6g}")
