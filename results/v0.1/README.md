# v0.1 MVP Results

This directory contains release-facing result artifacts for the v0.1 MVP gate. The public benchmark release ships 36 public runnable tasks; the scored MVP gate is the 20-task LTspice circuit suite.

## Summary

| Run | Agent / Model | Tasks | Completed | Errored | **Mean** | Status |
|---|---|---:|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20 | 20 | 0 | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-minimax-m25-20260506` | claude-code · MiniMax-M2.5-highspeed | 20 | 20 | 1 | **0.936** | non-reasoning |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · MiniMax-M2.7 | 20 | 20 | 3 | **0.776** | reasoning |

Read this as: the oracle baseline is what the verifier scores when the solve.sh ships the right answer; any model row reads against that ceiling.

## Files

- `summary.json` — machine-readable release summary (above table + dependency snapshot).
- `ltspice20-oracle-20260503.{csv,json}` — oracle reference run.
- `ltspice20-minimax-m25-20260506.{csv,json}` — MiniMax-M2.5-highspeed run.
- `ltspice20-minimax-m27-20260506.{csv,json}` — MiniMax-M2.7 run.

## Per-Case Comparison (LTspice 20)

| Case | Tier | Leakage | Oracle | M2.5 | M2.7 |
|---|---|---:|---:|---:|---:|
| `bridge_rectifier_ripple` | M | 1 | 1.000 | 0.700 | **0.000** |
| `diff_amp` | M | 2 | 1.000 | 1.000 | 1.000 |
| `half_wave_rectifier` | S | 2 | 1.000 | 1.000 | **0.000** |
| `inv_amp` | M | 3 | 1.000 | 1.000 | 1.000 |
| `lc_lowpass_2nd` | M | 2 | 1.000 | **0.550** | 1.000 |
| `lc_resonator` | M | 2 | 1.000 | 1.000 | 1.000 |
| `noninv_amp` | M | 3 | 1.000 | 1.000 | 1.000 |
| `opamp_buffer` | S | 3 | 1.000 | 1.000 | 1.000 |
| `opamp_integrator` | M | 2 | 1.000 | 1.000 | **0.202** |
| `opamp_summer` | M | 2 | 1.000 | 1.000 | 1.000 |
| `rc_highpass_ac` | S | 3 | 1.000 | 1.000 | 1.000 |
| `rc_lowpass_ac` | M | 1 | 1.000 | **0.775** | **0.325** |
| `rc_pulse_response` | S | 3 | 1.000 | 1.000 | 1.000 |
| `rl_lowpass_ac` | S | 3 | 1.000 | 1.000 | **0.000** |
| `rl_step` | S | 3 | 1.000 | 1.000 | 1.000 |
| `rlc_bandpass` | S | 2 | 1.000 | 1.000 | 1.000 |
| `rlc_notch` | M | 1 | 1.000 | **0.700** | 1.000 |
| `rlc_step_overdamped` | M | 2 | 1.000 | 1.000 | 1.000 |
| `rlc_step_underdamped` | M | 2 | 1.000 | 1.000 | 1.000 |
| `sallen_key_lp` | M | 2 | 1.000 | 1.000 | 1.000 |
| **Mean** | | | **1.000** | **0.936** | **0.776** |

## Observations

- **M2.5 outperforms M2.7 on this task suite** by a wide margin (+0.16 mean). The difference is concentrated in three cases where M2.7 returned 0 — the reasoning variant appears to have spent its 80-turn budget on planning and never submitted `/tmp/agent/result.json`. M2.5's worst cases are still partial credit (0.55–0.78), no zero-score outright failures.
- **Both models bottom out on the upgraded design tasks** (`bridge_rectifier_ripple`, `rc_lowpass_ac`, `rlc_notch`, `lc_lowpass_2nd`). These are the cases where the model has to sweep a parameter (capacitor value) and choose by spec — not just measure. Leakage 1 cases (bridge_rectifier_ripple, rc_lowpass_ac, rlc_notch) are the deliberately novel-variant tasks and behave as designed: they discriminate.
- **No analytical-shortcut hits seen.** Both models actually ran LTspice (every passing trial has a real `.log` and `.raw` artifact).

## Reproduction

```bash
# Oracle (no LLM, no API key)
harbor run -p cases/circuits --agent oracle --job-name release-v0.1-ltspice20-oracle -o jobs --force-build -y

# MiniMax-M2.5-highspeed
export MINIMAX_API_KEY=<your-key>
harbor run -c configs/release-v0.1-ltspice20-minimax-m25.yaml --force-build -y

# MiniMax-M2.7
harbor run -c configs/release-v0.1-ltspice20-minimax-m27.yaml --force-build -y
```

The MiniMax runs are routed via [`claude-code-router`](https://github.com/musistudio/claude-code-router); the harness wires it up at trial setup. See `tools/agent_harness.py:ClaudeCodeViaCcr`.
