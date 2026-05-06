# Task — NASA wall-mounted hump (CFDVAL2004 baseline, no flow control)

Solve the steady, low-speed, fully turbulent flow over the NASA
wall-mounted Glauert-Goldschmied hump in a flat channel and report
separation/reattachment quantities plus selected wall coefficients.
This is the CFDVAL2004 Case 3 "baseline" (no-flow-control) experiment
of Greenblatt et al. (2006).

## Geometry

- 2D smooth-body wall-mounted hump on the lower wall of a low-speed
  channel.
- Hump chord c is the streamwise reference length. Place the hump so
  that:
  - leading edge at x/c = 0
  - trailing edge at x/c = 1
  - apex of the hump near x/c ≈ 0.19 (peak suction near x/c ≈ 0.48)
- Maximum hump thickness ≈ 0.128 c. The leading edge is faired smoothly
  to the upstream flat wall; the trailing edge slopes down sharply to
  a small backward step that re-meets the flat wall — this is the
  feature that triggers the separation bubble. Use the canonical
  Glauert-Goldschmied profile distributed on the NASA TMR page.
- Total streamwise extent of the channel: ahead of the hump from
  at least x/c = -2.14 (upstream profile reference station of the
  experiment) to at least x/c = 4.0 downstream of the hump trailing
  edge.
- Channel half-height (slip-wall top): ≈ 0.91 c above the tunnel floor,
  matching the CFDVAL2004 wind-tunnel test section.
- Spanwise: 2D / empty / single-cell.

The exact (x/c, y/c) coordinates of the hump are tabulated on the
NASA TMR page (link below). For solver-neutral framing, reproducing the
experimental wall Cp distribution (peak suction Cp ≈ -0.87 near
x/c = 0.48) over the hump is the geometric correctness check.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.1 (essentially incompressible) |
| Reynolds number based on chord c | 9.36 × 10⁵ |
| free-stream temperature | 298 K |
| free-stream pressure | 101 325 Pa |
| boundary-layer state at x/c = -2.14 | fully turbulent, δ ≈ 0.08 c |
| reference station for Cp | free-stream static pressure |

## Boundary conditions

- Inflow (upstream of x/c = -2.14): subsonic velocity inlet, fully
  developed turbulent BL profile from the experimental
  `noflow_u_inflow.exp.dat` (or a synthetic profile that matches
  Re_θ ≈ 7 200 and δ ≈ 0.08 c at x/c = -2.14).
- Outflow (downstream end): subsonic outflow with back-pressure matched
  to free-stream static.
- Lower wall (flat plate + hump): no-slip, adiabatic.
- Top (channel ceiling): symmetry / Euler slip wall (the experimental
  rig has a slight contour to mimic free-stream; slip wall at constant
  height is the standard TMR simplification).
- Spanwise: 2D / empty / single-cell.

Converge so the momentum-equation residual drops by at least 4 orders
of magnitude and is stationary for the last 500 iterations.

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation |
| `separation_xc` | x/c where the wall C_f first crosses zero from positive (separation point on the lee side of the hump) |
| `reattachment_xc` | x/c where the wall C_f crosses back from negative to positive (reattachment point downstream) |
| `cp_min_separation` | minimum (most-negative) wall Cp anywhere on the hump (peak suction) |
| `cf_recovery_at_xc_2` | wall C_f at x/c = 2.0 (well downstream of reattachment, where the boundary layer is recovering) |

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
    "value": 90000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "separation_xc": {
    "value": 0.665,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0.4 && $1<=0.9 {print $1, $4}' | awk 'BEGIN{prev_x=-99; prev_cf=99} {if (prev_cf>0 && $2<0) {printf \"%.4f\\n\", prev_x + (0-prev_cf)/($2-prev_cf)*($1-prev_x); exit} prev_x=$1; prev_cf=$2}'"
    }
  },
  "cp_min_separation": {
    "value": -0.872,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallPressure/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0.0 && $1<=1.0 {if ($4<m) m=$4} END {print m}'"
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

There is no closed-form solution for separation or reattachment over a
smooth-body wall-mounted hump. The peak suction Cp ≈ -0.87 is set by
the inviscid potential-flow distortion plus boundary-layer
displacement; the separation point depends on the adverse-pressure-
gradient response of the turbulence model; and the reattachment
location is set by the Reynolds-stress-driven shear-layer mixing in
the bubble. None of these can be inferred from flat-plate, similarity,
or thin-airfoil correlations. Hard-coding x/c values from the cited
experiment without a real solver run will fail the verifier's
`physics_faithful` check (which inspects sim-cli's `RunResult` for
solver output, mesh cell count, and residual history). Real solver run
required.

## Reference

- Greenblatt, D., Paschal, K. B., Yao, C.-S., Harris, J., Schaeffler,
  N. W., Washburn, A. E. (2006). "Experimental Investigation of
  Separation Control Part 1: Baseline and Steady Suction." *AIAA
  Journal*, 44(12), 2820-2830. doi:10.2514/1.13817
- NASA Turbulence Modeling Resource (TMR), 2D NASA Wall-Mounted Hump
  validation case: https://tmbwg.github.io/turbmodels/nasahump_val.html
- Reference data (linked from TMR per-model pages):
  - https://tmbwg.github.io/turbmodels/Nasahump_validation/noflow_cp.exp.dat
  - https://tmbwg.github.io/turbmodels/Nasahump_validation/noflow_cf.exp.dat
  - https://tmbwg.github.io/turbmodels/Nasahump_validation/noflow_u_inflow.exp.dat
- CFDVAL2004 Workshop Case 3 baseline (no flow control).
