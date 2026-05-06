# Task — 30P30N three-element high-lift airfoil (JAXA APC-IV)

Solve the steady, low-speed turbulent flow over the 30P30N
three-element high-lift airfoil (deployed slat + main + flap) at the
JAXA Aerodynamics Prediction Challenge IV (APC-IV) test point, and
report integral force coefficients plus the peak suction Cp on the
slat upper surface.

## Configuration

- "30P30N" denotes a three-element configuration with a 30° slat
  deflection and a 30° flap deflection.
- The reference geometry is the JAXA APC-IV configuration (modified
  slat configuration "F"). It defines absolute element positions
  (gap, overlap) for slat, main, and flap relative to the stowed
  reference chord.
- Stowed reference chord `c_stow = 0.5588 m` (used for Re and as the
  CL/CD normalisation length).
- The configuration is 2D / single-cell-thick spanwise slab; no 3D
  finite-span effects.

The agent must obtain the geometry. Two acceptable paths:

1. **Direct mesh use (preferred)** — use one of the JAXA APC-IV
   meshes shipped with the SU2 V&V repository. They live under
   `/opt/vv/30p30n/` inside the container as gzipped SU2 unstructured
   meshes, five refinement levels:

   ```
   /opt/vv/30p30n/2D_L1_coarse_r1.su2.gz       (~0.3 M cells)
   /opt/vv/30p30n/2D_L2_medium_r1.su2.gz       (~0.6 M cells)
   /opt/vv/30p30n/2D_L3_fine_r1.su2.gz         (~1.4 M cells)
   /opt/vv/30p30n/2D_L4_extra-fine_r1.su2.gz   (~3.0 M cells)
   /opt/vv/30p30n/2D_L5_super-fine_r1.su2.gz   (~5.6 M cells)
   ```

   `gunzip` and use `L2` or `L3` as a baseline; converters to other
   solvers' formats are an agent responsibility.

2. **Fetch CGNS from JAXA** — original APC-IV meshes are publicly
   available at
   `https://cfdws.chofu.jaxa.jp/apc/grids/3element_highlift_airfoil/30P30N_modified_slat_configF/cgns/`
   if the agent prefers a different topology / level. Internet access
   is permitted by `task.toml` for this case.

The agent may also build its own mesh from element coordinates if it
prefers; in that case it is responsible for honouring the modified-F
slat configuration (gap/overlap) — the SU2 / JAXA reference grids are
the authoritative geometry source.

## Flow conditions

| quantity | value |
|---|---|
| free-stream Mach `M_inf` | 0.17 |
| Reynolds number (based on stowed chord) | 1.71 × 10⁶ |
| free-stream temperature `T_inf` | 300 K (effectively any low-speed value; flow is essentially incompressible) |
| free-stream pressure `p_inf` | 101 325 Pa |
| working fluid | air, ideal gas, γ = 1.4 (or incompressible) |
| boundary-layer state | fully turbulent on all three elements |
| primary angle of attack `α` | **5.5°** (linear-regime point used by SU2 V&V and JAXA APC-IV reporting) |

The case is in the linear-lift regime; CL/CD are reported at α = 5.5°
only. The agent does not need to sweep AoA.

## Boundary conditions

- **Slat surface, main element surface, flap surface**: no-slip,
  adiabatic. The 30P30N has three independent element surfaces; on
  the SU2 mesh they are typically named `airfoil` (a single MARKER
  containing all three elements) or split into per-element MARKERs.
- **Far-field**: characteristic-based / Riemann-invariant, ≥ 100·c_stow
  away from the airfoil cluster (the SU2 V&V meshes use ≈ 200·c_stow).
- **Spanwise**: 2D / single-cell-thick / empty.

## Required mesh discipline

- Wall-normal `y+ ≤ 1` on all three elements (the SU2 V&V meshes are
  built to this standard at `L2` and finer).
- Cove regions (slat cove and main-element cove) must be resolved —
  this is the single biggest sensitivity for total CL and slat
  suction-peak prediction.
- Cell count in the range `[3e5, 6e6]` is acceptable; the SU2 V&V
  L1–L5 levels span this band and are all "valid" mesh choices.

## Required output

