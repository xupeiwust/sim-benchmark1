<div align="center">

<img src="assets/banner.svg" alt="sim-benchmark — industrial simulation agent benchmark" width="820">

<br>

> **An industrial simulation agent benchmark.** Hand an LLM agent a real
> CAE/EDA task — meshing, boundary conditions, solver invocation, log parsing,
> KPI extraction — and grade what it actually produced. No LLM-as-judge; the
> verifier re-runs the agent's claimed extraction commands against the
> agent's produced solver artifacts.

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick_Start-2_min-3b82f6?style=for-the-badge" alt="Quick Start"></a>
  <a href="#first-reference-runs"><img src="https://img.shields.io/badge/Reference_runs-Claude_Opus_4.6_%E2%80%A2_MiniMax_M2.5hs_%E2%80%A2_M2.7-8b5cf6?style=for-the-badge" alt="Reference models"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/runner-Harbor-009688" alt="Harbor">
  <img src="https://img.shields.io/badge/circuits-LTspice-blue" alt="LTspice">
  <img src="https://img.shields.io/badge/CFD-OpenFOAM-orange" alt="OpenFOAM">
  <img src="https://img.shields.io/badge/scoring-source--provenance-7c3aed" alt="Source provenance">
</p>

[What this measures](#what-this-measures) · [Scope](#scope) · [Reference runs](#first-reference-runs) · [Quick start](#quick-start) · [Scoring](#how-scoring-works-in-60-seconds) · [Layout](#repository-layout)

</div>

---

## What this measures

Every task hands the agent a natural-language problem statement, a working
container with a real solver installed, and one rule: produce
`/tmp/agent/result.json` whose KPIs come with **source provenance** —
`(value, source.kind, source.path, source.extract)`. The verifier re-runs
each `source.extract` command against the file the agent named and confirms
the value. Hand-written numbers, fabricated logs, and unreproducible KPIs
score zero.

**Out of scope (deliberately).** This is not a knowledge quiz, not a
syntax-of-Fluent test, not an LLM-as-judge tournament. It does not require
the agent to use any specific tool or library — `sim-cli`, native solver
CLIs, Python wrappers, or the agent's own scratch scripts are all valid
launch routes. Tooling is implementation, not the thing being benchmarked.

## Scope

| Domain | Tasks | Backing solver |
|---|---:|---|
| Circuits / SPICE | 20 | LTspice (free, open-format) |
| Fluids / CFD | 11 | OpenFOAM (open source) |

Every task has a deterministic `solution/solve.sh` oracle that produces
the verifier's upper-bound sanity check. Coverage will keep growing on the
OpenFOAM side (more turbulent boundary layers, transonic airfoils, separated
flows) as new oracles are written and validated.

See [`CASES.md`](CASES.md) for the full catalog with leakage, tier, and
oracle-status flags per case. See [`SCHEMA.md`](SCHEMA.md) for the case /
verifier contract.

## First reference runs

Every task ships with a deterministic `solution/solve.sh` oracle. Running
the oracle gives the verifier's upper-bound sanity check; model rows are
read against that ceiling.

We include first reference runs with Claude Opus 4.6, MiniMax-M2.5-highspeed,
MiniMax-M2.7-highspeed, and MiniMax-M2.7 through a claude-code harness.

| Suite | Tasks | Claude Opus 4.6 | MiniMax-M2.7-highspeed | MiniMax-M2.5-highspeed | MiniMax-M2.7 | Oracle ceiling |
|---|---:|---:|---:|---:|---:|---:|
| LTspice circuits | 20 | **0.986** | **0.899** | **0.899** | **0.838** | 1.000 |
| OpenFOAM fluids | 11 | **0.918** | **0.804** | **0.706** | **0.675** | n/a* |

\* OpenFOAM oracle reference run not yet produced; oracles are calibrated and `solution/solve.sh` is in repo.

Reads:
- **LTspice**: all four agents complete most artifact-grounded circuit
  workflows. Opus 4.6 is at 19/20 perfect (only `opamp_integrator` at 0.72);
  the MiniMax pair leave more headroom and parameter-sweep / design-selection
  tasks still discriminate between them.
- **OpenFOAM**: CFD is the harder suite — agents must author case files,
  mesh, run solvers, post-process fields, and produce replayable KPI provenance.
  The 11-case set covers Bénard convection, dam-break multiphase, DNS
  turbulence, oblique shock, non-Newtonian flow, pitzdaily, and lid-driven
  cavities at Re=100/400/1000. Opus opens a clear ~11-point gap;
  M2.7-highspeed is the strongest MiniMax variant on this suite;
  the reasoning M2.7 underperforms its highspeed sibling on CFD;
  `pitzdaily-bfs-rans` is a model watershed (Opus 0.978 vs M2.7 0.000).

These are reference runs, not a mature cross-model leaderboard. Per-case
scores, completion policy, and harness-exception accounting live in
[`LEADERBOARD.md`](LEADERBOARD.md) and the per-run records under
[`results/`](results/).

The useful early signal is workflow-shaped: artifact-grounded grading
separates agents that can talk about simulation from agents that can produce
solver artifacts that survive replay.

## Why three audiences should care

### For AI / agent companies

A hard, reproducible, end-to-end task suite where the only thing that scores
is **what the model actually produced**, not whether it described the right
answer in chat. Every task is a real solver run with artifact-grounded
grading: the model writes a netlist, runs LTspice, parses the `.log`, and
submits the parse command alongside the value. We re-run the parse. If your
`value` and our re-extraction disagree, you score zero on that KPI.

This gives a clean, commercially-relevant signal that:
- separates models that "know about" vs models that "can complete"
  industrial workflows;
- breaks down by task tier (S/M/L), leakage class, and template
  (measurement / numerical / workflow);
- runs locally with `harbor` + Docker — no submission portal, no API key
  for us, no rate-limited grader.

To publish a leaderboard row, see [`REPRODUCING.md`](REPRODUCING.md). To
see what the harness does on each trial, see [`docs/hooks.md`](docs/hooks.md).

### For CAE / EDA software vendors

Industrial CAE has been "the agent layer is too brittle" for a decade.
This benchmark turns that into a measurable signal — over real cases,
real solver artifacts, real numerical-vs-physical pass criteria — and
makes it possible to talk concretely about *which* parts of the agent loop
fail on *which* solvers.

You can use this to:
- evaluate whether AI agents can drive your solver well enough for
  customer-facing automation;
- benchmark internal solver wrappers / Python APIs against the same task
  suite the open community runs;
- propose new cases via PR — see [`cases/circuits/README.md`](cases/circuits/README.md)
  and [`cases/fluids/README.md`](cases/fluids/README.md) for tier / leakage
  norms.

The contract is in [`SCHEMA.md`](SCHEMA.md).

### For CAE practitioners

If you've been asked "should we put an LLM in front of our solver
workflow", this is a yardstick. Run the oracle smoke (no LLM, free):

```bash
uv tool install harbor
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y
# Expect: reward = 1.000, wall-clock ~1 min on Docker Desktop.
```

If that returns 1.0, your environment is sound and any model run you do
will be apples-to-apples comparable to ours. Then run a model — the same
command with `--agent claude-code` (or your wrapper) replacing
`--agent oracle`. See [`REPRODUCING.md`](REPRODUCING.md) for the three
reproduction paths (GHCR pull / build from source / paranoid).

## Quick start

```bash
# 1. install harbor (the runner — same one Terminal-Bench uses)
uv tool install harbor

# 2. clone
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark

# 3. oracle smoke on one circuit (no LLM, no API key)
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y

# 4. oracle smoke on a CFD case (also no LLM; needs the OpenFOAM base
#    image — see REPRODUCING.md Path B for local builds)
harbor run -p cases/fluids -i lid_driven_cavity_re100 --agent oracle -y
```

Both should print `reward: 1.000`. If you see anything else, the bug is
in your environment, not in the agent.

## How scoring works in 60 seconds

Every case is verified against a `tests/kpis.json` that lists named KPIs
and how to measure them. The agent submits:

```json
{
  "f_3db": {
    "value": 175.6,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/rc_lowpass.log",
      "query": "measure",
      "measurement": "f_3db"
    }
  }
}
```

The verifier opens the file at `path`, runs the declared extraction, gets
the actual measured value, and compares against ground truth (within the
tolerance `tests/kpis.json` declares). Scoring templates per task type:

| Template | Groups | Used for |
|---|---|---|
| `measurement` | setup 0.10 / outputs 0.90 | "measure this circuit" |
| `numerical` | setup 0.10 / numerical 0.15 / outputs 0.75 | "this CFD case must converge" |
| `workflow` | setup 0.15 / process 0.25 / outputs 0.60 | multi-step GUI / artifact tasks |

Total per case is a weighted sum of the per-group means. See
[`SCHEMA.md`](SCHEMA.md) for the formal contract.

## Repository layout

```text
sim-benchmark/
├── cases/
│   ├── circuits/          # LTspice tasks
│   └── fluids/            # OpenFOAM tasks
├── configs/               # release run configs (oracle, M2.7, M2.5)
├── docs/                  # design appendices
├── environment/
│   ├── base/              # OpenFOAM base image
│   └── wine-base/         # LTspice-on-Wine image
├── lib/
│   └── sim_benchmark_verifier/   # the grader (Python)
├── tools/                 # harness, lint, aggregation, scoring helpers
├── results/               # per-run record artifacts
├── CASES.md               # public catalog with status / leakage / tier
├── LEADERBOARD.md         # current and historical results
├── ORACLE.md              # oracle baseline + verifier sanity checks
├── RELEASE.md             # release gate
├── REPRODUCING.md         # three reproduction paths
└── SCHEMA.md              # case + verifier contract
```

## Roadmap

- **Now** — deterministic verifier, in-trial Stop hook with schema and
  extract-runnability passes, four reference model rows.
- **Next** — broader OpenFOAM coverage (transonic airfoil, more separated
  flows, more multiphase), harden Docker Hub package distribution.
- **Later** — stable schema, public leaderboard, multi-org submission flow.

Track open work on [GitHub Issues](https://github.com/svd-ai-lab/sim-benchmark/issues).

## Contributing

PRs welcome. Two common contributions:

- **A new case.** Use [`tools/new_circuit_case.py`](tools/new_circuit_case.py)
  for circuits or copy an existing fluids case as a template. Run
  [`tools/lint_case.py`](tools/lint_case.py) and the verifier tests
  before opening a PR. See [`SCHEMA.md`](SCHEMA.md) §9.
- **A model harness.** New `agent_harness.py:Agent` subclass; bring your
  own routing layer. See [`tools/agent_harness.py`](tools/agent_harness.py)
  for the existing CC + ccr pattern.

## Citing

```bibtex
@misc{simbenchmark2026,
  title  = {sim-benchmark: An Industrial Simulation Agent Benchmark},
  author = {{svd-ai-lab}},
  year   = {2026},
  url    = {https://github.com/svd-ai-lab/sim-benchmark}
}
```

## License

Apache 2.0. See [`LICENSE`](LICENSE).

The repo bundles example assets (LTspice netlists, OpenFOAM mesh files)
that are themselves under their respective upstream licenses; see each
case's `solution/` directory for source attribution.
