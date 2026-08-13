# Task — OpenFOAM laminar backward-facing step at Re = 389

Build and solve a reproducible OpenFOAM case for the Armaly et al. laminar
backward-facing-step validation condition and obtain the primary reattachment
length.

## Engineering specification

- Step height `S=0.0049 m`; expansion ratio `H_out/H_in=1.94`.
- Use the supplied physical scale with upstream development length at least
  `20S` and downstream length at least `30S`.
- Mean inlet speed `Umean=1 m/s`, `nu=2.51928e-5 m^2/s`, giving
  `Re=Umean(2S)/nu=389`.
- Steady incompressible laminar flow; one-cell-thick 2D mesh with `empty`
  spanwise faces.
- Inlet velocity is uniform and the upstream section develops it before the
  step. Outlet uses fixed kinematic pressure / zero-gradient velocity. All
  physical walls and the step face are stationary no-slip.
- Resolve the separated shear layer and downstream wall shear sufficiently to
  locate the first negative-to-positive wall-shear crossing after the step.
  The scored outcome is `x_r/S`.

## What to produce

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, builds the mesh, solves, and
   writes `results.csv`. It must return non-zero on failure and **must finish
   within 2400 seconds** — the evaluator re-runs it under exactly that limit
   from a clean copy, and a run that overruns is scored zero however good the
   physics.

   You may leave the mesh, time directories and logs behind. The evaluator
   strips every generated artefact — including `results.csv` itself — before
   re-running, so nothing you leave can affect the score.

2. **`results.csv`** — written by `Allrun` into the submission root, with a
   header row and one data row:

   | column | meaning |
   |---|---|
   | `reattachment_length_xr_over_h` | reattachment length on the downstream floor, in step heights |

   The format, with placeholders that are not the answer:

   ```
   reattachment_length_xr_over_h
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh, discretise, converge and extract is yours
to decide.
