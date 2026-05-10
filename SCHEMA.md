# SCHEMA - sim-benchmark public v0

This file describes the case contract for the public industrial simulation
agent benchmark. It is intentionally solver-neutral: OpenFOAM, LTspice, and
future solver domains use the same Harbor task shape, result contract, and KPI
grader.

## 1. Case Layout

Each case lives at:

```text
cases/<domain>/<case_id>/
├── task.toml
├── instruction.md
├── environment/
│   └── Dockerfile
├── solution/
│   └── solve.sh
└── tests/
    ├── test.sh
    └── kpis.json
```

When `oracle_status = "available"`, `solution/solve.sh` is the oracle entry
point. `tests/test.sh` runs the deterministic verifier and writes Harbor reward
files under `/logs/verifier`. Case-specific helper files are allowed.
`oracle_status = "deferred"` cases may omit `solution/solve.sh` while the
no-token oracle is still being built; this does not by itself make the task a
draft.

## 2. Harbor Task Metadata

All cases use Harbor schema version `1.1`.

```toml
schema_version = "1.1"

[task]
name        = "sim-benchmark/<case-slug>"
description = "One-line task description"
authors     = [{name = "sim-benchmark"}]
keywords    = ["solver", "topic"]

[environment]
docker_image    = "sim-benchmark-wine-base:latest" # or a case-built image
cpus            = 2
memory_gb       = 2
internet_access = true

[agent]
timeout_s      = 1200
execution_user = "root"

[verifier]
timeout_s      = 120
execution_user = "root"

[metadata.sim]
solver          = "neutral" # or openfoam, ltspice, ...
source_type     = "vv_standard"
source_citation = "Human-readable source"
source_url      = "https://example.com"
difficulty_tier = "S"
gt_type         = "high-fidelity-solver"
tags            = ["solver-neutral", "scalar-kpi"]
release_status  = "public_runnable"
oracle_status   = "available"
score_template  = "measurement"
leakage_risk    = 2
capability_target = "postprocess"
```

`docker_image` may point to a shared prebuilt image for fast iteration. Cases
that build their own image must still keep the same agent/verifier/result
contract.

Required fields are enforced by `tools/lint_case.py`.

## 3. KPI Spec

KPI specs live in `tests/kpis.json` and use `schema_version:
"neutral-v0.3"`.

```json
{
  "schema_version": "neutral-v0.3",
  "case_id": "rc_highpass_ac",
  "source": {
    "primary_url": "https://example.com",
    "citation": "Reference or oracle provenance"
  },
  "kpi_groups": {
    "setup": { "weight": 0.10 },
    "outputs": { "weight": 0.90 }
  },
  "kpis": {
    "sim_completed": {
      "group": "setup",
      "shape": "scalar",
      "description": "1 if the solver run completed, else 0",
      "gt_value": 1,
      "T_good": 0.5,
      "T_bad": 0.5,
      "physics_min": 0,
      "physics_max": 1,
      "T_good_source": "Binary flag"
    }
  }
}
```

Rules:

- `kpi_groups` weights must sum to `1.0`.
- Every KPI must reference an existing group.
- Every group with positive weight must contain at least one KPI. Empty groups
  are invalid case schema, not a valid way to reserve future score mass.
- Current verifier support is scalar KPIs only.
- Missing KPIs in `/tmp/agent/result.json` score zero.

## 4. Scoring Templates

Cases should use one of these templates unless a PR explains why a custom
template is necessary.

| Template | Use | Groups |
|---|---|---|
| `measurement` | Ordinary simulation plus KPI measurement | `setup 0.10`, `outputs 0.90` |
| `numerical` | Cases that explicitly evaluate convergence, residuals, or numerical stability | `setup 0.10`, `numerical 0.15`, `outputs 0.75` |
| `workflow` | GUI, export, or multi-step process tasks | `setup 0.15`, `process 0.25`, `outputs 0.60` |

The template is a scoring design choice, not a solver-wide default. Two cases
using the same solver may legitimately use different templates if they test
different failure modes.

## 5. Agent Result Contract

The agent must write `/tmp/agent/result.json`. The canonical shape is:

```json
{
  "gain_hf": {
    "value": -0.000011,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/out.log",
      "extract": "python3 /root/case/extract_gain.py /root/case/out.log"
    }
  }
}
```

Each top-level key must match a KPI in `tests/kpis.json`.

Supported source kinds:

- `file_extract`: rerun an extraction command against a file produced by the
  agent or solver.
- `ltspice_log`: parse a native LTspice `.log` file for completion status,
  scalar `.meas` output, stepped `Measurement:` tables, or stepped parameter
  values. This is the preferred LTspice provenance source because it is
  launcher-neutral.
- `sim_run_stdout`: extract from a recorded sim-cli run stdout.
- `sim_run_kpi`: extract from structured parsed output recorded by sim-cli.

Bare numeric answers are not enough. If the solver fails, the agent may still
report failure-oriented KPIs, but each value must point to a verifiable log or
artifact source.

Do not hand-write, edit, or fabricate solver logs, `.meas` output, `.raw` data,
or run-history records to satisfy provenance. The claimed source must be an
artifact produced by the actual run or by deterministic post-processing of that
run.

## 6. Reward Files

The verifier writes:

```json
// reward.json
{"score": 1.0}
```

`reward.json` has exactly one numeric key because Harbor expects a single
aggregate metric.

The verifier also writes `reward_detail.json` with:

