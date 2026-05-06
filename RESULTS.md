# Results

The release-facing v0.1 MVP results live in
[`results/v0.1/`](./results/v0.1/).

v0.1 is a benchmark release first. The public catalog contains 36 runnable
tasks: 20 LTspice circuit tasks and 16 OpenFOAM fluid tasks.

## v0.1 Reference Runs

### LTspice circuits (20 tasks)

| Run | Agent / Model | Tasks | Errors | **Mean** | Notes |
|---|---|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20 | 0 | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** (non-reasoning) | 20 | 1 | **0.936** | original 80-turn run; per-case audit shows no further gain expected from re-running with the v0.1-final harness (only 1 case bridge_rectifier_ripple was max_turns-bounded) |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** (reasoning) | 19/20 | 2 | **0.930** | rerun with v0.1-final harness (300-turn cap, ccr reasoning-block fix, Pass-2 hook). Up from 0.776 in 80-turn run. 1 case (bridge_rectifier_ripple) terminated at wall-time cap before completing |

### OpenFOAM fluids (3 oracle-available tasks)

| Run | Agent / Model | Tasks | Errors | **Mean** | Notes |
|---|---|---:|---:|---:|---|
| `release-v0.1-openfoam3-oracle-20260506` | oracle (deterministic) | 3 | 0 | **0.999** | reference upper bound; flatplate cf_x097 = 0.997 (within numerical noise of NASA-TMR ref) |
| `release-v0.1-openfoam3-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** | 3 | 1 | **0.408** | cavity_re100 = 1.0; cavity_re1000 = 0.225; flatplate = 0.0 (NonZeroAgentExitCodeError) |
| `release-v0.1-openfoam3-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** | 3 | 0 | **0.284** | cavity_re100 = 0.0 (extract paperwork bug — physics correct, see Caveat below); cavity_re1000 = 0.390; flatplate = 0.462 |

### Caveats and known harness-limited results

- **M2.5-highspeed LTspice** uses the original 80-turn / pre-fix harness,
  not the v0.1-final harness used by M2.7. Cross-row comparison should
  bias slightly in M2.7's favour (M2.5-highspeed had 1 case (bridge_rectifier_ripple)
  capped at max_turns=80; with 300 turns it would likely score 1.0,
  raising mean to ~0.948).
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
- `results/v0.1/ltspice20-{oracle,minimax-m25,minimax-m27}-*.{csv,json}`
- `results/v0.1/openfoam3-{oracle,minimax-m25hs,minimax-m27}-*.json`
- [`LEADERBOARD.md`](./LEADERBOARD.md) — historical and ablation results

## OpenFOAM scope

The 3 OpenFOAM tasks above are the no-token-oracle subset. The full
OpenFOAM catalog has 16 public-runnable tasks; the remaining 13 ship
verifier-defined KPIs but no oracle baseline yet. The default OpenFOAM
release gate ships in v0.2 once `svd-ai-lab/sim-benchmark-base:latest`
is publicly pullable.
