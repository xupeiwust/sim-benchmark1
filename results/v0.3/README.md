# OpenFOAM Aerodynamic 6 Results

OpenFOAM evaluation: 6 newly-promoted aerodynamic / boundary-layer cases
× 4 reference models. Coverage: NACA 0012 subsonic airfoil sweep,
NACA 4412 trailing-edge separation, NASA hump separated flow,
backward-facing step turbulent reattachment, bump-in-channel turbulent
RANS, and zero-pressure-gradient flat plate. All cases are 2D RANS or
quasi-2D steady simulations grounded in NASA TMR, Coles & Wadcock 1979,
and Driver-Seegmiller validation data.

These cases are deliberately harder than the foundational 11-case set:
each requires the agent to author a working blockMesh /
snappyHexMesh configuration, set up an alpha sweep (airfoils) or
capture an adverse-pressure-gradient reattachment (BFS / hump), then
extract integral force coefficients or skin-friction profiles. A correct
mesh is the gate condition — without it, all downstream KPIs are zero.

## Summary

| Run | Agent / Model | Assigned | Completed | Harness exceptions | Completed Mean | Status |
|---|---|---:|---:|---:|---:|---|
| `release-v0.3-of6-claude-opus46-20260511` | claude-code · Claude Opus 4.6 | 6 | 6 | 0 | **0.622** | included |
| `release-v0.3-of6-minimax-m27-20260511` | claude-code · MiniMax-M2.7 | 6 | 6 | 0 | **0.071** | included |
| `release-v0.3-of6-minimax-m25hs-20260511` | claude-code · MiniMax-M2.5-highspeed | 6 | 6 | 0 | **0.000** | included |
| `release-v0.3-of6-minimax-m27hs-20260511` | claude-code · MiniMax-M2.7-highspeed | 6 | 6 | 0 | **0.000** | included |

Harness budget: `--max-turns 270` for Phase 1, `+30` wrap-up reserve
(`agent.kwargs.max_turns: 300` in config).

## Per-Case Comparison

| Case | Opus 4.6 | M2.7-highspeed | M2.5-highspeed | M2.7 |
|---|---:|---:|---:|---:|
| `bump_in_channel_2d` | **1.000** | 0.000 | 0.000 | 0.000 |
| `flatplate_zpg_subsonic` | **1.000** | 0.000 | 0.000 | 0.000 |
| `nasa_hump_separated` | 0.594 | 0.000 | 0.000 | 0.000 |
| `naca0012_subsonic` | 0.444 | 0.000 | 0.000 | 0.000 |
| `backstep_driver_seegmiller_turbulent` | 0.443 | 0.000 | 0.000 | 0.000 |
| `naca4412_trailing_edge_separation` | 0.250 | 0.000 | 0.000 | **0.426** |
| **Mean (6/6)** | **0.622** | **0.000** | **0.000** | **0.071** |

## Terminal-reason breakdown

`terminal_reason` is recorded from Claude Code's final `result` event.
`completed` means the agent exited voluntarily (wrote what it could).
`max_turns` means CC reached the Phase-1 turn budget (271 turns) and
exited 1. Per-trial counts are reported in the per-model bundle JSONs.

| Model | completed | max_turns |
|---|---:|---:|
| Opus 4.6 | 6 / 6 | 0 / 6 |
| MiniMax-M2.7-highspeed | 2 / 6 | 4 / 6 |
| MiniMax-M2.5-highspeed | 0 / 6 | 6 / 6 |
| MiniMax-M2.7 | 2 / 6 | 4 / 6 |

Opus finishes every case within the turn budget; the heaviest case is
`naca4412` at 296 turns. The three MiniMax variants either run the
budget out or voluntarily stop without producing extractable artifacts.

## Observations

- **Opus 4.6 is the only model to score on any of the 6 cases.** Two
  perfect runs (`bump_in_channel_2d`, `flatplate_zpg_subsonic`), four
  partial runs (0.25–0.59). Opus drives the solver natively (not
  through `sim run`), writes correct `file_extract` source paths, and
  produces re-extractable mesh logs, residual logs, and force-coefficient
  files.
- **All three MiniMax variants score 0 on 17/18 trials.** The single
  M2.7 non-zero (`naca4412 = 0.426`) was a `completed` trial whose
  alpha sweep partially executed before the agent stopped; M2.5-HS and
  M2.7-HS scored exactly 0 on all 6 cases each.
- **The failure mode is not "ran out of turns".** Inspecting trial
  records (`reward_detail.json:meta_detail.records`) shows MiniMax
  trials *did* write and execute multi-hundred-line Python solver
  scripts; the scripts crashed at `blockMesh` (mesh generation) with
  `RuntimeError: Command failed: blockMesh > blockMesh.log`. With no
  mesh log, no solver log, and no force-coefficient files, every
  `file_extract` KPI returns empty — verifier scores 0 across all
  groups. Agents then wrote placeholder garbage values
  (e.g. `1.49e-36`) into `result.json` with empty `source: {}` objects
  to satisfy the schema, but verifier rejects unverified KPIs.
