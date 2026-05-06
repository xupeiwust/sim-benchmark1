# Task — 2D bump-in-channel, subsonic turbulent

Solve the steady, subsonic turbulent flow over a smooth wall-mounted
bump in a flat channel, and report integral force coefficients and
local skin friction at three streamwise stations.

## Geometry

- 2D channel: lower wall is the bump-and-flat surface, upper wall is a
  flat slip wall (free-stream).
- Bump occupies 0 ≤ x ≤ 1.5 m on the lower wall, with maximum height
  0.05 m at x = 0.75 m, defined by the smooth profile

  ```
  y_wall(x) = 0.05 · sin⁴(π · x / 1.5)         for 0 ≤ x ≤ 1.5
            = 0                                 elsewhere
  ```

- Total streamwise extent of the channel: x ∈ [-25, 26.5] (i.e. 25 m of
  flat plate ahead of the bump and 25 m downstream).
- Channel half-height: 5 m (free-stream slip top at y = 5).
- Reference length L_ref = 1.5 m (bump chord); reference area per span
  = 1.5.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.2 |
| Reynolds number based on L_ref = 1.5 m | 3 × 10⁶ |
| free-stream temperature | 300 K |
| boundary-layer state | fully turbulent (tripped at the channel inlet) |

## Boundary conditions

- Inflow (x = -25): subsonic free-stream (Mach + temperature inlet).
- Outflow (x = 26.5): subsonic outflow with back-pressure matched to
  free-stream static pressure.
- Lower wall (y = y_wall(x)): no-slip, adiabatic.
- Top (y = 5): symmetry / Euler slip wall.
- Spanwise: 2D / empty / single-cell periodic.

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation |
| `cd_total` | total drag coefficient on the bump-and-flat lower wall, normalised by 0.5·ρ_∞·U_∞²·L_ref (per unit span; ref area = L_ref = 1.5) |
| `cd_pressure` | pressure-drag component of `cd_total` |
| `cd_viscous` | viscous (skin-friction) drag component of `cd_total` |
| `cf_at_x_063` | local skin-friction coefficient C_f at x = 0.63 m |
| `cf_at_x_075` | local C_f at x = 0.75 m (apex of bump) |
| `cf_at_x_087` | local C_f at x = 0.87 m |

C_f = τ_w / (0.5 · ρ_∞ · U_∞²).

### Source kinds

- `file_extract` — value lives in a file you produced. Provide absolute
  `path` and an `extract` shell pipeline of allowed binaries
  (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).
- `sim_run_stdout` — value in captured `sim run` stdout; provide
  `run_id` and `extract`.
- `sim_run_kpi` — value in a sim-run's `parsed_output` dict; provide
  `run_id` and `field`.

### Worked example

```json
{
  "mesh_cell_count": {
    "value": 60000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "cd_total": {
    "value": 0.003572,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $3}'"
    }
  },
  "cf_at_x_075": {
    "value": 0.006149,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0.74 && $1<=0.76 {sum+=$4; n++} END {if(n) print sum/n}'"
    }
  }
}
```

## Environment

You are in an empty working directory.

This benchmark is solver-neutral. Discover what is installed at runtime:

```
sim --json check              # list all installed solvers
ls $SIM_SKILLS_ROOT           # list solver playbooks
cat $SIM_SKILLS_ROOT/<solver>/SKILL.md
```

Pick any installed CFD solver and any installed meshing tool. Invoke
the solver through sim-cli.

## Analytical-shortcut notice

There is no closed-form solution for the boundary layer over a 5%-thick
smooth bump at Re = 3 × 10⁶. The pressure-drag component (≈ 11% of
total drag) is sensitive to the bump-induced pressure gradient and
cannot be inferred from flat-plate correlations. Real solver run
required.

## Reference

- NASA Turbulence Modeling Resource bump-in-channel verification:
  https://turbmodels.larc.nasa.gov/bump.html
- SU2 V&V case study:
  https://su2code.github.io/vandv/Bump_Channel/
- Reference values are from CFL3D Spalart-Allmaras solution on the
  finest TMR grid (1409 × 641, ≈ 901 k cells).
