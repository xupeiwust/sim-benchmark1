# Task — OpenFOAM natural convection cavity at Ra = 10^4

Build and solve a reproducible OpenFOAM case for the de Vahl Davis
differentially heated square-cavity benchmark.

## Engineering specification

- Unit square in x-y, represented by a one-cell-thick 2D slab with `empty`
  spanwise faces.
- Boussinesq, steady, laminar natural convection; `Ra=1e4`, `Pr=0.71`.
- Use the nondimensional setup `L=1`, `T_hot=1`, `T_cold=0`, `|g|=1`,
  `beta=1`, so `nu=sqrt(0.71e-4)=8.4261498e-3` and `alpha=nu/Pr`.
- Gravity acts in negative y. The left vertical wall is hot, the right wall is
  cold, and horizontal walls are adiabatic. All physical walls are no-slip.
- Resolve the circulation and wall thermal boundary layers sufficiently to
  reproduce the established mean hot-wall Nusselt number.

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
   | `nu_avg_hot_wall` | average Nusselt number on the hot wall, normalised by that wall's own area |

   The format, with placeholders that are not the answer:

   ```
   nu_avg_hot_wall
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh, discretise, converge and extract is yours
to decide.
