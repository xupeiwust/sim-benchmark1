# Task — OpenFOAM developing laminar channel entry at Re = 100

Build and solve a reproducible OpenFOAM case for the entrance region of a
two-dimensional plane channel.

## Engineering specification

- Full channel height `D=2H=1`, walls at `y=+-0.5`, length `6`.
- One-cell-thick 2D slab with `empty` spanwise faces.
- Uniform inlet velocity `Umean=1`, `nu=0.01`, giving `Re=Umean D/nu=100`.
- Steady incompressible laminar flow; stationary no-slip channel walls;
  fixed-pressure outlet with zero-gradient velocity.
- Resolve the developing entrance flow sufficiently to reproduce the
  centreline velocity ratio `Ux/Umean` at `x=0.01 Re D=1`. This is the scored
  native-field outcome; the flow is not yet fully developed there.

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
   | `u_centerline_ratio` | centreline velocity at x = 1 divided by the inlet mean velocity |

   The format, with placeholders that are not the answer:

   ```
   u_centerline_ratio
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh, discretise, converge and extract is yours
to decide.
