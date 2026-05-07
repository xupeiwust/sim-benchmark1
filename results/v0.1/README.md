# v0.1 MVP Results

This directory contains current release-facing result artifacts for the
initial public benchmark release. Git history is the archive for superseded
runs; files kept here are the current public result set.

## Summary

| Run | Agent / Model | Assigned | Completed | Harness exceptions | Completed Mean | Assigned Mean | Status |
|---|---|---:|---:|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20 | 20 | 0 | **1.000** | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-claude-opus46-20260507` | claude-code · Claude Opus 4.6 | 20 | 20 | 0 | **0.986** | **0.986** | included |
| `release-v0.1-ltspice20-minimax-m25-20260506` | claude-code · MiniMax-M2.5-highspeed | 20 | 20 | 1 | **0.936** | **0.936** | included |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · MiniMax-M2.7 | 20 | 19 | 2 | **0.930** | **0.884** | included; `bridge_rectifier_ripple` wall-time capped |
| `release-v0.1-openfoam3-oracle-20260506` | oracle (deterministic) | 3 | 3 | 0 | **0.999** | **0.999** | reference upper bound |
| `release-v0.1-openfoam3-claude-opus46-20260507` | claude-code · Claude Opus 4.6 | 3 | 3 | 0 | **1.000** | **1.000** | included |
| `release-v0.1-openfoam3-minimax-m25hs-20260506` | claude-code · MiniMax-M2.5-highspeed | 3 | 3 | 1 | **0.408** | **0.408** | included |
| `release-v0.1-openfoam3-minimax-m27-20260506` | claude-code · MiniMax-M2.7 | 3 | 3 | 0 | **0.284** | **0.284** | included |

`Completed Mean` averages completed trials only. `Assigned Mean` counts
assigned but incomplete tasks as zero. `Harness exceptions` are agent or
runner exit-status events; they are not always zero-score tasks because the
verifier may still have replayable artifacts.

## Files

- `summary.json` - machine-readable current release summary.
- `economics.md` / `economics.json` - per-run + per-case turns / wall-time / tokens / `$` cost.
- `ltspice20-oracle-20260503.{csv,json}` - LTspice oracle reference run.
- `ltspice20-claude-opus46-20260507.json` - Claude Opus 4.6 LTspice run.
- `ltspice20-minimax-m25-20260506.{csv,json}` - MiniMax-M2.5-highspeed LTspice run.
- `ltspice20-minimax-m27-20260506-final.{csv,json}` - MiniMax-M2.7 LTspice final run.
- `openfoam3-{oracle,claude-opus46,minimax-m25hs,minimax-m27}-2026050{6,7}.json` - OpenFOAM reference subset.

An earlier MiniMax-M2.7 LTspice run was superseded by the final run after a
reasoning-content router fix and turn-cap correction. It is intentionally not
kept beside current artifacts.

## Per-Case Comparison (LTspice 20)

| Case | Tier | Leakage | Oracle | Opus 4.6 | M2.5 | M2.7 final |
|---|---|---:|---:|---:|---:|---:|
| `bridge_rectifier_ripple` | M | 1 | 1.000 | 1.000 | 0.700 | n/a |
| `diff_amp` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `half_wave_rectifier` | S | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `inv_amp` | M | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `lc_lowpass_2nd` | M | 2 | 1.000 | 1.000 | 0.550 | 1.000 |
| `lc_resonator` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `noninv_amp` | M | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `opamp_buffer` | S | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `opamp_integrator` | M | 2 | 1.000 | 0.718 | 1.000 | 0.201 |
| `opamp_summer` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rc_highpass_ac` | S | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rc_lowpass_ac` | M | 1 | 1.000 | 1.000 | 0.775 | 0.775 |
| `rc_pulse_response` | S | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rl_lowpass_ac` | S | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rl_step` | S | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rlc_bandpass` | S | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rlc_notch` | M | 1 | 1.000 | 1.000 | 0.700 | 0.700 |
| `rlc_step_overdamped` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `rlc_step_underdamped` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| `sallen_key_lp` | M | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| **Completed Mean** | | | **1.000** | **0.986** | **0.936** | **0.930** |
| **Assigned Mean** | | | **1.000** | **0.986** | **0.936** | **0.884** |

## Observations

- The LTspice reference agents are both strong on many circuit workflows.
  Parameter-sweep and design-selection tasks remain more discriminating than
  simple measurement tasks.
- OpenFOAM is substantially harder because the agent must author case files,
  mesh, solve, post-process, and submit replayable KPI provenance.
- Several misses are workflow or provenance failures rather than pure physics
  failures. That is a core benchmark signal, not just bookkeeping noise.

## Cost / turns / wall (cross-model)

See [`economics.md`](./economics.md) for the full table + price sources.
Mean per case:

| Suite | Model | Turns | Wall (s) | $ / case |
|---|---|---:|---:|---:|
| LTspice 20 | MiniMax-M2.5-highspeed | 29.7 | 238 | $0.09 |
| LTspice 20 | MiniMax-M2.7              | 26.1 | 284 | $0.07 |
| LTspice 20 | Claude Opus 4.6           | 27.6 | 281 | **$6.57** |
| OpenFOAM 3 | MiniMax-M2.5-highspeed | 175.7 | 1,513 | $1.22 |
| OpenFOAM 3 | MiniMax-M2.7              | 157.0 | 2,341 | $0.67 |
| OpenFOAM 3 | Claude Opus 4.6           | 110.3 | 1,315 | **$42.62** |

MiniMax USD figures use May-2026 published rates; Claude Opus 4.6 uses
claude-code's trial-cumulative `total_cost_usd`. Per-case ratio Opus 4.6
vs MiniMax-M2.7 is **~94×** on LTspice and **~64×** on OpenFOAM. On the
OF oracle-available subset Opus reaches the oracle ceiling (1.000) while
M2.7 stays at 0.284, so the cost gap on CFD buys score, not just
latency: ~30 % fewer turns and ~44 % shorter wall than M2.7.

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

The MiniMax runs are routed via
[`claude-code-router`](https://github.com/musistudio/claude-code-router);
the harness wires it up at trial setup. See
`tools/agent_harness.py:ClaudeCodeViaCcr`.