- `schema_version` (currently `reward-v3.2`)
- diagnostic `meta_score` and `meta_detail`
- `kpi_score`
- per-group and per-KPI scoring detail (each per-KPI entry carries
  `solver_stage` + `provenance_stage` + legacy `failure_class` — see below)
- `kpi_detail.solver_stage_counts` and `kpi_detail.provenance_stage_counts`
  — distributions of each axis across the case's KPIs
- `final_score`

### Two-axis failure classification (per-KPI diagnostic layer)

Schema `reward-v3.2` carries two orthogonal axes per KPI, both
deterministic. Inspired by ccl-evaluator's L0–L6 design (see
sim-proj #125 RFC). Each axis answers a different question.

**`provenance_stage`** — solver-agnostic. Did the agent honestly record
what they got?

| Value | Meaning |
|---|---|
| `P0_hallucination` | KPI absent / claim has no source / unknown `source.kind` |
| `P1_path_invalid` | `source.path` missing / not absolute / file doesn't exist |
| `P2_extract_unrunnable` | `source.extract` failed to run (sandbox reject, non-zero exit, timeout) |
| `P3_extract_mismatch` | extract runs fine, extracted value differs from claim |
| `P4_pass` | extract reproduces the claim |
| `spec_error` | case author's `kpis.json` is malformed (not the agent's fault) |

**`solver_stage`** — solver-agnostic axis, solver-specific detector.
How far did the simulation make it? `null` when the verifier doesn't
have enough signal (cascading provenance failure, or detector for that
solver hasn't been written yet).

| Value | Meaning |
|---|---|
| `L0_input_syntax` | input file doesn't parse (per-solver detector) |
| `L1_input_semantics` | input not well-posed / contradicts intent |
| `L2_solver_crash` | solver started then died, or refused to start |
| `L3_convergence` | solver ran but did not converge |
| `L4_conservation` | converged but conservation broken (where applicable) |
| `L5_physics` | value outside `[physics_min, physics_max]` |
| `L5_quantitative` | value matches physics range but `|pred − gt| > T_bad` |
| `L6_pass` | nothing wrong on this axis |

Phase 1 populates `L5_physics` / `L5_quantitative` / `L6_pass` from
data the verifier already has. **Phase 2** (current commit) adds
`L2_solver_crash` attribution from `sim --json logs` records: when
provenance failed AND every sim run on the trial reports failure
(`ok=False` or non-zero exit), we emit `L2_solver_crash`. Records are
now preserved in `meta_detail.records` (previously popped) so the
classifier can run post-hoc on saved `reward_detail.json`.

`L0_input_syntax` / `L1_input_semantics` / `L3_convergence` /
`L4_conservation` still require solver-specific log analysis; those
remain `null` until phases 3–4 (sim-benchmark #4) land.

**Why two axes.** A KPI that passes provenance but fails physics is a
model-capability problem; a KPI that passes physics but fails
provenance is a paperwork / SKILL-prompt problem. Different fixes,
different routing. A flat enum can't represent the cross-product —
`(L6_pass, P3_extract_mismatch)` is the most interesting analytical
cell ("simulated correctly but recorded badly").

**Backward compatibility.** The legacy v3.1 `failure_class` field is
still emitted on each per-KPI entry (mapped from the two-axis values),
so reward-v3.1 readers continue to work. Trial-level classes
(`wall_time`, `turn_cap`, `infra`) are NOT on either axis — they need
the harness transcript, populated post-hoc by an aggregator
(sim-proj #121 follow-up).

The final public score is KPI-only:

```text
final_score = kpi_score
```

sim-cli execution metadata is diagnostic-only. It may help explain how the
agent solved the task, but it must not be required for score eligibility.

## 7. Public Case Classification

All OpenFOAM and LTspice cases may be public, but they must be classified so
readers can separate runnable leaderboard tasks from draft task definitions and
high-leakage classics.

Classification fields live in `[metadata.sim]`.

| Field | Allowed values | Meaning |
|---|---|---|
| `release_status` | `public_runnable`, `public_draft`, `hidden_eval` | Whether the task/verifier is public and leaderboard-runnable now |
| `oracle_status` | `available`, `deferred`, `not_applicable` | Whether a no-token oracle solution is present |
| `score_template` | `measurement`, `numerical`, `workflow` | Which standard KPI group template the case uses |
| `leakage_risk` | integer `0..3` | 0 = novel/low leakage, 3 = very classic/high leakage |
| `capability_target` | `setup`, `solver_execution`, `numerical`, `postprocess`, `debugging`, `physics` | Primary capability the case is meant to stress |

Recommended interpretation:

- `public_runnable`: has task/verifier assets and can be included in the
  public leaderboard.
- `public_draft`: task definition is public, but it lacks enough runnable
  assets for the main leaderboard.
- `hidden_eval`: reserved for future private, license-gated commercial solver
  cases.

`oracle_status` is separate from `release_status`. A case can be a runnable
public benchmark task with a deterministic verifier even when its no-token
oracle is still deferred.

The public catalog is `CASES.md`. It should list every public case, including
drafts, instead of silently hiding unfinished tasks.

## 8. Lint and Verification

Useful local checks:

```bash
python tools/lint_case.py cases/ltspice/circuits/rc_highpass_ac
python tools/v19_static_validate.py
python -m pytest lib/sim_benchmark_verifier/tests
harbor run -p cases/ltspice/circuits --agent oracle -i rc_highpass_ac
```

On Windows with Docker Desktop, set:

```powershell
$env:DOCKER_HOST='npipe:////./pipe/docker_engine'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```
