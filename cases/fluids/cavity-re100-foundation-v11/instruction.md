# Lid-driven cavity, Re = 100 — OpenFOAM Foundation v11

## Problem

Simulate 2D incompressible flow in a square cavity of side `L = 0.1 m`.
The top wall (lid) moves horizontally at `U_lid = 1.0 m/s`; the other three
walls are no-slip. Newtonian fluid, kinematic viscosity
`ν = 0.001 m²/s` → `Re = U_lid · L / ν = 100`. Constant density, steady
laminar.

## What to produce

Report the **x-component of velocity along the vertical centerline at
(x = 0.05 m, y = 0.05 m)** in m/s, after the flow reaches steady state.

Reference: Ghia, Ghia & Shin 1982 Table I, Re = 100, u at centerline
y = 0.5 ≈ `-0.20581`.

## How you will be graded

When your work is finished, a grader script will read
`/tmp/agent/result.json`. That file **must** exist and must be a JSON object
containing at minimum the key `RESULT` whose value is the requested `u_x`
in m/s (a number, not a string).

Example (the number is illustrative — compute the real one):

```json
{"RESULT": 0.123}
```

You are also strongly encouraged to include a boolean key `converged` indicating whether the solver actually converged (final residuals crossed the configured threshold or the solver printed a clean End). Including `"converged": true` when the solver really converged earns an extra 0.2 on your score; omitting it or setting it false forfeits that portion.

You may include additional keys (diagnostics, residual history, cell count);
they are ignored.

## Environment

- An **OpenFOAM distribution** is installed inside your container. Probe
  the container to discover which fork / version / solver binary is
  available (hint: the ESI-style solver binaries such as `icoFoam` may or
  may not exist; if they don't, look for a generic solver runner in the
  OpenFOAM install tree).
- `sim-cli` is **NOT** installed in this container (the image ships a
  Python older than sim-cli supports). Drive OpenFOAM directly.
- The container is **offline** — do not attempt network access.
- You are free to write files anywhere you like; just ensure the final
  `/tmp/agent/result.json` is present and well-formed before you stop.
- **You are expected to build the case from physics first principles**
  (mesh, boundary conditions, fluid properties, solver choice) and to
  discover the correct invocation pattern for whichever OpenFOAM fork is
  present. The grader tests understanding + adaptability, not recall.
