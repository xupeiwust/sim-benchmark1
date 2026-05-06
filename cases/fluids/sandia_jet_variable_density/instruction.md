# Task — Sandia variable-density propane–air turbulent jet

Solve the steady, incompressible-variable-density, **non-reacting**,
**non-premixed** turbulent jet of pure propane (C₃H₈) issuing into
co-flowing air, and report centreline velocity / propane mass-fraction
decay plus the jet half-width on a 2-D axisymmetric grid. This is the
Schefer / Sandia experimental benchmark used by the SU2 V&V suite
(propane–air variable-density jet).

## Geometry

- 2-D axisymmetric round jet — symmetry axis at y=0, jet enters from
  the left through a circular nozzle of inner diameter
  **D = 5.26 mm**, surrounded by an annular co-flow of air.
- Domain length ≥ 80·D streamwise, ≥ 20·D radial; outer radial wall
  treated as slip / Euler.
- Inlet plane is the nozzle exit (no internal-pipe geometry required).

The agent provides its own mesh. A reference SU2 mesh
(`MESH_validation.su2` from the SU2 V&V repository) covering this
domain has roughly 67 000 cells; any grid with 30 000–500 000 cells
plus near-axis / shear-layer refinement is acceptable.

## Flow conditions

| stream | quantity | value |
|---|---|---|
| jet  | bulk velocity (uniform inlet) | 53.0 m/s |
| jet  | composition | pure propane (Y_C₃H₈ = 1) |
| jet  | turbulence intensity | 4 % |
| jet  | eddy-viscosity ratio | 5 |
| jet  | Re_D = ρ_jet U_jet D / μ_jet | ≈ 68 000 |
| coflow | velocity | 9.2 m/s |
| coflow | composition | air (Y_C₃H₈ = 0) |
| coflow | turbulence intensity | 0.4 % |
| coflow | eddy-viscosity ratio | 0.1 |

Common conditions:

| quantity | value |
|---|---|
| temperature | 294 K (energy equation off) |
| thermodynamic pressure | 101 325 Pa |
| density model | **variable** — composition-dependent, ideal-gas mixing |
| MW(C₃H₈), MW(air) | 44.097, 28.96 g/mol |
| μ(C₃H₈), μ(air) | 8.04 × 10⁻⁶, 1.8551 × 10⁻⁵ Pa·s |
| viscosity mixing rule | Wilke (or any standard mixture rule) |
| turbulent Schmidt number | 0.7 |
| Lewis number | 1 (unity) — `Sc_t ≈ Pr_t` |
| turbulence model | **k–ω SST** (V2003m or equivalent) |

## Solver requirements

This case is **species-transport / variable-density** — pick a solver
and run mode that supports both:

- SU2: `SOLVER = INC_RANS` with `INC_DENSITY_MODEL = VARIABLE`,
  `FLUID_MODEL = FLUID_MIXTURE`, `KIND_SCALAR_MODEL = SPECIES_TRANSPORT`.
- OpenFOAM: `rhoReactingFoam` (or `reactingFoam` with `chemistry off`)
  in steady mode — a `multicomponentMixture` of `C3H8` + `air` with
  reactions disabled.
- Other solvers: any incompressible / low-Mach RANS that carries one
  passive species and updates ρ from the local mixture.

Solvers that lack species transport (e.g. `simpleFoam`) cannot model
this case correctly and will fail the propane-mass-fraction KPIs.

## Boundary conditions

- `inlet_jet`     — velocity inlet, U = 53 m/s, Y_C₃H₈ = 1.
- `inlet_coflow`  — velocity inlet, U = 9.2 m/s, Y_C₃H₈ = 0.
- `outlet`        — pressure outlet, p_gauge = 0.
- `axis`          — axisymmetric symmetry boundary at r = 0.
- `top_wall`      — far-field slip / Euler at the outer radial boundary.
- `wall` (nozzle lip, between jet and coflow inlets) — adiabatic no-slip.

## Required output

Write `/tmp/agent/result.json`. Each KPI is a JSON object
`{"value": <number>, "source": {...}}`. The verifier re-extracts the
value from the declared source and grades it.

