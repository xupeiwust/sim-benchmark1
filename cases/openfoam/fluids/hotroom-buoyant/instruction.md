# Hot-room buoyant natural convection

## Problem

Simulate steady-state buoyancy-driven flow in a rectangular room with a
localised hot patch on the floor:

**Geometry**: 10 × 5 × 10 m rectangular room (x: 0→10 m, y: 0→5 m,
z: 0→10 m). Gravity acts in the `−y` direction, `g = (0, -9.81, 0) m/s²`.

**Boundary conditions**:
- Floor (y = 0): no-slip wall, fixed temperature `T_floor = 300 K`,
  EXCEPT a 1 × 1 m square patch centred on the floor at
  `(x, z) ∈ [4.5, 5.5] × [4.5, 5.5]` initialised to `T = 600 K` (see
  initial condition below).
- Ceiling (y = 5): no-slip wall, fixed temperature `T_ceil = 300 K`.
- Four side walls (x = 0, x = 10, z = 0, z = 10): no-slip wall, zero-gradient
  temperature.
- All walls: pressure = zero-gradient.

**Fluid / model**:
- Air at roughly atmospheric conditions.
- **Boussinesq** buoyancy approximation: `ρ = ρ_ref · (1 − β (T − T_ref))`
  with `T_ref = 300 K`, thermal expansion `β = 3e-3 /K`, reference density
  `ρ_ref = 1 kg/m³`, kinematic viscosity `ν = 1e-5 m²/s`, Prandtl number
  `Pr = 0.7`, turbulent Prandtl `Pr_t = 0.85`.
- Turbulence: k-epsilon RANS with standard wall functions.
- Solver: `buoyantBoussinesqSimpleFoam` (steady-state).

**Initial condition**: Set T = 300 K everywhere except in a sub-box
`[4.5, 5.5] × [0, 0.5] × [4.5, 5.5]` where T = 600 K. The hot patch heats
this sub-volume at t = 0; after SIMPLE iterations it establishes a steady
plume.

Mesh resolution is a judgement call — coarse enough to run in ≲ 60 s,
fine enough to resolve the plume near the hot patch.

## What to produce

After convergence, find the **maximum velocity magnitude anywhere in the
domain** — i.e. `max |U|` over all internal cells at the final time step.
Report this single scalar in m/s.

## How you will be graded

When your work is finished, a grader script will read
`/tmp/agent/result.json`. That file **must** exist and must be a JSON object
containing at minimum the key `RESULT` whose value is `max |U|` in m/s
(a positive number, not a string).

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
