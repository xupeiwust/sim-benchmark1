# Task — second-order LC low-pass with source impedance

Build, simulate, and characterise a **second-order LC low-pass filter**
fed through a source impedance, in small-signal AC analysis. Report
the DC gain and the -3 dB cutoff frequency.

## Topology

```
  in ──[R_s]── a ──[L]── out
                          │
                         [C]
                          │
                          0
```

`V1` drives `in` (with AC 1); `R_s` represents source impedance; `L`
and `C` form the second-order low-pass; output at `out`.

## Component values

| component | value |
|---|---|
| AC source `V1` | small-signal `AC 1` between `in` and `0` |
| Source resistor `R_s` | 50 Ω |
| Inductor `L1` | 10 mH (ideal) |
| Capacitor `C1` | 1 µF (ideal) |

## Analysis

AC sweep wide enough to see DC pass-band, the resonance/peak (around
1.6 kHz for these values), and the HF rolloff. 10 Hz to 100 kHz with
≥ 100 pts per decade.

## Required output

Three KPIs:

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if sweep ran without `***` errors, else 0 | flag |
| `gain_dc` | low-frequency gain (dB) — measured at 10 Hz, well below corner | dB |
| `f_3db` | frequency at which `|V(out)|` drops to `1/√2` of DC value | Hz |

Suggested `.meas`:

```spice
.meas AC gain_dc FIND mag(V(out)) AT 10
.meas AC f_3db   WHEN mag(V(out))=gain_dc*0.7071 CROSS=1
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
  "gain_dc": {
    "value": 0,
    "source": {
      "kind": "ltspice_log",
      "path": "/root/case/<your-netlist-stem>.log",
      "query": "measure",
      "measurement": "gain_dc"
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
  "gain_dc": {
    "value": 0,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "001",
      "extract": "tail -1 | jq -r '.measures.gain_dc.value'"
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

## Note

Approximate closed-form: ω0 = 1/√LC = 10⁴ rad/s ≈ 1.59 kHz.
The actual -3 dB cutoff is shifted by Q (= ω0·L/R_s = 2 here);
for moderate Q the corner sits near ω0 with mild peaking, so
expect `f_3db` close to 1.6 kHz.
