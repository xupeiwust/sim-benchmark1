# Task — OpenFOAM DFG cylinder benchmark 2D-1

Build and solve a reproducible OpenFOAM case for the steady laminar
Schäfer–Turek DFG benchmark 2D-1 and obtain the cylinder drag coefficient.

## Engineering specification

- Channel: `2.2 m` long and `0.41 m` high.
- Cylinder: diameter `D=0.1 m`, centre `(0.2, 0.2)`; retain the specified
  0.005 m offset from the channel centreline.
- Use a one-cell-thick 2D mesh with `empty` spanwise faces.
- `rho=1`, `nu=1e-3 m^2/s`, steady incompressible laminar flow.
- At the inlet use the DFG parabolic profile
  `u(y)=4 Umax y(H-y)/H^2`, with `Umax=0.3 m/s`, `H=0.41 m`; its mean is
  `Umean=0.2 m/s`, giving `Re=20` based on `D`.
- Outlet: zero-gradient velocity and fixed kinematic pressure. Channel walls
  and cylinder: stationary no-slip.
- Resolve the circular surface, wake and wall interaction sufficiently to
  reproduce the established steady cylinder drag.
- Report the drag coefficient `cd`, normalised as the DFG benchmark defines it:
  `cd = 2 F_D / (rho * Umean^2 * D * span)`, with `Umean = 0.2`, `rho = 1`,
  `D = 0.1` and `span` the spanwise thickness of your own mesh. The spanwise
  thickness is yours to choose — it is a 2D problem — so the reference area
  that goes with it is yours to get right.

## What to produce

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, generates the mesh, solves, and
   writes `results.csv`. It must return non-zero on failure and **must finish
   within 1800 seconds** — the evaluator re-runs it under exactly that limit
   from a clean copy, and a run that overruns is scored zero however good the
   physics.

   You may leave the mesh, time directories and logs behind. The evaluator
   strips every generated artefact — including `results.csv` itself — before
   re-running, so nothing you leave can affect the score.

2. **`results.csv`** — written by `Allrun` into the submission root, with a
   header row and one data row:

   | column | meaning |
   |---|---|
   | `cd` | the drag coefficient defined above |

   The format, with a placeholder that is not the answer:

   ```
   cd
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the
   submission root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh the cylinder, name your patches, discretise
and extract the force is yours to decide.
