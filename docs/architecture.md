# sim-benchmark trial architecture & generality

How a single trial actually executes — and which parts of this design
extend to simulation domains beyond what we currently ship (LTspice +
OpenFOAM).

For per-hook implementation detail, see [`hooks.md`](hooks.md). This
doc is the level above: how the pieces fit, and a first-principles
read on which assumptions can travel.

## Trial pipeline (left → right time)

```
┌─────────────────┐  ┌─────────────────────────────────────┐  ┌────────────────┐
│ harbor builds   │  │  trial container                    │  │ host           │
│ case image FROM │  │                                     │  │                │
│ patched base    │  │  ┌─────────────┐                    │  │                │
│ (sim_benchmark_ │──┼─▶│ harness     │ install hooks +    │  │                │
│  verifier +     │  │  │ install     │ skills + (ccr/proxy│  │                │
│  detectors      │  │  │ (agent_     │ if applicable)     │  │                │
│  baked in)      │  │  │  harness.py)│                    │  │                │
│                 │  │  └─────────────┘                    │  │                │
└─────────────────┘  │                                     │  │                │
                     │  ┌─────────────────────────────┐    │  │                │
                     │  │ agent loop                  │    │  │                │
                     │  │   read instruction.md       │    │  │                │
                     │  │   run solver via shell      │    │  │                │
                     │  │   write artifacts           │    │  │                │
                     │  │   write /tmp/agent/result   │    │  │                │
                     │  │   .json                     │    │  │                │
                     │  │   try to stop               │    │  │                │
                     │  │     → Stop hook fires       │    │  │                │
                     │  │       Pass 1: schema OK?    │    │  │                │
                     │  │       Pass 2: extract runs? │    │  │                │
                     │  │     → block / pass          │    │  │                │
                     │  │   (loop until pass)         │    │  │                │
                     │  └─────────────────────────────┘    │  │                │
                     │                                     │  │                │
                     │  ┌─────────────────────────────┐    │  │                │
                     │  │ verifier (score.py)          │   │  │                │
                     │  │   _score_groups()            │   │  │                │
                     │  │     per-KPI verify_source    │   │  │                │
                     │  │     compute kpi_score        │   │  │                │
                     │  │   annotate_per_kpi()         │   │  │                │
                     │  │     → detector dispatch      │   │  │                │
                     │  │     → solver_stage / prov    │   │  │                │
                     │  │   write reward.json + detail │───┼──┼──▶ jobs/<dir>/  │
                     │  └─────────────────────────────┘    │  │                │
                     └─────────────────────────────────────┘  └────────────────┘
```

Five layers, each with **one job**:

| Layer | Code | Job |
|---|---|---|
| Harness install | `tools/agent_harness.py:_install_hooks()` | Drop hook scripts into the container, write `~/.claude/settings.json` |
| Skills mount | `tools/agent_harness.py:_register_sim_skills()` | Make `sim-skills/` visible to Claude as native skills |
| Hooks (in-trial) | `tools/agent_harness.py:_*_HOOK_SRC` | Schema/runnability check + subprocess wedge defence |
| Agent loop | claude-code | Read prompt, drive the solver, write `result.json`, attempt to stop |
| Verifier (post-stop) | `lib/sim_benchmark_verifier/score.py` | Compute score from artifacts + KPI claims, annotate failure axes |

Two design rules hold across all five:

1. **Verifier is the only judge of correctness.** Hooks do schema +
   runnability bookkeeping; detectors add post-hoc attribution
   metadata. Neither touches the score.
2. **Artifact-rooted, not contract-rooted.** Verifier + detectors read
   files the solver actually produced. Doesn't matter whether the
   agent invoked `sim-cli` or shelled out directly.

## Harness layer (in detail)

`tools/agent_harness.py` exposes two `ClaudeCode` subclasses, picked
per agent in the YAML config:

