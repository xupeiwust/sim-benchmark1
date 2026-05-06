# Task — Bachalo & Johnson 1986 axisymmetric transonic bump (shock-induced separation)

Solve the steady, fully-turbulent, transonic flow over an axisymmetric
circular-arc bump on a long thin-walled cylinder. The shock that forms
on the downstream face of the bump is strong enough to separate the
turbulent boundary layer; the flow reattaches further downstream on the
cylindrical body. Report integral and local shock / separation /
reattachment quantities.

## Geometry

- Long thin-walled cylinder of diameter d = 0.1524 m (6 in), radius
  R = 0.0762 m, aligned with the freestream.
- A single circular-arc bump is wrapped around the cylinder. The bump
  has chord c = 0.2032 m (8 in) measured along the body axis, and a
  maximum height t = 0.01905 m (3/4 in) above the cylinder surface,
  i.e. t/c ≈ 0.094 (about a 9.4% thick arc).
- A small leading-edge fillet smooths the junction (the fillet radius
  is reported as somewhere in the range 18.3–20.3 cm in the
  experimental documentation; treat it as a smooth blend).
- The bump's leading edge is at axial station x = 0; the trailing edge
  is at x = c. Use **non-dimensional axial coordinate x/c** for all
  downstream output reporting (so x/c = 0 at LE, 1 at TE).
- Set the inflow well upstream of the bump (e.g. x/c ≤ −5) so that an
  equilibrium turbulent boundary layer is established at the LE.
  Set the outflow well downstream of the expected reattachment point
  (e.g. x/c ≥ 3) so that the separated/recovering shear layer is fully
  contained in the domain.
- The case is **axisymmetric**: build either a single-wedge
  axisymmetric mesh (e.g. a 5° wedge with one cell in the azimuthal
  direction, axis on the centerline of the cylinder) **or** a 2D r-z
  plane mesh with appropriate axisymmetric solver settings. Either is
  acceptable.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach M_∞ | **0.875** (transonic) |
| Reynolds number based on bump chord c, Re_c | **2.763 × 10⁶** |
| free-stream static temperature T_∞ | 300 K (= 540 °R) |
| free-stream turbulence intensity | ≈ 0.6 % (negligible for RANS closure init) |
| α (angle of attack) | 0° |
| gas | calorically perfect air, γ = 1.4, R = 287 J/(kg·K) |
| viscosity | Sutherland's law (μ_ref = 1.716 × 10⁻⁵, T_ref = 273.1 K, S = 110.4 K) |
| boundary-layer state | fully turbulent throughout |

Pick a free-stream pressure consistent with M_∞ = 0.875, T_∞ = 300 K
and Re_c = 2.763 × 10⁶ at the chosen Sutherland μ; a few percent
mismatch in p_∞ is acceptable as long as Re_c is on target.

## Boundary conditions

- Inflow (upstream of LE): subsonic free-stream / characteristic-based
  inlet at the prescribed M_∞, T_∞.
- Outflow (downstream of bump and recovery zone): subsonic outflow with
  back-pressure matched to free-stream static pressure (the freestream
  is subsonic; only the local supersonic pocket on the bump's downstream
  face produces the shock).
- Cylinder + bump wall: no-slip, adiabatic.
- Outer / far-field boundary: characteristic far-field; place it
  several chords away (≥ 5 c) so the inviscid streamlines around the
  bump are not pinched.
- Axisymmetric closure: axis BC on the centerline (wedge mesh) or
  axisymmetric symmetry (2D r-z).

