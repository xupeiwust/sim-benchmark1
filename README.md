<div align="center">

<img src="assets/banner.svg" alt="sim-benchmark — industrial simulation agent benchmark" width="820">

<br>

**Hand a real CAE/EDA task to an LLM agent. Score what it produced.**

*No LLM-as-judge. The verifier replays the agent's own extraction commands*
*against the agent's own solver artifacts.*

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-2_min-3b82f6?style=for-the-badge" alt="Quick Start"></a>
  <a href="CASES.md"><img src="https://img.shields.io/badge/v0.1-23_oracle--verified_tasks-22c55e?style=for-the-badge" alt="23 tasks"></a>
  <a href="#-reference-runs"><img src="https://img.shields.io/badge/Reference_runs-MiniMax_M2.5hs_%E2%80%A2_M2.7-8b5cf6?style=for-the-badge" alt="MiniMax reference"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/runner-Harbor-009688" alt="Harbor">
  <img src="https://img.shields.io/badge/circuits-LTspice-blue" alt="LTspice">
  <img src="https://img.shields.io/badge/CFD-OpenFOAM-orange" alt="OpenFOAM">
  <img src="https://img.shields.io/badge/scoring-source--provenance-7c3aed" alt="Source provenance">
  <img src="https://img.shields.io/badge/status-v0.1-f97316" alt="Status: v0.1">
</p>