- **Mesh authoring is the new threshold.** On the foundational 11-case
  set ([`../v0.2/`](../v0.2/)), MiniMax models cleared 0.67–0.80 because
  cavity / oblique-shock / Bénard cases have small `blockMeshDict`
  grids the model can write correctly. The 6 aerodynamic cases require
  graded meshes, locationInMesh choice, snappyHexMesh refinement
  regions, and feature-edge capture — all of which the MiniMax cluster
  miswrites here.

## Infrastructure fixes folded in (MiniMax runs only)

Two issues surfaced during the MiniMax runs and were addressed mid-experiment.
They are infrastructure-level — they let the model get a fair shot — and
do *not* explain the 0-score outcomes.

1. **MiniMax-side context-limit kill before CC auto-compact.**
   MiniMax M2.5-HS / M2.7-HS true context windows are smaller than
   Claude Code's default 200 k assumption. Trials would die at
   ~58 k cumulative input tokens with HTTP 400 "context window exceeds
   limit (2013)" before Claude Code's auto-compact threshold (~184 k)
   triggered. Two-part fix:
   - **[`tools/openai_usage_proxy.py`](../../tools/openai_usage_proxy.py) v2 patch** —
     MiniMax stream events emit real `usage` only in a trailing chunk
     after `finish_reason`, which `claude-code-router`'s OpenAI →
     Anthropic stream translator never reads (it `break`s on
     `finish_reason`). The proxy now injects real-or-estimated token
     usage onto the `finish_reason` chunk itself, ensuring CC receives
     non-zero `input_tokens` per turn.
   - **`CLAUDE_CODE_AUTO_COMPACT_WINDOW=50000`** in `agent.env` forces
     Claude Code's compact threshold to ≈ 46 k (`50 000 × 0.92`), well
     below MiniMax's actual limit. See the `env:` block in
     `configs/release-v0.3-of6-minimax-{m25hs,m27,m27hs}.yaml`.

   Result: MiniMax trials run 60–200 minutes with 3–14 successful
   compact events per trial and zero API errors. Pre-fix m25hs trials
   exhausted at ~50 min with `context window exceeds limit`.

   Note: the M2.7 run (`release-v0.3-of6-minimax-m27-20260511`) used
   the OLD proxy (pre-v2 patch). Its single non-zero result is from a
   trial that completed before context overflow hit; the other 5 cases
   stopped at or near `max_turns` without an API error event being
   recorded.

2. **Harbor harness wrap-up bug (declared, not patched).** Phase 1 of
   `tools/agent_harness.py:_two_phase_run` raises
   `NonZeroAgentExitCodeError` when Claude Code exits with code 1
   (which `--max-turns` triggers). The surrounding `try/finally` does
   not catch this exception, so Phase 2 wrap-up never runs. Agents that
   hit `max_turns` therefore lose the wrap-up pass and submit whatever
   incomplete `/tmp/agent/result.json` they already wrote. This affected
   every MiniMax `max_turns` trial in this run. Fix deferred — would
   not have changed scores here since no MiniMax `max_turns` trial had
   extractable solver artifacts to wrap up.

## Files

- [`summary.json`](./summary.json) — machine-readable release summary.
- [`of6-claude-opus46-20260511.json`](./of6-claude-opus46-20260511.json) — Claude Opus 4.6 OpenFOAM aero-6 run.
- [`of6-minimax-m27hs-20260511.json`](./of6-minimax-m27hs-20260511.json) — MiniMax-M2.7-highspeed run.
- [`of6-minimax-m25hs-20260511.json`](./of6-minimax-m25hs-20260511.json) — MiniMax-M2.5-highspeed run.
- [`of6-minimax-m27-20260511.json`](./of6-minimax-m27-20260511.json) — MiniMax-M2.7 run.

## Reproduction

```bash
# Claude Opus 4.6
export OPUS46_AUTH_TOKEN=<your-token>
export OPUS46_BASE_URL=<your-anthropic-compatible-gateway>
harbor run -c configs/release-v0.3-of6-claude-opus46.yaml --force-build -y

# MiniMax-M2.7-highspeed and M2.5-highspeed (full-access key)
export MINIMAX_API_KEY=<key-with-full-model-access>
harbor run -c configs/release-v0.3-of6-minimax-m27hs.yaml --force-build -y
harbor run -c configs/release-v0.3-of6-minimax-m25hs.yaml --force-build -y

# MiniMax-M2.7 (works with restricted-access key too)
export MINIMAX_API_KEY=<your-key>
harbor run -c configs/release-v0.3-of6-minimax-m27.yaml --force-build -y
```

The MiniMax configs set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=50000` in
`agent.env`. Without that override, MiniMax trials die on these cases
with HTTP 400 before Claude Code triggers auto-compact.

MiniMax runs are routed via
[`claude-code-router`](https://github.com/musistudio/claude-code-router)
with the local sidecar proxy ([`tools/openai_usage_proxy.py`](../../tools/openai_usage_proxy.py));
the harness wires both up at trial setup. See
`tools/agent_harness.py:ClaudeCodeViaCcr`.