Converge so residuals drop ≥ 4 orders of magnitude and are stationary
(no monotonic drift) for the last ≥ 500 iterations.

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares. Bare numbers are rejected.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation |
| `shock_location_xc` | x/c at which the wall Cp jumps (taken as the streamwise position halfway between the local Cp minimum just upstream of the shock and the first sample showing post-shock recovery; reported in units of x/c, dimensionless) |
| `cp_post_shock` | wall Cp value just downstream of the shock, sampled at x/c = 0.6563 (the experimental sample station immediately following the shock; this is the first datum inside the separation region) |
| `separation_xc` | x/c at which the wall skin-friction coefficient C_f first crosses zero from positive to negative (separation point on the bump's downstream face) |
| `reattachment_xc` | x/c at which wall C_f crosses zero from negative back to positive (reattachment downstream of the bump) |

Conventions: Cp = (p − p_∞) / (0.5 · ρ_∞ · U_∞²). C_f = τ_w / (0.5 · ρ_∞ · U_∞²),
sign of C_f determined by the streamwise component of wall shear stress
(positive when wall stress is in the freestream direction).

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
  "shock_location_xc": {
    "value": 0.661,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallPressure_xc.dat",
      "extract": "awk 'NR>1 && $1>=0.50 && $1<=0.80 {print $1, $2}' | awk 'BEGIN{prev_x=-99; prev_cp=99; cpmin=99; xmin=0} {if ($2<cpmin) {cpmin=$2; xmin=$1} if (prev_cp<-0.4 && $2>prev_cp+0.15) {printf \"%.4f\\n\", 0.5*(prev_x+$1); exit} prev_x=$1; prev_cp=$2}'"
    }
  },
  "separation_xc": {
    "value": 0.69,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress_xc.dat",
      "extract": "awk 'NR>1 && $1>=0.55 && $1<=0.95 {print $1, $2}' | awk 'BEGIN{prev_x=-99; prev_cf=99} {if (prev_cf>0 && $2<0) {printf \"%.4f\\n\", prev_x + (0-prev_cf)/($2-prev_cf)*($1-prev_x); exit} prev_x=$1; prev_cf=$2}'"
    }
  }
}
```

Run-time metadata (solver name, mesh cells, residuals, wall-time) is
recorded by sim-cli separately. Do NOT include those fields in
`result.json` beyond what the schema asks for.

## Environment

You are in an empty working directory.

This benchmark is solver-neutral. Discover what is installed at runtime:

```
sim --json check              # list all installed solvers
ls $SIM_SKILLS_ROOT           # list solver playbooks
cat $SIM_SKILLS_ROOT/<solver>/SKILL.md
```

Pick any installed compressible-CFD solver (rhoSimpleFoam /
rhoCentralFoam in OpenFOAM, SU2_CFD, etc.) capable of resolving a
shock and the resulting separated boundary layer. The only hard
requirement: invoke the solver through sim-cli
(`sim run --solver <solver> <script>`).

## Analytical-shortcut notice

There is no closed-form prediction for shock-induced separation. The
shock location depends on wall-curvature-induced supersonic-pocket
extent, the post-shock Cp recovery depends on turbulent-stress
redistribution, and the separation/reattachment locations are sensitive
to the turbulence model's response to adverse-pressure-gradient +
streamline-curvature coupling. Shock-position correlations from
inviscid theory will miss the experimental shock location by ≥ 5% chord
because they ignore the displacement effect of the boundary layer.
Real solver run required.

## Reference

- Bachalo, W. D., and Johnson, D. A. (1986). "Transonic, Turbulent
  Boundary-Layer Separation Generated on an Axisymmetric Flow Model."
  AIAA Journal, Vol. 24, No. 3, pp. 437–443. (Original experimental
  campaign; primary reference.)
- NASA Turbulence Modeling Resource — Axisymmetric Transonic Bump
  validation case: https://tmbwg.github.io/turbmodels/axibump_val.html
- Per-model SA results: https://tmbwg.github.io/turbmodels/axibump_val_sa.html
- Reference data files (under https://tmbwg.github.io/turbmodels/Axi_Bump_validation/):
  - cp.exp.dat (experimental wall Cp)
  - axibump_cfl3d_cp_sa.dat (CFL3D + Spalart–Allmaras Cp)
  - axibump_cfl3d_cf_sa.dat (CFL3D + Spalart–Allmaras Cf)
  - exp.alldata.875.dat (all profile data at M=0.875)
