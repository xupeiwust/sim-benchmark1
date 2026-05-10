# lid-driven-cavity-re100

First Phase-1 end-to-end case. Lid-driven cavity, Re=100, 2D steady.
Reference: Ghia, Ghia & Shin (1982) Table I, u_centerline_y0.5 ≈ −0.20581.

## Status (2026-04-21) — ✅ Phase 1 done-signal MET

| Check | Status |
|---|---|
| Directory layout matches SCHEMA.md | **done** |
| `task.toml` passes `tools/lint_case.py` | **done** |
| Dockerfile builds via Harbor's compose stack | **done** |
| Oracle `solve.sh` runs green, all four reward tiers ≥ 0.9 | **done** — `exec_ok:1, converged:1, physics_faithful:1, kpi_accurate:0.936`, pred u = −0.19259 vs GT −0.20581 |
| `test.sh` against broken run returns `exec_ok = 0` | **done** — verifier correctly emits `"no RESULT JSON on last stdout line"` |
| `harbor run` end-to-end | **done** — Mean 0.981, Reward 0.9807 via `harbor run -p ... --agent oracle` (no custom runner code) |

## Latest Harbor run

```
~/.local/bin/harbor run -p cases/openfoam/lid-driven-cavity-re100 \
    --agent oracle --jobs-dir /tmp/harbor-jobs

  1/1 Mean: 0.981 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 0:00:23 0:00:00
adhoc • oracle
┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ Trials ┃ Exceptions ┃  Mean ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│      1 │          0 │ 0.981 │
└────────┴────────────┴───────┘
```

Per-trial detail preserved at
`/tmp/harbor-jobs/<job-id>/<trial-id>/verifier/reward_detail.json`:

```json
{"exec_ok": 1.0, "converged": 1.0, "physics_faithful": 1.0, "kpi_accurate": 0.9358}
```

## Prerequisites on the build host

See `SCHEMA.md §9` for the full recipe. Minimum:

```bash
# one-time
git clone https://github.com/svd-ai-lab/sim-cli.git /tmp/sim-cli-clone
git -C /tmp/sim-cli-clone checkout ba9e157

# If the daemon's registry-mirrors can't resolve docker.io:
docker pull docker.1panel.live/opencfd/openfoam-default:2412
docker tag  docker.1panel.live/opencfd/openfoam-default:2412 opencfd/openfoam-default:2412
# (our docker-compose.yaml passes BASE_REGISTRY=docker.1panel.live as a
#  build-arg, so this tag is what Harbor's build will actually reach)
```

## Ad-hoc invocation (outside Harbor)

For iteration without full Harbor overhead:

```bash
docker build \
    --network=host \
    --build-arg BASE_REGISTRY=docker.1panel.live \
    --build-context sim-cli-src=/tmp/sim-cli-clone \
    -t sim-benchmark/cavity-re100 \
    cases/openfoam/lid-driven-cavity-re100/environment

docker run --rm \
    -v $PWD/cases/openfoam/lid-driven-cavity-re100:/case:ro \
    --tmpfs /logs \
    --user root --entrypoint bash \
    sim-benchmark/cavity-re100 \
    -c '/case/solution/solve.sh && /case/tests/test.sh && cat /logs/verifier/reward.json'
```

## Known design points worth revisiting

- **`converged` tier is a proxy.** Currently `converged = 1.0` iff the script
  reached the final JSON print. A real residual-based check requires sim-cli
  to expose residuals in `RunResult` — tracked against
  `feedback_sim_tool_layer.md`.
- **Tutorial `endTime` bump.** `solve.py` extends `system/controlDict` from
  0.5 s to 2.0 s so Re=100 actually settles. If a finer mesh is adopted later,
  revisit this.
- **BASE_REGISTRY override is CN-specific.** Public users keep the
  `docker.io` default inside the Dockerfile; our `environment/docker-compose.yaml`
  overrides it for the current build host. Not a portability concern for v0
  (private repo, internal team), but will need cleanup before any public
  release.
