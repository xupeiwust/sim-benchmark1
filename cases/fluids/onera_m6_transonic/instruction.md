# Task — ONERA M6 swept wing, transonic flow

Solve the steady, 3-D transonic turbulent flow over the ONERA M6 wing
at the Schmitt-Charpin AGARD test point, and report integral force
coefficients plus a wall pressure coefficient at a chordwise location
in the canonical lambda-shock pattern on the suction side.

## Geometry

The ONERA M6 is a swept, tapered, untwisted wing built from a single
ONERA D airfoil section (symmetric, max thickness ≈ 9.8 % c at
x/c ≈ 0.36). Geometry per Schmitt & Charpin (AGARD AR-138, 1979):

| quantity | value |
|---|---|
| section | ONERA D (symmetric) — shared along span |
| root chord `c_r` | 0.8059 m |
| tip chord  `c_t` | 0.4561 m |
| taper ratio | 0.562 |
| semi-span  `b` | 1.1963 m |
| aspect ratio (full wing) | 3.8 |
| leading-edge sweep | 30° |
| trailing-edge sweep | 15.8° |
| dihedral / twist | 0° / 0° (untwisted) |
| reference area `S_ref` (semi-span) | 0.7532 m² (semi-span area = (c_r+c_t)/2 · b) |
| reference chord `c_ref` (mean aero chord) | 0.6463 m |

The wing is mounted at the symmetry plane (`y = 0`); only one
semi-span need be modelled, with a symmetry / Euler-slip boundary
condition on `y = 0`. Place the wing at `α = 3.06°`. The spanwise
station "2y/b" is normalised by the full span `2·b = 2.3926 m`, so
`2y/b = 0.44` corresponds to `y = 0.44 · b = 0.5264 m`.

The ONERA D section coordinates are public (Schmitt & Charpin
AGARD AR-138, Appendix B). If the agent needs a digitised airfoil
profile and no internet is available, it is acceptable to use any
publicly tabulated ONERA D digitisation (NASA TMR / GMSH community)
provided the profile has the same max-thickness and shape; the wing
KPIs (`cl`, `cd`, `cp_at_2y_b_044_xc_05`) are largely insensitive to
sub-1 % chord differences in the digitised section.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach `M_inf` | 0.8395 |
| chord Reynolds number (root chord) | 1.172 × 10⁷ |
| angle of attack `α` | 3.06° |
| free-stream temperature `T_inf` | 300 K (or 255.6 K — Schmitt-Charpin tunnel value; either is acceptable, KPIs are dimensionless) |
| free-stream pressure `p_inf` | 101 325 Pa (consistency with chosen T_inf and Re) |
| working fluid | air, ideal gas, γ = 1.4, R = 287.058 J/(kg·K) |
| viscosity model | Sutherland (μ_ref = 1.716e-5, T_ref = 273.15 K, S = 110.4 K) |
| Pr_lam / Pr_turb | 0.72 / 0.90 |
| boundary-layer state | fully turbulent |

The flow is transonic with a clearly-defined lambda-shock pattern on
the suction (upper) side: an inboard front shock and a stronger
outboard rear shock that merge near `2y/b ≈ 0.8`. Resolving the
double-shock requires a chordwise mesh of at least ~120 points and
y+ ≤ 1 in the wall-normal direction.

## Boundary conditions

- **Wing surface**: no-slip, adiabatic.
- **Symmetry plane** (`y = 0`, semi-span calculation): symmetry / Euler slip.
- **Far-field**: characteristic-based (Riemann-invariant) inflow /
  outflow, ≥ 15 root chords from the wing in all unobstructed
  directions.
- The agent meshes the volume from CAD / parametric definition.

## Required mesh discipline

- Surface mesh resolves the leading-edge curvature and the suction-
  side shock band (`x/c ∈ [0.2, 0.8]`) without flattening the
  lambda-shock kink.
- Wall-normal `y+ ≤ 1` (low-Re wall integration) or wall-function
  with `y+ ∈ [30, 100]` and a turbulence model that supports the
  chosen approach.
- Aim for a mesh in the 1–6 M cell range (single-block hex or
  unstructured tet/hex hybrid both acceptable). The AIAA Drag
  Prediction-Workshop-style ONERA M6 grids span 0.9 M (coarse) to
  ~13 M (fine); any cell count in `[5e5, 2e7]` is physically
  defensible.

