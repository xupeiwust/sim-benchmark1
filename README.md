# sim-benchmark

> **An industrial simulation agent benchmark.** Hand an LLM agent a real
> CAE/EDA task — meshing, boundary conditions, solver invocation, log parsing,
> KPI extraction — and grade what it actually produced. No LLM-as-judge; the
> verifier re-runs the agent's claimed extraction commands against the
> agent's produced solver artifacts.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tasks](https://img.shields.io/badge/v0.1-36%20public%20tasks-success)](CASES.md)
[![Solvers](https://img.shields.io/badge/solvers-OpenFOAM%20%7C%20LTspice-informational)]()

中文版 → [`README.zh.md`](README.zh.md)

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

## v0.1 release scope

| Domain | Tasks | Oracle available | Backing solver |
|---|---:|---:|---|
| Circuits / SPICE | 20 | 20 | LTspice (free, open-format) |
| Fluids / CFD | 16 | 3 | OpenFOAM (open source) |
| **Total** | **36** | **23** | |

The MVP scored gate is the 20 LTspice tasks. They run on Linux via Wine,
with a deterministic oracle baseline at **mean reward = 1.000**. The 16
OpenFOAM tasks ship as public catalog members; only 3 have no-token oracle
solutions today (the other 13 are public, verifier-defined, and runnable
against any model — but the no-token baseline is deferred to v0.2).

Future commercial-solver cases (Ansys Mechanical / Abaqus / Flotherm /
Fluent) will live in `release_status: hidden_eval`, evaluated only when an
authorised licensed-solver run is requested. They are **not in this
public release**.

See [`CASES.md`](CASES.md) for the full catalog with leakage, tier, and
oracle-status flags per case. See [`SCHEMA.md`](SCHEMA.md) for the case /
verifier contract.

## Day-one results (reference run)

Every task ships with a deterministic `solution/solve.sh` (the *oracle*).
Running the oracle produces the maximum reachable score under the current
verifier; any model's score is read against this upper bound.

**LTspice circuits (20 tasks)**

| Run | Agent / Model | Tasks | Errors | **Mean** |
|---|---|---:|---:|---:|
| oracle (deterministic) | — | 20/20 | 0 | **1.000** |
| **MiniMax-M2.5-highspeed** (non-reasoning) | claude-code | 20/20 | 1 | **0.936** |
| **MiniMax-M2.7** (reasoning) | claude-code | 19/20 | 2 | **0.930** |

**OpenFOAM fluids (3 oracle-available tasks)**

| Run | Agent / Model | Tasks | Errors | **Mean** |
|---|---|---:|---:|---:|
| oracle (deterministic) | — | 3/3 | 0 | **0.999** |
| **MiniMax-M2.5-highspeed** | claude-code | 3/3 | 1 | **0.408** |
| **MiniMax-M2.7** | claude-code | 3/3 | 0 | **0.284** |

**v0.1 read.** On LTspice, **M2.5-highspeed and M2.7 are within ~0.6 %** (0.936 vs
0.930) — reasoning gives no measurable LTspice headroom over fast non-reasoning, at
~10 × the per-turn latency. Both models bottom out on the upgraded design tasks
(`bridge_rectifier_ripple`, `rc_lowpass_ac`, `rlc_notch`, `lc_lowpass_2nd`) where the
model has to sweep a parameter and choose by spec rather than just measure.

**OpenFOAM is harder** for both: the agent has to write blockMeshDict, system/, 0/,
constant/ from scratch, run blockMesh + simpleFoam + checkMesh + postProcess, and
parse multi-format logs. M2.7's `cavity_re100 = 0.0` is **not a physics failure** —
it solved the cavity correctly (u_centerline within 2 % of Ghia 1982 GT) but wrote
extract pipelines using relative paths that the verifier cannot replay. v0.1's new
Pass-2 Stop hook ([`docs/hooks.md`](docs/hooks.md)) catches this paperwork failure
mode in future runs. v0.2 will revisit OpenFOAM with that hook in place.

Per-case scores and machine-readable artifacts live in
[`results/v0.1/`](results/v0.1/). [`LEADERBOARD.md`](LEADERBOARD.md) tracks
historical and ablation results.

## Why three audiences should care

### For AI / agent companies

We give you a hard, reproducible, end-to-end task suite where the only
thing that scores is **what the model actually produced**, not whether it
described the right answer in chat. Every task is a real solver run with
artifact-grounded grading: the model writes a netlist, runs LTspice,
parses the `.log`, and submits the parse command alongside the value. We
re-run the parse. If your `value` and our re-extraction disagree, you score
zero on that KPI.

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
- contribute commercial-solver tasks (we keep them in `hidden_eval` and
  evaluate them only when you authorise a licensed run);
- benchmark internal solver wrappers / Python APIs against the same task
  suite the open community runs.

The contract is in [`SCHEMA.md`](SCHEMA.md). Cases proposed via PR are
reviewed for verifiability — see [`cases/circuits/README.md`](cases/circuits/README.md)
and [`cases/fluids/README.md`](cases/fluids/README.md) for tier / leakage
norms.

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

## Quick start (5 minutes, no LLM)

```bash
# 1. install harbor (the runner — same one Terminal-Bench uses)
uv tool install harbor

# 2. clone
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark

# 3. oracle smoke on one circuit (no LLM, no API key)
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y

# 4. oracle smoke on a CFD case (also no LLM, requires the OpenFOAM base
#    image to build locally — see REPRODUCING.md Path B)
harbor run -p cases/fluids -i lid_driven_cavity_re100 --agent oracle -y
```

Both should print `reward: 1.000`. If you see anything else, the bug is
in your environment, not in the agent.

## How scoring works in 60 seconds

Every case is verified against a `tests/kpis.json` that lists named KPIs
and how to measure them. The agent submits:

```json
{
  "kpis": {
    "f_3db": {
      "value": 175.6,
      "source": {
        "kind": "ltspice_log",
        "path": "rc_lowpass.log",
        "extract": "section=measure name=f_3db"
      }
    }
  }
}
```

The verifier opens `rc_lowpass.log`, runs the declared extraction, gets
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
│   ├── circuits/          # 20 LTspice tasks
│   └── fluids/            # 16 OpenFOAM tasks
├── configs/               # release run configs (oracle, M2.7, M2.5)
├── docs/                  # design appendices
├── environment/
│   ├── base/              # OpenFOAM base image
│   └── wine-base/         # LTspice-on-Wine image
├── lib/
│   └── sim_benchmark_verifier/   # the grader (Python)
├── tools/                 # harness, lint, aggregation, scoring helpers
├── results/v0.1/          # published reference-run artifacts
├── CASES.md               # public catalog with status / leakage / tier
├── LEADERBOARD.md         # historical & ablation results
├── ORACLE.md              # oracle baseline + verifier sanity checks
├── RELEASE.md             # v0.1 release gate
├── REPRODUCING.md         # three reproduction paths
└── SCHEMA.md              # case + verifier contract
```

## Roadmap

- **v0.1 (current)** — 36 public tasks, deterministic verifier, 20 LTspice
  oracle gate at 1.000, day-one MiniMax reference rows.
- **v0.2** — publish OpenFOAM base image; add 13 OpenFOAM no-token
  oracles; harden Docker Hub package distribution.
- **v0.3** — second commercial-solver track in `hidden_eval` (Mechanical
  or Abaqus, evaluated under licensed-run authorisation).
- **v1.0** — stable schema, public leaderboard, multi-org submission flow.

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

For the Reasoning behind the launch positioning (problem-first, not
tool-first), see [PR #2 on the internal repo](https://github.com/svd-ai-lab/sim-benchmark-internal/pull/2).

## Citing

```bibtex
@misc{simbenchmark2026,
  title  = {sim-benchmark: An Industrial Simulation Agent Benchmark},
  author = {{svd-ai-lab}},
  year   = {2026},
  url    = {https://github.com/svd-ai-lab/sim-benchmark},
  note   = {v0.1}
}
```

## License

Apache 2.0. See [`LICENSE`](LICENSE).

The repo bundles example assets (LTspice netlists, OpenFOAM mesh files)
that are themselves under their respective upstream licenses; see each
case's `solution/` directory for source attribution.
