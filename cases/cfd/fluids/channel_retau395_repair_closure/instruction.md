# Task — a channel-flow case that returns the wrong bulk velocity

An engineer set up the OpenFOAM case in `case/` for fully-developed plane
channel flow and handed it over. It meshes and it runs to completion — and the
bulk velocity it reports is far too high for the Reynolds number the case is
supposed to be at, by close to an order of magnitude.

Find out why, fix it, and hand back a case that produces the right answer.

## What the case is meant to represent

- Channel half-height `delta = 1`, full height `2`; periodic streamwise length
  `4`; a one-cell-thick 2D slab with `empty` spanwise faces.
- No-slip walls on both sides, cyclic streamwise boundaries.
- `u_tau = 1`, `nu = 1/395`, and a uniform streamwise body force of magnitude
  `u_tau^2 / delta = 1`. By momentum balance that forcing fixes the friction
  Reynolds number at `Re_tau = 395` — the flow is **fully turbulent**, not a
  laminar Poiseuille flow.
- Because the forcing fixes `u_tau`, the bulk velocity is an *output* of the
  solve. `U_b / u_tau = U_b` is the quantity that is checked.

The geometry, the mesh, the boundary conditions, the material properties and
the body force are all consistent with that specification. The defect is
somewhere else, and it is a single modelling decision rather than a typo.

## What to change

Whatever is required to make the case represent the physics above. If your fix
introduces fields or settings the current case does not carry, add them — a
correct case is the deliverable, not a minimal diff. Keep `Re_tau = 395`:
do not change `nu`, the body force, the geometry or the mesh to move the
answer, because those are what define the operating point.

**The iteration budget is part of the problem, not part of the defect.** The
supplied case runs a fixed number of iterations and stops there, and every
submission is solved under that same budget so that the answers are comparable.
Leave it as it is. Running longer is not the fix — the defect is a single
modelling decision, and the answer this task checks is the one that budget
produces.

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
   | `ub_over_utau` | bulk velocity divided by the friction velocity |

   The format, with placeholders that are not the answer:

   ```
   ub_over_utau
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 is available. How you mesh, discretise, converge and extract is yours
to decide.
