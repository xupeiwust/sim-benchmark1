# Task — zero-pressure-gradient turbulent flat plate, subsonic

Solve the steady flow over a smooth 2D flat plate with zero streamwise
pressure gradient, and report two integral wall-friction quantities.

## Geometry

- A flat plate extending from x = 0 to x = 2 (non-dimensional; reference
  length L = 2).
- Domain height above the plate: 1 L.
- Treat as 2D (a single-cell-thick 3D slab is also acceptable).

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | 0.2 |
| free-stream Reynolds number, per unit length | 5 × 10⁶ |
| free-stream temperature | 300 K |
| free-stream pressure | 101 325 Pa |
| boundary-layer state on the plate | fully turbulent, tripped at x = 0 |

## Boundary conditions

- Inflow (x = 0): free-stream conditions.
- Outflow (x = 2): subsonic outflow (first-order extrapolation).
- Wall (y = 0, 0 ≤ x ≤ 2): no-slip, adiabatic.
- Top (y = 1): far-field / free-stream.
- Spanwise faces: 2D / empty / periodic — whatever your solver requires.

## Required output

Write `/tmp/agent/result.json`. Each KPI is an object with `value` and a
`source` describing where the number came from. The verifier
re-extracts from the source and compares; bare numbers are rejected.

The benchmark scores four KPIs (extras are ignored):

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation |
| `cf_x097` | local skin-friction coefficient C_f at x = 0.9700; C_f = τ_w / (0.5 · ρ_∞ · U_∞²) |
| `drag_coefficient` | integrated viscous drag, normalised by 0.5 · ρ_∞ · U_∞² · L (per unit span; ref area per span = L = 2) |

### Source kinds

- `file_extract` — value lives in a file you produced. Provide absolute
  `path` and an `extract` shell pipeline of allowed binaries
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
    "value": 40000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "final_residual_U": {
    "value": 9.1e-6,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/log.simpleFoam",
      "extract": "awk -F'Final residual = ' '/Solving for Ux,/ {print $2}' | awk '{print $1}' | tail -1 | tr -d ','"
    }
  },
  "cf_x097": {
    "value": 0.002706,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0.96 && $1<=0.98 {sum+=$4; n++} END {if(n) print sum/n}'"
    }
  },
  "drag_coefficient": {
    "value": 0.002856,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "awk 'NR>2 {x=$2} END {print x}'"
    }
  }
}
```

Do **not** include run metadata (solver name, mesh cells, residuals,
wall-time) in result.json beyond what the schema asks for —
sim-cli records run metadata separately.

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

There is no closed-form solution for the skin friction of a compressible
turbulent boundary layer at finite Reynolds. Empirical correlations
(Schlichting, Van Driest II) can be quoted but are not the same as a
wall-resolved computation and will not hit the required tolerance. You
must actually solve the flow.
