# Task — DSMA-661 airfoil, low-speed turbulent

Solve the steady, low-speed turbulent flow over the DSMA-661
single-element airfoil at zero angle of attack, and report force
coefficients and wake-deficit characteristics.

## Geometry

- DSMA-661 single-element airfoil cross-section, chord c = 1 m, at
  α = 0°.
- Coordinates: a 2D digitized profile of the DSMA-661 airfoil surface
  is provided at `/opt/vv/dsma661/airfoil_coords.dat` (ASCII `x/c y/c`,
  upper surface then lower surface). If absent, fetch from
  `https://turbmodels.larc.nasa.gov/Other_DPW/dsma661/dsma661.txt`.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.088 (effectively incompressible) |
| chord Reynolds number | 1.2 × 10⁶ |
| free-stream temperature | 300 K |
| free-stream pressure | 101 325 Pa |
| boundary-layer state | fully turbulent (tripped at LE) |
| angle of attack | 0° |

## Boundary conditions

- Airfoil surface: no-slip, adiabatic.
- Far-field: Riemann / characteristic-based, ≥ 100 c from the airfoil.
- 2D / single-cell-thick spanwise slab.

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your mesh |
| `final_residual_U` | last momentum-equation residual |
| `cl` | lift coefficient (normalised by 0.5 ρ_∞ U_∞² c) |
| `cd` | total drag coefficient |
| `cdp` | pressure-drag component |
| `cdv` | viscous-drag component |
| `wake_min_u_at_xc_1p05` | minimum u/U_∞ across the wake at x/c = 1.05 (just behind the trailing edge) |
| `wake_min_u_at_xc_1p40` | minimum u/U_∞ at x/c = 1.40 (near wake) |
| `wake_min_u_at_xc_3p00` | minimum u/U_∞ at x/c = 3.00 (far wake recovery) |

The wake minimum is the deepest velocity deficit on a vertical line at
the specified x-station (sample y across the full wake width).

### Source kinds

- `file_extract` — value lives in a file you produced.
- `sim_run_stdout` — value in captured `sim run` stdout.
- `sim_run_kpi` — value in a sim-run's `parsed_output` dict.

Allowed extract binaries: head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq.

### Worked example

```json
{
  "cl": {
    "value": 0.161,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $4}'"
    }
  },
  "wake_min_u_at_xc_1p40": {
    "value": 0.783,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/sample/0/wake_x1p40_U.xy",
      "extract": "awk 'BEGIN{m=1e9} {if ($2<m) m=$2} END {print m}'"
    }
  }
}
```

## Environment

You are in an empty working directory. Solver-neutral; pick any
installed CFD solver. Invoke through sim-cli.

## Analytical-shortcut notice

The DSMA-661 has no closed-form analytical solution. Wake-deficit
recovery rate is set by turbulence-model constants (mixing-length /
Prandtl-number-of-momentum) and cannot be inferred from blade-element or
inviscid theory.

## Reference

- NASA Turbulence Modeling Resource (DSMA-661 verification entry).
- SU2 V&V case study: https://su2code.github.io/vandv/dsma661/
- Reference values from CFL3D Spalart-Allmaras solution on the finest
  grid (2369 × 449, ≈ 1.06 M cells).
