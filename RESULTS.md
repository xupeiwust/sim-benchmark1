# Results

The release-facing v0.1 MVP results live in
[`results/v0.1/`](./results/v0.1/).

v0.1 is a benchmark release first. The public catalog contains 23 runnable
tasks: 20 LTspice circuit tasks and 3 OpenFOAM fluid tasks. Every task has a
no-token oracle.

## v0.1 Reference Runs

### LTspice circuits (20 tasks)

| Run | Agent / Model | Assigned | Completed | Harness exceptions | Completed Mean | Assigned Mean | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20 | 20 | 0 | **1.000** | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** (non-reasoning) | 20 | 20 | 1 | **0.936** | **0.936** | pre-final harness; all assigned tasks completed |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** (reasoning) | 20 | 19 | 2 | **0.930** | **0.884** | final harness; `bridge_rectifier_ripple` terminated at wall-time cap before completing |

### OpenFOAM fluids (3 oracle-available tasks)

| Run | Agent / Model | Assigned | Completed | Harness exceptions | Completed Mean | Assigned Mean | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| `release-v0.1-openfoam3-oracle-20260506` | oracle (deterministic) | 3 | 3 | 0 | **0.999** | **0.999** | reference upper bound; flatplate cf_x097 = 0.997 within numerical noise of NASA-TMR ref |
| `release-v0.1-openfoam3-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** | 3 | 3 | 1 | **0.408** | **0.408** | cavity_re100 = 1.0; cavity_re1000 = 0.225; flatplate = 0.0 |
| `release-v0.1-openfoam3-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** | 3 | 3 | 0 | **0.284** | **0.284** | cavity_re100 = 0.0 from an extract-path paperwork bug; cavity_re1000 = 0.390; flatplate = 0.462 |

`Completed Mean` averages completed trials only. `Assigned Mean` counts
assigned but incomplete tasks as zero. `Harness exceptions` are agent or
runner exit-status events; they are not always zero-score tasks because the
verifier may still have replayable artifacts.

### Caveats and known harness-limited results

- **Superseded MiniMax-M2.7 LTspice run.** An earlier M2.7 run was
  invalidated by a claude-code-router reasoning-content translation bug
  and a too-low turn cap. It is preserved in git history, but not in the
  current release artifacts.
- **M2.7 OpenFOAM cavity_re100 = 0.0** is a paperwork failure: the agent
  ran the solver correctly (u_centerline = -0.201 vs Ghia 1982 GT -0.205,
  within 2 %) but wrote `extract` pipelines using relative paths (e.g.
  `grep cells log.checkMesh`) that the verifier cannot replay because its
  cwd is not the case dir. The Pass-2 Stop hook (added in this release)
  will catch this in future runs by replaying the extract before letting
  the agent stop. **Not a model capability failure for the simulation
  itself**; it is a model failure on harness-contract bookkeeping.
- **M2.7 LTspice bridge_rectifier_ripple was terminated at wall-time
  budget (~1 hour, 88 turns of 300)** — counted as not-completed in the
  19/20 above. Partial trace shows the agent was actively reasoning
  about ripple-time-step resolution when stopped. Score is "n/a" for that
  case, not 0.

## Machine-readable artifacts

- [`results/v0.1/summary.json`](./results/v0.1/summary.json) — release summary
- `results/v0.1/ltspice20-oracle-20260503.{csv,json}`
- `results/v0.1/ltspice20-minimax-m25-20260506.{csv,json}`
- `results/v0.1/ltspice20-minimax-m27-20260506-final.{csv,json}`
- `results/v0.1/openfoam3-{oracle,minimax-m25hs,minimax-m27}-*.json`
- [`LEADERBOARD.md`](./LEADERBOARD.md) — historical and ablation results

## OpenFOAM scope

The 3 OpenFOAM tasks above are the v0.1 oracle-verified subset. v0.2 will
expand OpenFOAM scope (turbulent boundary layer, transonic airfoil,
multiphase, separated flows) once those oracles are written. The default OpenFOAM
release gate ships in v0.2 once `svd-ai-lab/sim-benchmark-base:latest`
is publicly pullable.
