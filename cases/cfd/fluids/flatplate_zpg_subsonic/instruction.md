# Task — zero-pressure-gradient turbulent flat plate, Re_x=5×10^6

Build and solve a native OpenFOAM ESI v2412 case for the low-Mach,
zero-pressure-gradient turbulent boundary layer over a smooth flat plate. The
evaluator will reproduce the clean case and independently assess local and
integrated wall friction against the NASA Turbulence Modeling Resource (TMR)
SST flat-plate verification family.

## Physical problem

- Plate and domain: `0 <= x <= 2`, `0 <= y <= 1`, with unit spanwise depth.
- Use `U_inf=1` and `nu=2e-7`, so `Re_x=5e6` at `x=1` and `1e7` at `x=2`.
- Approximate the TMR `M=0.2` verification condition with incompressible
  `simpleFoam`. Scoring uses the NASA TMR finest-grid SST-Vm family as the
  engineering reference; NASA reports that SST, SST-V and SST-Vm are nearly
  identical for this low-speed flat-plate case. The evaluator tolerance
  accounts for the documented incompressible/compressible and code-to-code
  spread without exposing its private numerical thresholds.
- Use RANS `kOmegaSST` and a wall-resolved mesh. Target `y+ <= 2` along the
  plate and activate the fully turbulent boundary layer at the leading edge.
- At `x=0`, impose the free stream. Use a pressure-compatible outlet at `x=2`,
  a no-slip plate at `y=0`, and a free-stream/symmetry top boundary at `y=1`.
- Use a one-cell spanwise slab with `empty` front/back patches.

The evaluator scores two physical outcomes from the reproduced native field:

- local skin-friction coefficient `C_f` at `x=0.970084071`;
- integrated viscous drag coefficient over `0 <= x <= 2`, normalized by
  `0.5 rho U_inf^2 A_ref` with `rho=1` and `A_ref=2` per unit span.

Exact reference values and tolerances are not part of the submission contract.

## Submission contract

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, builds the mesh, solves, and
   writes `results.csv`. It must return non-zero on failure and **must finish
   within 1700 seconds** — the evaluator re-runs it under exactly that limit
   from a clean copy, and a run that overruns is scored zero however good the
   physics.

   You may leave the mesh, time directories and logs behind. The evaluator
   strips every generated artefact — including `results.csv` itself — before
   re-running, so nothing you leave can affect the score.

2. **`results.csv`** — written by `Allrun` into the submission root, with a
   header row and one data row:

   | column | meaning |
   |---|---|
   | `cf_x097` | skin-friction coefficient on the plate at x = 0.970084071 |
   | `drag_coefficient` | total drag coefficient on the plate |

   The format, with placeholders that are not the answer:

   ```
   cf_x097,drag_coefficient
   1.0,1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh the plate, discretise, converge and extract
the wall quantities is yours to decide.