[Why](#-why-this-benchmark) · [Quick Start](#-quick-start) · [Reference runs](#-reference-runs) · [How scoring works](#-how-scoring-works) · [Layout](#-repository-layout) · [Contributing](#-contributing)

</div>

---

## 🤔 Why this benchmark?

LLM agents already know how to write simulation scripts — training data is full
of them. What no benchmark measured cleanly was whether they can **drive a
real solver, parse its real output, and submit results that survive an
independent replay**.

Today, the choices for "can this agent do CAE?" are awful:

- **Pass-through QA** — model paraphrases a Wikipedia article on Reynolds
  number; nothing was simulated.
- **LLM-as-judge** — the grader is itself an LLM with the same blind spots.
- **Synthetic toy tasks** — agent solves a problem that looks like CAE but
  bypasses every real industrial pain point (units, file formats, log parsing,
  convergence diagnostics).

`sim-benchmark` measures the workflow itself. Each task hands the agent a
container with a real solver installed and asks for `/tmp/agent/result.json`
where every KPI is paired with a `source.kind / source.path / source.extract`
provenance triple. The verifier re-runs every `extract` against the agent's
produced artifacts and compares. Hand-written numbers, fabricated logs, and
unreproducible KPIs score zero.

> Tooling is implementation, not the thing being benchmarked. `sim-cli`,
> native solver CLIs, Python wrappers, or the agent's own scratch scripts are
> all valid launch routes.

---

## 🧭 v0.1 release scope

| Domain | Public tasks | Oracle | Backing solver |
|---|---:|---:|---|
| Circuits / SPICE | 20 | 20 | LTspice (free, open-format) |
| Fluids / CFD | 3 | 3 | OpenFOAM (open source) |
| **Total** | **23** | **23** | |

Every v0.1 task ships with a deterministic `solution/solve.sh` oracle that
exercises the full pipeline without an LLM. That gives the verifier's
upper-bound sanity check; model rows are read against that ceiling.

Future commercial-solver cases (Mechanical / Abaqus / Flotherm / Fluent) live
in `release_status: hidden_eval`, evaluated only when an authorised
licensed-solver run is requested. **They are not in this public release.**

See [`CASES.md`](CASES.md) for the full catalog with leakage, tier, and
oracle-status flags. See [`SCHEMA.md`](SCHEMA.md) for the case / verifier
contract.

---

## 🚀 Quick Start

```bash
# 1. Install Harbor — the same runner Terminal-Bench uses
uv tool install harbor

# 2. Clone
git clone https://github.com/svd-ai-lab/sim-benchmark
cd sim-benchmark

# 3. Run the oracle on one circuit (no LLM, no API key)
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y
# → reward: 1.000, ~1 min on Docker Desktop.

# 4. Run a model — same command, swap --agent
harbor run -c configs/release-v0.1-ltspice20-minimax-m25.yaml -y
```

If step 3 prints `reward: 1.000`, your environment is sound and any model run
you do is apples-to-apples comparable to ours. If it doesn't, the bug is
in your environment, not in the agent.

For local builds without GHCR, see [`REPRODUCING.md`](REPRODUCING.md).

---

## 📊 Reference runs

| Suite | Reference models | Read |
|---|---|---|
| **LTspice circuits** | MiniMax-M2.5-highspeed and MiniMax-M2.7 both land around **0.9** | Strong agents already complete many artifact-grounded circuit workflows. Parameter-sweep and design-selection tasks still discriminate. |
| **OpenFOAM fluids** | Both MiniMax runs are below **0.5** on the oracle-available CFD subset | CFD remains much harder: agents must author case files, mesh, run solvers, post-process fields, and produce replayable KPI provenance. |

These are reference rows, not a mature cross-model leaderboard. Exact scores,
completion policy, per-case artifacts, and superseded-run notes live in
[`LEADERBOARD.md`](LEADERBOARD.md) and [`results/v0.1/`](results/v0.1/).

The useful early signal is workflow-shaped: source-provenance grading
separates agents that can talk about simulation from agents that can produce
solver artifacts that survive replay.

---

## 🔬 How scoring works

Every case has a `tests/kpis.json` that names KPIs and tolerances. The agent
submits one `result.json`:

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

The verifier opens the file at `path`, replays the declared extraction, gets
the actual measured value, and compares against ground truth within the
case's `T_good` / `T_bad` tolerances. Three scoring templates cover all v0.1
tasks:

| Template | Group weights | Used for |
|---|---|---|
| `measurement` | setup 0.10 / outputs 0.90 | "Measure this circuit" |
| `numerical` | setup 0.10 / numerical 0.15 / outputs 0.75 | "This CFD case must converge" |
| `workflow` | setup 0.15 / process 0.25 / outputs 0.60 | Multi-step GUI / artifact tasks |

In-trial validation runs through two Stop-hook passes inside the agent
container — schema (KPI shape, allowed binaries, run_id history) and
runnability (replay each `file_extract` against its declared path, report
empty-vs-non-empty without leaking the value). Details:
[`docs/hooks.md`](docs/hooks.md). The full contract:
[`SCHEMA.md`](SCHEMA.md).

---

## ✨ Features

### 🧠 Built for agents, not for chat

- **Source-provenance scoring** — every KPI has a replayable `extract`
  pipeline; bare numbers score zero.
- **Two in-trial Stop-hook passes** catch malformed JSON / disallowed
  extractor binaries / empty extracts before the agent commits.
- **Oracle baseline** every task; you always know the verifier's ceiling.

### 🔌 Solver-real, harness-light

- **Real solvers, not mocks** — LTspice runs through Wine, OpenFOAM v2412
  runs natively, both shipped as ready-to-pull base images.
- **Harness-agnostic agent contract** — claude-code, custom Python, even a
  bare Bash script all qualify; only `result.json` is graded.
- **Harbor runner** — the same task / job protocol as
  [Terminal-Bench](https://www.tbench.ai/), so existing tooling slots in.

### 🎯 Designed to discriminate

- **Three scoring templates** match the case shape (measurement / numerical
  / workflow) instead of one-size-fits-all.
- **Leakage-1 design tasks** (sweep + select) keep textbook-memorisation
  from carrying low-tier scores.
- **Mesh-quality KPIs alongside resolution** for boundary-layer cases — y+
  matters more than cell count when wall friction is the question.

---

## 🏛 Repository layout

```text
sim-benchmark/
├── cases/
│   ├── circuits/          # 20 LTspice tasks
│   └── fluids/            # 3 OpenFOAM tasks
├── configs/               # Reference run configs (oracle, M2.5-hs, M2.7)
├── docs/                  # Design notes, hooks contract
├── environment/
│   ├── base/              # OpenFOAM v2412 base image
│   └── wine-base/         # LTspice-on-Wine base image
├── lib/
│   └── sim_benchmark_verifier/   # Grader (Python)
├── tools/                 # Harness, lint, scoring helpers
├── results/v0.1/          # Published reference-run artifacts
├── CASES.md               # Public catalog + leakage / tier
├── LEADERBOARD.md         # Reference rows + history
├── ORACLE.md              # Oracle baseline + verifier sanity
├── RELEASE.md             # v0.1 release gate
├── REPRODUCING.md         # Three reproduction paths
└── SCHEMA.md              # Case + verifier contract
```

---

## 🗺️ Roadmap

- **v0.1 (current)** — 23 oracle-verified tasks (20 LTspice + 3 OpenFOAM),
  Pass-1 + Pass-2 Stop hook, reasoning-content-safe routing, MiniMax
  reference runs.
- **v0.2** — expand OpenFOAM scope (turbulent boundary layer, transonic
  airfoil, multiphase, separated flows) once their oracles are written.
- **v0.3** — second commercial-solver track in `hidden_eval`
  (Mechanical or Abaqus, evaluated under licensed-run authorisation).
- **v1.0** — stable schema, public leaderboard, multi-org submission flow.

Open work tracked at [GitHub Issues](https://github.com/svd-ai-lab/sim-benchmark/issues).

---

## 🤝 Contributing

Two common contributions:

- **A new case.** Use [`tools/new_circuit_case.py`](tools/new_circuit_case.py)
  for circuits or copy an existing fluids case as a template. Run
  [`tools/lint_case.py`](tools/lint_case.py) and the verifier tests before
  opening a PR. See [`SCHEMA.md`](SCHEMA.md) §9 for the full contract.
- **A new agent harness.** A new `agent_harness.py:Agent` subclass; bring
  your own routing layer. The existing claude-code + ccr pattern is in
  [`tools/agent_harness.py`](tools/agent_harness.py).

For the launch positioning (problem-first, not tool-first) see
[the upstream PR](https://github.com/svd-ai-lab/sim-benchmark-internal/pull/2).

---

## 📚 Citing

```bibtex
@misc{simbenchmark2026,
  title  = {sim-benchmark: An Industrial Simulation Agent Benchmark},
  author = {{svd-ai-lab}},
  year   = {2026},
  url    = {https://github.com/svd-ai-lab/sim-benchmark},
  note   = {v0.1 — 23 oracle-verified tasks across LTspice + OpenFOAM}
}
```

---

## 📄 License

Apache-2.0 — see [`LICENSE`](LICENSE).

The repo bundles example assets (LTspice netlists, OpenFOAM mesh files) under
their respective upstream licenses; see each case's `solution/` directory for
source attribution.

### Trademarks

`sim-benchmark` is an independent open-source project and is **not affiliated
with, endorsed by, or sponsored by** any solver vendor. Product, solver, and
company names referenced anywhere in this repository remain the property of
their respective owners:

- **OpenFOAM®** is a registered trademark of **OpenCFD Ltd.**
- **LTspice®** is a registered trademark of **Analog Devices, Inc.**
- All other solver and product names are trademarks of their respective owners.
