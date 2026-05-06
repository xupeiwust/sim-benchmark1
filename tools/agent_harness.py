"""sim-benchmark agent harness.

Two ClaudeCode subclasses tailored for the way we drive sim-benchmark
trials. Both replace upstream `ClaudeCode.install()`'s
`curl https://claude.ai/install.sh` (geo-restricted in CN) with an
npm + taobao mirror install of `@anthropic-ai/claude-code`. Both also
register the sim-skills directory into `~/.claude/skills/` at install
time so Claude Code surfaces them as native skills.

Two flavors:

  ClaudeCodeAnthropicDirect (was: ClaudeCodeCN)
      Claude Code → ANTHROPIC_BASE_URL directly. Use when the model
      speaks Anthropic protocol natively (MiniMax via
      api.minimaxi.com/anthropic, Anthropic API itself, etc.). Token
      usage propagates correctly via Claude Code's own usage events.

  ClaudeCodeViaCcr (was: ClaudeCodeCNCcr)
      Claude Code → claude-code-router (3456) → openai_usage_proxy
      (3457) → OpenAI-format upstream (paratera Kimi/GLM/DeepSeek/...).
      The local proxy injects `stream_options.include_usage=true` and
      normalizes the per-request `cch=<hex>` cache-buster — both
      necessary for token data + prompt caching to work on
      ccr-routed paths. Sidecar log at /logs/agent/proxy-usage.jsonl is
      consumed by tools/cost_meter.py.

Reference in YAML:
    agents:
      # Anthropic-format (MiniMax direct)
      - import_path: tools.agent_harness:ClaudeCodeAnthropicDirect
        model_name: MiniMax-M2.7-highspeed
        env:
          ANTHROPIC_API_KEY: 'sk-...'
          ANTHROPIC_BASE_URL: 'https://api.minimaxi.com/anthropic'

      # OpenAI-format (paratera) via in-container ccr + proxy
      - import_path: tools.agent_harness:ClaudeCodeViaCcr
        model_name: Kimi-K2.5
        env:
          CCR_UPSTREAM_BASE: 'https://llmapi.paratera.com/v1/chat/completions'
          CCR_UPSTREAM_KEY:  'sk-...'
"""
import base64
import json
import shlex
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.utils.env import resolve_env_vars

shlex_quote = shlex.quote

NPM_REGISTRY = "https://registry.npmmirror.com"
NODE_MIRROR = "https://npmmirror.com/mirrors/node"
NODE_VERSION = "20.19.0"