| Class | Upstream | Used for |
|---|---|---|
| `ClaudeCodeAnthropicDirect` | `${ANTHROPIC_BASE_URL}` (native Anthropic protocol) | Claude Opus 4.6 via xaminim, MiniMax `…/anthropic` endpoint, etc. |
| `ClaudeCodeViaCcr` | claude-code-router (3456) → `openai_usage_proxy` (3457) → OpenAI-format upstream | MiniMax M2.5 / M2.7 via `api.minimaxi.com/v1/chat/completions`, paratera Kimi/GLM/DeepSeek |

Both subclasses share three install steps, in order:

1. **Replace `claude.ai/install.sh` with npm + taobao mirror.** The
   official installer is geo-blocked from CN; we install
   `@anthropic-ai/claude-code` from the npmmirror registry.
2. **Mount `sim-skills/` into `~/.claude/skills/`.** Claude Code reads
   skill metadata at startup from this path; the agent then sees them
   as native skills it can call (no "load a skill" turn cost).
3. **Install the two hooks + write `settings.json`** at three paths
   (user, sessions dir, project cwd) so claude-code finds at least
   one of them regardless of how it boots.

The ccr variant additionally stands up an in-container proxy chain to
inject `stream_options.include_usage=true` into OpenAI requests
(otherwise MiniMax / paratera return `usage: {input_tokens: 0, ...}`
and the cost meter is blind).

## Hooks layer

| Hook | Event | Purpose | Information leak |
|---|---|---|---|
| `result_json_check.py` | `Stop` | Force agent to write a contract-conformant `/tmp/agent/result.json` before exiting. Pass 1 schema, Pass 2 file_extract runnability. | Reveals only "schema valid yes/no" + "extract returns non-empty yes/no". Never values, never `gt_value`, never `T_decay`, never whether claim ≈ extracted. |
| `bash_timeout.py` | `PreToolUse` matcher=`Bash` | Wrap every Bash call in `timeout --kill-after=5s <secs>s bash -c <orig>` so daemonized children (wineserver, etc.) get cleaned up by GNU `timeout(1)`'s session-group signal — claude-code's own SIGKILL doesn't reach them. | None (transparent rewrite the agent doesn't see). |

The boundary is sharp: **hooks fix agent-environment affordance gaps,
they do not change the contract**. Adding a hook that, say, told the
agent "your value is off by 8 %" would leak GT-adjacent semantics and
make the verifier's `T_decay` curve reverse-engineerable. We
deliberately don't.

For implementation, see [`hooks.md`](hooks.md).

## Detector layer (post-stop, post-score)

The verifier (`score.py`) runs after the agent has stopped. It
computes scores, then dispatches the per-KPI score dicts through the
detector plugin layer (`lib/sim_benchmark_verifier/detectors/`).
Detectors emit two annotations onto each per-KPI entry — both are
**diagnostic-only metadata, not score components**.

| Axis | Values | Detector(s) |
|---|---|---|
| `provenance_stage` | P0_hallucination · P1_path_invalid · P2_extract_unrunnable · P3_extract_mismatch · P4_pass · spec_error | universal (single, solver-agnostic) |
| `solver_stage` | L0_input_syntax · L2_solver_crash · L3_convergence · L4_conservation · L5_physics · L5_quantitative · L6_pass · (open enum) | universal (L2/L5/L6 from KPI fields) + openfoam (L3/L4 from log scan) + ltspice (L2/L3 from log scan) + future per-solver |

Two-axis split solves a v3.1 confusion: provenance failures
("paperwork") and solver failures ("physics") need different fixes.
See `SCHEMA.md §6` for the full enum + back-compat with `failure_class`.

## First-principles generality analysis

The architecture above makes specific assumptions about what a
"simulation trial" looks like. Below: which assumptions actually
generalize to other domains, and which need extension.

### Strong assumptions (built into the contract)

#### A1. Output is one or more **scalar KPIs** with a deterministic extraction rule

Currently: `result.json = {kpi: {value: <number>, source: <how to re-extract>}}`.

