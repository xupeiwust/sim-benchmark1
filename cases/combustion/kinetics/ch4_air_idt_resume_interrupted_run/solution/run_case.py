"""Reference solution: finish an interrupted constant-volume ignition run.

The operating point is not written down anywhere -- it is whatever the
checkpoint on disk says it is. So this driver reads the state, continues from
it, and keeps the rows the interrupted run had already completed.
"""
import matplotlib
matplotlib.use("Agg")
import csv
import cantera as ct
import numpy as np
import matplotlib.pyplot as plt

MECHANISM = "gri30.yaml"
RTOL, ATOL = 1e-09, 1e-18
QUIET_FRACTION = 1e-3      # stop once dT/dt has fallen to 0.1% of its peak

# ── what is on disk ────────────────────────────────────────────────────────
# The process died mid-write, so the last line of results.csv may be a partial
# record. Keep only rows that carry all three fields and parse.
done = []
with open("results.csv", newline="") as fh:
    reader = csv.reader(fh)
    header = next(reader)
    for row in reader:
        if len(row) != 3:
            continue
        try:
            done.append(tuple(float(v) for v in row))
        except ValueError:
            continue

with open("state.csv", newline="") as fh:
    reader = csv.reader(fh)
    keys = next(reader)
    values = [float(v) for v in next(reader)]
state = dict(zip(keys, values))
t_restart = state["time_s"]

# The checkpoint is the last state that was actually saved; anything the trace
# carries beyond it was not checkpointed and is dropped rather than trusted.
done = [r for r in done if r[0] <= t_restart]

gas = ct.Solution(MECHANISM)
gas.TPY = (
    state["T_K"],
    state["P_Pa"],
    {name[2:]: state[name] for name in keys if name.startswith("Y_")},
)
reactor = ct.IdealGasReactor(gas)
net = ct.ReactorNet([reactor])
net.rtol, net.atol = RTOL, ATOL

# ── continue ───────────────────────────────────────────────────────────────
t_hist = [t_restart]
T_hist = [reactor.T]
P_hist = [reactor.phase.P]
peak = 0.0
while len(t_hist) < 400_000:
    t = net.step() + t_restart
    dt = t - t_hist[-1]
    rate = (reactor.T - T_hist[-1]) / dt if dt > 0 else 0.0
    t_hist.append(t)
    T_hist.append(reactor.T)
    P_hist.append(reactor.phase.P)
    peak = max(peak, rate)
    if peak > 0 and rate < QUIET_FRACTION * peak and t > t_restart:
        break

rows = done + list(zip(t_hist[1:], T_hist[1:], P_hist[1:]))
with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["time_s", "T_K", "P_Pa"])
    for row in rows:
        w.writerow([repr(v) for v in row])

t = np.array([r[0] for r in rows]); T = np.array([r[1] for r in rows])
idt_ms = t[int(np.argmax(np.gradient(T, t)))] * 1e3

dTdt = np.gradient(T, t)
t_ms = t * 1e3
window = idt_ms * 1.5
sel = t_ms <= window
fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.axvline(idt_ms, color="#eb6834", linewidth=1.5, linestyle="--", zorder=2)
    ax.axvline(t_restart * 1e3, color="#8a8a8a", linewidth=1.2, zorder=2)
    ax.set_xlabel("time (ms)")
    ax.set_xlim(0, window)
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
axes[0].plot(t_ms[sel], T[sel], color="#2a78d6", linewidth=2, zorder=3)
axes[0].set_ylabel("temperature (K)")
axes[0].set_title("temperature history (grey line: where the run was resumed)")
axes[1].plot(t_ms[sel], dTdt[sel], color="#1baf7a", linewidth=2, zorder=3)
axes[1].set_ylabel("dT/dt (K/s)")
axes[1].set_title("dT/dt — the maximum defines the delay")
fig.tight_layout(); fig.savefig("ignition_history.png")

print(f"reused_rows={len(done)} resumed_at_s={t_restart!r}")
print(f"ignition_delay_ms={idt_ms:.6g}")
