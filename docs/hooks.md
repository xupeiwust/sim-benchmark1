# Claude Code hooks for sim-benchmark trials

`tools/agent_harness.py` installs two [Claude Code hooks][1] into every trial
container at agent setup time. They live in the agent layer (not the verifier,
not the cases) and exist to fix specific framework affordance gaps that v17–v18
exposed.

[1]: https://docs.claude.com/en/docs/claude-code/hooks

## TL;DR

| Hook | Event | What it does | Why |
|---|---|---|---|
| `result_json_check.py` | `Stop` | Schema-validates `/tmp/agent/result.json` before letting `claude` stop. Blocks termination on missing file or schema problems with a per-KPI error list. | v17 had 16 / 20 trials stop with no `result.json`. Without an in-trial signal, agents learn nothing about the contract until the post-hoc verifier scores 0. |
| `bash_timeout.py` | `PreToolUse` (matcher: `Bash`) | Transparently rewrites every Bash `command` to `timeout --kill-after=5s 90s bash -c <orig>`. | Claude Code's own 2-min default Bash timeout failed to clean up daemonized children (wineserver) in v18e — a single `wine-ltspice -?` wedged the trial for 75 minutes. GNU `timeout(1)` runs in a new session group and signals the whole group on expiry. |

The first one teaches the agent how to satisfy the contract; the second
defends against unbounded subprocess hangs.

## How they ship

Both hooks are installed by `_install_hooks(agent, environment)` in
`tools/agent_harness.py`, called from `ClaudeCodeAnthropicDirect.install()`
and `ClaudeCodeViaCcr.install()`. The install step does three things:

1. Writes the two Python scripts to `/opt/sim-benchmark-hooks/` inside the
   container.
2. Writes a `settings.json` referencing them at three locations:
   - `~/.claude/settings.json` (user-level)
   - `/logs/agent/sessions/settings.json` (Harbor's
     `CLAUDE_CONFIG_DIR` — written defensively even though Claude Code
     does not load settings from there)
   - `/root/case/.claude/settings.json` (project-cwd, since the agent
     runs from `/root/case`)
3. `chmod +x` on the scripts.

The triple-write is belt-and-braces: v18 + v18b spent two iterations
narrowing down which path Claude Code actually loads. `~/.claude/settings.json`
is the load-bearing one in our setup, but writing all three costs nothing and
removes a class of bug.

## Stop hook — `result_json_check.py`

### Problem statement

The benchmark verifier reads `/tmp/agent/result.json` to grade KPIs. Each
entry has a strict shape (see `lib/sim_benchmark_verifier/provenance.py`):

```jsonc
{
  "<kpi_name>": {
    "value": <number>,
    "source": {
      "kind": "sim_run_stdout",
      "run_id": "<id from sim --json logs>",
      "extract": "<sandboxed shell pipeline that re-extracts the value>"
    }
  }
}
```

Without an in-trial signal, agents fail this contract in three ways
(measured in v17–v18f):

| Failure mode | Frequency | Verifier message |
|---|---|---|
| File never written | 12 / 20 in v17 | `result.json not found at /tmp/agent/result.json` |
| `extract` starts with disallowed binary (e.g. `sim --json logs ...`) | rl_step in v18f | `extractor stage starts with disallowed binary 'sim'` |
| `run_id` invented (e.g. `"direct"`) | opamp_buffer in v18f | `sim run with run_id 'direct' not found in history` |

The Stop hook converts all three from post-hoc 0-scoring to in-trial
re-prompts.

### What it checks

Pure schema. **No value comparisons** — the hook never reveals whether
the agent's claimed value matches the extracted value, what the
`gt_value` is, or where the claim sits on the `T_decay` curve. That
keeps the verifier as the only judge of correctness; the hook is just
bookkeeping triage.

State machine:

| State | Action |
|---|---|
| `result.json` missing | Block + onboarding reason (worked example with copy-pasteable extract pipeline) |
| File present, not parseable JSON | Block + parse error |
| File present, top-level not a dict | Block + shape error |
| File present, schema problems per KPI | Block + per-KPI error list + available run\_ids + allowed binaries |
| File present, all KPIs schema-valid | Exit 0 → `claude` stops normally |