Write `/tmp/agent/result.json`. Each KPI is a JSON object
`{"value": <number>, "source": {...}}`; the verifier re-extracts
deterministically and compares.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in your computational mesh |
| `final_residual_U` | last residual of the streamwise momentum equation at end of the α=5.5° solve |
| `cl_at_alpha_5p5` | total lift coefficient (slat + main + flap, integrated as the configuration), normalised by `0.5·ρ_∞·U_∞²·c_stow` with `c_stow = 0.5588 m` |
| `cd_at_alpha_5p5` | total drag coefficient on the configuration, same normalisation |
| `cp_min_slat_at_alpha_5p5` | minimum (most negative) wall pressure coefficient `Cp` on the slat **upper** surface at α=5.5° (the leading-edge suction-peak; typically the most negative Cp in the entire flow field) |

`Cp = (p − p_∞) / (0.5·ρ_∞·U_∞²)`. The slat upper-surface suction
peak typically sits very close to the slat leading-edge stagnation
point on the upper side; sample `Cp(x)` densely on the slat upper
surface and report the most negative value.

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
    "value": 600000,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "awk '/cells:/ {print $2; exit}'"
    }
  },
  "cl_at_alpha_5p5": {
    "value": 2.83,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/forceCoeffs/0/coefficient.dat",
      "extract": "tail -1 | awk '{print $4}'"
    }
  },
  "cp_min_slat_at_alpha_5p5": {
    "value": -10.5,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/cp_slat/cp_slat.xy",
      "extract": "awk 'NR>1 {if ($2<m || NR==2) m=$2} END {print m}'"
    }
  }
}
```

The `cp_min_slat_at_alpha_5p5` extract assumes a sampled file
restricted to the slat upper surface (or the slat element only with
both surfaces, since the lower-surface Cp will be much higher / less
negative and will not win the minimum). Equivalent post-processing is
fine as long as the resulting file is deterministically queriable.

## Environment

You are in an empty working directory. Internet access **is** allowed
in this task (to fetch JAXA APC-IV CGNS grids if desired). The
preferred path is the bundled SU2 meshes under `/opt/vv/30p30n/`.

This benchmark is solver-neutral:

```
sim --json check              # list all installed solvers
ls $SIM_SKILLS_ROOT           # list solver playbooks
cat $SIM_SKILLS_ROOT/<solver>/SKILL.md
```

Pick any installed CFD solver (compressible-low-Mach or
incompressible) and any installed meshing tool. If `sim` is on PATH,
drive the solver through it (`sim run --solver <solver> <script>`) —
sim-cli's run record is referenced by the `sim_run_stdout` /
`sim_run_kpi` source kinds. If `sim` is not installed, call the solver
natively and use the `file_extract` source kind. The verifier scores
on KPI accuracy and source provenance, not on launcher choice.

## Analytical-shortcut notice

Multi-element high-lift CL has **no closed-form solution**. Thin-
airfoil + flap-deflection correlations (e.g. Hoerner's flap-CL
increment) cannot reproduce the slat suction peak (which is set by
inviscid leading-edge geometry plus the slat-cove recirculation), the
main-element pressure recovery (set by main-cove and slat wake
mixing), or the flap-induced CL on the main element. Drag is
dominated by viscous boundary-layer and cove dissipation and has no
analytical form. CD must come from a real solver run with three-
element y+ ≤ 1 wall resolution. The reported `cp_min_slat` is
particularly sensitive to slat leading-edge mesh resolution.

## References

- **SU2 V&V case study (RANS on JAXA APC-IV configuration F)**:
  https://su2code.github.io/vandv/30p30n/ — primary reference for
  CL(α), CD(α), and per-element Cp distributions across SA-neg /
  SST-2003m on L1–L5 meshes.
- **JAXA Aerodynamics Prediction Challenge IV (APC-IV)**:
  https://cfdws.chofu.jaxa.jp/apc/apc4/ — original test-case
  description, experimental data, and CGNS grids
  (`30P30N_modified_slat_configF/cgns/`).
- **JAXA APC-IV proceedings**: JAXA-SP-18-008, "Proceedings of the
  Aerodynamics Prediction Challenge (APC-IV)", 2019 (paper-tabulated
  experimental CL/CD and Cp at α=5.5° for the modified-slat
  configuration F; APC-IV reference data is distributed in tar.gz
  archives at JAXA's challenge site).
- Reference KPI values + tolerances in `tests/kpis.json` (verifier-
  side; not exposed to the agent).
