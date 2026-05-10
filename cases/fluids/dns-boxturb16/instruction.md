# Decaying isotropic turbulence (DNS, 16³ box)

## Problem

Run a direct numerical simulation (DNS) of incompressible decaying isotropic
turbulence in a cubic box with triply-periodic boundaries:

**Geometry**: cube of side `L = 2π m` (0 ≤ x, y, z ≤ 2π) discretised with a
**16 × 16 × 16** uniform hex mesh.

**Boundary conditions**: all six faces are **cyclic (triply periodic)** so
that turbulence has no wall influence and is genuinely isotropic.

**Fluid / model**:
- Incompressible, constant density.
- Kinematic viscosity `ν = 0.01 m²/s` (the higher-than-air viscosity makes
  16³ sufficient to resolve the Kolmogorov scale for this short run).
- No turbulence model — this is DNS. Solver: `dnsFoam` (OpenFOAM's explicit
  incompressible DNS solver), transient.

**Initial condition**: a synthetic isotropic turbulence field consistent
with a Pope / Comte-Bellot-Corrsin–style spectrum. OpenFOAM ships a
pre-processing utility `boxTurb` that generates exactly this: a divergence-free
random velocity field with prescribed energy spectrum. Run `boxTurb` before
`dnsFoam` to populate `0/U`.

**Integration**: run `dnsFoam` from `t = 0` to `t = 10 s` with a stable
explicit time step (use e.g. `deltaT = 0.005 s`).

## What to produce

After integration, compute the **mean turbulent kinetic energy** of the
final velocity field:

```
TKE = (1/N) · Σ_cells (1/2) · |u_cell|²
```

where the sum is over all internal cells of the latest time directory and
N is the cell count. Report TKE in m²/s² as a single positive scalar.

(For decaying isotropic turbulence the mean velocity is essentially zero,
so |u|² ≈ |u'|². No need to subtract the mean.)

## How you will be graded

When your work is finished, a grader script will read
`/tmp/agent/result.json`. That file **must** exist and must be a JSON object
containing at minimum the key `RESULT` whose value is the requested TKE in
m²/s² (a positive number, not a string).

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
