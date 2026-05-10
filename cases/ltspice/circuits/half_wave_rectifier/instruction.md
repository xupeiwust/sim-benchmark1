# Task — single-diode half-wave rectifier with capacitor smoothing

Build, simulate, and characterise a **half-wave rectifier**: a single
diode driven by an AC source, feeding a smoothing capacitor in
parallel with a resistive load. Report the average DC output and the
peak-to-peak ripple.

## Topology

```
  in ──[D1]──┬─── p   (DC + rail; output node)
             │
             │ C ─── 0
             │ R ─── 0
             │
             0   (returned via the source's negative rail)
```

The AC source `V1` is between `in` and `0`; the diode `D1` conducts
only when `V(in) > V(p) + Vf`, so the cap charges only during the
positive half-cycle and discharges through R the rest of the time.

## Component values

| component | value |
|---|---|
| AC source `V1` | sinusoidal between `in` and `0`, 12 V peak amplitude, 60 Hz, 0 V offset, no phase delay |
| Diode `D1` | use a real silicon-rectifier model — **1N4007** (Is≈14 nA, Rs≈34 mΩ, N≈2). Do not use `.model` defaults |
| Smoothing capacitor `C` | 470 µF, IC=0 |
| Load resistor `R` | 100 Ω |

## Analysis

Transient long enough for steady-state. τ = R·C = 47 ms, so ≥ 5τ
≈ 235 ms is needed for settling. A 500 ms run is comfortable.

## Required output

Three KPIs:

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if transient ran without `***` errors | flag |
| `vout_avg` | time-average of `V(p)` over a steady-state window of at least 16.7 ms (one line cycle) | V |
| `vrip_pp` | peak-to-peak excursion of `V(p)` over the same steady-state window | V |

Suggested `.meas`:

```spice
.meas tran vout_avg AVG V(p) FROM 450m TO 500m
.meas tran vrip_pp  PP  V(p) FROM 450m TO 500m
```

### Source kinds & worked example

<!-- v19-worked-example-rewritten -->

The verifier accepts several source kinds for each KPI. Prefer
`ltspice_log`: it parses the native `.log` directly, including scalar
`.meas` output, stepped `Measurement:` tables, AC complex dB values, and
completion status. Use `file_extract` only as a fallback for custom
post-processing or non-LTspice artifacts.

**Path A — `ltspice_log` against LTspice's `.log` (preferred).** Point
`path` at the log produced by the LTspice run. For stepped `.meas`
tables, add `"step": <1-based row>`. For a selected `.step` parameter
value, use `"query": "step_param"` with `param`, `step`, and optional
`scale`.

```json
{
  "sim_completed": {
    "value": 1,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "completed"
    }
  },
  "vout_avg": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "vout_avg"
    }
  }
}
```

**Path B — `sim_run_stdout` against sim-cli's parsed JSON** (only works
when `sim` CLI + sim_ltspice driver are installed in the container).
sim_ltspice parses the `.log` and appends a JSON line to the run's
stdout containing a `measures` dict keyed by `.meas` name; one-liner
extracts via `tail -1 | jq -r`:

```json
{
  "sim_completed": {
    "value": 1,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r 'if .errors == [] then 1 else 0 end'"
    }
  },
  "vout_avg": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.vout_avg.value'"
    }
  }
}
```

Adjust the `value` and KPI names to match what you measured. The
`file_extract` fallback, if you use it, must start with one of the
allowed binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).

## Note

Closed-form half-wave: V_dc ≈ V_pk - Vf - V_ripple/2; ripple V_r ≈
I_load/(C·f) where f = 60 Hz. With V_pk=12, Vf≈0.7-0.9, R=100, C=470µ
expect V_dc ≈ 9-10 V and ripple a few volts. Real diode + finite
charging current shifts these by 10-20 %; the simulator captures the
exact numbers.

## Provenance and authenticity

Report only values that can be re-extracted from artifacts produced during
your run. For LTspice cases, the preferred artifact is the native `.log`
file, `.raw` data if you post-process it, or a sim-cli run record generated
by running LTspice on the netlist you created.

Do not hand-write, edit, or fabricate solver logs, `.meas` output, `.raw`
data, or sim-cli run records to satisfy provenance. Values copied from a
formula, from the prompt, or from memory without a produced artifact score
zero because the verifier re-runs the declared extraction. If the simulation
fails, report only failure/status values that can be verified from the log
that was actually produced; leave unavailable output KPIs absent rather than
inventing them.

## Environment
<!-- v19-uniform-discovery -->

You are in an empty working directory. **Before doing anything else,
introspect the container** to discover what tools are available — the
v19 evaluation runs each case across 4 different containers
(`bare`/`lib`/`launcher`/`full`) that ship different subsets of the
sim ecosystem, and what's installed differs per container:

```bash
command -v sim wine-ltspice              # which launchers are on PATH?
pip list 2>/dev/null | grep -iE 'sim|ltspice'   # which Python sim libs?
ls ~/.claude/skills 2>/dev/null          # which Claude Code skills auto-loaded?
ls $SIM_SKILLS_ROOT 2>/dev/null          # alt skill mount path (if set)
which iconv tr awk grep jq               # text-processing primitives
```

Use whatever you find. The verifier scores you on KPI accuracy and
source provenance (`ltspice_log` / `file_extract` / `sim_run_stdout` /
`sim_run_kpi`) -- NOT on which launcher you used. Notes on the source
kinds:

- **`ltspice_log`** -- preferred for LTspice. Point `path` at the native
  `.log` and use `query="completed"`, `query="measure"` with a
  `.meas` name, or `query="step_param"` for a selected `.step` value.
- **`file_extract`** -- fallback for custom post-processed files or
  non-LTspice artifacts. `extract` is a shell pipeline of allowed
  binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).
- **`sim_run_stdout`** / **`sim_run_kpi`** -- only work when `sim` is on
  PATH (it queries `sim --json logs <run_id>` to verify provenance).
  In containers without sim-cli, the Stop hook will block these and
  point you to `ltspice_log` or `file_extract`.

