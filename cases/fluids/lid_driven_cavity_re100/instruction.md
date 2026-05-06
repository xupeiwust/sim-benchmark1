# Task — 2D lid-driven cavity flow, Re = 100

Solve the classic square-cavity driven-lid problem and report the
velocity profile along the vertical centreline.

## Geometry

A 2D square cavity of side L = 1 m. Origin at the bottom-left corner;
the cavity occupies 0 ≤ x ≤ 1 and 0 ≤ y ≤ 1.

## Flow conditions

| quantity | value |
|---|---|
| Reynolds number (based on lid velocity and cavity side) | 100 |
| lid velocity U_lid | 1.0 m/s in +x direction |
| kinematic viscosity ν | 0.01 m²/s (set so Re = U_lid · L / ν = 100) |
| fluid density ρ | 1.0 kg/m³ |
| flow regime | laminar, incompressible |

## Boundary conditions

- **Top wall** (y = 1, moving lid): no-slip, fixed velocity `(1, 0, 0)`.
- **Bottom wall** (y = 0): no-slip, stationary.
- **Left wall** (x = 0): no-slip, stationary.
- **Right wall** (x = 1): no-slip, stationary.
- Spanwise (z): 2D treatment (empty or single-cell periodic).
- **Pressure**: no reference pressure; zero-gradient on all walls is
  conventional.

Initialise at rest and advance to steady state (or run a transient
solver until residuals are stationary).

## Required output

Write `/tmp/agent/result.json`. Each KPI is an object with `value` and a
`source` describing where the number came from. The verifier
re-extracts from the source and compares; bare numbers are rejected.

The benchmark scores five KPIs (more is fine, extras are ignored):

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh (resolution proxy) |
| `max_non_orthogonality` | max non-orthogonality angle (degrees) from `checkMesh -allGeometry` — quality proxy; uniform structured cavity should be ~0 |
| `final_residual_p` | last residual of the pressure equation |
| `u_centerline_y0p5` | x-velocity at exactly (x=0.5, y=0.5); expected **negative** |
| `u_min_along_x0p5` | most-negative u along x=0.5 centreline (vortex peak) |

### Source kinds

- `file_extract` — value lives in a file you produced. Provide the
  absolute `path` and an `extract` shell pipeline of allowed binaries
  (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq/python3) that
  prints just the number to stdout.
- `sim_run_stdout` — value is in the captured stdout of a specific
  `sim run`; provide `run_id` and an `extract` pipeline.
- `sim_run_kpi` — value is in a sim run's `parsed_output` dict
  (set when your script prints a final JSON line). Provide `run_id`
  and `field`.

### Worked example

```json
{
  "mesh_cell_count": {
    "value": 6400,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "final_residual_p": {
    "value": 7.4e-6,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/log.simpleFoam",
      "extract": "awk -F'Final residual = ' '/Solving for p,/ {print $2}' | awk '{print $1}' | tail -1 | tr -d ','"
    }
  },
  "u_centerline_y0p5": {
    "value": -0.2058,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/sets/200/centerline_U.csv",
      "extract": "awk -F',' '$1==0.5 {print $2}'"
    }
  },
  "u_min_along_x0p5": {
    "value": -0.21,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/sets/200/centerline_U.csv",
      "extract": "awk -F',' 'NR>1 {print $2}' | sort -n | head -1"
    }
  }
}
```

Run-time metadata is recorded by sim-cli; do not duplicate in `result.json`.

## Environment

Your working directory may contain a pre-staged input file (`ls .` to
check). If `cavity.msh` is present, it is a solver-neutral 2D mesh of
the unit cavity already prepared for you — load it instead of generating
your own. The mesh has named boundary zones; query the solver's
introspection (`get_state` / `child_names` / equivalent) to discover the
exact zone names. If no pre-staged file is present, generate the mesh
yourself per the geometry above.

This benchmark is solver-neutral. Discover tools:

```
sim --json check              # list installed solvers + paths
ls $SIM_SKILLS_ROOT           # solver playbooks
```

Pick any installed CFD solver and any meshing tool. If `sim` is on
PATH, route runs through `sim run --solver <solver> <script>` to
populate sim-cli's run history (referenced by `sim_run_stdout` /
`sim_run_kpi` source kinds). If `sim` is not installed, invoke the
solver natively and use `file_extract` for every KPI.

## Analytical-shortcut notice

Published reference values (Ghia 1982 Table I) are available online. You
must not hard-code them: every KPI needs a verifiable source pointing
at a file you produced from running the solver. Quoting Ghia values
without an underlying mesh + solve fails source-verification (the
extract pipeline returns no value or the wrong one).