Per-KPI checks:
- `value` field present
- `source` is a dict
- `source.kind` ∈ `{sim_run_stdout, sim_run_kpi, file_extract}`
- `source.extract` is non-empty, no command substitution (`$(...)`,
  backticks), every pipe stage starts with an allowed binary
  (`head`, `tail`, `awk`, `sed`, `grep`, `cut`, `tr`, `sort`, `uniq`,
  `wc`, `cat`, `jq`)
- For `sim_run_stdout` / `sim_run_kpi`: `source.run_id` exists in
  `sim --json logs` history (queried at hook fire time)

### What it deliberately doesn't check

- **`value` correctness** — that's the verifier's `T_decay` job; revealing
  any signal here would let the agent reverse-engineer `gt_value`.
- **`extract` actually re-derives the claim** — that's the verifier's
  source-verification job; revealing the extracted value (even just
  pass/fail) would tell the agent whether their `value` is consistent
  with their own sim run, which is a step away from leaking the
  measured magnitude.
- **`physics_min`/`physics_max` bounds** — also verifier-side.

The line is: **schema yes, semantics no.**

### Sentinel for forensics

The hook writes `/logs/agent/.stop-hook-fired` (one line per fire) so
post-trial inspection can answer "did the hook ever run?" — independent
of whether `decision: block` was honored. Lives in `/logs/agent/`
(mounted to the trial dir), not `/tmp/agent/` (volatile, gone with the
container).

## PreToolUse hook — `bash_timeout.py`

### Problem statement

Claude Code's Bash tool has a documented 2-min default timeout, but in
v18e a single agent call deadlocked the trial for 75 minutes:

```bash
wine-ltspice -? 2>&1 | head -10
```

Sequence:
1. `wine-ltspice` invoked LTspice with an unrecognized flag → wine opened
   a GUI dialog under xvfb, blocking on a click that never came.
2. Wine spawned `wineserver` as a daemon, which inherited the bash
   pipeline's stdout pipe and detached to PID 1.
3. After 2 minutes, Claude Code's timeout fired and SIGKILLed the
   wine process — but `wineserver` was no longer a child of bash, so
   it survived and kept the stdout pipe open.
4. `head` waited indefinitely for EOF that never came → bash never
   returned → Claude Code waited indefinitely for the bash tool result.
5. Trial harness eventually forced the timeout via Harbor's outer
   `timeout_multiplier × agent.timeout_s` (90 minutes) — but only after
   the trial was completely wedged.

### What it does

Transparently rewrites every Bash `command` from:

```
<original-cmd>
```

to:

```
timeout --kill-after=5s 90s bash -c "<original-cmd>"
```

GNU `timeout(1)` runs its child in a **new session group** and on
expiry signals the **whole group**, so daemonizing children (wineserver
included) get cleaned up with `SIGTERM`, then `SIGKILL` after 5 seconds
of grace. The bash pipeline collapses cleanly, `head` sees EOF, and
Claude Code sees the bash tool return.

The rewrite is invisible to the agent — Claude Code's PreToolUse hook
mechanism (`hookSpecificOutput.updatedInput`) lets the hook return a
modified `tool_input` without the agent observing the wrap.

### Timeout policy

