# Task — Supersonic ZPG turbulent flat plate with wall heat transfer

Solve the steady, compressible, fully turbulent boundary layer over an
**iso-thermal** flat plate at M = 5. Three wall-temperature ratios are
required. Report skin friction at fixed Re_θ stations.

## Geometry and domain

- 2D flat plate with leading edge at x = 0. Choose plate length so that
  the boundary layer reaches at least Re_θ = 11 000 by the trailing
  edge (typically x ∈ [0, 1] m at the prescribed Re/L).
- Domain height ≥ 0.3 L above the plate, sufficient that the upper
  boundary lies above the boundary-layer edge.
- 2D treatment (single-cell-thick spanwise slab is also acceptable).
- Wall-normal y⁺ < 0.5 at first cell, on the plate, at the finest grid.
  Wall-normal stretching recommended; cluster cells near x = 0.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach | **5.0** (supersonic) |
| free-stream Reynolds per unit length | 15 × 10⁶ /m |
| free-stream temperature, T_∞ | 300 K |
| free-stream pressure | 24 600 Pa (consistent with Re/L at the chosen T_∞ and Sutherland μ) |
| Prandtl number (laminar / turbulent) | 0.72 / 0.9 |
| gas | calorically perfect air, γ = 1.4, R = 287 J/(kg·K) |
| viscosity | Sutherland's law: μ_ref = 1.716 × 10⁻⁵ kg/(m·s), T_ref = 273.1 K, S = 110.4 K |
| boundary-layer state | fully turbulent from leading edge |
| **wall temperature ratios** T_w/T_∞ to run | **1.090 (cold), 2.725 (intermediate), 5.450 (≈ adiabatic-recovery)** |

## Boundary conditions

- Inflow: free-stream static conditions at M = 5.
- Outflow: supersonic outflow (first-order extrapolation; no back-pressure).
- Wall: no-slip, **iso-thermal** at T_w = (T_w/T_∞) · T_∞ for each of
  the three runs.
- Top: characteristic-based / supersonic inflow far-field consistent
  with M = 5.

Converge each case so that residuals drop ≥ 4 orders of magnitude and
are stationary (no monotonic drift) for the last 500 iterations.

## Required output

For each of the three T_w/T_∞ runs, find the x-station at which the
**momentum-thickness Reynolds number Re_θ = 10 000**, and report the
local skin-friction coefficient C_f at that station. Re_θ is defined by
integrating the local boundary-layer velocity profile:

```
θ(x) = ∫₀^∞ (ρu)/(ρ_∞ U_∞) · (1 − u/U_∞) dy
Re_θ(x) = ρ_∞ · U_∞ · θ(x) / μ_∞
C_f(x) = τ_w(x) / (0.5 · ρ_∞ · U_∞²)
```

Write `/tmp/agent/result.json`. Each KPI is `{value, source}`; the
verifier re-extracts and compares. Bare numbers are rejected.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your plate mesh (single mesh, used for all 3 Tw runs) |
| `final_residual_U` | last momentum-equation residual at the **Tw/T_∞ = 2.725** case |
| `cf_at_retheta_10000_tw1p090` | local C_f at Re_θ = 10 000 for the cold-wall case (T_w/T_∞ = 1.090) |
| `cf_at_retheta_10000_tw2p725` | local C_f at Re_θ = 10 000 for the intermediate-wall case (T_w/T_∞ = 2.725) |
| `cf_at_retheta_10000_tw5p450` | local C_f at Re_θ = 10 000 for the warm-wall case (T_w/T_∞ = 5.450) |
| `cf_at_retheta_5000_tw2p725` | local C_f at Re_θ = 5 000 for the intermediate-wall case (anchor at lower Re_θ) |

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
    "value": 80000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/Mesh has/ {print $3}' | head -1"
    }
  },
  "final_residual_U": {
    "value": 7.6e-6,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/tw2p725/log.rhoSimpleFoam",
      "extract": "awk -F'Final residual = ' '/Solving for Ux,/ {print $2}' | awk '{print $1}' | tail -1 | tr -d ','"
    }
  },
  "cf_at_retheta_10000_tw2p725": {
    "value": 0.001225,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/tw2p725/postProcessing/cf_vs_retheta.dat",
      "extract": "awk '$1>=9900 && $1<=10100 {print $2; exit}'"
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

Pick any installed compressible-CFD solver (rhoSimpleFoam / sonicFoam
in OpenFOAM, SU2_CFD, etc.). The only hard requirement: invoke the
solver through sim-cli (`sim run --solver <solver> <script>`).

## Analytical-shortcut notice

Van Driest II provides an empirical compressibility transformation of
the Karman-Schoenherr Cf(Re_θ) curve for ZPG flat plates. The
transformation involves Tw/T_aw and recovery-factor-corrected
adiabatic-wall temperature. Memorising the numerical correlation curve
is technically possible — but the per-T_w factors involve
Crocco-Busemann temperature integrals that are awkward to bottom-line
without calculus. To win the tolerance bar reliably, run the
compressible RANS solve.

## Reference

- Van Driest, E. R. (1956). The Problem of Aerodynamic Heating.
- Karman-Schoenherr incompressible Cf(Re_θ) baseline.
- NASA Turbulence Modeling Resource:
  https://tmbwg.github.io/turbmodels/ZPGflatplateSS_val.html
- Reference data file:
  https://tmbwg.github.io/turbmodels/ZPGflatplateSS_validation/cf_vandriestII.dat
