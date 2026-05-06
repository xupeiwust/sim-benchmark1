# Results

The release-facing v0.1 MVP results live in
[`results/v0.1/`](./results/v0.1/).

v0.1 is a benchmark release first. The public catalog contains 36 runnable
tasks: 20 LTspice circuit tasks and 16 OpenFOAM fluid tasks. The MVP scored
gate is the 20-task LTspice suite.

| Run | Scope | Completed | Mean score | Status |
|---|---|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | LTspice 20 oracle gate | 20/20 | 1.000 | passed |
| `release-v0.1-openfoam3-oracle-20260503` | OpenFOAM 3 oracle attempt | 0/3 | n/a | base image unavailable |

Machine-readable artifacts:

- [`results/v0.1/summary.json`](./results/v0.1/summary.json)
- [`results/v0.1/ltspice20-oracle-20260503.csv`](./results/v0.1/ltspice20-oracle-20260503.csv)
- [`results/v0.1/ltspice20-oracle-20260503.json`](./results/v0.1/ltspice20-oracle-20260503.json)

OpenFOAM remains part of the public benchmark catalog. Its default oracle gate
is deferred until `svd-ai-lab/sim-benchmark-base:latest` is published or
documented for local builds.