| Domain | Fits? | Notes |
|---|---|---|
| Circuit / SPICE measurements (gain, f₃dB, settling time) | ✅ | Native fit — log files have scalar measures |
| CFD numerical KPIs (Cd, Cl, residual, max y+) | ✅ | Native fit |
| FEA stress / displacement at named locations | ✅ | Same shape — extract from solver's text output |
| EM frequency-response, S-parameters | ✅ | Scalar at chosen frequency |
| Robotics: collision count, path length, settling time | ✅ | Scalar from rosbag / sim log |
| **Field outputs (CFD vorticity field, FEA stress contour)** | ⚠️ | Single scalar reduction (max, integral, line-probe) fits; full field comparison needs different verifier |
| **Image outputs (camera frame from robotic sim, CAD render)** | ❌ | No scalar; would need perceptual similarity metric or LLM judge |
| **Time-series / trajectory (joint angles over time)** | ⚠️ | Reduce to scalar features (overshoot, settling time, RMS); the contract works, the case author has more upfront work |
| **Stochastic outputs (Monte Carlo, RL training reward)** | ⚠️ | Single trial returns a sample; tolerance via `T_decay` accommodates fuzz but not full distribution |

#### A2. Extraction is **re-runnable** by the verifier

Currently: agent declares `(value, source.path, source.extract)` →
verifier re-runs extract with file as stdin, asserts match.

