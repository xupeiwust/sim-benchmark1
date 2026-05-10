# Backward-facing step, RANS k-epsilon

## Problem

Run a steady-state RANS simulation of incompressible flow through a
**2D backward-facing step (BFS)** geometry:

- Inlet channel of height `h = 0.0254 m`, extending from `x = -0.0206 m` to
  `x = 0`. The step is at `x = 0` on the lower wall.
- Downstream channel (after the step) has expanded height `H = 0.0508 m`
  (full channel height = inlet height + step height, both equal to `h`).
  The downstream section extends from `x = 0` to `x ≈ 0.29 m`.
- The geometry is effectively 2D (make it 1 cell thick in the z direction
  with empty patches on the front/back).

**Boundary conditions:**

- **Inlet** (`x = -0.0206`): uniform velocity `U = (10, 0, 0) m/s`;
  zero-gradient pressure; turbulent quantities set consistent with
  `I ≈ 5%` free-stream turbulence intensity.
- **Outlet** (`x ≈ 0.29`): zero-gradient velocity, fixed pressure = 0 Pa.
- **All walls** (upper wall, lower wall, step face): no-slip for velocity;
  k-epsilon wall functions (e.g. `kqRWallFunction` for k,
  `epsilonWallFunction` for epsilon, `nutkWallFunction` for nut).
- **Front/back**: `empty` (2D).

**Fluid / model:**

- Incompressible, constant density.
- Kinematic viscosity `ν = 1e-5 m²/s`. Reynolds number based on step height:
  `Re_h = U · h / ν ≈ 41600` — turbulent.
- **Turbulence**: k-epsilon with standard wall functions. Solve with
  `simpleFoam` (steady-state SIMPLE algorithm).

## What to produce

After the run reaches steady state, identify the **reattachment point on
the lower wall downstream of the step** — i.e. the smallest `x > 0` (in
metres) at which the near-wall streamwise velocity component changes from
negative (recirculation zone) to positive (reattached flow).

Report the reattachment length normalized by step height:
`x_r / h`, where `h = 0.0254 m`.

A k-epsilon RANS prediction on this geometry typically gives `x_r / h`
in the single-digit range (model-dependent; not a hard analytical
answer — you are expected to run the solver and extract the
reattachment from the flow field, not guess).

## How you will be graded

When your work is finished, a grader script will read
`/tmp/agent/result.json`. That file **must** exist and must be a JSON object
containing at minimum the key `RESULT` whose value is `x_r / h` (a positive
float).

Example (the number is illustrative — compute the real one):

```json
{"RESULT": 0.123}
```

You are also strongly encouraged to include a boolean key `converged` indicating whether the solver actually converged (final residuals crossed the configured threshold or the solver printed a clean End). Including `"converged": true` when the solver really converged earns an extra 0.2 on your score; omitting it or setting it false forfeits that portion.

You may include additional keys (diagnostics, residual history, cell count);
they are ignored.

## Environment

- OpenFOAM v2412 is installed inside your container.
- **sim-cli is installed.** Recommended invocation: write your solution as a
  Python script `solve.py` and run it via `sim run solve.py --solver openfoam`.
  This wraps the run in a structured `RunResult` (exit_code/stdout/duration)
  stored under `.sim/runs/` for later inspection via `sim logs last`.
  Calling OpenFOAM binaries directly (`blockMesh`, `icoFoam`, etc.) from
  bash also works; pick whichever is more comfortable.
- **OpenFOAM domain knowledge lives at `/opt/sim-skills/openfoam/`.** The
  index is `SKILL.md`; topical references are under `references/`. Use
  the progressive loading the SKILL.md describes — read what you need,
  not the whole tree.
- The container is **offline** — do not attempt network access.
- You are free to write files anywhere you like; just ensure the final
  `/tmp/agent/result.json` is present and well-formed before you stop.
- **You are expected to build the case from physics first principles**
  (mesh, boundary conditions, fluid properties, solver choice). The
  grader tests understanding, not recall.
