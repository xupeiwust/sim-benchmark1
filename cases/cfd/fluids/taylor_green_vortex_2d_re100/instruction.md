# Task — OpenFOAM 2D Taylor–Green vortex decay at Re = 100

Build and solve a reproducible transient OpenFOAM case for the exact
two-dimensional Taylor–Green vortex.

## Engineering specification

- Doubly periodic box `0 <= x,y <= 2 pi`; one-cell-thick 2D slab with `empty`
  spanwise faces.
- `nu=0.01` (`Re=100` for unit length/velocity); incompressible laminar flow.
- At `t=0` impose
  `Ux=-cos(x) sin(y)`, `Uy=sin(x) cos(y)`, `Uz=0` and a compatible pressure
  gauge.
- Integrate the transient Navier–Stokes equations to `t*=5` with adequate
  spatial and temporal resolution. Do not substitute the analytic decay for
  the solver run.
- The scored outcome is the maximum cell-centre `|Ux|` in the final native
  field; the exact solution decays uniformly as `exp(-2 nu t)`.

## What to produce

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, builds the mesh, solves, and
   writes `results.csv`. It must return non-zero on failure and **must finish
   within 600 seconds** — the evaluator re-runs it under exactly that limit
   from a clean copy, and a run that overruns is scored zero however good the
   physics.

   You may leave the mesh, time directories and logs behind. The evaluator
   strips every generated artefact — including `results.csv` itself — before
   re-running, so nothing you leave can affect the score.

2. **`results.csv`** — written by `Allrun` into the submission root, with a
   header row and one data row:

   | column | meaning |
   |---|---|
   | `u_peak_at_tstar` | peak |Ux| in the final velocity field |

   The format, with placeholders that are not the answer:

   ```
   u_peak_at_tstar
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh, discretise, converge and extract is yours
to decide.
