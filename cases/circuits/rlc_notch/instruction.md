# Task — loaded series LC notch filter, capacitor selection

Build, simulate, and characterise a **loaded series LC notch
(band-stop) filter**, in which a series LC pair shunts the signal path
to ground near resonance. Sweep candidate trap capacitors and choose the
one that gives the deepest 5.033 kHz notch.

## Topology

```
  in --[R_s]-- out --[Rload]-- 0
                     │
                    [L]
                     │
                    [C]
                     │
                     0
```

`V1 (AC 1)` drives `in` through source resistor `R_s`. The series LC
pair (`L` + `C`) shunts the loaded output node. Output node `out` is
between `R_s`, `Rload`, and the LC trap.

## Component values

| component | value |
|---|---|
| AC source `V1` | `AC 1` between `in` and `0` |
| Source resistor `R_s` | 1 kΩ |
| Load resistor `Rload` | 10 kΩ |
| Inductor `L1` | 10 mH with 0.35 Ω series resistance |
| Candidate trap capacitors `C1` | 75 nF, 91 nF, 110 nF, 130 nF |

## Analysis

Use `.step param` or equivalent repeated runs to evaluate all candidate
capacitors. Sweep 100 Hz to 100 kHz with at least 100 points/decade.
Choose the candidate that gives the deepest notch at 5033 Hz while
preserving pass-band response at 100 Hz.

## Required output

Four KPIs:

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if sweep ran without errors | flag |
| `selected_cap_nF` | selected trap capacitor value | nF |
| `dc_gain` | `|V(out)|` at 100 Hz for the selected capacitor | dB |
| `notch_depth` | `|V(out)|` at 5033 Hz for the selected capacitor | dB |

Suggested `.meas`:

```spice
.step param Ctrap list 75n 91n 110n 130n
.meas AC dc_gain     FIND mag(V(out)) AT 100
.meas AC notch_depth FIND mag(V(out)) AT 5033
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
  "dc_gain": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "dc_gain"
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
  "dc_gain": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.dc_gain.value'"
    }
  }
}
```

Adjust the `value` and KPI names to match what you measured. The
`file_extract` fallback, if you use it, must start with one of the
allowed binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).

## Note

The unloaded closed-form notch frequency is only a starting point, and
none of the candidate capacitors lands exactly on the ideal 5033 Hz
resonance. The load and inductor DCR limit the actual depth, so choose
from the candidate capacitors using a solver artifact rather than
reporting the ideal zero-output result.

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
