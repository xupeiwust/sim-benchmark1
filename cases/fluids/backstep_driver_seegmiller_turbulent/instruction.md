# Task — 2D backward-facing step, turbulent (Driver & Seegmiller 1985)

Solve the steady, subsonic, **fully turbulent** flow over a 2D
backward-facing step matching the Driver & Seegmiller 1985 experiment,
and report integral and local KPIs that compare directly to the NASA
Turbulence Modeling Resource (TMR) validation case.

> NOTE — this is the **TURBULENT** backstep (M = 0.128, Re_H ≈ 36 000).
> It is NOT the laminar Re = 5000 backstep that already lives in
> `cases/fluids/backstep_re5000/`. Confusing the two will produce
> answers that are wrong by a large margin. The expected reattachment
> length here is x/H ≈ 6.26 (turbulent), not the much shorter laminar
> value.

## Geometry

- 2D channel with a single rearward-facing step on the lower wall.
- Step height **H = 0.0127 m** (= 0.5 in).
- Channel inlet height (upstream of step) = 8 H.
- Channel outlet height (downstream of step) = 9 H. **Expansion ratio
  = 9/8 = 1.125.**
- Both upper and lower walls are viscous walls (straight, parallel,
  zero deflection — the original experiment varied the top-wall angle,
  but only the zero-angle case is used here).
- The naturally-developing turbulent boundary layer on the lower wall
  upstream of the step must reach approximately the correct thickness
  and skin friction at the step lip — i.e. boundary-layer thickness
  delta ≈ 1.5 H at x/H = 0, momentum-thickness Reynolds number
  Re_theta ≈ 5000.
- Streamwise extent: at least −110 H ≤ x/H ≤ 50 H (or equivalent
  domain that yields the correct upstream profile and a reattached,
  recovered downstream boundary layer beyond x/H = 30).
- Spanwise: 2D / empty / single-cell periodic (no spanwise variation).

## Flow conditions

| quantity | value |
|---|---|
| reference Mach number (centre-channel near x/H = −4) | 0.128 |
| Reynolds number based on step height H | ≈ 36 000 |
| Reynolds number based on inflow momentum thickness (theta) | ≈ 5000 |
| free-stream temperature | 298 K (room temperature, lab air) |
| boundary-layer state at step | fully turbulent |

The flow is **essentially incompressible**; an incompressible solver
is acceptable. If a compressible solver is used, set freestream
M = 0.128 and adjust the back-pressure so the centre-channel Mach
number near x/H = −4 matches.

## Boundary conditions

- Inflow: subsonic free-stream sufficient to produce Re_theta ≈ 5000
  and delta ≈ 1.5 H at x/H = 0. Either (a) long upstream development
  region with free-stream inflow, or (b) prescribed turbulent
  boundary-layer profile near x/H = −4. Pick one and document it.
- Outflow: subsonic outflow with back-pressure adjusted so
  M ≈ 0.128 at x/H = −4.
- Lower wall: no-slip, adiabatic.
- Upper wall: no-slip, adiabatic, **straight (zero deflection angle)**.
- Spanwise: 2D / empty / single-cell periodic.

## Reference quantities

- Length scale H = 0.0127 m (step height).
- Reference velocity U_ref = velocity at centre-channel, near x/H = −4
  (used to non-dimensionalise Cp and Cf).
- Cf = tau_w / (0.5 · rho_inf · U_ref^2).
- Cp uses the **shifted** convention: report Cp such that Cp = 0 at
  x/H ≈ 40 on the lower wall (this is the convention used in
  Driver & Seegmiller's `cp.expnew.dat` and in Eca et al.'s V&V
  workshop summaries — the second column `cp` in that file, not the
  third column `cp_orig`).

## Required output

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the momentum equation |
| `reattachment_length_xH` | x/H at which the lower-wall skin friction crosses zero downstream of the step (zero-Cf reattachment point), measured from the step face (x/H = 0). |
| `cp_min_in_recirculation` | minimum (most negative) lower-wall Cp inside the separation bubble, i.e. the minimum of Cp(x) over 0 ≤ x/H ≤ 6, using the shifted Cp convention (Cp = 0 at x/H ≈ 40) |
| `cf_recovery_at_xH_20` | lower-wall skin-friction coefficient Cf at x/H = 20 (downstream recovery region, well past reattachment) |

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
    "value": 48000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "final_residual_U": {
    "value": 8.3e-6,
    "source": {
      "kind": "sim_run_kpi",
      "run_id": "001",
      "field": "final_residual_U"
    }
  },
  "reattachment_length_xH": {
    "value": 6.21,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0 {x=$1/0.0127; cf=$4; if (prev_cf<0 && cf>=0) {print prev_x + (0-prev_cf)/(cf-prev_cf)*(x-prev_x); exit} prev_x=x; prev_cf=cf}'"
    }
  },
  "cp_min_in_recirculation": {
    "value": -0.187,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallCp/0/wall.raw",
      "extract": "awk 'NR>1 && $1>=0 && $1<=6*0.0127 {if ($4<m || NR==2) m=$4} END {print m}'"
    }
  },
  "cf_recovery_at_xH_20": {
    "value": 2.05e-3,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/wallShearStress/0/wall.raw",
      "extract": "awk 'NR>1 {x=$1/0.0127; if (x>=19.8 && x<=20.2) {sum+=$4; n++}} END {if (n) print sum/n}'"
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

There is no closed-form solution for a turbulent separating /
reattaching shear layer. The reattachment length, recirculation Cp
trough, and downstream Cf recovery all depend on turbulence-model
behaviour in the free shear layer and post-reattachment recovery —
none can be inferred from flat-plate or laminar correlations. Real
solver run required.

## Reference

- NASA Turbulence Modeling Resource — 2D Backward Facing Step:
  https://turbmodels.larc.nasa.gov/backstep_val.html
  (M = 0.128, Re_H ≈ 36 000, expansion ratio 1.125).
- Experiment: Driver, D. M. and Seegmiller, H. L., "Features of
  Reattaching Turbulent Shear Layer in Divergent Channel Flow,"
  AIAA Journal, Vol. 23, No. 2, Feb 1985, pp. 163-171.
  https://doi.org/10.2514/3.8890
- Reference data files (downloaded from TMR):
  - `Backstep_validation/cp.expnew.dat` (revised 2014-02-28) — Cp
    along bottom and top walls; column 2 is the shifted Cp used
    here.
  - `Backstep_validation/cf.exp.dat` (revised 2015-10-17) — Cf along
    bottom wall, including x/H = 20.196 → Cf = 2.02e-3 ± 0.141e-3.
  - Reattachment x/H = 6.26 ± 0.10 (laser oil-flow interferometer
    measurement, quoted directly on TMR's `backstep_val.html`).
