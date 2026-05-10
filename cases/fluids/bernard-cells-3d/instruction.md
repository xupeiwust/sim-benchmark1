# Task

Perform a 3D Bernard Cell simulation using OpenFOAM buoyantFoam solver. The computational domain spans 9 m x 1 m x 2 m. The simulation begins at t=0 seconds and runs until t=1000 seconds with a time step of 1 second, and results are written at intervals of every 50 seconds. One wall has a temperature of 301 K, while the other has a temperature of 300 K.

## How you will be graded

When your work is finished, a grader script will read `/tmp/agent/result.json`.
That file **must** exist and must be a JSON object containing **both** of the
following KPIs under a `kpis` dict (exact key names required):

```json
{
  "kpis": {
    "max_U_magnitude": <number>,
    "max_T":           <number>
  },
  "converged": <bool>
}
```

Each KPI:

- **`max_U_magnitude`** — peak velocity magnitude |U| anywhere in the domain
  at the final time (t = 1000 s), in m/s. Measures buoyant plume intensity
  with ΔT = 1 K driving force.
- **`max_T`** — peak temperature T anywhere in the domain at t = 1000 s, in K.
  Sanity check that T stays bounded by the hot wall value (~ 301 K).

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
