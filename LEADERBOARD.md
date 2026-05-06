# Leaderboard

## v0.1 MVP Release Gate · 2026-05-03

v0.1 is a benchmark release first, not a broad leaderboard release. The public
repo should ship the task suite, deterministic verifier, case catalog, and
reproduction commands. A single reference model row can be added after a full
model run completes.

### Published Scope

| Scope | Count | Status |
|---|---:|---|
| Public runnable tasks | 36 | 20 LTspice + 16 OpenFOAM |
| Oracle-available tasks | 23 | 20 LTspice + 3 OpenFOAM |
| MVP scored gate | 20 | LTspice oracle-verified |
| OpenFOAM public tasks | 16 | Public catalog; base image/oracle packaging still needs release work |

### Current Results · v0.1 (2026-05-06)

#### LTspice circuits (20 tasks)

| Run | Agent / Model | Tasks | Errors | **Mean** | Notes |
|---|---|---:|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle (deterministic) | 20/20 | 0 | **1.000** | reference upper bound |
| `release-v0.1-ltspice20-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** (non-reasoning) | 20/20 | 1 | **0.936** | original 80-turn harness; per-case audit shows ~0.948 expected with v0.1-final harness |
| `release-v0.1-ltspice20-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** (reasoning) | 19/20 | 2 | **0.930** | v0.1-final harness (300-turn cap, ccr reasoning-block fix, Pass-2 hook). Up from 0.776 in 80-turn run. 1 case (bridge_rectifier_ripple) terminated at wall-time cap |

#### OpenFOAM fluids (3 oracle-available tasks)

| Run | Agent / Model | Tasks | Errors | **Mean** | Notes |
|---|---|---:|---:|---:|---|
| `release-v0.1-openfoam3-oracle-20260506` | oracle (deterministic) | 3/3 | 0 | **0.999** | reference upper bound; flatplate cf_x097 = 0.997 (within numerical noise) |
| `release-v0.1-openfoam3-minimax-m25hs-20260506` | claude-code · **MiniMax-M2.5-highspeed** | 3/3 | 1 | **0.408** | cavity_re100 1.0 / cavity_re1000 0.225 / flatplate 0.0 |
| `release-v0.1-openfoam3-minimax-m27-20260506` | claude-code · **MiniMax-M2.7** | 3/3 | 0 | **0.284** | cavity_re100 0.0 (extract paperwork bug — see caveat) / cavity_re1000 0.390 / flatplate 0.462 |

Per-case scores in [`results/v0.1/README.md`](./results/v0.1/README.md). JSON artifacts in
`results/v0.1/`.

### v0.1 reads (corrected after harness audit)

The v0.1 first-cut leaderboard (M2.5-highspeed 0.936 vs M2.7 0.776 on LTspice) **was
mostly an artifact of two harness limitations** that have since been fixed:

1. **ccr-plugins reasoning-block translation bug** (commit `b8d7372`): claude-code-router's
   OpenAI→Anthropic response translator could not map `reasoning_content` blocks to a valid
   Anthropic content type, exiting trials with `API Error: Content block is not a text
   block`. M2.7 hit this on 3/20 LTspice cases; M2.5-highspeed (non-reasoning) never hit it.
   After fix: those 3 cases now score 1.000 each. M2.7 mean rose **0.776 → 0.930** on the
   same suite.
2. **`max_turns: 80`** was tight enough for M2.5-highspeed (median ~25 turns) but cut off
   M2.5-highspeed's bridge_rectifier_ripple at turn 81 (0.7) and several M2.7 cases. Bumped
   to 300 in commit `df37b24`.

**Real model-capability finding** (only after harness fixes): M2.5-highspeed and M2.7 are
within ~0.6 % on LTspice (0.936 vs 0.930) — close to noise. M2.7 reasoning gives no
measurable LTspice headroom over fast non-reasoning, while costing ~10× per-turn latency.
**OpenFOAM tells a different story** that v0.2 needs more data to resolve — the M2.7 cases
that scored 0 are paperwork-related (relative paths in `extract` pipelines), not physics
failures, and v0.1's new Pass-2 Stop hook should fix that for v0.2.

The historical tables below are development history (v3 / v4 / v5 / v7 / v9–v18 OpenFOAM
work). They should not be presented as the v0.1 public result.

---

