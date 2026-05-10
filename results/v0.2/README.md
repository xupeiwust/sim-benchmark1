# OpenFOAM 11 Results

OpenFOAM evaluation: 11 calibrated cases × 4 reference models. Coverage:
Bénard convection, dam-break multiphase, DNS turbulence, oblique shock,
non-Newtonian flow, pitzdaily backward-facing step, and 3 lid-driven
cavities (Re=100/400/1000), plus a foundation-edition cavity Re=100.

## Summary

| Run | Agent / Model | Assigned | Completed | Harness exceptions | Completed Mean | Status |
|---|---|---:|---:|---:|---:|---|
| `release-v0.2-of11-claude-opus46-20260509` | claude-code · Claude Opus 4.6 | 11 | 11 | 0 | **0.918** | included |
| `release-v0.2-of11-minimax-m27hs-20260509` | claude-code · MiniMax-M2.7-highspeed | 11 | 11 | 0 | **0.804** | included |
| `release-v0.2-of11-minimax-m25hs-20260509` | claude-code · MiniMax-M2.5-highspeed | 11 | 11 | 2 | **0.706** | included |
| `release-v0.2-of11-minimax-m27-20260509` | claude-code · MiniMax-M2.7 | 11 | 11 | 0 | **0.675** | included |

`Completed Mean` averages all 11 trials per model. Harness exceptions
are agent or runner exit-status events; they are not always zero-score
because the verifier may still have replayable artifacts.

## Per-Case Comparison

| Case | Opus 4.6 | M2.7-highspeed | M2.5-highspeed | M2.7 |
|---|---:|---:|---:|---:|
| `bernard-cells-3d` | 0.867 | 0.998 | 0.895 | 0.895 |
| `cavity-re100-foundation-v11` | 0.997 | 0.996 | 0.995 | 0.799 |
| `cylinder-nonnewtonian` | 0.792 | 0.786 | 0.878 | 0.778 |
| `dambreak-multiphase` | 0.993 | 0.971 | 0.700 | 0.971 |
| `dns-boxturb16` | 0.798 | 0.700 | 0.700 | 0.500 |
| `hotroom-buoyant` | 0.830 | 0.700 | 0.700 | 0.200 |
| `lid-driven-cavity-re100` | 0.996 | 0.783 | 0.995 | 0.401 |
| `lid-driven-cavity-re1000` | 0.993 | 0.798 | 0.700 | 0.981 |
| `lid-driven-cavity-re400` | 0.904 | 0.880 | 0.200 | 0.903 |
| `oblique-shock` | 0.950 | 0.993 | 1.000 | 0.991 |
| `pitzdaily-bfs-rans` | 0.978 | 0.236 | 0.000 | 0.000 |
| **Mean (11/11)** | **0.918** | **0.804** | **0.706** | **0.675** |

## Files

- `summary.json` — machine-readable release summary.
- `of11-claude-opus46-20260509.json` — Claude Opus 4.6 OpenFOAM 11 run.
- `of11-minimax-m27hs-20260509.json` — MiniMax-M2.7-highspeed OpenFOAM 11 run.
- `of11-minimax-m25hs-20260509.json` — MiniMax-M2.5-highspeed OpenFOAM 11 run.
- `of11-minimax-m27-20260509.json` — MiniMax-M2.7 OpenFOAM 11 run.

## Bug fixes folded in

This release set landed two harness fixes mid-run; affected trials were
rerun and the merged board reflects post-fix scores.

1. **Wrap-up phase schema bug** — `tools/agent_harness.py:WRAP_UP_INSTRUCTION`
   originally used the literal phrase "(RESULT, converged)" when teaching
   the agent what keys to write into `/tmp/agent/result.json`. On cases
   where Phase 1 ran out of turn budget before writing a result file,
   Phase 2 wrap-up taught the agent to wrap KPI values under a top-level
   `"RESULT"` key, contradicting the per-case `instruction.md` schema
   (typically `{"kpis": {...}, "converged": ...}`). Verifier saw `pred=null`
   and scored 0 even when the agent's physics was correct. Fix: rewrote
   the wrap-up instruction to defer to instruction.md's schema, and made
   the validity check schema-agnostic. **Affected 7 trials**: `bernard`
   on all four models, `cylinder` for M2.5-HS, `oblique-shock` for M2.5-HS
   and M2.7-HS, plus the M2.7 oblique trial (rerun separately).
2. **Authenticity path-whitelist gap** — `cavity-re100-foundation-v11`'s
   `verify.py` only searched `/root/case/`, `/tmp/`, and cwd for valid
   OpenFOAM case artifacts. Opus 4.6 chose `/root/cavity/` (mirroring
   the canonical OpenFOAM `tutorials/cavity/` naming convention),
   and the verifier returned "no valid OpenFOAM case artifact found"
   despite a converged simulation that matched the Ghia reference within
   1%. Fix: broadened the search root to `/root/` so any subdirectory
   with a valid case structure passes. **Affected 1 trial**: Opus
   `cavity-re100-foundation-v11`.

## Observations

- Opus 4.6 opens a clear gap on OpenFOAM (~11 points above the next
  best). Strong on solver authoring, post-processing, and KPI provenance.
  9 of 11 cases at ≥ 0.79; 5 of 11 at ≥ 0.99.
- M2.7-highspeed is the strongest MiniMax variant on this suite (0.804),
  doing well on harder turbulent / multiphase cases. The reasoning
  variant M2.7 underperforms M2.7-highspeed on this CFD set —
  `pitzdaily-bfs-rans` in particular is a model watershed (Opus 0.978
  vs M2.7 0.000).
- Several misses are setup or workflow failures rather than pure physics
  failures, which is the intended discriminator.
- Wrap-up phase salvage works: the 8 trials that hit max_turns and entered
  Phase 2 still produced scoreable results post-fix (range 0.79–1.0)
  rather than being lost.

## Reproduction

```bash
# Claude Opus 4.6
export OPUS46_AUTH_TOKEN=<your-token>
export OPUS46_BASE_URL=<your-anthropic-compatible-gateway>
harbor run -c configs/release-v0.2-of11-claude-opus46.yaml --force-build -y

# MiniMax-M2.7-highspeed (line 7 key, full access)
export MINIMAX_API_KEY=<line-7-key>
harbor run -c configs/release-v0.2-of11-minimax-m27hs.yaml --force-build -y

# MiniMax-M2.5-highspeed and MiniMax-M2.7 (line 8 key, no M2.7-HS access)
export MINIMAX_API_KEY=<line-8-key>
harbor run -c configs/release-v0.2-of11-minimax-m25hs.yaml --force-build -y
harbor run -c configs/release-v0.2-of11-minimax-m27.yaml --force-build -y
```

MiniMax runs are routed via [`claude-code-router`](https://github.com/musistudio/claude-code-router);
the harness wires it up at trial setup. See
`tools/agent_harness.py:ClaudeCodeViaCcr`.
