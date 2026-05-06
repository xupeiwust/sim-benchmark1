# Task — NACA 4412 trailing-edge separation at maximum lift (Coles & Wadcock 1979)

Solve the steady, near-incompressible turbulent flow over a 2D NACA
4412 airfoil at the Coles & Wadcock 1979 maximum-lift condition, where
the upper-surface boundary layer experiences a strong adverse pressure
gradient and undergoes massive trailing-edge separation. Report
integral force coefficients, a mid-chord upper-surface pressure value
(in the APG zone, well before separation), and the upper-surface
separation point.

This is the NASA TMR `naca4412sep_val` validation case. It is
deliberately turbulence-model-sensitive: published CFD results on the
TMR span CL ~ 1.62 (SST) to ~ 1.72 (SA), and the upper-surface
separation point varies by ~0.05 c between models. The experimental
reference is Coles & Wadcock's flying-hot-wire campaign at "maximum
lift" — the airfoil is past the linear-lift regime, near stall.

## Geometry

A 2D NACA 4412 airfoil at chord c = 0.9012 m (the experimental chord;
non-dimensional results are scaled by c, so any chord works as long as
your Re is correct). The 4-digit NACA 4412 surface is defined by the
standard NACA-4-digit camber + thickness construction with maximum
camber 4 % c at x/c = 0.4 and maximum thickness 12 % c. A
sharp-trailing-edge variant is acceptable; the canonical TMR grid uses
the closed-trailing-edge form. The airfoil is rotated to alpha = 13.87
deg about the leading edge (or any pivot — only the relative
orientation matters for the integral coefficients).

## Flow conditions

| quantity | value |
|---|---|
| free-stream velocity | 27.13 m/s |
| chord | 0.9012 m |
| kinematic viscosity | 1.605 × 10⁻⁵ m²/s (0.1605 cm²/s) |
| chord Reynolds number | 1.52 × 10⁶ |
| free-stream Mach | ~ 0.08 (treat as essentially incompressible) |
| angle of attack | 13.87 deg |
| boundary-layer state | fully turbulent (no laminar zone modelled) |

## Boundary conditions

- Airfoil surface: no-slip, adiabatic.
- Far-field: characteristic-based / Riemann invariant, ≥ 100 c from the
  airfoil to keep blockage and circulation-image effects negligible.
- 2D (single-cell-thick spanwise slab is acceptable).

Run a single steady solve at alpha = 13.87 deg. With massive separation,
strict steady convergence to machine zero is unrealistic; aim for at
least 4 orders of residual drop, with the last several hundred
iterations stationary (no growing oscillation).

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts from the source and compares. Bare numbers are
rejected.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | final residual of the momentum equation at end of solve |
| `cl` | lift coefficient at alpha = 13.87 deg, normalised by 0.5·ρ_∞·U_∞²·c |
| `cd` | drag coefficient at alpha = 13.87 deg, same normalisation |
| `cp_at_xc_06_upper` | wall Cp on the **upper** (suction) surface at x/c = 0.6 (linearly interpolate between your two nearest wall-data x/c samples that bracket 0.6) |
| `separation_xc_upper` | x/c on the upper surface where wall skin friction Cf first crosses from positive to negative (linearly interpolate; the value should be < 1.0 — separation lies on the airfoil, not in the wake) |

### Source kinds

- `file_extract` — value lives in a file you produced. Provide absolute
  `path` and an `extract` shell pipeline of allowed binaries
  (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq) that prints the
  number to stdout.
- `sim_run_stdout` — value is in the captured stdout of a specific
  `sim run`; provide `run_id` and an `extract` pipeline.
- `sim_run_kpi` — value is in a sim run's `parsed_output` dict (set when
  your script prints a final JSON line). Provide `run_id` and `field`.

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
  "cl": {
    "value": 1.69,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $4}'"
    }
  },
  "cp_at_xc_06_upper": {
    "value": -0.74,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallPressure_upper/wall_cp.dat",
      "extract": "awk '$1>0.55 && $1<0.65 {x[NR]=$1; cp[NR]=$2} END {for (i in x) {if (x[i]<=0.6 && (i+1) in x && x[i+1]>=0.6) {f=(0.6-x[i])/(x[i+1]-x[i]); printf \"%.4f\\n\", cp[i]+f*(cp[i+1]-cp[i]); exit}}}'"
    }
  },
  "separation_xc_upper": {
    "value": 0.84,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress_upper/wall_cf.dat",
      "extract": "awk '$1>0.6 {if (prev_cf>0 && $2<=0) {f=prev_cf/(prev_cf-$2); printf \"%.4f\\n\", prev_x+f*($1-prev_x); exit} prev_x=$1; prev_cf=$2}'"
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

Pick any installed CFD solver and any installed meshing tool. No
restriction on solver, turbulence model, mesh type, cell count, or
numerical scheme. If `sim` is on PATH, drive the solver through it
(`sim run --solver <solver> <script>` or equivalent) — sim-cli captures
a run history that the `sim_run_stdout` and `sim_run_kpi` source kinds
reference. If `sim` is not installed in this container, invoke the
solver natively and use the `file_extract` source kind for every KPI.
The verifier scores on KPI accuracy and source provenance, not on which
launcher you used.

## Analytical-shortcut notice

At alpha = 13.87 deg the NACA 4412 is **past the linear-lift regime,
near maximum lift**. Thin-airfoil theory predicts CL = 2π·sin(α) ≈ 1.50
plus a NACA-4412 zero-lift offset of ~0.45 (giving roughly 1.95 from
naive 2π·α + zero-lift correction). Coles & Wadcock measured the
airfoil at maximum lift, where viscous unloading from the trailing-edge
separation pulls CL down — published RANS predictions on this exact
case land in the range 1.62 (k-ω SSTm) to 1.72 (Spalart-Allmaras),
which is the band the verifier accepts.

Hard-coding any of:

- thin-airfoil CL = 2π sin(α)
- NACA 4412 ideal CL ≈ 1.50 (the linear-extrapolation value)
- a tabulated XFOIL polar value

will fail the CL tolerance, and there is no closed-form prediction at
all for CD (viscous + form drag at separation), the upper-surface Cp at
x/c = 0.6 (set by the displacement-thickness growth and trailing-edge
back-pressure), or the separation x/c (set by the turbulence model's
APG response). The agent **must** run the solver to satisfy any of the
last four KPIs.

## Reference

- Coles, D. & Wadcock, A. J. (1979). "Flying-Hot-Wire Study of Flow Past
  an NACA 4412 Airfoil at Maximum Lift." *AIAA Journal*, Vol. 17, No.
  4, pp. 321–329.
- Wadcock, A. J. (1979). "Structure of the Turbulent Separated Flow
  Around a Stalled Airfoil." NASA-CR-152263.
- NASA Turbulence Modeling Resource — NACA 4412 trailing-edge separation
  validation: https://tmbwg.github.io/turbmodels/naca4412sep_val.html
- Reference data files (linked from TMR per-model pages):
  `naca4412.cp.expt.dat` (experimental surface Cp),
  `naca4412-flowfield-expt-dat.zip` (flowfield),
  `exp.profiles.new.dat` (boundary-layer profiles).
