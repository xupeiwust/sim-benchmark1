# Task — bridge rectifier, capacitor selection

Build, simulate, and characterise a textbook AC-to-DC converter. Sweep
candidate smoothing capacitors, choose the smallest value that meets the
ripple target, then report the selected design's steady-state DC output
voltage and ripple.

## Topology

A standard four-diode bridge driven by a sinusoidal AC source, with a
smoothing capacitor and a resistive load on the DC side:

```
  in1 ───┬──[D1]──┬─── p   (DC + rail; output node)
         │        │
         │        │ C ─── 0
         │        │ R ─── 0
         │        │
  in2 ───┼──[D2]──┘
         │
  in1 ───┼──[D3]── 0
  in2 ───┴──[D4]── 0
```

- Diodes are configured in the standard bridge so that **either polarity
  of `V(in1) − V(in2)` drives current through the load in the same
  direction** (out of `p`, into `0`).
- The smoothing capacitor `C` sits between the DC + rail (`p`) and
  ground (`0`).
- The load resistor `R` is in parallel with `C`.
- Ground is node `0`.

## Component values

| component | value |
|---|---|
| AC source `V1` | sinusoidal between `in1` and `in2`, **12 V peak amplitude, 60 Hz, 0 V offset, no phase delay** |
| Diodes `D1..D4` | use a real silicon-rectifier model — **1N4007** is canonical (Is≈14 nA, Rs≈34 mΩ, N≈2). Do **not** use `.model` defaults — those are an idealised D() with Is=10fA, which under-predicts forward drop |
| Candidate smoothing capacitors `C` | 220 µF, 330 µF, 470 µF, 680 µF, initial voltage 0 |
| Load resistor `R` | 100 Ω |

## Analysis

Use `.step param` or equivalent repeated runs to evaluate all candidate
capacitors. Run a transient simulation long enough for the cap-rail
voltage to reach steady state for the largest capacitor. Use a maximum
step that resolves the ripple cleanly at 120 Hz (50 µs is comfortable).

Choose the **smallest** capacitor that keeps steady-state ripple below
1.5 V peak-to-peak.

## Required output

Write `/tmp/agent/result.json`. Each KPI is an object with `value` and a
`source` describing where the number came from. The verifier
re-extracts from the source and compares; bare numbers are rejected.

The benchmark scores four KPIs (more is fine, extras are ignored):

| key | meaning | unit |
|---|---|---|
| `sim_completed` | 1 if the transient ran to completion with no `***` error in the LTspice log; 0 otherwise | flag |
| `selected_cap_uF` | selected smoothing capacitor value | µF |
| `vout_avg` | time-average of `V(p)` for the selected capacitor over a steady-state window of at least 16.7 ms | V |
| `vrip_pp` | peak-to-peak excursion of `V(p)` for the selected capacitor over the same window | V |

`vout_avg` is the DC output. `vrip_pp` is the ripple amplitude.
**Both are dominated by diode forward drop and finite C×R discharge —
the textbook ideal-diode formulas (`V_dc = V_pk`, `V_r = I/(C·f)`) are
off by ~15-30%.** Quote the simulator, not the formula.

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

Closed-form approximations for V_dc and V_ripple from undergraduate
power-electronics textbooks are widely published. **They are off by
significantly more than the per-KPI tolerance for the values requested
here** (real diode drop ≈ 0.7-0.9 V each, two diodes always in series,
non-zero source impedance, exponential cap discharge during the
non-conducting interval). Each KPI must be backed by a verifiable
source (file or sim-run record); hand-quoted textbook numbers without
running the simulator score 0 because the verifier re-extracts and
will find no underlying `.meas` line for `vout_avg` / `vrip_pp`.
