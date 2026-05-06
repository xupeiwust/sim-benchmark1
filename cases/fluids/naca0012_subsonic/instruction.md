# Task — NACA 0012 airfoil, subsonic turbulent

Predict the steady aerodynamic performance of a NACA 0012 airfoil in
fully-turbulent subsonic flow over a sweep of angles of attack, and
report integral force coefficients.

## Geometry

A 2D airfoil with NACA 0012 cross-section, chord length c = 1 m, with
sharp closed trailing edge. Surface defined by the modified NACA
4-digit formula:

```
y/c = ± 0.594689181 · [ 0.298222773·√(x/c)
                      − 0.127125232·(x/c)
                      − 0.357907906·(x/c)²
                      + 0.291984971·(x/c)³
                      − 0.105174606·(x/c)⁴ ]
```

x/c runs from 0 at the leading edge to 1 at the trailing edge. Maximum
thickness ≈ 11.89 % c. The airfoil is centred at the origin with the
chord along the x-axis at α = 0.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.15 |
| chord Reynolds number | 6 × 10⁶ |
| free-stream temperature | 300 K |
| free-stream pressure | 101 325 Pa |
| boundary-layer state | fully turbulent (tripped at leading edge) |

Run the airfoil at angles of attack α ∈ {0°, 4°, 8°, 10°, 12°} (five
separate steady solves) and report force coefficients at each.

## Boundary conditions

- Airfoil surface: no-slip, adiabatic.
- Far-field: characteristic-based / Riemann invariant, ≥ 100 c from the
  airfoil to keep blockage negligible.
- 2D (single-cell-thick spanwise slab is also acceptable).

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts from the source and compares. Bare numbers are
rejected.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation at α = 8° |
| `CL_at_alpha_4` | lift coefficient at α = 4°, normalised by 0.5·ρ_∞·U_∞²·c |
| `CL_at_alpha_10` | lift coefficient at α = 10° |
| `CL_at_alpha_12` | lift coefficient at α = 12° |
| `CD_at_alpha_4` | drag coefficient at α = 4° |
| `CD_at_alpha_10` | drag coefficient at α = 10° |
| `CL_alpha_slope_per_deg` | linear-regression slope of CL vs α (°), regressed on the data points α ∈ {0, 4, 8} |

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
    "value": 65000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "final_residual_U": {
    "value": 8.4e-6,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/alpha_8/log.simpleFoam",
      "extract": "awk -F'Final residual = ' '/Solving for Ux,/ {print $2}' | awk '{print $1}' | tail -1 | tr -d ','"
    }
  },
  "CL_at_alpha_10": {
    "value": 1.072,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/alpha_10/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $4}'"
    }
  },
  "CL_alpha_slope_per_deg": {
    "value": 0.1085,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/CL_alpha_table.dat",
      "extract": "awk 'NR==1 {a0=$1; CL0=$2} NR==3 {a8=$1; CL8=$2} END {printf \"%.6f\\n\", (CL8-CL0)/(a8-a0)}'"
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

Thin-airfoil theory predicts CL = 2π·α (with α in radians), giving a
lift-curve slope of ≈ 0.1097/deg. This is **not** sufficient to satisfy
the tolerance: the real NACA 0012 at Re = 6 × 10⁶ has CL_α ≈ 0.109/deg
(modified by viscosity, finite thickness, and trailing-edge separation
near stall), and CD has no closed-form prediction at all — viscous drag
requires resolving the boundary layer. Memorising correlations will
score on slope but fail on CD and on the off-linear CL points.

## Reference

- Ladson, C. L. (1988). *Effects of Independent Variation of Mach and
  Reynolds Numbers on the Low-Speed Aerodynamic Characteristics of the
  NACA 0012 Airfoil Section*. NASA TM-4074.
- NASA Turbulence Modeling Resource:
  https://tmbwg.github.io/turbmodels/naca0012_val.html
