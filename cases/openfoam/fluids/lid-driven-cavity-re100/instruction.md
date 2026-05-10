# Lid-driven cavity, Re = 100

## Problem

Simulate 2D incompressible flow in a square cavity of side L = 0.1 m. The top
wall (lid) moves horizontally at U_lid = 1.0 m/s; the other three walls are
no-slip. The fluid is Newtonian with kinematic viscosity ν chosen to give a
Reynolds number Re = U_lid · L / ν = 100 (so ν = 0.001 m²/s). Density is
constant (incompressible). Assume steady laminar flow.

## What to produce

Report the **x-component of velocity along the vertical centerline
(x = 0.05 m) at y = 0.05 m** — i.e. the single sample u_x(x=0.05, y=0.05)
in m/s, after the flow has reached steady state.

Reference solution is Ghia, Ghia & Shin (1982) Table I.

## How you will be graded

When your work is finished, a grader script will read
`/tmp/agent/result.json`. That file **must** exist and must be a JSON object
containing at minimum the key `RESULT` whose value is the requested `u_x` in
m/s (a number, not a string).

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