The wrap duration follows the resolved `tool_input.timeout` — whatever
the agent passes, or claude-code's own default if the agent didn't.
Fallback is 120s (matching claude-code's documented default) for
hypothetical paths where no timeout reaches the hook. Clamped to
[30s, 600s]; the upper bound is claude-code's hard ceiling per
[GitHub issue #25881](https://github.com/anthropics/claude-code/issues/25881)
and applies to all Bash invocations including background mode.

The hook's value-add is the **process-group cleanup**, not a tighter
wall-clock policy than the agent or claude-code already chose. The
v18e wedge happened because claude-code's SIGKILL didn't reach a
daemonized `wineserver`; GNU `timeout(1)` solves that without changing
how long anyone is allowed to wait.

### When the hook skips wrapping

| Condition | Reason |
|---|---|
| `tool_input.run_in_background == true` | Background mode — claude-code holds the task handle and polls output incrementally via a separate tool. Wrapping with `timeout Ns` would kill the background process at N seconds, defeating the entire reason agents use background mode. |
| Command starts with `timeout ` (agent self-bounded) | Don't double-wrap. |
| Command starts with `setsid ` | Intentional session-group invocation; trust the agent. |

### Long-running simulations (> 10 min)

Claude-code's 600s ceiling is a hard architectural limit (issue #25881)
that no per-call config can lift. For sims that genuinely take longer:

- **Recommended**: solver-side checkpointing + multiple foreground
  calls. OpenFOAM writes `Time/` directories every `writeInterval`,
  so a sim killed at 600s can be resumed by re-launching with the
  later `startTime`. SU2 has `RESTART_SOL=YES` + `SOLUTION_FILENAME`.
  Most CAE solvers support some form of restart-from-state.

- **Alternative**: `tool_input.run_in_background = true` for a single
  long invocation. The hook skips wrapping; claude-code returns a
  task handle immediately and the agent polls output via a separate
  tool until the process exits. Still subject to the 600s wall-clock
  ceiling per claude-code's architecture, but the agent isn't blocked
  during execution so it can read partial output and decide whether
  to wait or kill.

- **The "续算" (resume) pattern**: agent starts sim with a modest
  `tool_input.timeout` (e.g. 180000 = 3 min), inspects partial output
  (residuals, time directories), and re-runs with a longer timeout
  (≤ 600000 = 10 min) if the solver hasn't converged. With
  checkpointing on, each retry continues from the previous endpoint.
  This works automatically with the hook's "respect agent timeout"
  policy — no special handling needed.

## Why both hooks together

The two hooks attack different failure surfaces:

- **Stop hook** is about the **agent's contract with the verifier** —
  fixing communication-protocol mistakes.
- **PreToolUse hook** is about the **agent's contract with the
  environment** — defending against unbounded subprocess execution.

They compose cleanly: a Bash call that hangs gets killed at 90s, the
agent sees the failure, retries — and when they're ready to stop, the
Stop hook validates their `result.json` shape. Each hook is small (single
file, < 200 lines including docs) and independent.

## Empirical impact

### Iteration history on a 5-case probe set

The worst-scoring 4 from v17 + 1 control, same model
(`MiniMax-M2.5-highspeed`), `n_concurrent_trials = 5`, `max_turns = 80`:

| Version | Mean score | Wall time | What's in |
|---|---|---|---|
| v17 (baseline) | 0.21 | 15 min | no hooks |
| v18e | 0.63 | 16 min | Stop hook (existence-check only); rc_highpass_ac wedged 75 min on wine deadlock |
| v18f | 0.39 | 11 min | + PreToolUse Bash timeout (no more wedge); 3 cases regressed because agent guessed wrong extract / run\_id with no in-trial feedback |
| **v18g** | **0.81** | **10 min** | + Stop hook upgraded to schema validation. All 5 cases ≥ 0.775 |

Hook fire counts in v18g (per case): 2–5. Higher counts mean the agent
iterated on schema feedback before getting it right — exactly what the
hook is for.

### Full circuits sweep (20 cases)

v17 baseline vs v18 (v18g 5-case probe + v18h 15-case sweep with the
same hook config):

| | v17 (no hooks) | v18 (both hooks) |
|---|---|---|
| Mean score | **0.226** | **0.645** |
| Cases ≥ 0.5 | 4 / 20 (20 %) | 15 / 20 (75 %) |
| Cases ≥ 0.7 | 4 / 20 | 15 / 20 |
| Wedged trials | 0 | 0 |

Per-case deltas:

| case | v17 | v18 | Δ |
|---|---|---|---|
| half_wave_rectifier | 0.0 | 0.775 | **+0.775** |
| inv_amp | 0.0 | 0.775 | +0.775 |
| rl_step | 0.1 | 0.865 | +0.765 |
| opamp_buffer | 0.1 | 0.775 | +0.675 |
| rc_highpass_ac | 0.865 | 0.865 | 0 |
| lc_lowpass_2nd | 0.1 | 0.865 | +0.765 |
| noninv_amp | 0.1 | 0.865 | +0.765 |
| rc_pulse_response | 0.865 | 0.865 | 0 |
| rlc_step_overdamped | 0.1 | 0.865 | +0.765 |
| rlc_step_underdamped | 0.0 | 0.865 | +0.865 |
| rlc_bandpass | 0.865 | 0.858 | -0.007 |
| lc_resonator | 0.1 | 0.775 | +0.675 |
| opamp_summer | 0.1 | 0.775 | +0.675 |
| rl_lowpass_ac | 0.1 | 0.775 | +0.675 |
| sallen_key_lp | 0.0 | 0.775 | +0.775 |
| opamp_integrator | 0.1 | 0.266 | +0.166 |
| diff_amp | 0.1 | 0.0 | -0.1 |
| bridge_rectifier_ripple | 0.1 | 0.1 | 0 |
| rc_lowpass_ac | 0.719 | 0.1 | **-0.619** |
| rlc_notch | 0.1 | 0.1 | 0 |

15 of 20 cases improved; 4 unchanged at the floor; 2 regressed
(rlc_bandpass within noise, rc_lowpass_ac materially).

### Remaining failure modes (v18 floor)

The 5 cases scoring < 0.5 in v18 reveal what hooks **don't** fix:

| case | v18 | Remaining problem |
|---|---|---|
| diff_amp | 0.0 | Agent invented `run_id="local-ltspice-wine-xvfb"` — schema check rejected, agent tried twice and gave up. **Model capability** (didn't query `sim --json logs` to find the real run_id). |
| rc_lowpass_ac | 0.1 | Agent kept producing invalid JSON (escape error at line 7 col 71). Hook fired 6 times with parse errors but agent didn't fix. **Either model capability OR the parse-error feedback should be more actionable** (currently passes Python's exception text through verbatim). |
| opamp_integrator | 0.27 | Some KPIs scored, others didn't — partial schema pass. Likely agent ran out of turns mid-iteration. |
| bridge_rectifier_ripple | 0.1 | Hit `max_turns = 80` before writing `result.json` at all (`hook_fires = 0`). Agent thrashed on the simulation itself, never reached the Stop event. **Model capability or `max_turns` too tight for this case.** |
| rlc_notch | 0.1 | Same as bridge — `max_turns` exhaustion, `hook_fires = 0`. |

The pattern: hooks fix **bookkeeping/protocol** failures (most of v17's
losses); they do not fix **model capability** failures (writing valid
SPICE for a topology, debugging convergence). The remaining floor is
the model's capability gap, not the framework's.

`max_turns` could be bumped from 80 → 120 to give iterating agents more
runway, but that's an orthogonal knob.

## Extending

Adding a new check to the Stop hook: edit `_RESULT_CHECK_HOOK_SRC` in
`tools/agent_harness.py`. The script is base64-baked into the install
step, so changes ship next trial.

Adding a new event hook (e.g. PreToolUse on `Write` to validate the
`result.json` content as it's being written, instead of waiting for
Stop): add another entry to the `settings["hooks"]` dict in
`_install_hooks()` and write the script source as a new
`_<NAME>_HOOK_SRC` template.

Don't add hooks for cosmetic / informational reasons. The two we have
each fix a measurable failure mode that cost real trials. New hooks
should clear that bar.

## Where the hook outputs land at runtime

| Path | Purpose |
|---|---|
| `<trial-dir>/agent/.stop-hook-fired` | Sentinel — one ISO timestamp per Stop-hook fire |
| `<trial-dir>/agent/sessions/projects/-root-case/<id>.jsonl` | Claude session log; `decision:block` user-messages from the hook appear inline as user-role messages |
| `<trial-dir>/result.json` (Harbor `TrialResult`) | Trial metadata; agent\_execution start/end times reflect the additional turns the Stop hook added |

`<trial-dir>` is `jobs/<job-name>/<timestamp>/<case-name>__<rand>/` on
the host.
