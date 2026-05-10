# Task

do a laminar offsetcylinder simulation. Use PIMPLE algorithm with a generalized Newtonian model and Cross-Power-Law viscosity for momentum transport, characterized by specific parameters nuInf=10, m=0.4, n=3. Boundary conditions specify a fixed velocity of 1m/s at the inlet (left),zero gradient pressure at the outlet (right), and no-slip conditions for walls, including the cylinder surface. Use timestep of 0.0025 and output every 0.05. Finaltime is 0.5. use constant viscosity model with nu value of 0.01 in physical properties.

## How you will be graded

When your work is finished, a grader script will read `/tmp/agent/result.json`.
That file **must** exist and must be a JSON object containing **both** of the
following KPIs under a `kpis` dict (exact key names required):

```json
{
  "kpis": {
    "max_U_magnitude": <number>,
    "max_p":           <number>
  },
  "converged": <bool>
}
```

Each KPI:

- **`max_U_magnitude`** — the peak velocity magnitude |U| = sqrt(Ux² + Uy² + Uz²)
  anywhere in the domain at the final time (t = 0.5 s), in m/s. Measures how
  much the flow accelerates around the offset cylinder.
- **`max_p`** — the peak (maximum) pressure p anywhere in the domain at
  t = 0.5 s, in Pa. Measures the stagnation pressure on the cylinder surface.

Including `"converged": true` when the solver actually converged earns an
extra 0.2 on your score. Missing either KPI key (or using a different name)
forfeits the `exec_ok` / `physics_faithful` / `kpi_accurate` portions of the
score. Additional keys (diagnostics, residual history, extra samples) are
allowed and ignored.

## Environment

You're in an empty directory. OpenFOAM 10 (Foundation fork) is
installed; the standard utilities (`blockMesh`, `foamRun`, `postProcess`, ...)
are on PATH once you source `/opt/openfoam10/etc/bashrc`.

The OpenFOAM tutorials shipped with the image have been **removed** —
you must construct the case yourself from first principles.

An OpenFOAM skill library is available at `/opt/sim-skills/openfoam/SKILL.md`
and `/opt/sim-skills/openfoam/references/*.md` (case setup / solver selection /
boundary conditions / numerics / post-processing / error recovery). Feel free
to consult it.
