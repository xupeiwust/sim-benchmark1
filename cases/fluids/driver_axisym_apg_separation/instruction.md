# Task — Driver 1991 axisymmetric APG separated boundary layer

Solve the steady, low-speed turbulent flow over a Driver-1991-style
axisymmetric body: a cylinder followed by a diverging-radius section
that imposes an adverse pressure gradient strong enough to separate
the boundary layer and reattach it downstream. Report integral and
local separation/reattachment quantities.

## Geometry

- Axisymmetric body: a long cylinder of radius R_cyl on the centerline,
  followed downstream by a diverging "skirt" that smoothly increases the
  outer radius. The diverging section starts at x = 0 (defined as the
  start of the deflecting fairing).
- The streamwise extent of the wall reference data is x ∈ [−0.46, +0.76]
  metres. Set the inflow well upstream (e.g. x = −1.0 m or further) so
  that a fully-developed turbulent boundary layer is established at
  the start of the APG region.
- Use a single-wedge axisymmetric mesh (e.g. 5° wedge with one cell in
  the azimuthal direction) or a 2D r-z plane mesh, your choice.

The exact geometry for the deflecting fairing is the "C.S0" (separated)
configuration from Driver's NASA Ames campaign; full coordinates are in
NASA TM-102211 (Driver, 1991). For solver-neutral framing, you may
construct the diverging-radius profile so that the experimentally
measured Cp distribution (rising from 0 to ~0.59 between x = −0.23 m
and x = +0.46 m) is reproduced.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.088 (essentially incompressible) |
| free-stream temperature | 298 K |
| free-stream pressure | 101 325 Pa |
| boundary-layer state at x = 0 | fully turbulent |
| reference pressure for Cp | static pressure at x = −0.457 m |

## Boundary conditions

- Centerline / axis of symmetry on the bottom.
- Outer wall: characteristic / pressure-outlet far-field, sufficiently
  far away that the inviscid streamlines feel the body shape.
- Inflow: fully-developed turbulent BL, chosen to match
  Re_θ ≈ 8 200 at x = 0 (Driver's experiment).
- Outflow: subsonic outflow / extrapolation.
- Cylinder + fairing wall: no-slip, adiabatic.

Converge so residuals drop ≥ 4 orders of magnitude and are stationary
for the last 500 iterations.

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last momentum-equation residual |
| `separation_x_m` | streamwise location (in metres) where wall C_f first crosses zero from positive (separation point) |
| `reattachment_x_m` | streamwise location (in metres) where wall C_f crosses zero from negative back to positive (reattachment point) |
| `cf_min_in_bubble` | most-negative wall C_f anywhere inside the separation bubble (signed; expect negative value) |
| `cp_max_recovery` | maximum wall Cp on the deflecting fairing (peak pressure-recovery point), with the Driver convention that Cp = 0 at the upstream reference station x = −0.457 m |

### Source kinds

- `file_extract` — value lives in a file you produced. Provide absolute
  `path` and an `extract` shell pipeline of allowed binaries
  (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).
- `sim_run_stdout` — value in captured `sim run` stdout; provide
  `run_id` and `extract`.
- `sim_run_kpi` — value in a sim-run's `parsed_output` dict.

### Worked example

```json
{
  "separation_x_m": {
    "value": 0.064,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=-0.05 && $1<=0.10 {print $1, $4}' | awk 'BEGIN{prev_x=-99; prev_cf=99} {if (prev_cf>0 && $2<0) {printf \"%.4f\\n\", prev_x + (0-prev_cf)/($2-prev_cf)*($1-prev_x); exit} prev_x=$1; prev_cf=$2}'"
    }
  },
  "cp_max_recovery": {
    "value": 0.593,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallPressure/0/wall.raw",
      "extract": "awk 'NR>1 {if ($4>m) m=$4} END {print m}'"
    }
  }
}
```

## Environment

You are in an empty working directory. Solver-neutral; pick any
installed CFD solver. Invoke through sim-cli.

## Analytical-shortcut notice

There is no closed-form solution for the location or extent of an APG
separation bubble. The peak Cp = 0.59 in the recovery region is set by
the geometry-driven streamline curvature plus turbulent-stress
redistribution, neither of which is captured by inviscid theory. The
agent must run the solver.

## Reference

- Driver, D. M. (1991). "Reynolds Shear Stress Measurements in a
  Separated Boundary Layer Flow." AIAA Paper 91-1787.
- NASA Turbulence Modeling Resource:
  https://tmbwg.github.io/turbmodels/driver_val.html
- Reference data files:
  - https://tmbwg.github.io/turbmodels/Driver_validation/cp.exp.dat
  - https://tmbwg.github.io/turbmodels/Driver_validation/cf.exp.dat