Stations are non-dimensionalised by jet diameter D = 5.26 mm; "x" is
streamwise distance from the nozzle exit, "r" (or y in 2-D) is the
radial distance from the symmetry axis.

| key | meaning |
|---|---|
| `mesh_cell_count` | total cells in the agent's mesh |
| `final_residual_species` | last propane mass-fraction RMS residual |
| `centerline_velocity_at_xD_15` | U on the symmetry axis at x/D = 15 (m/s) |
| `centerline_velocity_at_xD_30` | U on the symmetry axis at x/D = 30 (m/s) |
| `centerline_velocity_at_xD_50` | U on the symmetry axis at x/D = 50 (m/s) |
| `centerline_propane_mass_fraction_at_xD_15` | Y_C₃H₈ on axis at x/D = 15 |
| `centerline_propane_mass_fraction_at_xD_30` | Y_C₃H₈ on axis at x/D = 30 |
| `jet_half_width_at_xD_30` | r/D where U = 0.5 · U_centerline at x/D = 30 |

The **centerline** values are sampled exactly on the symmetry axis
(r = 0). The **half-width** is the smallest positive r/D at which the
streamwise velocity equals half the centerline value at that station;
sample U(r) along a radial line at x/D = 30 and find the radius where
U crosses 0.5 · U(r=0).

### Source kinds

- `file_extract` — value lives in a file you produced (typically a
  sample-line / probe `.csv` / `.xy` / `.dat`).
- `sim_run_stdout` — value appears in captured `sim run` stdout.
- `sim_run_kpi` — value lives in a sim-run's `parsed_output` dict.

Allowed extract binaries: head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq.

### Worked example

```json
{
  "centerline_velocity_at_xD_15": {
    "value": 44.9,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/centerline/0/U_centerline.xy",
      "extract": "awk '$1>=0.0789 && $1<0.080 {print $2; exit}'"
    }
  },
  "jet_half_width_at_xD_30": {
    "value": 2.67,
    "source": {
      "kind": "file_extract",
      "path": "/root/case/postProcessing/radial_xD30/0/U_radial.xy",
      "extract": "awk 'NR==1{Uc=$2; next} ($2<=Uc/2){printf \"%.4f\", ($1-prev1)/($2-prev2)*(Uc/2-prev2)+prev1; exit} {prev1=$1; prev2=$2}'"
    }
  }
}
```

For SU2 the agent will typically write a custom `MARKER_ANALYZE` line
or post-process the `restart_*.csv` / ParaView output with `awk` /
`paraview --script`. Equivalent post-processing is fine for any other
solver, as long as the resulting file contains the queried value and
the `extract` recipe deterministically yields it.

(x/D = 15 corresponds to x = 15 · 5.26 mm = 0.0789 m; x/D = 30 to
0.1578 m; x/D = 50 to 0.263 m.)

## Environment

You are in an empty working directory with sim-cli on PATH. The case
is solver-neutral; pick any installed CFD solver that supports
species transport and variable density. Invoke the solver through
sim-cli — the verifier checks `sim --json logs` to confirm the agent
actually ran a solver.

## Analytical-shortcut notice

Variable-density jet decay does not collapse to the classical
constant-density 1/x velocity-decay law: the local density (and hence
inertia) is a function of the propane mass fraction, which is itself
the unknown. Centerline U/Y_C₃H₈ at x/D = 15…50 must be obtained from
a numerical solution of the coupled momentum + species transport
equations on a 2-D axisymmetric mesh. There is **no closed-form
shortcut** — any agent that hard-codes a similarity profile rather
than running the solver will mis-predict at least one of the radial
half-width or species-decay KPIs.

## References

- R. W. Schefer et al., *Propane Jet Data*, Sandia National
  Laboratories TNF Workshop archive (datasets 1994 / 2003).
- SU2 V&V case study: https://su2code.github.io/vandv/SANDIA_jet/
- SU2 reference configuration: `VVSandiaJet.cfg` (SU2 V&V repo,
  rans/SANDIA_jet/).
- Reference experimental values for the eight KPIs are listed in
  `tests/kpis.json` together with their tolerances and provenance.
