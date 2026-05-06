# Task — series RLC band-pass filter, AC frequency response

Build, simulate, and characterise a textbook **series RLC band-pass
filter** in small-signal AC analysis, and report two scalar KPIs that
describe its frequency response.

## Topology

Series chain from the AC source through L, C, and R, with the output
voltage taken across the resistor:

```
  in ──[L]── a ──[C]── out
                       │
                      [R]
                       │
                       0
```

The AC source `V1` drives node `in` against ground (`0`).

## Component values

| component | value |
|---|---|
| AC source `V1` | small-signal `AC 1` between `in` and `0` (1 V amplitude, used for AC sweep — phase and DC offset don't affect the magnitude response) |
| Inductor `L1` | 10 mH (ideal) |
| Capacitor `C1` | 100 nF (ideal) |
| Resistor `R1` | 50 Ω (ideal) |

All components are ideal — no ESR, no parasitics.

## Analysis

Run an **AC small-signal sweep** wide enough to clearly capture the
resonance peak. The natural frequency for these values is in the
**1–10 kHz** range. A sweep from 100 Hz to 100 kHz with at least 50
points per decade resolves the peak smoothly.

## Required output

Write `/tmp/agent/result.json`. Each KPI is an object with `value` and
a `source` describing where the number came from. The verifier
re-extracts from the source and compares; bare numbers are rejected.

The benchmark scores three KPIs (more is fine, extras are ignored):

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if the AC sweep ran to completion with no `***` error in the LTspice log; 0 otherwise | flag |
| `peak_freq` | frequency at which `|V(out)|` is maximum across the sweep | Hz |
| `peak_gain` | maximum gain over the sweep, expressed in **dB** (LTspice's `.meas AC mag(...)` writes magnitudes in dB form into the log; a peak gain of 1.0 V/V appears as ~0 dB) | dB |

`peak_freq` is the resonant frequency `f0`; `peak_gain` is the
gain at resonance.

**You are responsible for putting `.meas` directives in the netlist.**
LTspice only computes a measure if you ask for one. Without `.meas`
entries the `.log` will have nothing for the verifier to extract. The
two output KPIs above are computed by:

```spice
.meas AC peak_gain MAX mag(V(out))
.meas AC peak_freq WHEN mag(V(out))=peak_gain
```

The first finds the maximum of |V(out)| across the swept frequencies;
the second finds the frequency at which that maximum occurs (the
`WHEN ... CROSS` form puts the axis point — frequency, here — into
`Measure.value`).

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
  "peak_freq": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "peak_freq"
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
  "peak_freq": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.peak_freq.value'"
    }
  }
}
```

Adjust the `value` and KPI names to match what you measured. The
`file_extract` fallback, if you use it, must start with one of the
allowed binaries (head/tail/awk/sed/grep/cut/tr/sort/uniq/wc/cat/jq).

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

## Analytical-shortcut notice

For an **ideal** series RLC band-pass:
- f₀ = 1/(2π√LC) ≈ 5.03 kHz
- peak gain |V(R)/V(in)| at resonance = 1 (the inductor and capacitor
  cancel; all input voltage drops across R)

These closed-form answers match what the simulator computes for ideal
components. The verifier nonetheless requires each KPI to declare a
verifiable source (file or sim-run record) — hand-derived numbers
without a backing `.meas` extract fail the source-verification check.
