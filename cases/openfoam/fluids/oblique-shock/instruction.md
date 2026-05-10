# Task

do a 2D oblique shock wave simulation using OpenFOAM with the rhoCentralFoam solver. The computational domain spans 4.1 m x 1.0 m x 0.1 m. Use inlet velocity of 2.9 m/s and top velocity of (2.61933,-0.50632,0.0) m/s. Use an inlet temperature of 1.0 K and top boundary temperature of 1.25853, and an inlet pressure of 1.0 Pa. Use normalized thermodynamic properties where molWeight is set to 11640.3, Cp is 2.5, Pr is 1.0, and dynamic viscosity mu is 0. This corresponds to a gas constant R of 0.7143 and a specific heat ratio of 1.4. Use a time step of 0.0025 seconds, output results every 1.0 seconds, and run the simulation until a final time of 10 seconds.

## How you will be graded

When your work is finished, a grader script will read `/tmp/agent/result.json`.
That file **must** exist and must be a JSON object containing **both** of the
following KPIs under a `kpis` dict (exact key names required):

```json
{
  "kpis": {
    "max_p":   <number>,
    "max_rho": <number>
  },
  "converged": <bool>
}
```

Each KPI:

- **`max_p`** — peak pressure p anywhere in the domain at the final time
  (t = 10 s), in Pa (normalized). Measures pressure rise behind the shock.
- **`max_rho`** — peak density ρ anywhere in the domain at t = 10 s,
  in normalized ρ units. Measures the density jump across the shock.

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