| Source kind | Generalises to | Notes |
|---|---|---|
| `file_extract` (text file + UNIX pipeline) | Any text-format solver output | Most solvers; covers CFD logs, SPICE logs, structured text dumps |
| `ltspice_log` (LTspice native .log query) | LTspice variants (UTF-16 logs) | Solver-specific path; same pattern (custom parser per format) extends to e.g. CSV-only outputs, HDF5 outputs |
| `sim_run_*` (sim-cli's own record) | Anything that runs through sim-cli | Optional — most agents bypass |
| **Binary-format outputs (HDF5, VTK, ROS bag)** | Need adapter | New `source.kind` per format — e.g. `h5_extract` with HDF5 path query, `rosbag_query` with topic + time |
| **Image outputs** | Don't fit re-extraction model | Need similarity-metric verifier; outside this architecture |

#### A3. Workflow is **agent → solver → final state → verifier**

Currently: agent writes inputs, runs solver, writes `result.json`,
verifier scores once at the end.

| Workflow shape | Fits? | Notes |
|---|---|---|
| Batch CFD / SPICE / FEA (run once, score once) | ✅ | Native fit |
| Multi-step CAE (mesh → solve → post-process → judge) | ✅ | Multiple solver calls within one agent loop; verifier still scores once at end |
| **Interactive GUI (Fluent meshing workflow, COMSOL Desktop attach)** | ⚠️ | Agent does many small actions; verifier still scores final state. PreToolUse hooks could add per-step validation if needed. |
| **Closed-loop control (robot follows commanded trajectory)** | ⚠️ | KPI is final-state scalar (e.g. position error at t=T), so contract works; but the SIMULATION environment is more complex (need physics step + sensor feedback loop). Requires real-time sim platform inside the container. |
| **Multi-trial campaigns (Monte Carlo, parameter sweeps)** | ⚠️ | One trial = one sample; aggregate at harbor level via multiple trials. Doesn't break the architecture, but the per-trial score becomes statistical. |

#### A4. Time budget is **bounded per Bash call** (claude-code's 600s ceiling)

Currently: agent's bash calls each capped at ≤ 600s (claude-code
[issue #25881][1]). For longer sims, agent must use solver
checkpointing + multiple foreground calls, or `run_in_background=true`.

[1]: https://github.com/anthropics/claude-code/issues/25881

| Sim wall-time | Pattern |
|---|---|
| < 5 min | Single foreground call. Default. |
| 5 – 30 min | `run_in_background=true` + claude-code's output-polling tool. Hook auto-skips wrapping for background mode. |
| > 30 min | Solver checkpointing (`writeInterval` for OF, `RESTART_SOL=YES` for SU2) + multiple foreground calls. Each retry continues from previous endpoint. |
| > 1 day | Doesn't fit at all. The trial container itself is bounded by harbor's `agent.timeout_s × timeout_multiplier`. Architecture would need a different runtime (job queue + checkpoint orchestration). |

#### A5. Agent framework is **claude-code**

Currently: hooks use Claude Code's `Stop` and `PreToolUse` hook system.
Switching agent framework requires porting both hooks.

| Framework | Equivalent of Stop hook? | Equivalent of PreToolUse Bash? |
|---|---|---|
| Claude Code (current) | ✅ native | ✅ native |
| Terminal-Bench `terminus-2` | Built-in: refuses to terminate until result.json written | No equivalent needed (different shell architecture) |
| Open-source agent (langchain, autogen) | Wrap final-output validator | Wrap subprocess.run with timeout |
| Code Interpreter / OpenAI assistant | Limited — no native hook events | Need an outer-loop validator |

The **principle** (in-trial validation, in-trial wedge prevention) is
agent-agnostic; the **implementation** is claude-code-specific. Each
new agent framework needs its own port.

### Things that travel cleanly across simulation domains

Independent of the assumptions above:

- **Source-provenance verification.** "Re-extract from declared
  source" works for any deterministic output. New `source.kind` per
  format.
- **Two-axis failure attribution** (`provenance_stage` ×
  `solver_stage`). Provenance axis is solver-agnostic. Solver axis
  uses per-domain detector plugins; the universal stages (L0 / L2 /
  L5 / L6) apply to every solver, domain-specific stages get added
  per-detector.
- **Calibration discipline.** Real broken/healthy fixture pairs +
  TPR/FPR validation per detector. `EVIDENCE.md` template applies to
  any new domain.
- **Cost / wall / turns instrumentation.** `cost_meter.py` reads
  claude-code transcripts; agent-framework-specific but the *concept*
  (capture turn count + USD cost per trial) applies anywhere.

### Domains we'd need to extend the architecture for

Concrete examples of where the current scheme falls short:

| Domain | What breaks | Required extension |
|---|---|---|
| **Generative design (CAD shape from prompt)** | No scalar KPI for "is this shape good" | New verifier paradigm: design rules + manufacturability scoring + LLM-judge-with-rubric. Outside scope of this benchmark. |
| **Computer vision in robotics sim** | Image-output → no re-extractable scalar | New source kind: `image_metric` with reference image + similarity threshold. Verifier needs CV library. |
| **Autonomous driving sim** | Long-running real-time + closed-loop + safety-critical | Different runtime (CARLA/SUMO instead of Docker), different harness (real-time sim API vs shell), different verifier (trajectory + collision metrics). Architecturally a fork. |
| **Quantum circuit simulation** | Outputs are state-vector / density-matrix / shot histogram | New source kind: `quantum_state` with HDF5 / npz reader; KPI extracts measurement-basis probabilities. Numerical contract holds. |
| **Climate / weather** | Multi-day wall-clock, terabyte outputs | Doesn't fit container model; needs job-scheduler runtime + remote storage. |

The good news: the **first three layers (harness install, hooks,
verifier core)** generalise as long as we extend the source-kind set.
The runtime/infrastructure layer (claude-code, harbor, docker, 600s
ceiling) is the harder constraint.

## When the architecture is the right tool

Use it when:
- Output is a finite set of scalar KPIs extractable deterministically from solver artifacts
- Per-trial wall ≤ ~30 min (with checkpointing) or bounded enough for `run_in_background` polling
- Verification is rule-based, not human-judgment-based
- Solver runs in Linux (Docker) or via wine (LTspice / commercial via wrapper)

Don't force it when:
- The "right answer" requires human aesthetic judgment (shape, layout, design)
- Outputs are inherently non-scalar (full fields, images, trajectories without natural reductions)
- The simulation needs real-time stimulus / closed loops outside container's reach
- Single trials take > 1 day

## References

- [`hooks.md`](hooks.md) — per-hook implementation detail
- [`SCHEMA.md`](../SCHEMA.md) — case + verifier contract, two-axis enum
- [`../lib/sim_benchmark_verifier/EVIDENCE.md`](../lib/sim_benchmark_verifier/EVIDENCE.md) — detector calibration TPR/FPR
- [sim-proj#125 RFC (private)](https://github.com/svd-ai-lab/sim-proj/issues/125) — two-axis design discussion
