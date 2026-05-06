# cases/fluids/

Fluid-mechanics cases (CFD, flow). The first domain shipped under
sim-benchmark and the source of the v10–v13 leaderboard data.

All cases here are **solver-neutral by construction** — the agent is
given pure physics and must discover what tools are available, pick one,
and drive it through sim-cli end-to-end. (See "Design principles" below;
that property is shared with `cases/circuits/` and any future domain.)

## Design principles

A case under `cases/fluids/` MUST satisfy all three:

### 1. Pure physics, zero solver hint

`instruction.md` describes only:

- Geometry (coordinate frame, length scales, dimensionality)
- Flow / loading conditions (Re, density, viscosity, temperature, etc.)
- Boundary conditions (every face accounted for)
- Physical meaning of each KPI

It does **not** name a solver, mesher, turbulence model, or numerical
scheme. The agent picks via `sim --json check`.

### 2. Forced through sim-cli + auto-registered skills

The image installs `sim-cli` and the agent harness symlinks
`~/.claude/skills/sim-cli` (mandatory) plus `~/.claude/skills/<solver>`
for each ok solver from `sim --json check`. Claude Code discovers them as
native skills at startup.

The verifier rejects any KPI whose `value` doesn't re-extract from the
declared `source`. KPIs declared with `kind: "sim_run_*"` need a
matching record in `sim --json logs`; KPIs declared with `kind:
"file_extract"` just need the file to exist and the pipeline to return
the claimed number. Agents in containers without sim-cli (see the
v19 with-sim/without-sim study) must use `file_extract` exclusively.

### 3. KPIs with provenance

Each KPI in `result.json` carries `value` + `source` (file_extract /
sim_run_stdout / sim_run_kpi). The verifier re-runs the agent's `extract`
pipeline against the source file and rejects numbers that don't match
within 1%. Anti-hallucination by construction.

## How to add a new fluids case

```
cases/fluids/<case_id>/
├── instruction.md          # physics-only prompt; copy cases/_template/
├── task.toml               # Harbor schema_version = "1.1" + [metadata.sim]
├── environment/
│   └── Dockerfile          # FROM svd-ai-lab/sim-benchmark-base:latest
├── solution/
│   └── solve.sh            # oracle entry — required (proves case is solvable)
└── tests/
    ├── test.sh             # one-liner: exec python3 -m sim_benchmark_verifier.score
    └── kpis.json           # per-KPI {gt_value, T_good, T_bad, physics_min, ...}
```

`task.toml` must declare:

```toml
[metadata.sim]
solver          = "neutral"        # property: agent self-selects (not a folder name)
source_type     = "vv_standard"    # paper | vv_standard | novel_variant
source_citation = "..."            # what produced gt_value
source_url      = "..."
difficulty_tier = "S"              # S | M | H
```

Then `python tools/lint_case.py cases/fluids/<case_id>` to validate
the schema.

## Current contents

| Case | Tier | Source | KPIs |
|---|---|---|---|
| `lid_driven_cavity_re100`  | S | Ghia 1982 (vv_standard) | mesh_cell_count, final_residual_p, u_centerline_y0p5, u_min_along_x0p5 |
| `lid_driven_cavity_re1000` | S | Ghia 1982 (vv_standard) | same shape |
| `flatplate_zpg_subsonic`   | M | NASA TMR + CFL3D/FUN3D  | mesh_cell_count, final_residual_U, cf_x097, drag_coefficient |
| `backstep_re5000`          | M | WIP — instruction.md + task.toml not yet written | — |

## What `cases/fluids/` is NOT

- **Not a solver-specific tutorial**. If you find yourself writing
  "icoFoam needs ... " or "use SIMPLE algorithm with ...", that text
  belongs in a sim-skills `references/` doc, not in instruction.md.
- **Not a knowledge quiz**. The benchmark measures end-to-end
  agent-driving-sim-cli capability, not whether the agent knows that
  k-omega-SST exists.
- **Not the place for physics with a closed-form shortcut**. If there's
  a one-line analytical answer the agent can hardcode without running
  a solver, the case isn't load-bearing — pick a variant that forces
  numerical solution.

See the top-level [`SCHEMA.md`](../../SCHEMA.md) for the contract that every
fluids case must satisfy.
