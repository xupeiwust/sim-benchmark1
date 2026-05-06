# Task — summing op-amp amplifier

Build, simulate, and characterise an **inverting summing amplifier**
that takes two AC inputs at different frequencies and produces a
weighted-sum output. Report the peak output magnitude.

## Topology

```
  V1 ──[R1]──┐
              │
  V2 ──[R2]──┼── invnode ──[R_f]── out
              │      │
              │   op-amp ──── out
              │      │
              0    vin+ = 0
```

The op-amp's inverting input collects current from both inputs (via
R1 and R2), and feeds back through R_f to the output. Non-inverting
input is grounded.

## Op-amp model

Use **LT1001** from `LTC.lib`:

```
.lib LTC.lib
XU1 0 invnode vcc vee out LT1001    ; vin+=0, vin-=invnode
```

## Component values

| component | value |
|---|---|
| Source `V1` | sine 200 mV peak, 1 kHz |
| Source `V2` | sine 100 mV peak, 2 kHz |
| `R1` | 10 kΩ (V1's input resistor) |
| `R2` | 5 kΩ (V2's input resistor) |
| `R_f` | 10 kΩ (feedback) |
| `V_pos` (`vcc`) | +15 V |
| `V_neg` (`vee`) | -15 V |

Each input gain: `-R_f/R_n`. So V1 → -1 (gain -1), V2 → -2.
Output `V(out) = -V1 - 2·V2` (inverting sum).

## Analysis

Transient ≥ 5 ms (covers ≥ 5 cycles of the 1 kHz V1 input).

## Required output

Two KPIs (plus sim_completed):

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if transient ran without errors | flag |
| `vout_pk` | peak `|V(out)|` over the steady-state window (last 3 ms) | V |
| `vout_avg` | time-average of `V(out)` over the same window (≈ 0 V — both inputs are zero-mean) | V |

Suggested `.meas`:

```spice
.meas tran vout_pk  MAX abs(V(out)) FROM 2m TO 5m
.meas tran vout_avg AVG V(out) FROM 2m TO 5m
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
  "vout_pk": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "vout_pk"
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
  "vout_pk": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.vout_pk.value'"
    }
  }
}
```

Adjust the `value` and KPI names to match what you measured. The
`file_extract` fallback, if you use it, must start with one of the
allowed binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).

## Note

Worst-case peak occurs when V1 and V2 are both at their peak
(combined waveform peaks ≤ |V1_pk · g1| + |V2_pk · g2| =
0.2·1 + 0.1·2 = 0.4 V; depending on phase alignment the actual
peak may be smaller). Mean ≈ 0 V (inputs are zero-mean sines).

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

