# cases/circuits/

Analog/power-electronics circuit cases (SPICE-class). The second domain
to ship after fluids, opened with the bridge-rectifier case.

All cases here follow the same **solver-neutral by construction** rule
as `cases/fluids/` — instruction.md describes only the topology, the
component values, and the physical KPIs; the agent discovers the
installed circuit simulator via `sim --json check` and picks one.

## Design principles

Identical to `cases/fluids/README.md` — see there for the canonical
statement. Three invariants:

1. **Pure physics, no launcher mandate**: instruction.md describes the
   topology, component values + models, KPI physics, and provenance
   contract. Agents may use `sim run`, direct LTspice batch, or portable
   parsing helpers as long as the reported values are reproducible.
2. **Real solver artifacts required**: scoring is based on KPI accuracy
   and source provenance, not on agent-side sim-cli usage. Solver logs,
   `.meas` output, `.raw` data, or sim-cli run records must be produced by
   an actual circuit simulation, not hand-written to satisfy extraction.
3. **KPIs with provenance**: each KPI in `result.json` carries
   `value` + `source`; verifier re-runs the agent's `extract` pipeline.

## How to add a new circuits case

```
cases/circuits/<case_id>/
├── instruction.md          # physics-only prompt; topology + component values
├── task.toml               # Harbor schema_version = "1.1" + [metadata.sim]
├── environment/
│   └── Dockerfile          # FROM svd-ai-lab/sim-benchmark-wine-base:latest
├── solution/
│   ├── solve.sh            # oracle entry
│   ├── case/<id>.net       # canonical netlist (oracle-only; agent writes its own)
│   └── build_result.py     # oracle's result.json builder
└── tests/
    ├── test.sh             # exec python3 -m sim_benchmark_verifier.score
    └── kpis.json           # per-KPI {gt_value, T_good, T_bad, ...}
```

The base image differs from fluids: circuits use `sim-benchmark-wine-base`
(Ubuntu + wine + LTspice 26 + sim-cli + verifier + sim-skills) instead
of `sim-benchmark-base` (OpenFOAM stack).

`task.toml` must declare:

```toml
[metadata.sim]
solver          = "neutral"        # property: agent self-selects
source_type     = "vv_standard"    # paper | vv_standard | novel_variant
source_citation = "..."            # textbook / V&V dataset that produced gt_value
difficulty_tier = "S"
```

Then `python tools/lint_case.py cases/circuits/<case_id>` to validate.

## Current contents

| Case | Tier | Source | KPIs |
|---|---|---|---|
| `bridge_rectifier_ripple` | S | Mohan, Undeland, Robbins (2003) Ch. 5 — high-fidelity-solver GT | sim_completed, vout_avg, vrip_pp |

## Anti-shortcut focus for circuits

Power-electronics textbooks publish closed-form approximations for most
canonical circuits (V_dc = V_pk for bridge rectifier, time constants for
RC filters, etc.). These approximations are **off by 15-30% from the
real silicon-diode + finite-RC reality**. The verifier's `T_bad` bounds
in `kpis.json` are tight enough to reject the textbook formula and
require the SPICE solve.

When proposing a new circuits case, demonstrate in the issue that the
analytical shortcut misses by more than the verifier tolerance — see
`bridge_rectifier_ripple/instruction.md`'s "Analytical-shortcut notice"
section for the canonical wording.

See the top-level [`SCHEMA.md`](../../SCHEMA.md) for the contract that every
circuits case must satisfy.
