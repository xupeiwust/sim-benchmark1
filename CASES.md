# Public Case Catalog

23 public-runnable cases ship in v0.1: **20 LTspice circuits** + **3 OpenFOAM
fluids**. Every case has a no-token oracle. The CFD scope is intentionally
narrow for v0.1; more OpenFOAM cases land in v0.2 once their oracles are
written.

## Status

| Status | Meaning |
|---|---|
| `public_runnable` | Public task with verifier assets; included in the public leaderboard set. |
| `public_draft` | Public task definition that is not yet leaderboard-runnable. |
| `hidden_eval` | Reserved for future private licensed-solver tasks. |

## Oracle Status

| Oracle | Meaning |
|---|---|
| `available` | A no-token oracle `solution/solve.sh` is present. |
| `deferred` | The task and verifier are public, but the no-token oracle is not built yet. |
| `not_applicable` | No oracle is expected for this case type. |

## Leakage Risk

| Risk | Meaning |
|---|---|
| `0` | Novel or private variant; low chance of memorized answer. |
| `1` | Public background, but the exact case/KPI path is meaningfully customized. |
| `2` | Standard textbook or validation case; similar examples likely exist online. |
| `3` | Very classic benchmark; high chance the model has seen the setup or answer pattern. |

## Cases

| Domain | Case | Status | Oracle | Template | Leakage | Target | Tier |
|---|---|---|---|---|---:|---|---|
| circuits | `bridge_rectifier_ripple` | public_runnable | available | measurement | 2 | postprocess | S |
| circuits | `diff_amp` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `half_wave_rectifier` | public_runnable | available | measurement | 2 | postprocess | S |
| circuits | `inv_amp` | public_runnable | available | measurement | 3 | postprocess | M |
| circuits | `lc_lowpass_2nd` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `lc_resonator` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `noninv_amp` | public_runnable | available | measurement | 3 | postprocess | M |
| circuits | `opamp_buffer` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `opamp_integrator` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `opamp_summer` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `rc_highpass_ac` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `rc_lowpass_ac` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `rc_pulse_response` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `rl_lowpass_ac` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `rl_step` | public_runnable | available | measurement | 3 | postprocess | S |
| circuits | `rlc_bandpass` | public_runnable | available | measurement | 2 | postprocess | S |
| circuits | `rlc_notch` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `rlc_step_overdamped` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `rlc_step_underdamped` | public_runnable | available | measurement | 2 | postprocess | M |
| circuits | `sallen_key_lp` | public_runnable | available | measurement | 2 | postprocess | M |
| fluids | `flatplate_zpg_subsonic` | public_runnable | available | numerical | 2 | numerical | S |
| fluids | `lid_driven_cavity_re100` | public_runnable | available | numerical | 3 | numerical | S |
| fluids | `lid_driven_cavity_re1000` | public_runnable | available | numerical | 3 | numerical | S |

Total: 23 public-runnable cases, all with no-token oracle solutions. v0.2 will
expand the OpenFOAM scope (turbulent boundary layer, transonic airfoil,
multiphase, separated flows) once those oracles are written and validated.