Every row is one run of Harbor's `terminus-2` agent (multi-turn tmux
session inside the task container) driving the named model over the
OpenAI-compatible [Paratera](https://llmapi.paratera.com/) endpoint.

**Pipeline.** Agent reads `instruction.md`, may consult the in-container
OpenFOAM skill at `/opt/sim-skills/openfoam/`, builds the OpenFOAM case
from physics first principles (no tutorial pointers given), runs the
solver, writes `/tmp/agent/result.json`. The case's own `tests/verify.py`
then produces a four-tier `reward.json` — `exec_ok` / `converged` /
`physics_faithful` / `kpi_accurate`, weighted 0.2 / 0.2 / 0.3 / 0.3.
No human-in-the-loop, no LLM-as-judge.

See `configs/paratera/full-matrix.yaml` for the exact configuration.

## v7 · 2026-04-23 · 6 models × 11 cases = 66 trials · `auth × 4-tier` schema

First apples-to-apples 6-model leaderboard on the 11-case v7 library.
**Kimi-K2.5 is the new leader at 0.9335.**

| Model | re100 | re400 | re1000 | pitzdaily | hotroom | dns-box | dambreak | v11-fork | cyl-nN | bernard-3d | oblique-sh | **mean** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Kimi-K2.5**              | 0.9963 | 0.9037 | 0.9961 | 0.9636 | 0.9159 | 0.7000 | 0.9846 | 0.9988 | 0.8344 | 0.9878 | 0.9869 | **0.9335** |
| **MiniMax-M2.7-highspeed** | 0.9885 | 0.9078 | 0.991  | 0.9815 | 0.9417 | 0.7000 | 0.9959 | 0.999  | 0.7928 | 0.8952 | 0.0000 | **0.8358** |
| **DeepSeek-V3.2-Thinking** | 0.9997 | 0.9217 | 0.9803 | 0.9300 | 0.4000 | 0.7991 | 0.4000 | 0.9990 | 0.7548 | 0.8198 | 0.2816 | **0.7533** |
| **DeepSeek-V3.2-Instruct** | 0.9989 | 0.8520 | 0.9757 | 0.9896 | 0.8111 | 0.4279 | 0.0000 | 0.9844 | 0.4001 | 0.8199 | 0.7373 | **0.7270** |
| Qwen3-Coder-Plus           | 0.4000 | 0.9348 | 0.9777 | 0.0000 | 0.6879 | 0.7000 | 0.0000 | 0.9998 | 0.0000 | 0.2152 | 0.6831 | **0.5090** |
| GLM-4.5-AirX               | 0.4000 | 0.9030 | 0.0000 | 0.8000 | 0.0000 | 0.7000 | 0.6701 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | **0.3157** |

### Stratified by case tier

**Tier S** = simple cavity family (re100, re400, v11-fork). **Tier M** = v6
hard cases (re1000, pitzdaily, hotroom, dns-box, dambreak). **Tier
FoamBench-novel** = the 3 new cases (cylinder-nN, bernard-3d, oblique-sh).

| Model | tier S (3 cases) | tier M (5 cases) | tier FB-novel (3 cases) | overall |
|---|---|---|---|---|
| **Kimi-K2.5**              | 0.9663 | 0.9120 | **0.9364** | **0.9335** |
| **MiniMax-M2.7-highspeed** | 0.9651 | 0.9220 | 0.5627      | 0.8358 |
| **DeepSeek-V3.2-Thinking** | 0.9735 | 0.7019 | 0.6187      | 0.7533 |
| **DeepSeek-V3.2-Instruct** | 0.9451 | 0.6409 | 0.6524      | 0.7270 |
| Qwen3-Coder-Plus           | 0.7782 | 0.4731 | 0.2994      | 0.5090 |
| GLM-4.5-AirX               | 0.4343 | 0.4340 | 0.0000      | 0.3157 |

### What the numbers say

- **Kimi-K2.5 took the v7 crown.** v5 mean 0.7276 → v7 mean 0.9335 — almost
  +0.21. The big lift comes from (a) `max_turns 40 → 100` resurrecting
  pitzdaily (0 → 0.96) and dns-box (0 → 0.70), and (b) genuinely strong
  performance on all 3 new cases (0.83 / 0.99 / 0.99). Kimi is the **only
  model** to score ≥ 0.7 on every case in the matrix.
- **MiniMax-M2.7-highspeed dropped from #1 to #2.** Stays strong on tier S/M
  (regime-identical to v6) but pulls down on tier FoamBench-novel —
  catastrophically on `oblique-shock` (0.0; never wrote `result.json` even
  with 100 turns) and notably on `cylinder-nonnewtonian` (0.79; agent
  declined to use Cross-Power-Law viscosity, fell back to constant nu).
- **DeepSeek-V3.2-Thinking is the tier-S champion** (0.9735, edges Kimi)
  but bombs hotroom (0.4) and dambreak (0.4) — same v5 weak cases that
  even 100 turns couldn't fix. Suggests a real physics gap, not a budget
  one.
- **DeepSeek-V3.2-Instruct stalls at 0.73.** Best on pitzdaily (0.99 — RANS
  closure done right) but **0 on dambreak** (multiphase setup failure
  despite 100 turns; this regressed from v5's 0.95).
- **Qwen3-Coder-Plus 0.51.** Bipolar: aces v11-fork (0.9998) and re400
  (0.9348), zeros on cavity-re100 / pitzdaily / dambreak / cylinder-nN.
  Looks like training-set memorization rather than physics reasoning.
- **GLM-4.5-AirX 0.32.** Catastrophically narrow — only re400 / pitzdaily
  / dns-box / dambreak produce non-zero scores. The 3 GLM trials that
  Harbor reported as exceptions (cavity-re1000, hotroom, v11-fork) all
  failed to write reward.json — an infrastructure-level collapse, not
  just bad physics.

### Where the 3 new FoamBench cases discriminate

The "tier FoamBench-novel" column is where models separate most:

- **`cylinder-nonnewtonian`** — only Kimi (0.83) and MiniMax (0.79) cleared
  0.5. The Cross-Power-Law viscosity model is the gate; agents that fall
  back to constant nu lose KPI accuracy by ~50× on max p.
- **`bernard-cells-3d`** — Kimi at 0.99 sets the ceiling; MiniMax 0.90;
  the rest 0.82 / 0.82 / 0.22 / 0. Tests 3D buoyant-flow setup correctness.
- **`oblique-shock`** — Kimi 0.99 vs MiniMax 0.0 vs Instruct 0.74 vs
  Thinking 0.28. **rhoCentralFoam + shock capturing scheme + normalized
  thermo** is the new "tier-L gate" — splits the field clearly.

### Method note

Run config: `configs/paratera/v7-11case.yaml` (paratera 5) +
`configs/minimax/v7-3new.yaml` rerun (MiniMax 3 new cases) + retained
v6 scores for MiniMax on 8 originals (schema-preserving). All trials at
`max_turns=100`, tutorials stripped, sim-skills mounted, multi-KPI
schema with authenticity gate. paratera matrix wall time: 2h 27m.

3 GLM trials produced no `reward.json` (Harbor reports as exceptions);
treated as 0 in aggregation.

### What changed schema-wise from v6

- `[[metadata.sim.kpis]]` array is now the authoritative KPI spec; each
  case can declare 1..N KPIs with weights. `reward.json` accepts both
  `{"kpis": {name: value, ...}}` and legacy `{"RESULT": value}` (the
  latter only when there is exactly one declared KPI).
- **Authenticity gate**: `verify.py` scans for a real OpenFOAM case dir
  (`constant/polyMesh/` + a time-dir with at least one standard field
  file). If absent, score is forced to 0 regardless of `RESULT` content —
  closes the "hardcode the right number" loophole.
- All 8 v6 cases were migrated; oracle re-verified bit-for-bit identical
  to v6.

### What changed library-wise

3 new cases from
[NLR-Theseus CFDLLMBench / FoamBench](https://github.com/NLR-Theseus/cfdllmbench):
`cylinder-nonnewtonian` (pimpleFoam + Cross-Power-Law viscosity),
`bernard-cells-3d` (buoyantFoam + 3D natural convection),
`oblique-shock` (rhoCentralFoam + 2D compressible shock). All three on
Foundation v10. Each ships 2 KPIs (primary weight 0.6 + secondary 0.4),
oracle-self-calibrated. Coverage: 8 → 11 cases; 5 → 8 OpenFOAM solvers;
+ compressible / + non-Newtonian / + 3D buoyancy.

## v6 · 2026-04-22 · MiniMax-M2.7-highspeed · stricter regime

Two methodology shifts relative to v5:

1. **OpenFOAM tutorials stripped from the container image.** v5 left
   `/usr/lib/openfoam/openfoam2412/tutorials/` intact; a subsequent smoke
   test showed MiniMax-M2.7 discovering and reading tutorial `blockMeshDict`
   / `controlDict` files on its own within the first 20 turns (v5 paratera
   models didn't). Commit `d36d691` deletes both ESI and Foundation tutorial
   trees at image build time and blanks `FOAM_TUTORIALS`. Oracle stays
   functional via a bundled `solution/tutorial-ref/` — invisible to the
   agent because Harbor only mounts `solution/` for `--agent oracle`.
2. **`max_turns` raised from 40 to 100.** MiniMax-M2.7 is a thinking model;
   the first smoke run burned 30 of its 40-turn budget on references before
   starting real work. Bumping to 100 lets the model actually finish.

**Tested in this regime**: `anthropic/MiniMax-M2.7-highspeed` via
`api.minimaxi.com/anthropic`. The full thinking variant was also run but
dropped after pitzdaily scored 0 even with 100 turns — thinking overhead
outweighed reasoning gain for our turn-bounded harness.

| Model | re100 | re400 | re1000 | pitzdaily | hotroom | dns-box | dambreak | v11-fork | **mean** |
|---|---|---|---|---|---|---|---|---|---|
| **MiniMax-M2.7-highspeed** | 0.9885 | 0.9078 | 0.991 | 0.9815 | 0.9417 | 0.7000 | 0.9959 | 0.9990 | **0.9382** |

Tier breakdown: S (re100, re400, v11-fork) = **0.9651**; M (rest) = **0.9220**.
Only miss is `dns-boxturb16` (0.70) — agent kept writing DNS-style setups
the solver didn't like; even 100 turns didn't resolve it. Every other case
lands ≥ 0.91.

**Cross-regime note**: the two changes in v6 affect the two model groups
differently.
- **Deleting tutorials**: v5 forensic grep of the paratera trajectories
  showed zero reads of `/usr/lib/openfoam/openfoam2412/tutorials/` across
  all 40 trials — paratera models never relied on that path. So the
  stripping affects only MiniMax-family behaviour, not paratera scores.
- **`max_turns` 40 → 100**: this *could* move paratera scores on their
  v5 zero-at-ceiling cases (Kimi pitzdaily / dns, Instruct pitzdaily,
  Thinking hotroom). Those five runs ended with agents still trying,
  so more turns might salvage them.

A clean apples-to-apples re-run of the five paratera models at
`max_turns=100` (image-identical otherwise) is what's actually missing
from the table. Not in this commit.

Configs: `configs/minimax/rerun-m27-highspeed.yaml` (rerun @ 100 turn for
7 cases) + the retained `cavity-re1000` score from the original
`configs/minimax/full-matrix.yaml` at 40 turn.

## v5 · 2026-04-22 · 5 models × 8 cases = 40 trials

| Model | re100 | re400 | re1000 | pitzdaily | hotroom | dns-box | dambreak | v11-fork | **mean** |
|---|---|---|---|---|---|---|---|---|---|
| **DeepSeek-V3.2-Thinking** | 0.9996 | 0.9027 | 0.9758 | 0.9769 | 0.5000 | 0.7991 | 0.9783 | 0.9997 | **0.8915** |
| **DeepSeek-V3.2-Instruct** | 0.9992 | 0.9062 | 0.9745 | 0.4120 | 0.5000 | 0.7981 | 0.9476 | 0.9991 | **0.8171** |
| **Kimi-K2.5**              | 0.9926 | 0.9266 | 0.9704 | 0.0000 | 0.9374 | 0.0000 | 0.9959 | 0.9982 | **0.7276** |
| GLM-4.5-AirX               | —      | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | **0.1429** |
| Qwen3-Coder-Plus           | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | **0.0000** |

GLM `re100` cell shows `—` because that trial hit a paratera "prompt
exceeds max length" infrastructure error and never produced a
`reward.json` — treated as missing data, not a 0.

_Short names:_ `re100 / re400 / re1000` = `lid-driven-cavity-re{100,400,1000}`;
`pitzdaily` = `pitzdaily-bfs-rans`; `v11-fork` = `cavity-re100-foundation-v11`
(same physics as re100, OpenFOAM Foundation v11 base image).

## Stratified by difficulty tier

`task.toml` declares each case's `difficulty_tier`. **Tier S** = cavity-family /
simple incompressible laminar (cavity-re100, re400, v11-fork — three of eight
cases). **Tier M** = turbulent, multiphase, buoyant, DNS, or transient with
non-trivial integration time (the other five).

| Model | tier S (3 cases) | tier M (5 cases) | overall |
|---|---|---|---|
| DeepSeek-V3.2-Thinking | **0.9673** | **0.8460** | **0.8915** |
| DeepSeek-V3.2-Instruct | 0.9682 | 0.7264 | 0.8171 |
| Kimi-K2.5              | 0.9725 | 0.5807 | 0.7276 |
| GLM-4.5-AirX           | 0.5000 | 0.0000 | 0.1429 |
| Qwen3-Coder-Plus       | 0.0000 | 0.0000 | 0.0000 |

## What the numbers say

- **DeepSeek-V3.2-Thinking is the clear leader.** Only model to score ≥ 0.9
  on a majority of tier-M cases. The reasoning trace that hurt it on the
  earlier tutorial-based leaderboard (where it over-thought simple `cp`
  operations) pays off when the agent has to build turbulence closures,
  multiphase initialisation, and buoyancy models from physics rather than
  from disk.
- **Kimi and Instruct are paired mid-tier.** Both ace tier S (≈ 0.96),
  both struggle on tier M (≈ 0.55). Kimi edges Instruct thanks to
  dambreak (0.98 vs 0.40) and pitzdaily (0.00 vs 0.42) — two KPIs where
  one of them happened to wire the RANS closures right and the other
  didn't.
- **Qwen collapses without tutorial pointers.** Previous leaderboard
  (with `$FOAM_TUTORIALS` hint in instruction.md) had Qwen at 0.37; on
  this from-scratch run Qwen hits 0.12 — and of that, 0.9986 is one lucky
  cavity-re100 hit. On tier M it scores 0.0 across the board. Strong
  "training-data recall" vs "engineering capability" signal.
- **GLM similarly shows it was a cp+sed operator.** Previous 0.65 → 0.05.
- **`pitzdaily-bfs-rans` separates Thinking from the rest.** 0.998 vs
  ≤ 0.42 — authoring a working k-ε RANS setup with the right wall-function
  choice from natural language alone is the sharpest single-case signal
  in the matrix.

## Three-version evolution (what each step measured)

| Run | Setup | What it tested | Outcome |
|---|---|---|---|
| **v3** (post-leak-fix) | `instruction.md` says sim-cli is "recommended"; no skill docs in container | Baseline — agent free to use raw shell, no domain doc help | Thinking 0.876 / Instruct 0.698 / Kimi 0.719 / Qwen 0.125 / GLM 0.050 |
| **v4** (sim-cli forced) | `instruction.md` says sim-cli is REQUIRED | Does forcing the tool layer help or hurt? | All scores dropped; Thinking lost 0.58. Listening agents (Thinking 86% sim_cli use) got penalised hardest. **sim-cli OpenFOAM driver too thin to add value, mandate is friction.** |
| **v5** (skill docs added, sim-cli back to recommended) | `/opt/sim-skills/openfoam/` mounted with 17 reference docs (case-setup, solver-selection, BCs, turbulence, mesh, numerics, multiphase, heat, parallel, post-proc, error-recovery, etc.); instruction relaxed | Does CAE domain documentation help, with no tool mandate? | Thinking 0.892 (+1.6% vs v3), Instruct 0.817 (+12%), Kimi 0.728 (~flat), GLM 0.143 (+9%), Qwen 0.000 (-12%). 4/5 models improved; Instruct biggest gainer. **Pure-doc skill is net positive; tool mandate is net negative.** |

`sim_cli_used` rate in v5 = 0% across all models — when given the
choice, every model invoked OpenFOAM binaries directly via shell
(`blockMesh && icoFoam …`). The skill docs were consulted (every
high-scoring trajectory shows `cat /opt/sim-skills/openfoam/SKILL.md`
plus topical references) but the recommended `sim run` wrapper was
ignored. The wrapper currently doesn't save the agent any work, so
"recommended" reads as "skip it." Follow-on work tracked on [GitHub issues](https://github.com/svd-ai-lab/sim-benchmark/issues).

## Caveats (still in progress — see [GitHub issues](https://github.com/svd-ai-lab/sim-benchmark/issues))

- **Three cases use oracle-self-calibrated GT** (hotroom, dns-boxturb16,
  dambreak). Replacing those with literature-anchored references is
  Phase B2; coupled to A2 (novel variants) and deferred.
- **Oracle uses sim-cli's `OpenFOAMDriver.parse_log` for
  converged/residuals**, but agents are only encouraged — not required —
  to use sim-cli when running the solver. Forensic checks (tmux
  trajectory grep) on the top-scoring trials confirm agents built cases
  from scratch (no `cp` of tutorials, no `$FOAM_TUTORIALS` access) but
  ran `blockMesh` / `icoFoam` / `simpleFoam` directly rather than through
  `sim run`. Making sim-cli mandatory (e.g. by scrubbing solver binaries
  from PATH) is future work.
- **A2 novel variants (trapezoidal cavity, inclined BFS) still not in
  the set.** All 8 cases map 1-to-1 to standard tutorial geometries, so
  agents with tutorial geometries memorised in training weights can
  succeed without true from-scratch geometric reasoning. That signal is
  measurable only once A2 lands.

## Regenerating this table

Full four-tier breakdowns per trial are under `jobs/paratera-matrix*/`:

```bash
python3 tools/aggregate_leaderboard.py \
    jobs/paratera-matrix/<ts> \
    jobs/paratera-matrix-v11/<ts>
```
