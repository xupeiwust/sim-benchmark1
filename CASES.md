# Public Case Catalog

All OpenFOAM and LTspice cases in this repository are public. The catalog
separates benchmark status from oracle availability: cases can be public and
leaderboard-runnable even when their no-token oracle is still deferred.

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
| fluids | `30p30n_three_element_highlift` | public_runnable | deferred | numerical | 1 | numerical | L |
| fluids | `axibump_transonic` | public_runnable | deferred | numerical | 1 | numerical | L |
| fluids | `backstep_driver_seegmiller_turbulent` | public_runnable | deferred | numerical | 2 | numerical | M |
| fluids | `bump_in_channel_2d` | public_runnable | deferred | numerical | 1 | numerical | M |
| fluids | `driver_axisym_apg_separation` | public_runnable | deferred | numerical | 1 | numerical | M |
| fluids | `dsma661_airfoil` | public_runnable | deferred | numerical | 1 | numerical | M |
| fluids | `flatplate_zpg_subsonic` | public_runnable | available | numerical | 2 | numerical | S |
| fluids | `flatplate_zpgh_supersonic` | public_runnable | deferred | numerical | 2 | numerical | L |
| fluids | `lid_driven_cavity_re100` | public_runnable | available | numerical | 3 | numerical | S |
| fluids | `lid_driven_cavity_re1000` | public_runnable | available | numerical | 3 | numerical | S |
| fluids | `naca0012_subsonic` | public_runnable | deferred | numerical | 2 | numerical | M |
| fluids | `naca4412_trailing_edge_separation` | public_runnable | deferred | numerical | 1 | numerical | L |
| fluids | `nasa_hump_separated` | public_runnable | deferred | numerical | 2 | numerical | M |
| fluids | `onera_m6_transonic` | public_runnable | deferred | numerical | 2 | numerical | L |
| fluids | `sandia_jet_variable_density` | public_runnable | deferred | numerical | 1 | numerical | L |
| fluids | `swbli_m5_flatplate` | public_runnable | deferred | numerical | 1 | numerical | L |

Current runnable public set: 36 cases: 20 LTspice/circuits cases and 16
OpenFOAM/fluids cases. No-token oracle solutions are currently available for
20 LTspice cases and 3 OpenFOAM cases.
