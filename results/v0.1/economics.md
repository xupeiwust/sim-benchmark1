# Economics — sim-benchmark v0.1 reference runs

Auto-generated from `tools/aggregate_economics.py` over per-trial `cost.json` files.

## Per-run summary

Cross-model comparable: turns, wall_seconds. Token / `$` cost columns vary by tokens_source — see methodology note below.

| Run | Model | Cases | Mean turns/case | Mean wall/case (s) | Total turns | Total wall (s) | Total tokens out | Total cost (USD) | tokens_source |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `2026-05-06__17-13-51` | MiniMax-M2.5-highspeed | 20 | 29.7 | 238.0 | 594 | 4,760.4 | 150,326 | — | openai_usage_proxy |
| `2026-05-06__22-06-27` | MiniMax-M2.7 | 20 | 26.1 | 283.6 | 496 | 5,387.7 | 105,059 | — | openai_usage_proxy |
| `2026-05-06__22-06-27` | MiniMax-M2.5-highspeed | 3 | 175.7 | 1,512.9 | 527 | 4,538.8 | 201,491 | — | openai_usage_proxy |
| `2026-05-06__22-06-30` | MiniMax-M2.7 | 3 | 157.0 | 2,341.3 | 471 | 7,023.9 | 149,494 | — | openai_usage_proxy |
| `2026-05-07__15-02-30` | claude-opus-4-6 | 20 | 27.6 | 280.9 | 553 | 5,617.9 | 5,201 | 131.47 | claude_code_assistant_sum |
| `2026-05-07__15-11-43` | claude-opus-4-6 | 3 | 110.3 | 1,315.1 | 331 | 3,945.4 | 3,250 | 127.86 | claude_code_assistant_sum |

## Per-case detail

Same caveat: trust turns + wall across models; tokens / `$` only within a tokens_source.

