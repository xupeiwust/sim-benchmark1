# Task — second-order RLC step response (overdamped)

Build, simulate, and characterise an **overdamped series RLC step
response** (large damping resistance, no overshoot). Report the
settled output and the time to reach 90 % of settled value.

## Topology

```
  in ──[R]── a ──[L]── out
                       │
                      [C]
                       │
                       0
```

V1 drives `in` with a step from 0 → 1 V; output across `C`.

## Component values

| component | value |
|---|---|
| Source `V1` | step `PULSE(0 1 0 1n 1n 1 2)` |
| Resistor `R` | 2 kΩ (large for overdamped) |
| Inductor `L` | 10 mH |
| Capacitor `C` | 100 nF (initial voltage 0) |

ζ = R/2 · √(C/L) ≈ 3.16 (overdamped, no overshoot).

## Analysis

Transient long enough to settle. With ζ=3 the slow root dominates, so
≈ 5 ms is plenty.

## Required output

Three KPIs:

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if transient ran without errors | flag |
| `vss` | settled `V(out)` averaged over the last 1 ms | V |
| `t90` | time at which `V(out)` first reaches 0.9 V (90 % of vss) | s |

Suggested `.meas`:

```spice
.meas tran vss AVG V(out) FROM 4m TO 5m
.meas tran t90 WHEN V(out)=0.9 RISE=1
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
  "vss": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "vss"
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
  "vss": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.vss.value'"
    }
  }
}
```

Adjust the `value` and KPI names to match what you measured. The
`file_extract` fallback, if you use it, must start with one of the
allowed binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).

## Note

For overdamped RLC the response is two decaying exponentials with no
oscillation. Settling time depends on the slower root; expect t90 in
the few-ms range.

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

