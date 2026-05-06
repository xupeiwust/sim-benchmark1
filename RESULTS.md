# Results

The release-facing v0.1 MVP results live in
[`results/v0.1/`](./results/v0.1/).

v0.1 is a benchmark release first. The public catalog contains 36 runnable
tasks: 20 LTspice circuit tasks and 16 OpenFOAM fluid tasks. The MVP scored
gate is the 20-task LTspice suite.

## v0.1 Reference Runs (LTspice 20-task gate)

| Run | Agent / Model | Tasks | Errors | Mean | Status |
|---|---|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20 | 0 | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-minimax-m25-20260506` | claude-code · MiniMax-M2.5-highspeed | 20 | 1 | **0.936** | non-reasoning |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · MiniMax-M2.7 | 20 | 3 | **0.776** | reasoning |

Read this as: the oracle row is what the verifier scores when `solve.sh`
ships the right answer; any model row reads against that ceiling. Per-case
breakdown in [`results/v0.1/README.md`](./results/v0.1/README.md).

## Machine-readable artifacts

- [`results/v0.1/summary.json`](./results/v0.1/summary.json) — release summary
- `results/v0.1/ltspice20-{oracle,minimax-m25,minimax-m27}-*.{csv,json}` — per-case scores
- [`LEADERBOARD.md`](./LEADERBOARD.md) — historical and ablation results

## OpenFOAM status

OpenFOAM cases remain part of the public benchmark catalog (16 public
tasks, 3 with no-token oracles, 13 with verifier-defined KPIs but no
oracle baseline yet). The default OpenFOAM oracle gate is deferred until
`svd-ai-lab/sim-benchmark-base:latest` is published or documented for
local builds. **No model run against OpenFOAM is included in v0.1**;
that ships in v0.2.
