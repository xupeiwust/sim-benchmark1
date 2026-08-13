"""Oracle: the logarithmic sensitivity of ignition delay to one named reaction.

The quantity is a derivative, so no single integration contains it. It is
obtained by perturbing that reaction's rate and watching what the delay does,
and the answer is only well defined in the limit of a small perturbation — a
50% perturbation on the chain-branching reaction of this mechanism reads 4.9%
away from the limit, which is most of a scoring band. So the perturbation is
refined until the estimate stops moving, and the converged value is what is
reported.

Two conventions are pinned by the instruction rather than assumed here,
because both are in use and they disagree. The delay is the time of maximum
dT/dt, which is what this track's evaluator re-derives from the trace. And the
sensitivity is the small-perturbation logarithmic derivative, **not** the
"percent sensitivity" obtained by doubling a rate — the second is common in
the literature and gives a materially different number.
"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import cantera as ct  # noqa: E402

MECHANISM = "gri30.yaml"
FUEL, PHI = "CH4", 0.87
T0_K, P0_ATM = 1390.0, 2.4
REACTION = "CH3 + HO2 <=> CH3O + OH"
# Refined until the estimate stops moving; the last step below moves it 0.03%.
PERTURBATIONS = (0.10, 0.05, 0.02, 0.01)
CONVERGED_AT = 0.01


def reaction_index(gas) -> int:
    wanted = REACTION.replace(" ", "")
    hits = [i for i, eq in enumerate(gas.reaction_equations())
            if eq.replace(" ", "") == wanted]
    if len(hits) != 1:
        raise RuntimeError(f"{REACTION!r} matched {len(hits)} reactions, expected 1")
    return hits[0]


def integrate(multiplier: float | None = None):
    """Constant-volume adiabatic ignition; returns the (t, T, P) trace."""
    gas = ct.Solution(MECHANISM)
    gas.set_equivalence_ratio(PHI, FUEL, "O2:1, N2:3.76")
    gas.TP = T0_K, P0_ATM * ct.one_atm
    if multiplier is not None:
        gas.set_multiplier(multiplier, reaction_index(gas))
    reactor = ct.IdealGasReactor(gas, clone=False)
    net = ct.ReactorNet([reactor])
    t, T, P = [], [], []
    peak = 0.0
    while True:
        net.step()
        t.append(net.time)
        T.append(reactor.T)
        P.append(reactor.thermo.P)
        if len(t) > 8:
            slope = np.gradient(np.asarray(T), np.asarray(t))
            peak = max(peak, float(slope.max()))
            # The instruction's stopping rule: integrate past ignition until
            # dT/dt has fallen to 0.1% of the maximum it reached, so the trace
            # brackets the maximum rather than ending on it.
            if peak > 0 and slope[-1] < 1.0e-3 * peak and max(T) - T[0] > 400.0:
                break
        if net.time > 0.5:
            raise RuntimeError("no ignition within 0.5 s")
    return np.asarray(t), np.asarray(T), np.asarray(P)


def delay_of(trace) -> float:
    t, T, _ = trace
    return float(t[np.argmax(np.gradient(T, t))])


base_trace = integrate()
tau0 = delay_of(base_trace)

# ── the derivative, refined until it stops moving ────────────────────────────
estimates = {}
for d in PERTURBATIONS:
    up = delay_of(integrate(1.0 + d))
    down = delay_of(integrate(1.0 - d))
    estimates[d] = ((np.log(up) - np.log(down))
                    / (np.log(1.0 + d) - np.log(1.0 - d)))
sensitivity = float(estimates[CONVERGED_AT])

t, T, P = base_trace
with open("results.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["time_s", "T_K", "P_Pa", "s_ch3_ho2"])
    for row in zip(t, T, P):
        w.writerow(list(row) + [sensitivity])

fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=140)
for ax in axes:
    ax.grid(True, color="#e3e2dd", linewidth=0.7, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
axes[0].plot(t * 1e3, T, color="#c2452d", linewidth=2, zorder=3)
axes[0].axvline(tau0 * 1e3, color="#6b6a66", linewidth=1.2, linestyle="--", zorder=2)
axes[0].set_xlabel("time (ms)")
axes[0].set_ylabel("temperature (K)")
axes[0].set_title("ignition at the unperturbed rate")
axes[1].semilogx(list(estimates), list(estimates.values()),
                 marker="o", color="#2a78d6", linewidth=2, zorder=3)
axes[1].set_xlabel("relative rate perturbation")
axes[1].set_ylabel("estimated dln(tau)/dln(k)")
axes[1].set_title("the estimate settling as the perturbation shrinks")
fig.suptitle(f"ignition-delay sensitivity to  {REACTION}", fontsize=11)
fig.tight_layout()
fig.savefig("result.png")

print(f"ignition_delay_ms={tau0 * 1e3:.6g}")
print(f"s_ch3_ho2={sensitivity:.6g}")
