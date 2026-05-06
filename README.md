# sim-benchmark

**sim-benchmark** 是一个面向工业仿真 agent 的 benchmark：给 LLM agent 一个真实仿真任务，让它建模、运行 solver、处理报错、提取工程 KPI，并提交可验证的结果。

目标不是证明某个内部 CLI 有用，而是回答一个更大的问题：

> LLM agent 到底能不能完成真实工业仿真任务？失败在哪里？

English: see [README.en.md](./README.en.md).

## What It Measures

每个 case 都要求 agent 端到端完成一件仿真工作：

- 从自然语言任务描述搭建 case
- 调用可用 solver 或仿真工具
- 处理运行失败、收敛问题、文件格式问题
- 从真实 solver artifact 中提取 KPI
- 写出 `/tmp/agent/result.json`

主分数只看 **真实 artifacts + KPI accuracy + source provenance**。agent 是否使用 `sim` / sim-cli 只作为诊断信息，不是得分门槛。

## Design Principles

### 1. 真实 solver，不用 LLM-as-judge

Verifier 是确定性的。它读取 agent 产生的文件、solver log、run history 或后处理输出，重新抽取 KPI 并计算分数。

### 2. 强 provenance，不强制成功

每个 KPI 必须是：

```json
{
  "value": 1.23,
  "source": {
    "kind": "file_extract",
    "path": "/root/case/output.log",
    "extract": "grep '^kpi:' | awk '{print $2}'"
  }
}
```

verifier 会重新执行 `extract`，确认 `value` 真能从声明的 source 里得到。裸数字、假 source、无法重抽取的值不得分。
不要手写、编辑或伪造 solver log、`.meas` 输出、`.raw` 数据或 run history 来满足 provenance。

推荐 task wording：

> Report only values that can be re-extracted from artifacts you produced. If the simulation fails, report the failure with a verifiable log source.

### 3. Case 分层

公开 suite 会区分：

- `smoke`: 高 leakage / 快速环境验证 / 示例
- `public_eval`: public leaderboard 的主评测
- `hidden_eval`: 未来商业软件 license suite 的私有 holdout

经典公开题（例如 Ghia cavity、标准 RC filter）适合 smoke，不适合作为 headline 证据。

### 4. Scoring Templates

每个 case 使用少数标准评分模板之一，而不是随意定义权重。

| Template | 用途 | Groups |
|---|---|---|
| `measurement` | 普通仿真 + KPI 测量 | `setup 0.10`, `outputs 0.90` |
| `numerical` | 明确测收敛/残差/稳定性 | `setup 0.10`, `numerical 0.15`, `outputs 0.75` |
| `workflow` | GUI / 多步流程 / artifact export | `setup 0.15`, `process 0.25`, `outputs 0.60` |

空 group 是无效 schema：如果一个 group 有正权重，必须至少有一个 KPI 引用它。

## Current Domains

所有公开 case 的当前状态见 [CASES.md](./CASES.md)。OpenFOAM 和 LTspice cases
都公开；`oracle_status` 单独标出 no-token oracle 是否已经可用，没有 oracle
不等于 draft。

### v0.1 MVP Scope

v0.1 发布 36 个 public runnable tasks：20 个 LTspice circuits 和 16 个
OpenFOAM fluids。MVP scored gate 先只承诺 20 个 LTspice oracle-available
tasks；它们已经在当前 release gate 中达到 `20/20`, mean `1.000`。

OpenFOAM 16 个 task 保留在公开 catalog 中，其中 3 个已有 oracle 标记，13 个
oracle deferred。OpenFOAM 的默认 release gate 还需要先发布或文档化
`svd-ai-lab/sim-benchmark-base:latest` base image。

发布用结果见 [RESULTS.md](./RESULTS.md) 和
[`results/v0.1/`](./results/v0.1/)。

### Fluids / OpenFOAM

OpenFOAM cases 主要用于公开透明的 CFD proving ground 和 pipeline shakedown。它们适合验证 harness、verifier、artifact provenance 和 failure taxonomy。

### Circuits / LTspice

LTspice cases 覆盖 SPICE 类电路仿真、`.meas`、log/source extraction、Wine/headless batch quirks。普通 `.meas` cases 使用 `measurement` 模板。

## Quickstart

### Docker + Harbor

```bash
uv tool install harbor
docker --version
```

### Oracle Smoke, No LLM Token

```bash
harbor run -p cases/circuits --agent oracle -i rc_highpass_ac
```

### Windows Docker Desktop Notes

PowerShell 下运行 Harbor + Docker Desktop 时建议设置：

```powershell
$env:DOCKER_HOST='npipe:////./pipe/docker_engine'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

## Repository Layout

```text
sim-benchmark/
├── cases/
│   ├── fluids/       # CFD / OpenFOAM tasks
│   └── circuits/     # SPICE / LTspice tasks
├── configs/          # Harbor run configs
├── docs/             # design notes and appendices
├── environment/      # base Docker images
├── lib/
│   └── sim_benchmark_verifier/
├── tools/            # harness, lint, aggregation, rescore
├── results/          # published v0.1 reference run artifacts
├── SCHEMA.md
└── LEADERBOARD.md
```

## Launch Direction

The public v0 goal is a credible Industrial Simulation Agent leaderboard:

- small but high-quality OpenFOAM + LTspice public eval set
- deterministic verifier
- source-provenance scoring
- failure taxonomy
- cost and wall-time reporting

sim-cli remains useful infrastructure, but not the headline variable.

See [RELEASE.md](./RELEASE.md) for the MVP release checklist and latest local
gate results.