async def _ensure_node_and_claude(agent, environment, claude_version):
    check = await agent.exec_as_root(
        environment,
        command="node --version 2>/dev/null | grep -qE '^v(1[6-9]|[2-9][0-9])' && echo PRE_INSTALLED || echo NEED_INSTALL",
    )
    node_present = "PRE_INSTALLED" in (check.stdout or "")
    if not node_present:
        await agent.exec_as_root(
            environment,
            command=(
                "set -euo pipefail; "
                f"curl -fsSL {NODE_MIRROR}/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-x64.tar.gz"
                f" | tar -xz -C /usr/local --strip-components=1; "
                "node --version; npm --version"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
    version_suffix = f"@{claude_version}" if claude_version else ""
    await agent.exec_as_agent(
        environment,
        command=(
            "set -euo pipefail; "
            f"npm config set registry {NPM_REGISTRY} && "
            "{ claude --version 2>/dev/null || "
            f"npm install -g @anthropic-ai/claude-code{version_suffix}; }} && "
            "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc && "
            "export PATH=\"$HOME/.local/bin:$PATH\" && "
            "claude --version"
        ),
    )


class ClaudeCodeAnthropicDirect(ClaudeCode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Harbor's factory passes agent.env raw (literal "${VAR}" strings).
        # claude reads env via Harbor's _exec env merge — without expanding
        # the templates here, claude sees literal "${MINIMAX_API_KEY}" as
        # the auth value and the upstream returns 401.
        self._extra_env = resolve_env_vars(self._extra_env)

    async def install(self, environment: BaseEnvironment) -> None:
        await _ensure_node_and_claude(self, environment, self._version)
        await _register_sim_skills(self, environment)
        await _install_hooks(self, environment)


class ClaudeCodeViaCcr(ClaudeCode):
    """CC + claude-code-router running inside the trial container.

    Reads CCR_UPSTREAM_BASE / CCR_UPSTREAM_KEY from the container env to build
    a minimal ccr config that proxies the agent's `model_name` to that upstream.
    Then exports ANTHROPIC_BASE_URL=http://127.0.0.1:3456 for CC to use.
    """

    async def install(self, environment: BaseEnvironment) -> None:
        await _ensure_node_and_claude(self, environment, self._version)
        # Bake the upstream values into the config via Python interpolation,
        # not bash ${VAR} expansion. Heredoc-time env vars proved fragile
        # (an empty CCR_UPSTREAM_KEY produced a silently broken ccr config
        # → 401 from upstream Kimi).
        # _extra_env holds raw YAML values (e.g. literal "${PARATERA_API_KEY}");
        # resolve_env_vars expands them against the harbor process's os.environ.
        resolved = resolve_env_vars(self._extra_env)
        upstream_base = resolved.get("CCR_UPSTREAM_BASE", "")
        upstream_key  = resolved.get("CCR_UPSTREAM_KEY", "")
        if not upstream_base or not upstream_key:
            raise RuntimeError(
                "ClaudeCodeViaCcr requires CCR_UPSTREAM_BASE and "
                "CCR_UPSTREAM_KEY in agent.env"
            )
        # ── Token-recovery proxy ──
        #
        # ccr 2.0's transformer hooks don't expose the outbound OpenAI body
        # (only inbound Anthropic; verified empirically with marker probe),
        # so we can't make ccr inject `stream_options.include_usage=true` into
        # what actually reaches the upstream. Without that flag, paratera
        # omits `usage` from stream chunks and Claude Code receives
        # `usage: {input_tokens: 0, ...}` for ccr-routed trials.
        #
        # Workaround: stand a tiny aiohttp proxy in front of paratera (port
        # 3457) that (a) injects the missing flag and (b) records each
        # request's usage to a sidecar JSONL that cost_meter.py reads.
        #
        # Pipeline:
        #   claude → ccr (3456, anthropic→openai) → proxy (3457, +include_usage)
        #          → paratera; usage tee'd into /logs/agent/proxy-usage.jsonl
        proxy_src = (Path(__file__).parent / "openai_usage_proxy.py").read_text(encoding="utf-8")
        proxy_b64 = base64.b64encode(proxy_src.encode()).decode()
        PROXY_PATH = "/opt/openai_usage_proxy.py"
        PROXY_PORT = 3457
        USAGE_LOG = "/logs/agent/proxy-usage.jsonl"

        # Per-provider transformer chain. `tooluse` is generic. MiniMax's
        # OpenAI endpoint additionally rejects mid-conversation system
        # messages (error 2013), so we layer the local minimax-system-merge
        # plugin (consolidates all role:system entries to index 0).
        transformer_chain = ["tooluse"]
        custom_transformers = []
        if "minimaxi.com" in upstream_base:
            transformer_chain.append("minimax-system-merge")
            custom_transformers.append({
                "path": "/opt/ccr-plugins/minimax_system_merge.js",
            })

        ccr_config_dict = {
            "HOST": "127.0.0.1",
            "PORT": 3456,
            "APIKEY": "harbor-ccr-2026",
            "NON_INTERACTIVE_MODE": True,
            # LOG=true keeps ccr's stream-translation log around for forensic
            # use; cost_meter falls back to it if the proxy log is missing.
            "LOG": True,
            "API_TIMEOUT_MS": 600000,
            "Providers": [{
                "name": "upstream",
                # Point ccr at our local proxy instead of upstream direct;
                # the proxy adds include_usage and forwards.
                "api_base_url": f"http://127.0.0.1:{PROXY_PORT}/v1/chat/completions",
                "api_key": upstream_key,
                "models": [self.model_name],
                "transformer": {"use": transformer_chain},
            }],
            "Router": {"default": f"upstream,{self.model_name}"},
        }
        if custom_transformers:
            ccr_config_dict["transformers"] = custom_transformers
        ccr_config = json.dumps(ccr_config_dict, indent=2)
        cfg_b64 = base64.b64encode(ccr_config.encode()).decode()
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"npm config set registry {NPM_REGISTRY} && "
                "{ ccr --version 2>/dev/null || "
                "npm install -g @musistudio/claude-code-router; } && "
                # aiohttp for the proxy; --quiet to keep install logs short.
                "pip install --quiet --break-system-packages aiohttp 2>/dev/null || "
                "pip install --quiet aiohttp && "
                "mkdir -p ~/.claude-code-router /logs/agent && "
                f"echo {proxy_b64} | base64 -d > {PROXY_PATH} && "
                f"echo {cfg_b64} | base64 -d > ~/.claude-code-router/config.json && "
                "mkdir -p /logs/agent/ccr && "
                "ln -sfn /logs/agent/ccr/ ~/.claude-code-router/logs && "
                # Start the usage proxy first; ccr only points at it after
                # health checks pass.
                f"UPSTREAM_BASE={shlex_quote(upstream_base)} "
                f"UPSTREAM_KEY={shlex_quote(upstream_key)} "
                f"UPSTREAM_PROXY_PORT={PROXY_PORT} "
                f"USAGE_LOG={USAGE_LOG} "
                f"nohup python3 {PROXY_PATH} > /tmp/proxy.log 2>&1 & disown; "
                "for i in 1 2 3 4 5 6 7 8 9 10; do "
                f"  curl -s -o /dev/null -w '' --max-time 1 http://127.0.0.1:{PROXY_PORT}/health && break; "
                "  sleep 1; "
                "done; "
                "nohup ccr start > /tmp/ccr.log 2>&1 & disown; "
                "for i in 1 2 3 4 5 6 7 8 9 10; do "
                "  curl -s -o /dev/null -w '' --max-time 1 http://127.0.0.1:3456/ && break; "
                "  sleep 1; "
                "done; "
                "echo 'proxy + ccr ready'"
            ),
        )
        await _register_sim_skills(self, environment)
        await _install_hooks(self, environment)


# ──────────────────────────────────────────────────────────────────────────
# sim-skills auto-registration
# ──────────────────────────────────────────────────────────────────────────

# Solver names where the sim driver and the sim-skills directory disagree.
# Driver (sim --json check) name → sim-skills directory name.
_SKILL_DIR_OVERRIDES = {
    "ls_dyna": "lsdyna",
}


async def _register_sim_skills(agent, environment):
    """Symlink sim-skills entries into ~/.claude/skills/ for installed solvers.

    Runs deterministically before claude is invoked. claude scans
    ~/.claude/skills/ at startup and lists the entries in its `skills`
    registry, so the agent sees `sim-cli` plus one skill per installed
    solver from `sim --json check`. No dependency on `--plugin-dir` or
    plugin.json — the file-system convention is more stable across
    claude-code versions and works on dev workstations identically.

    Failures are non-fatal: if sim CLI isn't reachable or sim-skills
    isn't present, we skip silently and let the agent fall back to the
    pre-skill behaviour.
    """
    overrides_csv = ",".join(f"{k}:{v}" for k, v in _SKILL_DIR_OVERRIDES.items())
    cmd = f'''set +e
mkdir -p ~/.claude/skills
# sim-cli skill is mandatory — agent always needs to know how to drive sim.
[ -d /opt/sim-skills/sim-cli ] && ln -sfn /opt/sim-skills/sim-cli ~/.claude/skills/sim-cli
# Per-installed-solver skills — query sim, dispatch to skill dir name.
INSTALLED=$(sim --json check 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    for s in d.get("data", {{}}).get("solvers", []):
        if s.get("status") == "ok":
            print(s["name"])
except Exception:
    pass
')
# Apply driver→dir name overrides (e.g. ls_dyna→lsdyna)
declare -A OVR
IFS=, read -ra pairs <<< "{overrides_csv}"
for p in "${{pairs[@]}}"; do
    k="${{p%%:*}}"; v="${{p##*:}}"
    [ -n "$k" ] && OVR[$k]="$v"
done
for s in $INSTALLED; do
    skill="${{OVR[$s]:-$s}}"
    [ -d /opt/sim-skills/$skill ] && ln -sfn /opt/sim-skills/$skill ~/.claude/skills/$skill
done
echo "[sim-skills] registered: $(ls ~/.claude/skills 2>/dev/null | tr '\\n' ' ')"
'''
    await agent.exec_as_agent(environment, command=cmd)


# ──────────────────────────────────────────────────────────────────────────
# Hooks — Stop (re-prompt for result.json) + PreToolUse (bound Bash calls)
# ──────────────────────────────────────────────────────────────────────────
#
# Two hooks are installed together in one settings.json:
#
# 1. Stop hook — Harbor's terminus-2 wraps the LLM in an in-container loop
#    that refuses to terminate until the agent writes /tmp/agent/result.json.
#    We use vanilla `claude` (not terminus-2), so we lose that property —
#    v17 confirmed this: 16 / 20 trials stopped with no result.json,
#    scoring 0.0 / 0.1 even when the underlying physics ran fine. Claude
#    Code's Stop hook is the equivalent: fires when the main agent tries
#    to end; printing `{"decision": "block", "reason": "..."}` makes claude
#    continue with the reason as a system message. max_turns bounds the loop.
#
# 2. PreToolUse hook on Bash — claude-code's Bash tool has a 2-min default
#    timeout, but v18e showed it can fail to clean up daemonized
#    descendants (wineserver detaches to PID 1 → keeps the bash pipe's
#    stdout reader stuck → claude waits indefinitely → 75-min wedge from
#    a single `wine-ltspice -?`). GNU `timeout(1)` from coreutils starts
#    its child in a new session group, then signals the WHOLE group on
#    expiry — so even daemonized children get cleaned up. The hook
#    transparently rewrites every Bash `command` to wrap with
#    `timeout --kill-after=5s 90s bash -c <orig>` (via PreToolUse's
#    `hookSpecificOutput.updatedInput` mechanism — the agent never sees
#    the rewrite). Idempotent: skips wrapping if the agent already
#    prefixed with `timeout ` or `setsid `.

_RESULT_JSON_PATH = "/tmp/agent/result.json"
_HOOKS_SCRIPT_DIR = "/opt/sim-benchmark-hooks"
# Bash timeout fallback (seconds) used when neither claude-code nor the agent
# specify a `tool_input.timeout`. Claude-code's documented default is 120 s,
# so this only kicks in for hypothetical paths where that default is absent;
# it is intentionally close to claude's default rather than something stricter.
# The hook's value-add is wrapping with GNU `timeout(1)` (which kills the
# whole process group on expiry, including daemonized children like
# wineserver) — NOT imposing a tighter wall-clock policy than the agent or
# claude already chose. OpenFOAM cases that legitimately need >120 s
# (snappyHexMesh, complex compiles) should pass `tool_input.timeout` >= the
# duration they expect; the hook respects it up to claude-code's 600 s
# ceiling.
_BASH_TIMEOUT_FALLBACK_SECS = 120
_BASH_TIMEOUT_MIN_SECS = 30   # Below this is almost certainly a misconfiguration
_BASH_TIMEOUT_MAX_SECS = 600  # Claude-code's documented hard ceiling
# The reason text is fed back to claude verbatim when the hook blocks. It
# must be unambiguous and concrete: v18d showed the agent will copy
# placeholder strings like `<binary-prefixed jq command>` literally into
# result.json, then the verifier's source-extract sandbox runs them, gets
# `null`, and zeroes the KPI even though the claimed values were correct.
# Give a copy-pasteable example for ltspice_log (the lowest-friction path).
_STOP_HOOK_REASON = (
    "You are about to stop, but {path} is missing. The benchmark verifier "
    "reads this file to grade your KPIs — without it your score is 0. "
    "For each KPI in instruction.md, write an entry of this shape:\n\n"
    "  {{\n"
    "    \"<kpi_name>\": {{\n"
    "      \"value\": <number — the value you measured>,\n"
    "      \"source\": {{\n"
    "        \"kind\": \"ltspice_log\",\n"
    "        \"path\": \"/absolute/path/to/your-run.log\",\n"
    "        \"query\": \"measure\",\n"
    "        \"measurement\": \"<meas_name>\"\n"
    "      }}\n"
    "    }}\n"
    "  }}\n\n"
    "For LTspice completion flags, use source {{\"kind\":\"ltspice_log\", "
    "\"path\":\"/absolute/path/to/your-run.log\", \"query\":\"completed\"}}. "
    "For stepped .meas tables, add \"step\": <1-based step>. For .step "
    "parameter values, use query=\"step_param\" with \"param\", \"step\", "
    "and optional \"scale\". Do NOT leave any `<...>` placeholders in the "
    "file. Then stop."
).format(path=_RESULT_JSON_PATH)


# PreToolUse hook script — installed at ${_HOOKS_SCRIPT_DIR}/bash_timeout.py
# and referenced from settings.json. Reads the {tool_name, tool_input} JSON
# claude code feeds on stdin, returns a hookSpecificOutput with updatedInput
# containing the rewritten command.
_BASH_TIMEOUT_HOOK_SRC = '''#!/usr/bin/env python3
"""PreToolUse hook for claude-code's Bash tool.

Wraps foreground Bash commands with GNU `timeout --kill-after=5s <secs>s
bash -c <orig>` to ensure unresponsive subprocess trees (notably
daemonizing children like wineserver that survive claude-code's own
SIGKILL) actually die. GNU `timeout(1)` runs in a new session group and
signals the whole group on expiry.

This hook does NOT impose a stricter wall-clock policy than claude-code
already would. The wrap duration follows the agent/claude-code-resolved
`tool_input.timeout`, falling back to {fallback}s only when no explicit
timeout reaches the hook (claude-code's documented default is 120s, so
the fallback is only a defensive fallback). Clamped to [{min_s}s,
{max_s}s] (claude-code's hard ceiling per GitHub issue #25881).

Skipped (no wrapping) when:
  - `tool_input.run_in_background` is true — claude-code owns the task
    lifecycle and reads output incrementally via a separate tool;
    wrapping with `timeout` would kill the background process and
    defeat the entire reason agents use background mode (multi-minute
    / multi-hour solver workloads via output polling).
  - command is already `timeout `-prefixed (agent self-wrapped) or
    `setsid `-prefixed (intentional session-group call).

For genuinely long simulations (>10 min wall): claude-code's 600s
ceiling makes a single foreground call insufficient. Canonical pattern
is solver checkpointing (e.g. OpenFOAM `writeInterval`, SU2
`RESTART_SOL=YES`) + multiple foreground calls each ≤ 600s, OR a
single `run_in_background=true` invocation polled to completion.
"""
import json
import sys

FALLBACK_SECS = {fallback}
MIN_SECS = {min_s}
MAX_SECS = {max_s}


def resolve_secs(inp: dict) -> int:
    raw = inp.get("timeout")
    if isinstance(raw, (int, float)) and raw > 0:
        secs = int(raw / 1000)
    else:
        secs = FALLBACK_SECS
    if secs < MIN_SECS:
        secs = MIN_SECS
    if secs > MAX_SECS:
        secs = MAX_SECS
    return secs


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # Malformed input — let claude-code apply default behavior.
    if data.get("tool_name") != "Bash":
        return 0  # Hook matcher should already gate this, but double-check.
    inp = data.get("tool_input") or {{}}
    if inp.get("run_in_background"):
        # Background mode — claude-code holds a task handle and polls
        # output via a separate tool. Wrapping with `timeout Ns` would
        # kill the background process at N seconds, defeating the whole
        # point of background mode (which exists precisely so agents can
        # run multi-minute / multi-hour solver workloads via incremental
        # output polling rather than blocking foreground calls). The
        # daemon-cleanup motivation also doesn't apply: claude-code itself
        # owns the lifecycle of background task processes.
        return 0
    cmd = inp.get("command", "") or ""
    stripped = cmd.lstrip()
    if stripped.startswith("timeout ") or stripped.startswith("setsid "):
        # Agent already bounded the call — leave it alone.
        return 0
    secs = resolve_secs(inp)
    new_inp = dict(inp)
    new_inp["command"] = (
        f"timeout --kill-after=5s {{secs}}s bash -c {{json.dumps(cmd)}}"
    )
    json.dump({{
        "hookSpecificOutput": {{
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": new_inp,
        }}
    }}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


# Stop hook script — installed at ${_HOOKS_SCRIPT_DIR}/result_json_check.py.
# Schema-only validator: catches the structural mistakes that v18f burned
# turns on (extract first token not in allow-list, run_id not in history)
# without leaking semantic info (gt_value, T_decay, or even claim-vs-extract
# value comparisons).
_RESULT_CHECK_HOOK_SRC = r'''#!/usr/bin/env python3
"""Stop hook: schema-validate /tmp/agent/result.json before letting claude stop.

Three states:
  - File missing → block + onboarding reason (how to write result.json)
  - File present but schema-broken → block + per-KPI structural errors
  - File present + schema-valid → exit 0, claude stops normally

Schema checks ONLY (no value comparisons): we tell the agent which fields
are malformed, but never reveal whether their claimed value matches the
extracted value, what the gt_value is, or where they sit on the T_decay
curve. This keeps the post-hoc verifier as the only judge of correctness;
the hook is just bookkeeping triage.
"""
import datetime
import json
import shlex
import subprocess
import sys
from pathlib import Path

RESULT_PATH = Path("/tmp/agent/result.json")
SENTINEL = Path("/logs/agent/.stop-hook-fired")
ALLOWED_BINARIES = {"head", "tail", "awk", "sed", "grep", "cut", "tr",
                    "sort", "uniq", "wc", "cat", "jq"}
VALID_SOURCE_KINDS = {"sim_run_stdout", "sim_run_kpi", "file_extract", "ltspice_log"}

REASON_MISSING = __REASON_MISSING_PLACEHOLDER__


def fire_sentinel() -> None:
    try:
        SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        with SENTINEL.open("a") as f:
            f.write(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ\n"))
    except Exception:
        pass  # Sentinel write failure is not fatal.


def block(reason: str) -> int:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    return 0


def get_sim_run_ids() -> set | None:
    """Return run_ids visible in `sim --json logs`, or None if unreachable."""
    try:
        r = subprocess.run(
            ["sim", "--json", "logs"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if r.returncode != 0:
            return None
        recs = json.loads(r.stdout)
        return {str(rec.get("run_id")) for rec in recs if rec.get("run_id") is not None}
    except Exception:
        return None


def check_extract(extract) -> str | None:
    """Return None if extract passes the sandbox, else a why-string."""
    if not isinstance(extract, str) or not extract.strip():
        return "extract is empty or not a string"
    for danger in ("$(", "`"):
        if danger in extract:
            return f"extract contains command-substitution {danger!r}"
    for stage in extract.split("|"):
        try:
            tokens = shlex.split(stage)
        except ValueError as e:
            return f"unparseable pipe stage {stage!r}: {e}"
        if not tokens:
            return "empty pipe stage (stray '|')"
        head = tokens[0]
        if head not in ALLOWED_BINARIES:
            allowed = ", ".join(sorted(ALLOWED_BINARIES))
            return f"first token {head!r} not in allowed binaries ({allowed})"
    return None


def check_kpi(entry, run_ids) -> list:
    errors = []
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    if "value" not in entry:
        errors.append("missing 'value' field")
    src = entry.get("source")
    if not isinstance(src, dict):
        return errors + ["missing or non-object 'source' field"]
    kind = src.get("kind")
    if kind not in VALID_SOURCE_KINDS:
        valid = ", ".join(sorted(VALID_SOURCE_KINDS))
        errors.append(f"source.kind={kind!r} not in {{{valid}}}")
    if kind == "ltspice_log":
        path = src.get("path")
        query = src.get("query")
        if not isinstance(path, str) or not path:
            errors.append("source.path missing")
        if query not in {"completed", "measure", "step_param"}:
            errors.append("source.query must be 'completed', 'measure', or 'step_param'")
        if query == "measure":
            measurement = src.get("measurement")
            if not isinstance(measurement, str) or not measurement.strip():
                errors.append("source.measurement missing")
            if "step" in src:
                try:
                    step = int(src.get("step"))
                    if step < 1:
                        errors.append("source.step must be >= 1")
                except Exception:
                    errors.append("source.step must be an integer")
            if src.get("field", "value") != "value":
                errors.append("source.field currently only supports 'value'")
        if query == "step_param":
            param = src.get("param")
            if not isinstance(param, str) or not param.strip():
                errors.append("source.param missing")
            try:
                step = int(src.get("step"))
                if step < 1:
                    errors.append("source.step must be >= 1")
            except Exception:
                errors.append("source.step must be an integer")
            if "scale" in src:
                try:
                    float(src.get("scale"))
                except Exception:
                    errors.append("source.scale must be numeric")
    else:
        extract_err = check_extract(src.get("extract"))
        if extract_err:
            errors.append(f"source.extract: {extract_err}")
    if kind in {"sim_run_stdout", "sim_run_kpi"}:
        rid = src.get("run_id")
        if not rid:
            errors.append("source.run_id missing")
        elif run_ids is not None and str(rid) not in run_ids:
            errors.append(
                f"source.run_id={rid!r} not in `sim --json logs` history"
            )
        elif run_ids is None:
            # `sim` CLI is not on PATH in this container — agent picked
            # a source kind that structurally cannot be verified here.
            # Tell them to switch to file_extract before letting them stop;
            # otherwise the verifier scores this KPI 0 silently.
            errors.append(
                f"source.kind={kind!r} requires `sim` CLI (for `sim --json logs`), "
                f"but `sim` is not available in this container. "
                f"Use source.kind=\"ltspice_log\" against LTspice's .log, "
                f"or source.kind=\"file_extract\" against another native output file."
            )
    return errors


def main() -> int:
    fire_sentinel()

    if not RESULT_PATH.exists():
        return block(REASON_MISSING)

    try:
        result = json.loads(RESULT_PATH.read_text())
    except Exception as e:
        return block(f"{RESULT_PATH} is not valid JSON: {e}. Fix and retry.")

    if not isinstance(result, dict):
        return block(f"{RESULT_PATH} top-level must be a JSON object of "
                     "{{kpi_name: {{value, source}}}} entries.")

    if not result:
        return block(f"{RESULT_PATH} is empty. Add an entry per KPI in instruction.md.")

    run_ids = get_sim_run_ids()

    failures = {}
    for name, entry in result.items():
        errs = check_kpi(entry, run_ids)
        if errs:
            failures[name] = errs

    if not failures:
        return 0  # All KPIs schema-valid; let claude stop.

    lines = [f"{RESULT_PATH} has schema problems — fix these before stopping:"]
    for name in sorted(failures):
        lines.append(f"  {name}:")
        for e in failures[name]:
            lines.append(f"    - {e}")
    lines.append("")
    if run_ids is not None:
        if run_ids:
            lines.append(f"run_ids in sim history: {sorted(run_ids)}")
            lines.append("Find the right one with: sim --json logs last | jq -r .run_id")
        else:
            lines.append("No sim runs in history yet. Run `sim run --solver ltspice <netlist>` first.")
    else:
        lines.append("`sim` CLI is not available in this container (no `sim --json logs`).")
        lines.append("Drive the simulator natively (e.g. `wine-ltspice <netlist>`) and use")
        lines.append("source.kind=\"ltspice_log\" with path pointing at the .log LTspice")
        lines.append("produces. Use source.kind=\"file_extract\" only as a fallback for")
        lines.append("non-LTspice artifacts or custom post-processed files.")
    lines.append("Allowed extract binaries: " + ", ".join(sorted(ALLOWED_BINARIES)))
    return block("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
'''


async def _install_hooks(agent, environment):
    """Install Stop + PreToolUse hooks via settings.json + a script file.

    See module-level comment for what each hook does and why.

    The Stop hook also drops a sentinel `/logs/agent/.stop-hook-fired` so
    that after the trial we can tell whether claude ever invoked it
    (independently of whether the JSON `decision` was honored). Sentinel
    lives in /logs/agent (mounted to the trial dir) so it survives
    container teardown.
    """
    stop_hook_command = f"python3 {_HOOKS_SCRIPT_DIR}/result_json_check.py"
    pretool_hook_command = f"python3 {_HOOKS_SCRIPT_DIR}/bash_timeout.py"
    # Stop hooks have no tool-name to match against; drop the matcher field.
    # PreToolUse uses matcher="Bash" so other tools (Write, Read, etc.) are
    # unaffected.
    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{"type": "command", "command": stop_hook_command}],
            }],
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": pretool_hook_command}],
            }],
        }
    }
    settings_b64 = base64.b64encode(
        json.dumps(settings, indent=2).encode()
    ).decode()
    # Format the bash-timeout script source with the chosen timeout
    # constants. The script uses double-braces ({{ }}) for literal braces
    # inside Python source (since the outer string is a .format() template).
    bash_timeout_script = _BASH_TIMEOUT_HOOK_SRC.format(
        fallback=_BASH_TIMEOUT_FALLBACK_SECS,
        min_s=_BASH_TIMEOUT_MIN_SECS,
        max_s=_BASH_TIMEOUT_MAX_SECS,
    )
    bash_timeout_b64 = base64.b64encode(bash_timeout_script.encode()).decode()

    # Substitute the missing-file reason into the result-check script. We
    # use a placeholder + repr() instead of .format() so the script can
    # contain literal `{` `}` freely (pulled-out of f-strings, dict
    # literals) without escape gymnastics.
    result_check_script = _RESULT_CHECK_HOOK_SRC.replace(
        "__REASON_MISSING_PLACEHOLDER__", repr(_STOP_HOOK_REASON)
    )
    result_check_b64 = base64.b64encode(result_check_script.encode()).decode()

    # We don't know which settings.json claude reads first in this setup.
    # Write to all locations the docs list as candidates (project-cwd > user
    # > CLAUDE_CONFIG_DIR fallback) and let the first one that wins, win.
    # All three are byte-identical so duplicate firing is not a concern.
    await agent.exec_as_agent(
        environment,
        command=(
            "set -euo pipefail; "
            f"mkdir -p ~/.claude /logs/agent/sessions /root/case/.claude {_HOOKS_SCRIPT_DIR} && "
            f"echo {bash_timeout_b64} | base64 -d > {_HOOKS_SCRIPT_DIR}/bash_timeout.py && "
            f"echo {result_check_b64} | base64 -d > {_HOOKS_SCRIPT_DIR}/result_json_check.py && "
            f"chmod +x {_HOOKS_SCRIPT_DIR}/bash_timeout.py {_HOOKS_SCRIPT_DIR}/result_json_check.py && "
            f"echo {settings_b64} | base64 -d > ~/.claude/settings.json && "
            f"echo {settings_b64} | base64 -d > /logs/agent/sessions/settings.json && "
            f"echo {settings_b64} | base64 -d > /root/case/.claude/settings.json && "
            f"echo '[hooks] installed: Stop(schema-check) + PreToolUse(Bash, fallback={_BASH_TIMEOUT_FALLBACK_SECS}s, max={_BASH_TIMEOUT_MAX_SECS}s)'"
        ),
    )
