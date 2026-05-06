# sim-benchmark

> **工业仿真 agent 测评。** 给 LLM agent 一个真实 CAE/EDA 任务——划网格、写
> 边界条件、跑 solver、解析 log、提取 KPI——按它**实际产出的工件**打分。
> 不用 LLM-as-judge：verifier 拿 agent 自己声明的提取命令，对它产生的
> solver 工件**重新执行一次**，对得上才得分。

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tasks](https://img.shields.io/badge/v0.1-36%20公开任务-success)](CASES.md)
[![Solvers](https://img.shields.io/badge/solvers-OpenFOAM%20%7C%20LTspice-informational)]()

English version → [`README.md`](README.md)

---

## 在测什么

每道题给 agent 三样东西：自然语言任务描述、装好真 solver 的容器、一条规则——
产出 `/tmp/agent/result.json`，每个 KPI 都要带 **source provenance**：
`(value, source.kind, source.path, source.extract)`。Verifier 拿 `source.extract`
对 agent 真产生的文件**重新跑一次**抽取，对不上、查不到、伪造的全部 0 分。

**故意不在范围内**：不是知识问答，不是 Fluent 语法测验，不是 LLM-as-judge
比赛。**也不要求 agent 必须用某个特定工具**——sim-cli、solver 原生 CLI、
Python 包装、agent 自己写的脚本，都行。**工具是手段不是被测对象**。

## v0.1 范围

| 域 | 题数 | Oracle 可用 | 后端 solver |
|---|---:|---:|---|
| 电路 / SPICE | 20 | 20 | LTspice（免费、open-format） |
| 流体 / CFD | 16 | 3 | OpenFOAM（开源） |
| **合计** | **36** | **23** | |

MVP 评分门是 20 个 LTspice 题。在 Linux + Wine 上跑，确定性 oracle
baseline = **mean reward 1.000**。16 个 OpenFOAM 题作为公开 catalog
成员发布，目前只有 3 个有"无 token oracle"脚本（其余 13 个是公开 +
verifier 已定义 + 任意模型可跑，但 oracle baseline 推迟到 v0.2）。

未来商业 solver case（Ansys Mechanical / Abaqus / Flotherm / Fluent）
会进 `release_status: hidden_eval`，只在授权 license run 时评测。
**这次公开 release 不包含**这些 case。

完整 catalog（含 leakage / tier / oracle 状态）见
[`CASES.md`](CASES.md)；case / verifier 契约见 [`SCHEMA.md`](SCHEMA.md)。

## 首日成绩（参考运行）

每个 case 都 ship 一个确定性 `solution/solve.sh`（**oracle**）。Oracle 跑
出的分数 = 当前 verifier 下可达的上限；任何模型的分数都对它读。

| 运行 | Agent | 题数 | Mean reward | 状态 |
|---|---|---:|---:|---|
| `release-v0.1-ltspice20-oracle` | Oracle（确定性） | 20 | **1.000** | 参考上限 |
| `release-v0.1-ltspice20-minimax-m25` | MiniMax-M2.5-highspeed | 20 | _跑测中_ | 非推理 |
| `release-v0.1-ltspice20-minimax-m27` | MiniMax-M2.7 | 20 | _跑测中_ | 推理 |

逐 case 分数和机读 artifact 见 [`results/v0.1/`](results/v0.1/)；
[`LEADERBOARD.md`](LEADERBOARD.md) 跟踪历史和 ablation 结果。

## 三种受众，分别为什么该读

### AI / agent 公司

我们给你一个**端到端、可复现、硬骨头**的任务套——能拿分的只有"模型实际
产出了什么"，不是"模型在 chat 里说了对的答案"。每道题都是真 solver
跑一遍：模型写 netlist、跑 LTspice、解 log，**把解析命令一并交上来**。
我们重跑解析命令，跟你给的 value 对不上 = 那条 KPI 拿 0。

得到的信号：
- 干净分离"知道"型模型 vs"能完成"型模型；
- 按题目难度（S/M/L）、leakage 等级、模板（measurement / numerical /
  workflow）切片；
- 本地 `harbor` + Docker 跑得起来——没提交门户、没 API key 上交我们、
  没 rate-limit 的 grader。

要发 leaderboard row，看 [`REPRODUCING.md`](REPRODUCING.md)；
harness 在每次试运行时做了什么，看 [`docs/hooks.md`](docs/hooks.md)。

### CAE / EDA 软件厂商

CAE 行业说"agent 层不够稳"已经十年了。这个 benchmark 把"不够稳"变成
**真实 case + 真实 solver 工件 + 物理-vs-数值 pass criteria 上的可测
信号**——能具体讨论"哪个 agent loop 在哪个 solver 上断了"。

可以用它来：
- 评估 AI agent 能不能驱动你家 solver 到客户场景的自动化水平；
- 贡献商业 solver case（我们放 `hidden_eval`，只在你授权 license
  run 时评测）；
- 把内部 solver wrapper / Python API 拿同一套题跑一遍，跟开源社区结果
  对齐。

契约在 [`SCHEMA.md`](SCHEMA.md)。新 case 走 PR，会按可验证性 review——
tier / leakage 规范见
[`cases/circuits/README.md`](cases/circuits/README.md) 和
[`cases/fluids/README.md`](cases/fluids/README.md)。

### CAE 工程实际用户

要是被问过"咱们要不要在 solver 流程前面加个 LLM"，这就是你的尺子。
跑一下 oracle smoke（无 LLM、免费）：

```bash
uv tool install harbor
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y
# 期望：reward = 1.000，Docker Desktop 上 ~1 min wall。
```

返回 1.0 = 你环境对了，之后跑任何模型都是 apples-to-apples。把上面那条
命令的 `--agent oracle` 换成 `--agent claude-code`（或你的 wrapper）就
是真模型测评。三条复现路径见 [`REPRODUCING.md`](REPRODUCING.md)。

## 5 分钟快速上手（无 LLM）

```bash
# 1. 装 harbor（runner，跟 Terminal-Bench 同款）
uv tool install harbor

# 2. clone
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark

# 3. 单个电路 case oracle smoke（无 LLM、免 API key）
harbor run -p cases/circuits -i rc_highpass_ac --agent oracle -y

# 4. CFD case oracle smoke（也无 LLM；本地需要先 build OpenFOAM
#    base 镜像，见 REPRODUCING.md Path B）
harbor run -p cases/fluids -i lid_driven_cavity_re100 --agent oracle -y
```

两条都该打印 `reward: 1.000`。其它任何值 = bug 在你的环境，不在 agent。

## 60 秒看懂打分

每个 case 在 `tests/kpis.json` 里列出 KPI 和测量方法。Agent 提交：

```json
{
  "kpis": {
    "f_3db": {
      "value": 175.6,
      "source": {
        "kind": "ltspice_log",
        "path": "rc_lowpass.log",
        "extract": "section=measure name=f_3db"
      }
    }
  }
}
```

Verifier 打开 `rc_lowpass.log`，按 `extract` 跑一次抽取，得到实际值，
和 ground truth 在 `tests/kpis.json` 声明的容差内对比。每种任务用对应
模板：

| 模板 | 权重组 | 用途 |
|---|---|---|
| `measurement` | setup 0.10 / outputs 0.90 | "测这个电路的 …" |
| `numerical` | setup 0.10 / numerical 0.15 / outputs 0.75 | "这个 CFD 必须收敛" |
| `workflow` | setup 0.15 / process 0.25 / outputs 0.60 | 多步 GUI / artifact 任务 |

总分 = 各组均值的加权和。形式化契约见 [`SCHEMA.md`](SCHEMA.md)。

## 仓库布局

```text
sim-benchmark/
├── cases/
│   ├── circuits/          # 20 个 LTspice 题
│   └── fluids/            # 16 个 OpenFOAM 题
├── configs/               # release 运行配置（oracle / M2.7 / M2.5）
├── docs/                  # 设计 appendix
├── environment/
│   ├── base/              # OpenFOAM base 镜像
│   └── wine-base/         # LTspice-on-Wine 镜像
├── lib/
│   └── sim_benchmark_verifier/   # grader（Python）
├── tools/                 # harness / lint / 聚合 / scoring 工具
├── results/v0.1/          # 已发布参考运行 artifact
├── CASES.md               # 公开 catalog（status / leakage / tier）
├── LEADERBOARD.md         # 历史与 ablation 结果
├── ORACLE.md              # oracle baseline + verifier sanity
├── RELEASE.md             # v0.1 release gate
├── REPRODUCING.md         # 三条复现路径
└── SCHEMA.md              # case + verifier 契约
```

## 路线图

- **v0.1（当前）**：36 公开 case、确定性 verifier、LTspice 20 oracle
  gate 1.000、首日 MiniMax 参考 row。
- **v0.2**：发布 OpenFOAM base 镜像；补全 13 个 OpenFOAM 无 token
  oracle；Docker Hub 包分发硬化。
- **v0.3**：在 `hidden_eval` 加第二条商业 solver 线（Mechanical 或
  Abaqus，授权 license run 下评测）。
- **v1.0**：stable schema、公开 leaderboard、多 org 提交流程。

未完成工作见 [GitHub Issues](https://github.com/svd-ai-lab/sim-benchmark/issues)。

## 贡献

欢迎 PR。两类常见贡献：

- **新 case**。Circuits 用 [`tools/new_circuit_case.py`](tools/new_circuit_case.py)；
  Fluids 复制现有 case 当模板。开 PR 前跑
  [`tools/lint_case.py`](tools/lint_case.py) 和 verifier 测试。详细见
  [`SCHEMA.md`](SCHEMA.md) §9。
- **新模型 harness**。新 `agent_harness.py:Agent` 子类，自带路由层。
  现有 CC + ccr 模式见 [`tools/agent_harness.py`](tools/agent_harness.py)。

launch 策略（problem-first 而非 tool-first）的 reasoning，见
[内部 repo PR #2](https://github.com/svd-ai-lab/sim-benchmark-internal/pull/2)。

## 引用

```bibtex
@misc{simbenchmark2026,
  title  = {sim-benchmark: An Industrial Simulation Agent Benchmark},
  author = {{svd-ai-lab}},
  year   = {2026},
  url    = {https://github.com/svd-ai-lab/sim-benchmark},
  note   = {v0.1}
}
```

## License

Apache 2.0，详见 [`LICENSE`](LICENSE)。

仓库自带的 case asset（LTspice netlist、OpenFOAM mesh）按其 upstream
license——见每个 case 的 `solution/` 目录。
