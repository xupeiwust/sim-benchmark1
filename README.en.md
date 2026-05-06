# sim-benchmark

**sim-benchmark** is a benchmark for industrial simulation agents. It asks an LLM agent to build a simulation case, run a real solver, debug failures, extract engineering KPIs, and submit verifiable results.

The goal is not to prove that an internal CLI is useful. The goal is to answer a broader question:

> Can LLM agents complete real industrial simulation tasks, and where do they fail?

中文版：见 [README.md](./README.md)。

## What It Measures

Each task requires the agent to:

- construct a simulation setup from a natural-language engineering request
- invoke the available solver or simulation tool
- recover from solver, convergence, format, or post-processing failures
- extract KPIs from real solver artifacts
- write `/tmp/agent/result.json`

The leaderboard score is based on **real artifacts, KPI accuracy, and source provenance**. Whether the agent used `sim` / sim-cli is diagnostic only; it is not a scoring gate.

## Design Principles

### 1. Real Solvers, No LLM Judge

The verifier is deterministic. It reads files, logs, run records, or post-processing outputs produced by the agent and computes the score directly.

### 2. Strict Provenance, Not Forced Success

Each KPI must include a value and a source:

```json
{
  "value": 1.23,
  "source": {
    "kind": "file_extract",
    "path": "/root/case/output.log",
    "extract": "grep '^kpi:' | awk '{print $2}'"
  }
}
```

The verifier reruns the `extract` command and checks that the declared `value` can be re-derived from the declared source. Bare numbers, fabricated sources, and non-reproducible claims do not score.
Do not hand-write, edit, or fabricate solver logs, `.meas` output, `.raw` data, or run history to satisfy provenance.

Preferred task wording:

> Report only values that can be re-extracted from artifacts you produced. If the simulation fails, report the failure with a verifiable log source.

### 3. Suite Roles

The public suite distinguishes:

- `smoke`: high-leakage or quick environment checks
- `public_eval`: the public leaderboard set
- `hidden_eval`: future private licensed-solver holdout tasks

Classic public cases such as Ghia cavity or textbook RC filters are useful smoke tests; they should not carry the headline benchmark claim.

### 4. Scoring Templates

Cases use a small set of standard scoring templates.

| Template | Use | Groups |
|---|---|---|
| `measurement` | ordinary simulation + KPI measurement | `setup 0.10`, `outputs 0.90` |
| `numerical` | convergence / residual / stability tasks | `setup 0.10`, `numerical 0.15`, `outputs 0.75` |
| `workflow` | GUI / multi-step workflow / artifact export | `setup 0.15`, `process 0.25`, `outputs 0.60` |

Empty groups are invalid: any positive-weight group must have at least one KPI assigned to it.

## Current Domains

See [CASES.md](./CASES.md) for the public case catalog. OpenFOAM and LTspice
cases are public; `oracle_status` separately marks whether a no-token oracle is
available. Missing oracle does not by itself make a task a draft.

### v0.1 MVP Scope

v0.1 publishes 36 public runnable tasks: 20 LTspice circuit tasks and 16
OpenFOAM fluid tasks. The MVP scored gate initially commits to the 20
LTspice oracle-available tasks; the latest local release gate reached `20/20`,
mean `1.000`.

The 16 OpenFOAM tasks remain in the public catalog. Three are marked
oracle-available and 13 are oracle-deferred. The default OpenFOAM release gate
still needs a published or documented `svd-ai-lab/sim-benchmark-base:latest`
base image.

Release-facing results are in [RESULTS.md](./RESULTS.md) and
[`results/v0.1/`](./results/v0.1/).

### Fluids / OpenFOAM

OpenFOAM cases are the transparent CFD proving ground and pipeline shakedown path. They exercise the harness, verifier, artifact provenance, and failure taxonomy.

### Circuits / LTspice

LTspice cases cover SPICE-class circuit simulation, `.meas`, log/source extraction, and Wine/headless batch quirks. Ordinary `.meas` cases use the `measurement` template.

## Quickstart

```bash
uv tool install harbor
docker --version
harbor run -p cases/circuits --agent oracle -i rc_highpass_ac
```

On Windows Docker Desktop, set:

```powershell
$env:DOCKER_HOST='npipe:////./pipe/docker_engine'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

## Repository Layout

```text
sim-benchmark/
├── cases/
│   ├── fluids/       # CFD / OpenFOAM tasks
│   └── circuits/     # SPICE / LTspice tasks
├── configs/          # Harbor run configs
├── docs/             # design notes and appendices
├── environment/      # base Docker images
├── lib/
│   └── sim_benchmark_verifier/
├── tools/            # harness, lint, aggregation, rescore
├── results/          # published v0.1 reference run artifacts
├── SCHEMA.md
└── LEADERBOARD.md
```

## Launch Direction

The public v0 goal is a credible Industrial Simulation Agent leaderboard:

- a small but high-quality OpenFOAM + LTspice public eval set
- deterministic verification
- source-provenance scoring
- failure taxonomy
- cost and wall-time reporting

sim-cli remains useful infrastructure, but it is not the headline variable.

See [RELEASE.md](./RELEASE.md) for the MVP release checklist and latest local
gate results.
