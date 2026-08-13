# Task — fully-developed turbulent plane-channel flow at Re_tau = 590

Build a reproducible native OpenFOAM case for steady, fully-developed
turbulent flow in a smooth plane channel. You may run and revise the case as
needed before submitting it.

## Geometry

- A plane channel between two parallel flat walls, half-height δ (the full
  channel height is 2δ). Use the box `0 ≤ x ≤ 4`, `−1 ≤ y ≤ 1`, and
  `0 ≤ z ≤ 1`, so δ = 1 (non-dimensional).
- The streamwise direction (x) is **statistically homogeneous**: the flow is
  fully developed, with no streamwise variation of the mean profile. Model x as
  **periodic** over a short box (a length of a few δ is sufficient).
- The mean flow is one-dimensional (depends only on the wall-normal coordinate
  y). Treat the spanwise direction with a single cell (2D / empty / periodic —
  whatever your solver requires).

## Flow conditions

- Friction Reynolds number **Re_τ = u_τ · δ / ν = 590**, where
  u_τ = √(τ_w / ρ) is the friction velocity and τ_w the mean wall shear stress.
- Incompressible, Newtonian, constant properties.
- The flow is **fully turbulent** and must be computed with the `kOmegaSST`
  RANS model. Use a low-Reynolds, wall-resolved mesh with first-cell y⁺ ≤ 1.

## Driving the flow

A fully-developed channel has no net pressure difference across a periodic box;
it is driven by a **uniform streamwise forcing** that balances the wall
friction. The global x-momentum balance over the full channel height is

    (driving force per unit volume) · (2δ)  =  2 · τ_w,

so a uniform body force of magnitude `g = u_τ² / δ` makes the friction velocity
exactly `u_τ = √(g·δ)`. A convenient, fully-specified choice is

- **u_τ = 1** and **δ = 1**, hence a uniform streamwise body force `g = 1`, and
- **ν = u_τ · δ / Re_τ = 1 / 590 = 0.00169492** (kinematic viscosity).

Implement the forcing with an OpenFOAM `vectorSemiImplicitSource` in either
`constant/fvOptions` or `system/fvOptions`, using `selectionMode all`,
`volumeMode specific`, and the velocity source `U ((1 0 0) 0)`.

With this choice the friction velocity is known a priori (u_τ = 1), so you do
not need to post-process the wall shear to get it — but your mesh and model
must still reproduce the correct turbulent mean profile.

## Boundary conditions

- Walls (y = ±δ): no-slip, smooth, with the turbulence wall treatment your
  model requires.
- Streamwise faces (x): periodic / cyclic.
- Spanwise faces: 2D / empty / periodic.

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
