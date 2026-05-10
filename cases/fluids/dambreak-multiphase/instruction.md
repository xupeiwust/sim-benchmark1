# Two-phase dam break (VOF)

## Problem

Simulate an incompressible two-phase (water + air) **dam break** in a 2D
rectangular tank using the Volume-of-Fluid (VOF) method:

**Geometry**: 2D rectangular tank, `0.584 m` wide × `0.584 m` tall (standard
Martin & Moyce 1952 proportions). Make it 1 cell thick in z with `empty`
front/back patches.

**Initial condition** (to be set explicitly, e.g. via `setFields`):
- A column of water occupies the lower-left region `x ∈ [0, 0.146], y ∈ [0, 0.292]`
  (i.e. width = L, height = 2L where L = 0.146 m; standard `a = 2` aspect).
  In this region set `α_water = 1`.
- Air (`α_water = 0`) everywhere else.

**Boundary conditions**:
- All four walls (left, right, top, bottom): no-slip for velocity,
  zero-gradient for α, zero-gradient for pressure — except the top is
  `totalPressure = 0` (atmospheric outlet) so air can flow out as water
  falls.
- Front/back: `empty` (2D).

**Physics**:
- Incompressible.
- Water: `ρ = 1000 kg/m³`, `ν = 1e-6 m²/s`.
- Air: `ρ = 1 kg/m³`, `ν = 1.48e-5 m²/s`.
- Surface tension between water and air: `σ = 0.07 N/m`.
- Gravity: `g = (0, -9.81, 0) m/s²`.
- Solver: `interFoam` (incompressible two-phase VOF), transient.

**Integration**: from `t = 0` (column at rest) to `t = 1.0 s`. The column
collapses under gravity and sloshes along the floor + up the right wall.
Use adaptive `deltaT` with `maxCo ≈ 1.0` and `maxAlphaCo ≈ 1.0`.

## What to produce

At `t = 1.0 s`, find the **maximum velocity magnitude anywhere in the
domain**:

```
RESULT = max_{cells in t=1 s} |u_cell|
```

Report this single positive scalar in m/s.

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