| Run | Case | Turns | Wall (s) | Output tok | Cost (USD) |
|---|---|---:|---:|---:|---:|
| `2026-05-06__17-13-51` | `bridge_rectifier_ripple` | 81 | 1,295.9 | 27,382 | — |
| `2026-05-06__17-13-51` | `diff_amp` | 15 | 71.5 | 2,431 | — |
| `2026-05-06__17-13-51` | `half_wave_rectifier` | 17 | 77.9 | 2,750 | — |
| `2026-05-06__17-13-51` | `inv_amp` | 19 | 86.4 | 2,980 | — |
| `2026-05-06__17-13-51` | `lc_lowpass_2nd` | 35 | 312.8 | 14,627 | — |
| `2026-05-06__17-13-51` | `lc_resonator` | 13 | 63.0 | 2,213 | — |
| `2026-05-06__17-13-51` | `noninv_amp` | 20 | 104.8 | 3,561 | — |
| `2026-05-06__17-13-51` | `opamp_buffer` | 9 | 52.9 | 1,569 | — |
| `2026-05-06__17-13-51` | `opamp_integrator` | 47 | 347.9 | 13,166 | — |
| `2026-05-06__17-13-51` | `opamp_summer` | 11 | 73.0 | 2,407 | — |
| `2026-05-06__17-13-51` | `rc_highpass_ac` | 40 | 271.0 | 12,774 | — |
| `2026-05-06__17-13-51` | `rc_lowpass_ac` | 70 | 392.5 | 20,456 | — |
| `2026-05-06__17-13-51` | `rc_pulse_response` | 25 | 104.9 | 3,851 | — |
| `2026-05-06__17-13-51` | `rl_lowpass_ac` | 10 | 54.6 | 1,870 | — |
| `2026-05-06__17-13-51` | `rl_step` | 10 | 59.9 | 1,649 | — |
| `2026-05-06__17-13-51` | `rlc_bandpass` | 33 | 202.0 | 8,967 | — |
| `2026-05-06__17-13-51` | `rlc_notch` | 21 | 119.6 | 4,879 | — |
| `2026-05-06__17-13-51` | `rlc_step_overdamped` | 24 | 227.4 | 3,562 | — |
| `2026-05-06__17-13-51` | `rlc_step_underdamped` | 46 | 470.4 | 7,970 | — |
| `2026-05-06__17-13-51` | `sallen_key_lp` | 48 | 372.1 | 11,262 | — |
| `2026-05-06__22-06-27` | `bridge_rectifier_ripple` | — | — | — | — |
| `2026-05-06__22-06-27` | `diff_amp` | 18 | 116.4 | 3,567 | — |
| `2026-05-06__22-06-27` | `half_wave_rectifier` | 15 | 170.4 | 2,603 | — |
| `2026-05-06__22-06-27` | `inv_amp` | 16 | 190.8 | 3,038 | — |
| `2026-05-06__22-06-27` | `lc_lowpass_2nd` | 15 | 114.6 | 3,698 | — |
| `2026-05-06__22-06-27` | `lc_resonator` | 31 | 317.6 | 4,947 | — |
| `2026-05-06__22-06-27` | `noninv_amp` | 20 | 219.5 | 3,987 | — |
| `2026-05-06__22-06-27` | `opamp_buffer` | 21 | 175.3 | 2,514 | — |
| `2026-05-06__22-06-27` | `opamp_integrator` | 27 | 408.1 | 5,661 | — |
| `2026-05-06__22-06-27` | `opamp_summer` | 75 | 1,101.7 | 16,052 | — |
| `2026-05-06__22-06-27` | `rc_highpass_ac` | 51 | 362.6 | 12,168 | — |
| `2026-05-06__22-06-27` | `rc_lowpass_ac` | 21 | 275.4 | 6,598 | — |
| `2026-05-06__22-06-27` | `rc_pulse_response` | 21 | 206.2 | 3,986 | — |
| `2026-05-06__22-06-27` | `rl_lowpass_ac` | 17 | 99.6 | 3,159 | — |
| `2026-05-06__22-06-27` | `rl_step` | 18 | 210.9 | 3,557 | — |
| `2026-05-06__22-06-27` | `rlc_bandpass` | 27 | 229.9 | 5,762 | — |
| `2026-05-06__22-06-27` | `rlc_notch` | 35 | 489.0 | 6,970 | — |
| `2026-05-06__22-06-27` | `rlc_step_overdamped` | 16 | 104.7 | 3,191 | — |
| `2026-05-06__22-06-27` | `rlc_step_underdamped` | 16 | 194.6 | 2,472 | — |
| `2026-05-06__22-06-27` | `sallen_key_lp` | 36 | 400.4 | 11,129 | — |
| `2026-05-06__22-06-27` | `flatplate_zpg_subsonic` | 301 | 3,217.0 | 137,293 | — |
| `2026-05-06__22-06-27` | `lid_driven_cavity_re1000` | 102 | 461.9 | 20,783 | — |
| `2026-05-06__22-06-27` | `lid_driven_cavity_re100` | 124 | 859.9 | 43,415 | — |
| `2026-05-06__22-06-30` | `flatplate_zpg_subsonic` | 239 | 4,581.3 | 91,477 | — |
| `2026-05-06__22-06-30` | `lid_driven_cavity_re1000` | 119 | 1,763.1 | 34,366 | — |
| `2026-05-06__22-06-30` | `lid_driven_cavity_re100` | 113 | 679.5 | 23,651 | — |
| `2026-05-07__15-02-30` | `bridge_rectifier_ripple` | 99 | 1,604.9 | 1,186 | 40.77 |
| `2026-05-07__15-02-30` | `diff_amp` | 17 | 102.1 | 166 | 2.98 |
| `2026-05-07__15-02-30` | `half_wave_rectifier` | 55 | 980.9 | 512 | 12.41 |
| `2026-05-07__15-02-30` | `inv_amp` | 15 | 122.1 | 124 | 2.21 |
| `2026-05-07__15-02-30` | `lc_lowpass_2nd` | 13 | 118.9 | 103 | 2.37 |
| `2026-05-07__15-02-30` | `lc_resonator` | 12 | 80.2 | 97 | 2.03 |
| `2026-05-07__15-02-30` | `noninv_amp` | 17 | 105.0 | 121 | 2.71 |
| `2026-05-07__15-02-30` | `opamp_buffer` | 16 | 95.2 | 133 | 2.69 |
| `2026-05-07__15-02-30` | `opamp_integrator` | 79 | 683.7 | 817 | 20.35 |
| `2026-05-07__15-02-30` | `opamp_summer` | 41 | 369.1 | 353 | 9.15 |
| `2026-05-07__15-02-30` | `rc_highpass_ac` | 11 | 77.4 | 71 | 1.79 |
| `2026-05-07__15-02-30` | `rc_lowpass_ac` | 18 | 144.6 | 194 | 3.30 |
| `2026-05-07__15-02-30` | `rc_pulse_response` | 13 | 83.1 | 87 | 2.03 |
| `2026-05-07__15-02-30` | `rl_lowpass_ac` | 18 | 134.8 | 128 | 3.26 |
| `2026-05-07__15-02-30` | `rl_step` | 19 | 107.9 | 172 | 3.00 |
| `2026-05-07__15-02-30` | `rlc_bandpass` | 12 | 73.9 | 106 | 1.97 |
| `2026-05-07__15-02-30` | `rlc_notch` | 21 | 150.3 | 157 | 3.81 |
| `2026-05-07__15-02-30` | `rlc_step_overdamped` | 40 | 287.5 | 424 | 8.62 |
| `2026-05-07__15-02-30` | `rlc_step_underdamped` | 18 | 161.5 | 88 | 2.61 |
| `2026-05-07__15-02-30` | `sallen_key_lp` | 19 | 134.8 | 162 | 3.42 |
| `2026-05-07__15-11-43` | `flatplate_zpg_subsonic` | 117 | 2,141.3 | 1,317 | 66.83 |
| `2026-05-07__15-11-43` | `lid_driven_cavity_re1000` | 109 | 958.7 | 986 | 33.55 |
| `2026-05-07__15-11-43` | `lid_driven_cavity_re100` | 105 | 845.5 | 947 | 27.48 |

## Methodology note

- **`turns`**: number of agent round-trips (claude-code's `result.num_turns`). Comparable across models.
- **`wall_s`**: end-to-end trial wall time (claude-code's `result.duration_ms`). Comparable across models.
- **`tokens_source = openai_usage_proxy`**: ccr-routed runs (MiniMax). Tokens are the proxy's exact request-by-request sum; no `$` figure (price varies by upstream).
- **`tokens_source = claude_code_assistant_sum`**: direct-Anthropic runs (Claude Opus 4.6). Per-message usage on streaming events is incomplete in the SDK transcript, so token totals here **undercount** the true cumulative; `$` cost is taken from claude-code's `total_cost_usd` (trial-cumulative, accurate).
- We do **not** publish a unified `tokens` × price table — different upstreams price differently. Use within-model rows for cost/quality reasoning.

