# Oracle baseline — 装置正常性校准

Every case in this benchmark ships with a known-good `solution/solve.sh`.
Running it through Harbor's `oracle` agent is **fully deterministic** (no
LLM) and produces the reference score below. **A reproducer hitting a
different number on the oracle means their environment is broken** —
debug the environment before trusting any AI-agent score.

Quick check:

```bash
harbor run -p cases/openfoam/fluids/lid_driven_cavity_re100 \
    --agent oracle \
    --include-task-name lid-driven-cavity-re100
# Expect: Mean = 0.9807 ± 0.0005, wall-clock ~25 s.
```

## Oracle scores (refreshed 2026-04-22 on schema v7 — `authenticity × 4-tier`)

### 8 original cases (single KPI each)

| Case | Mean (oracle) | Per-tier detail |
|---|---|---|
| `openfoam/lid-driven-cavity-re100` | **0.9807** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9358 (Ghia 1982 ref) |
| `openfoam/lid-driven-cavity-re400` | **0.8866** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.6220 (coarse-mesh limit) |
| `openfoam/lid-driven-cavity-re1000` | **0.8912** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.6373 (coarse-mesh limit) |
| `openfoam/pitzdaily-bfs-rans` | **0.9834** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9446 (x_r/h=6.86 vs 6.5) |
| `openfoam/hotroom-buoyant` | **0.9999** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9999 (oracle-self GT, max \|U\| = 0.182 m/s) |
| `openfoam/dns-boxturb16` | **0.9999** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9999 (oracle-self GT, TKE = 0.00908 m²/s²) |
| `openfoam/dambreak-multiphase` | **0.9999** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9999 (oracle-self GT, max \|U\| = 4.41 m/s) |
| `openfoam/cavity-re100-foundation-v11` | **0.9869** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9564 (Ghia 1982; OpenFOAM Foundation v11 fork vs all-other-cases ESI v2412) |

### 3 FoamBench-sourced cases (multi-KPI)

Added 2026-04-22 from [NLR-Theseus / CFDLLMBench FoamBench](https://github.com/NLR-Theseus/cfdllmbench).
Each has 2 KPIs (primary weight 0.6 + secondary 0.4), both oracle-self-calibrated against
OpenFOAM Foundation **v10** (FoamBench's target). v11 rejects these cases' fvSolution due
to the `foamRun` unified-solver translation.

| Case | Mean (oracle) | Per-tier detail |
|---|---|---|
| `openfoam/cylinder-nonnewtonian` | **1.0000** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:1.0000 (max\|U\|=3.8709 / max p=317.78) |
| `openfoam/bernard-cells-3d` | **0.9999** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:0.9999 (max\|U\|=0.03318 / max T=300.963) |
| `openfoam/oblique-shock` | **1.0000** | auth:1 / exec:1 / converged:1 / physics:1 / kpi:1.0000 (max p=4.499 / max ρ=4.044) |

## Coverage matrix

11 cases covering the open-source CFD regime axes:

| Case | Solver | Physics | Geom | Steady? | Turb | KPI(s) | Source kind |
|---|---|---|---|---|---|---|---|
| cavity-re100/400/1000 | icoFoam | incompressible NS | 2D | transient→steady | laminar | u_centerline | V&V (Ghia 1982 Table I) |
| pitzdaily-bfs-rans | simpleFoam | NS + k-ε | 2D | steady | RANS | reattachment x_r/h | tutorial + literature ref |
| hotroom-buoyant | buoyantBoussinesqSimpleFoam | NS + energy + Boussinesq | 3D | steady | RANS k-ε | max \|U\| | tutorial + oracle GT |
| dns-boxturb16 | dnsFoam | DNS NS | 3D periodic | transient | resolved DNS | mean TKE | tutorial + oracle GT |
| dambreak-multiphase | interFoam | NS + VOF (two-phase) | 2D | transient | laminar | peak \|U\| | tutorial + oracle GT |
| cavity-re100-foundation-v11 | foamRun incompressibleFluid | incompressible NS | 2D | transient→steady | laminar | u_centerline | Ghia 1982 on Foundation fork |
| **cylinder-nonnewtonian** | pimpleFoam (Foundation v10) | NS + Cross-Power-Law viscosity | 2D | transient | laminar | max \|U\| + max p | FoamBench + oracle GT |
| **bernard-cells-3d** | buoyantFoam (Foundation v10) | NS + energy + buoyancy | 3D | transient | laminar | max \|U\| + max T | FoamBench + oracle GT |
| **oblique-shock** | rhoCentralFoam (Foundation v10) | compressible NS + shock | 2D | transient | laminar | max p + max ρ | FoamBench + oracle GT |

**8 distinct OpenFOAM solvers** (icoFoam, simpleFoam, buoyantBoussinesqSimpleFoam, dnsFoam,
interFoam, pimpleFoam, buoyantFoam, rhoCentralFoam) covering laminar / RANS / DNS, 2D / 3D,
steady / transient, incompressible / compressible, single / multi-phase, Newtonian /
non-Newtonian, with / without heat transfer.

**Two CFD fork × three OpenFOAM versions**: ESI v2412 (8 original cases), Foundation v11
(1 cross-fork demo), Foundation v10 (3 FoamBench cases).

## Multi-fork support (verified 2026-04-21)

The same Ghia 1982 cavity-Re100 physics runs on both OpenFOAM forks:

| Fork | Case | Score | Solver | Property file |
|---|---|---|---|---|
| **ESI v2412** | `cavity-re100` | 0.9807 | `icoFoam` | `transportProperties` |
| **Foundation v11** | `cavity-re100-foundation-v11` | 0.9869 | `foamRun --solver incompressibleFluid` | `physicalProperties` |

Different base images, different tutorial layouts, different solver binaries, different file naming
conventions — all handled with no schema change. The `task.toml` template is fork-agnostic.
