# Task — OpenFOAM lid-driven square cavity at Re = 1000

Build and solve a reproducible OpenFOAM case for steady, incompressible,
laminar flow in the classic two-dimensional lid-driven square cavity.

## Engineering specification

- Unit square: `0 <= x <= 1`, `0 <= y <= 1`; use a one-cell-thick 2D slab.
- Lid speed `U_lid = 1` in the positive x direction and kinematic viscosity
  `nu = 0.001`, so `Re = U_lid L / nu = 1000`.
- The top wall is a moving no-slip wall. The left, right and bottom walls are
  stationary no-slip walls. Spanwise faces are `empty`.
- Use the laminar model and a steady incompressible OpenFOAM solver.
- Resolve the recirculating flow well enough to reproduce the established
  vertical-centerline velocity profile. The scored outcome is the minimum
  `Ux/U_lid` on `x = 0.5`, including the negative back-flow trough.

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
   | `u_min_vertical_centerline` | the minimum `Ux/U_lid` on the vertical centreline `x = 0.5` |

   The format, with a placeholder that is not the answer:

   ```
   u_min_vertical_centerline
   -0.9
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh the cavity, discretise, converge and sample
the centreline is yours to decide — including the spanwise thickness of the
slab, which is why sampling it is your job and not the evaluator's.