## Required output

Write `/tmp/agent/result.json`. Each KPI is a JSON object
`{"value": <number>, "source": {...}}`; the verifier re-extracts the
value from the declared source and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the streamwise momentum equation at end of solve |
| `cl` | lift coefficient on the (semi-span) wing, normalised by `0.5·ρ_∞·U_∞²·S_ref` (use `S_ref = 0.7532 m²` — semi-span area). Lift on the full wing is identical to lift on the semi-span when scaled by twice the area; the scalar KPI is the dimensionless coefficient and is identical for both conventions. |
| `cd` | drag coefficient on the wing, same normalisation as `cl` |
| `cp_at_2y_b_044_xc_05` | wall pressure coefficient `Cp` on the **suction (upper)** surface at the spanwise station `2y/b = 0.44` and chordwise location `x/c = 0.50`. This is the canonical Schmitt-Charpin probe location near the foot of the rear lambda-shock. |

`Cp = (p − p_∞) / (0.5·ρ_∞·U_∞²)`. `S_ref` is the semi-span planform
area (`(c_r + c_t)/2 · b = 0.7532 m²`).

### Source kinds

- `file_extract` — value lives in a file you produced. Provide
  absolute `path` and an `extract` shell pipeline of allowed binaries
  (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).
- `sim_run_stdout` — value in captured `sim run` stdout; provide
  `run_id` and `extract`.
- `sim_run_kpi` — value in a sim-run's `parsed_output` dict; provide
  `run_id` and `field`.

### Worked example

```json
{
  "mesh_cell_count": {
    "value": 2400000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/cells:/ {print $2; exit}'"
    }
  },
  "cl": {
    "value": 0.265,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $4}'"
    }
  },
  "cp_at_2y_b_044_xc_05": {
    "value": -0.42,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/cp_section_044/cp_xc.xy",
      "extract": "awk '$1>=0.495 && $1<=0.505 && $3>0 {print $2; exit}'"
    }
  }
}
```

The `cp_at_2y_b_044_xc_05` extract assumes a sampled file with
columns `x/c, Cp, surface_flag` where `surface_flag > 0` selects the
upper (suction) surface. Equivalent post-processing (paraView script,
solver-native section probe, etc.) is fine for any solver, as long as
the resulting file is deterministically queriable by the allowed
binaries.

## Environment

You are in an empty working directory. This benchmark is solver-
neutral:

```
sim --json check              # list all installed solvers
ls $SIM_SKILLS_ROOT           # list solver playbooks
cat $SIM_SKILLS_ROOT/<solver>/SKILL.md
```

Pick any installed compressible CFD solver and any installed meshing
tool. No restriction on solver, turbulence model, mesh type, cell
count, or numerical scheme. If `sim` is on PATH, drive the solver
through it (`sim run --solver <solver> <script>` or equivalent) —
sim-cli's run record is referenced by the `sim_run_stdout` /
`sim_run_kpi` source kinds. If `sim` is not installed, call the solver
natively and use the `file_extract` source kind. The verifier scores
on KPI accuracy and source provenance, not on which launcher you used.

## Analytical-shortcut notice

ONERA M6 transonic flow has **no closed-form solution**: the
suction-side lambda-shock pattern, its merging point, and the
shock-induced trailing-edge separation are sensitive to grid,
turbulence model, and numerical dissipation. A real solver run is
required. Inviscid panel methods cannot produce a defensible `cd`
(no wave-drag without shock capture) or a defensible `Cp` at
`x/c = 0.5` (the rear shock sits in this band and is a viscous-
inviscid interaction).

## References

- **Primary geometry & data**: Schmitt, V. & Charpin, F.,
  *Pressure Distributions on the ONERA-M6-Wing at Transonic Mach
  Numbers*, AGARD AR-138, May 1979 (test points 2308 / 2310).
- **NASA TMR ONERA M6 verification**:
  https://tmbwg.github.io/turbmodels/onerawingnumerics_val.html
  (per-model: `_sa.html`, `_sst.html` etc.)
- **AIAA DPW-style force-coefficient comparison**: see TMR figures
  for SA-neg / SST-2003m / SA-RC-QCR2000 reference values.
