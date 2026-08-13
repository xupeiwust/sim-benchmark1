"""Windows-local trial runner for sim-benchmark Path B (no Harbor).

Drives a headless ``claude -p`` session against a single case directory
using an Anthropic-compatible upstream (default: MiniMax via
``api.minimaxi.com/anthropic``). After the agent exits, runs the case's
``tests/test.bat`` against the agent-written ``result.json`` and prints
the verifier score.

Trial isolation
===============

The user's daily Claude Code state is left strictly untouched:

  1. ``work_dir`` lives OUTSIDE the simcli workspace by default
     (``E:/sim-bench-trials/<ts>-<model>-<slug>/``) so claude's CLAUDE.md
     auto-discovery walks up to ``E:/`` without hitting any project
     memory under the simcli tree.
  2. ``CLAUDE_CONFIG_DIR`` points at ``<work_dir>/.claude_config_dir/``
     (an empty directory) so claude reads no user-global config /
     CLAUDE.md / skills / plugins from ``~/.claude/``.
  3. ``--setting-sources project,local`` is passed to claude (defense in
     depth: even if CLAUDE_CONFIG_DIR is ignored, user-global settings
     are not loaded).
  4. ``ANTHROPIC_BASE_URL/API_KEY/MODEL`` are set only via
     ``subprocess.Popen(env=...)``; the parent shell is not modified.
  5. trial-local hooks + skills are written under ``<work_dir>/.claude/``,
     never into ``~/.claude/``.

Layout per trial
================

::

    <work_dir>/
      instruction.md             copy of the case prompt
      result.json                agent-written (graded by verifier)
      claude.log + claude.stream.jsonl
      reward.json + reward_detail.json
      .claude_config_dir/        empty; CLAUDE_CONFIG_DIR points here
      .claude/
        settings.json            references the trial-local hooks
        hooks/
          result_check.py        Stop-hook (schema + extract runnability)
        skills/
          comsol/                copy of sim_plugin_comsol._skills.comsol
          sim-cli/               copy of sim-skills/sim-cli

Usage
=====

::

    py -3 tools/run_local_trial.py \\
        --case cases/electromagnetics/capacitor_dc \\
        --model MiniMax-M2.5-highspeed \\
        --api-key-file API --api-key-line 8 \\
        --max-turns 100
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


REPO_ROOT       = Path(__file__).resolve().parent.parent
SIMCLI_ROOT     = REPO_ROOT.parent
DEFAULT_TRIAL_ROOT = Path(r"E:\sim-bench-trials")
SIM_CLI_SKILL_SRC  = SIMCLI_ROOT / "sim-skills" / "sim-cli"
GIT_BASH_BIN       = r"C:\Program Files\Git\usr\bin"

# ──────────────────────────────────────────────────────────────────────
# Soft-landing two-phase strategy (port from tools/agent_harness.py).
# Phase 1: solve with max_turns - SOFT_LANDING_TURNS.
# Phase 2 (only if result.json invalid): wrap-up with SOFT_LANDING_TURNS
# reserved, agent told to stop solving and dump best-effort answer from
# existing artifacts. Mirrors OF/LTspice _two_phase_run behaviour so a
# trial that hits the max_turns ceiling mid-solve still gets a chance to
# write something usable rather than scoring 0.0.
# ──────────────────────────────────────────────────────────────────────
SOFT_LANDING_TURNS = 30

WRAP_UP_INSTRUCTION = (
    "TIME BUDGET LOW - wrap-up phase only.\n\n"
    "You are out of solve budget. Do NOT run new solvers "
    "(comsolbatch / comsolcompile / `sim run` / new mphserver sessions) "
    "and do NOT optimize further.\n\n"
    "Your single task now: read whatever state already exists and write "
    "your best-effort answer to result.json in your current working "
    "directory:\n"
    "  - work/*.java, work/*.mph, work/*.log, work/*.txt, work/kpis.txt - "
    "anything you already produced\n"
    "  - any prior result.json you wrote earlier in this session\n"
    "  - your own scratch notes in this session\n\n"
    "Re-read instruction.md if you don't remember the KPI key names or "
    "schema. Each KPI must be a `{\"value\": <number>, \"source\": "
    "{\"kind\": \"file_extract\", \"path\": \"<abs path>\", \"extract\": "
    "\"<allowed-binary pipeline>\"}}` object. A rough estimate is better "
    "than no answer. If you genuinely have no solver output, write a "
    "documented placeholder with the KPI keys mapped to 0 (or NaN-style "
    "best guess) and let the Stop hook catch the schema issues - "
    "ANYTHING is better than missing result.json (which scores 0).\n"
)


# ──────────────────────────────────────────────────────────────────────
# Stop-hook script template — adapted from sim-benchmark's
# tools/agent_harness.py (_RESULT_CHECK_HOOK_SRC). Pass 1 schema check +
# Pass 2 file_extract runnability check, but reads result.json from the
# trial work_dir rather than /tmp/agent.
# ──────────────────────────────────────────────────────────────────────

_STOP_HOOK_TEMPLATE = r'''#!/usr/bin/env python3
"""Stop hook for sim-benchmark Path B trials (Windows-local).

Validates the trial-local result.json before letting claude stop.

Pass 1 (schema):
  - file present, valid JSON, every KPI {"value": <number>, "source": {...}}
  - source.kind in {file_extract, ltspice_log, sim_run_stdout, sim_run_kpi}
  - file_extract: source.path absolute + source.extract from allowed binaries
Pass 2 (runnability, file_extract only):
  - re-run the agent's extract pipeline against source.path content; the
    pipeline must produce non-empty stdout. Reveals only empty-vs-non-empty,
    never the value or whether it matches the agent's claim.

States:
  - file missing            -> block + onboarding reason
  - schema broken           -> block + per-KPI structural errors
  - extract returns empty   -> block + per-KPI runnability hint
  - schema valid + runnable -> exit 0 (agent stops normally)
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

# Templated by run_local_trial.py at install time:
RESULT_PATH = Path(r"__RESULT_PATH__")
SENTINEL    = Path(r"__SENTINEL__")

ALLOWED_BINARIES = {"head", "tail", "awk", "sed", "grep", "cut", "tr",
                    "sort", "uniq", "wc", "cat", "jq"}
VALID_SOURCE_KINDS = {"sim_run_stdout", "sim_run_kpi", "file_extract", "ltspice_log"}

REASON_MISSING = (
    f"You are about to stop, but {RESULT_PATH} is missing. The benchmark "
    "verifier reads this file to grade your KPIs - without it your score "
    "is 0.\n\n"
    "For each KPI in instruction.md, write an entry of this shape into "
    f"{RESULT_PATH}:\n\n"
    "  {\n"
    "    \"<kpi_name>\": {\n"
    "      \"value\": <number - the value you measured>,\n"
    "      \"source\": {\n"
    "        \"kind\": \"file_extract\",\n"
    "        \"path\": \"<ABSOLUTE windows path to your kpis.txt>\",\n"
    "        \"extract\": \"grep '^<kpi_name>=' | cut -d= -f2\"\n"
    "      }\n"
    "    }\n"
    "  }\n\n"
    "Allowed extract binaries (each pipe stage's first token): "
    + ", ".join(sorted(ALLOWED_BINARIES)) +
    ". COMSOL's Java sandbox blocks java.io writes - if your model can't "
    "write kpis.txt directly, capture stdout via Bash and write the file "
    "with the Write tool. Then stop."
)


def fire_sentinel() -> None:
    try:
        SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        with SENTINEL.open("a") as f:
            f.write(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ\n"))
    except Exception:
        pass


def block(reason: str) -> int:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    return 0


def check_extract(extract) -> "str | None":
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


def check_extract_runnable(entry):
    src = entry.get("source") or {}
    if src.get("kind") != "file_extract":
        return None
    path    = src.get("path")
    extract = src.get("extract")
    if not isinstance(path, str) or not path:
        return None
    if not isinstance(extract, str) or not extract.strip():
        return None
    full = Path(path)
    if not full.is_absolute():
        return f"source.path must be absolute (got {path!r})"
    if not full.is_file():
        return f"source.path does not exist or is not a file at {path!r}"
    try:
        file_text = full.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"source.path could not be read: {e}"
    try:
        proc = subprocess.run(
            ["bash", "-c", extract],
            input=file_text, capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return ("`bash` not on PATH. The verifier will use git-bash here; "
                "if you see this in the hook, the trial PATH is misconfigured "
                "(runner should have prepended C:/Program Files/Git/usr/bin).")
    except subprocess.TimeoutExpired:
        return "extract timed out (>10 s) when re-run against source.path"
    if proc.returncode != 0:
        return f"extract exited {proc.returncode}: {proc.stderr.strip()[:120]}"
    if not proc.stdout.strip():
        return ("extract produced empty stdout. Common causes: regex/awk pattern "
                "doesn't match; sanity-check the file with `head` / `tail` first.")
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
    if kind == "file_extract":
        extract_err = check_extract(src.get("extract"))
        if extract_err:
            errors.append(f"source.extract: {extract_err}")
        path = src.get("path")
        if not isinstance(path, str) or not path:
            errors.append("source.path missing")
        elif not os.path.isabs(path):
            errors.append(f"source.path not absolute: {path!r}")
    return errors


def main() -> int:
    fire_sentinel()
    if not RESULT_PATH.exists():
        return block(REASON_MISSING)
    try:
        result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return block(f"{RESULT_PATH} is not valid JSON: {e}. Fix and retry.")
    if not isinstance(result, dict):
        return block(f"{RESULT_PATH} top-level must be a JSON object of "
                     "{kpi_name: {value, source}} entries.")
    if not result:
        return block(f"{RESULT_PATH} is empty. Add an entry per KPI in instruction.md.")

    failures = {}
    for name, entry in result.items():
        errs = check_kpi(entry, None)
        if errs:
            failures[name] = errs
    if failures:
        lines = [f"{RESULT_PATH} has schema problems - fix these before stopping:"]
        for name in sorted(failures):
            lines.append(f"  {name}:")
            for e in failures[name]:
                lines.append(f"    - {e}")
        lines.append("Allowed extract binaries: " + ", ".join(sorted(ALLOWED_BINARIES)))
        return block("\n".join(lines))

    runnability_failures = {}
    for name, entry in result.items():
        why = check_extract_runnable(entry)
        if why:
            runnability_failures[name] = why
    if runnability_failures:
        lines = [
            f"{RESULT_PATH} schema is valid, but file_extract pipelines fail "
            "to produce output when re-run. The verifier scores these KPIs 0."
        ]
        for name in sorted(runnability_failures):
            lines.append(f"  {name}:")
            lines.append(f"    {runnability_failures[name]}")
        return block("\n".join(lines))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def read_api_key(path: Path, line_no: int) -> str:
    raw = path.read_text(encoding="utf-8").splitlines()
    if line_no < 1 or line_no > len(raw):
        raise ValueError(f"line {line_no} out of range (file has {len(raw)} lines)")
    key = raw[line_no - 1].strip()
    if not key or not key.startswith("sk-"):
        raise ValueError(f"line {line_no} of {path} does not look like an API key")
    return key


def slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s).strip("-").lower()


def resolve_solver_label(case_dir: Path) -> str | None:
    """Read [metadata.sim].solver from case_dir/task.toml. Returns None
    if the file or field is missing — caller falls back to legacy COMSOL
    defaults so the OF/LTspice/COMSOL paths keep working unchanged."""
    task_toml = case_dir / "task.toml"
    if not task_toml.is_file():
        return None
    try:
        import tomllib  # py 3.11+
        with task_toml.open("rb") as f:
            blob = tomllib.load(f)
    except Exception:
        try:
            text = task_toml.read_text(encoding="utf-8")
            import re
            m = re.search(r'^\s*solver\s*=\s*"([^"]+)"', text, re.M)
            return m.group(1) if m else None
        except Exception:
            return None
    return (blob.get("metadata", {}).get("sim", {}) or {}).get("solver")


def resolve_comsol_skill_dir() -> Path:
    """Locate sim_plugin_comsol's bundled COMSOL skill via package import."""
    venv_python = SIMCLI_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        raise FileNotFoundError(f"sim-plugin-comsol venv not found at {venv_python}")
    out = subprocess.check_output(
        [str(venv_python), "-c",
         "import sim_plugin_comsol; print(sim_plugin_comsol.skills_dir)"],
        text=True,
    ).strip()
    skill_root = Path(out)
    if not (skill_root / "comsol" / "SKILL.md").is_file():
        raise FileNotFoundError(f"comsol SKILL.md not found under {skill_root}")
    return skill_root / "comsol"


def install_skills(work_dir: Path, solver_label: str | None = None) -> None:
    """Copy per-solver skill bundles under <work_dir>/.claude/skills/.

    Default behaviour (solver_label in {None, "comsol"}) keeps the
    legacy "install COMSOL + sim-cli" path verbatim so existing OF /
    LTspice / COMSOL trials are unaffected. For solver_label="simulink"
    (and other future labels), skip the COMSOL skill — it's irrelevant
    and burns context.

    We copy rather than symlink because Windows symlinks require
    Developer Mode or admin. Bundles are small (~1 MB).
    """
    skills_dst = work_dir / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    if solver_label in (None, "comsol"):
        comsol_src = resolve_comsol_skill_dir()
        print(f"[runner] copying COMSOL skill: {comsol_src}")
        shutil.copytree(comsol_src, skills_dst / "comsol", dirs_exist_ok=True)
    else:
        print(f"[runner] solver={solver_label!r}: skipping COMSOL skill (not relevant)")
    if SIM_CLI_SKILL_SRC.is_dir():
        print(f"[runner] copying sim-cli skill: {SIM_CLI_SKILL_SRC}")
        shutil.copytree(SIM_CLI_SKILL_SRC, skills_dst / "sim-cli", dirs_exist_ok=True)
    else:
        print(f"[runner] WARNING: sim-cli skill not found at {SIM_CLI_SKILL_SRC}; skipping")


_BASH_TIMEOUT_HOOK_TEMPLATE = r'''#!/usr/bin/env python3
"""PreToolUse hook for claude-code's Bash tool (Windows-Path-B port).

Wraps foreground Bash commands with GNU `timeout --kill-after=5s <secs>s
bash -c <orig>` so unresponsive subprocess trees (notably daemonising
COMSOL children that may survive claude-code's own SIGKILL) actually
die. GNU `timeout(1)` runs its child in a new session group and signals
the whole group on expiry.

Mirrors tools/agent_harness.py:_BASH_TIMEOUT_HOOK_SRC behaviour:
  - Wrap duration follows tool_input.timeout (ms), fallback 120s, clamp
    [30s, 600s] per claude-code's hard ceiling.
  - Skip if tool_input.run_in_background is true.
  - Skip if command already prefixed with `timeout ` or `setsid `.

`timeout` is available from Git Bash's coreutils at GIT_BASH_BIN.
"""
import json
import sys

FALLBACK_SECS = 120
MIN_SECS = 30
MAX_SECS = 600


def resolve_secs(inp):
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
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    inp = data.get("tool_input") or {}
    if inp.get("run_in_background"):
        return 0
    cmd = inp.get("command", "") or ""
    stripped = cmd.lstrip()
    if stripped.startswith("timeout ") or stripped.startswith("setsid "):
        return 0
    secs = resolve_secs(inp)
    new_inp = dict(inp)
    new_inp["command"] = (
        "timeout --kill-after=5s " + str(secs) + "s bash -c " + json.dumps(cmd)
    )
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": new_inp,
        }
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _result_json_is_valid(work_dir: Path) -> bool:
    """Phase-1/Phase-2 boundary check: did Phase 1 produce a usable answer?

    Schema-agnostic: file parses as JSON, top-level dict, at least one
    numeric value somewhere in the nested structure. Mirrors the
    `_result_json_is_valid` heuristic in tools/agent_harness.py.
    """
    p = work_dir / "result.json"
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(d, dict) or not d:
        return False

    def has_numeric(x):
        if isinstance(x, bool):
            return False
        if isinstance(x, (int, float)):
            return True
        if isinstance(x, dict):
            return any(has_numeric(v) for v in x.values())
        if isinstance(x, list):
            return any(has_numeric(v) for v in x)
        return False

    return has_numeric(d)


def install_hooks(work_dir: Path) -> None:
    """Drop Stop + PreToolUse hooks + a settings.json that references them.

    Stop hook: schema validates result.json before letting claude stop
    (re-prompts on missing / malformed file). See _STOP_HOOK_TEMPLATE.

    PreToolUse Bash hook: wraps every foreground Bash call in
    `timeout --kill-after=5s Ns bash -c <orig>` so daemonising children
    get killed at deadline. See _BASH_TIMEOUT_HOOK_TEMPLATE.
    """
    hooks_dir = work_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    result_path = (work_dir / "result.json").resolve()
    sentinel    = (work_dir / ".claude" / ".stop-hook-fired").resolve()

    stop_hook_src = (
        _STOP_HOOK_TEMPLATE
        .replace("__RESULT_PATH__", str(result_path).replace("\\", "/"))
        .replace("__SENTINEL__",    str(sentinel).replace("\\", "/"))
    )
    (hooks_dir / "result_check.py").write_text(stop_hook_src, encoding="utf-8")
    (hooks_dir / "bash_timeout.py").write_text(_BASH_TIMEOUT_HOOK_TEMPLATE, encoding="utf-8")

    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f'py -3 "{hooks_dir / "result_check.py"}"',
                }],
            }],
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{
                    "type": "command",
                    "command": f'py -3 "{hooks_dir / "bash_timeout.py"}"',
                }],
            }],
        },
    }
    settings_path = work_dir / ".claude" / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"[runner] installed hooks: Stop(schema-check) + PreToolUse(Bash-timeout) @ {settings_path}")


def prepare_work_dir(case_dir: Path, model: str,
                     out_dir: Path | None) -> tuple[Path, str | None]:
    """Return (work_dir, solver_label). solver_label = task.toml
    [metadata.sim].solver, used downstream to pick prompts + skills."""
    if out_dir is None:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = DEFAULT_TRIAL_ROOT / f"{ts}-{slugify(model)}-{case_dir.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    instr_src = case_dir / "instruction.md"
    if not instr_src.is_file():
        raise FileNotFoundError(f"{instr_src} not found")
    shutil.copy(instr_src, out_dir / "instruction.md")
    # Given artifacts: a case MAY ship a `harness/` dir (test fixtures / provided
    # tooling the agent builds on, e.g. the rv32i functional-verification rig) —
    # the agent-facing analogue of a provided mesh. Copy it into the work dir so
    # the agent can use it. NOTE: solution/ and tests/ are deliberately NOT
    # copied (oracle answer + verifier are hidden from the agent).
    harness_src = case_dir / "harness"
    if harness_src.is_dir():
        shutil.copytree(harness_src, out_dir / "harness", dirs_exist_ok=True)
    (out_dir / ".claude_config_dir").mkdir(parents=True, exist_ok=True)
    solver_label = resolve_solver_label(case_dir)
    install_skills(out_dir, solver_label)
    install_hooks(out_dir)
    return out_dir, solver_label


_DEFAULT_SOLVE_PROMPT_COMSOL = (
    "Read instruction.md in your current working directory and complete "
    "the task it describes. Use the tools available to you (Bash, Write, "
    "Read, Edit, etc.) to drive COMSOL and write your KPI results to "
    "result.json in this directory. The COMSOL skill is available at "
    ".claude/skills/comsol/SKILL.md - read it before writing your model. "
    "When result.json is written and validated by the Stop hook, you may "
    "stop."
)

_DEFAULT_SOLVE_PROMPT_SIMULINK = (
    "Read instruction.md in your current working directory and complete "
    "the task it describes. You are on a Windows host with MATLAB "
    "R2024b + Simulink installed. The standard way to run a Simulink "
    "model headlessly is `matlab -batch \"run('build_and_run.m')\"`. "
    "Build the model programmatically (new_system / add_block / "
    "add_line / set_param) so you can run it from a single `.m` script. "
    "Persist y_out to a `.mat` file with `save` and emit a plain-text "
    "kpis.txt with `name = value` lines so result.json's "
    "`source.kind=\"file_extract\"` provenance can re-read your numbers. "
    "When result.json is written and validated by the Stop hook, you "
    "may stop."
)

_DEFAULT_SOLVE_PROMPT_GENERIC = (
    "Read instruction.md in your current working directory and complete "
    "the task it describes. Use the tools available to you (Bash, "
    "Write, Read, Edit, etc.) to drive the solver and write your KPI "
    "results to result.json in this directory. When result.json is "
    "written and validated by the Stop hook, you may stop."
)


def solve_prompt_for(solver_label: str | None) -> str:
    """Pick the per-solver solve prompt. Legacy default = COMSOL so
    existing OF / LTspice / COMSOL trials get the same string they
    always did."""
    if solver_label == "simulink":
        return _DEFAULT_SOLVE_PROMPT_SIMULINK
    if solver_label in (None, "comsol"):
        return _DEFAULT_SOLVE_PROMPT_COMSOL
    return _DEFAULT_SOLVE_PROMPT_GENERIC


# Backward-compat constant: anyone still importing DEFAULT_SOLVE_PROMPT
# from this module gets the COMSOL default (unchanged behaviour).
DEFAULT_SOLVE_PROMPT = _DEFAULT_SOLVE_PROMPT_COMSOL


def run_claude(work_dir: Path, env: dict, max_turns: int, timeout_s: int,
               prompt: str | None = None, log_suffix: str = "") -> int:
    """Run one claude invocation; appends to claude.log{,suffix}.

    log_suffix: empty for the main Phase 1 log; "wrap" for Phase 2 (so
    Phase 1's log isn't clobbered when both phases run).
    """
    if prompt is None:
        prompt = DEFAULT_SOLVE_PROMPT
    log_name = f"claude.log{log_suffix}" if log_suffix else "claude.log"
    stream_name = f"claude.stream.jsonl{log_suffix}" if log_suffix else "claude.stream.jsonl"
    log_path    = work_dir / log_name
    stream_path = work_dir / stream_name

    cmd = [
        "claude",
        "--setting-sources", "project,local",
        "--add-dir", str(work_dir),
        "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]
    print(f"[runner] cwd={work_dir}")
    print(f"[runner] env: ANTHROPIC_BASE_URL={env.get('ANTHROPIC_BASE_URL')}")
    print(f"[runner] env: ANTHROPIC_MODEL={env.get('ANTHROPIC_MODEL')}")
    if env.get("ANTHROPIC_AUTH_TOKEN"):
        tok = env["ANTHROPIC_AUTH_TOKEN"]
        print(f"[runner] env: ANTHROPIC_AUTH_TOKEN={tok[:10]}...{tok[-6:]}")
    if env.get("ANTHROPIC_CUSTOM_HEADERS"):
        print(f"[runner] env: ANTHROPIC_CUSTOM_HEADERS=<{len(env['ANTHROPIC_CUSTOM_HEADERS'])} chars>")
    print(f"[runner] env: CLAUDE_CONFIG_DIR={env.get('CLAUDE_CONFIG_DIR')}")
    print(f"[runner] timeout {timeout_s}s, max-turns {max_turns}")

    with open(log_path, "wb") as logf, open(stream_path, "wb") as streamf:
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(work_dir), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            print("[runner] ERROR: `claude` not on PATH.", file=sys.stderr)
            return 127

        # Wall-clock watchdog. proc.wait(timeout=...) doesn't fire while
        # proc.stdout is actively streaming, so the for-loop below would
        # otherwise read forever. The watchdog forcibly kills the entire
        # process tree (claude.exe + any spawned children — comsolbatch,
        # node, etc.) via `taskkill /F /T` after timeout_s seconds. The
        # for-loop then breaks naturally as stdout closes.
        timed_out = {"flag": False}

        def _watchdog() -> None:
            time.sleep(timeout_s)
            if proc.poll() is None:
                timed_out["flag"] = True
                elapsed = timeout_s
                print(f"[runner] WALL TIMEOUT {elapsed}s — killing process tree (pid {proc.pid})",
                      flush=True)
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, timeout=15,
                    )
                except Exception:
                    proc.kill()

        wd_thread = threading.Thread(target=_watchdog, daemon=True)
        wd_thread.start()

        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                logf.write(raw)
                logf.flush()
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("{") and line.endswith("}"):
                    streamf.write(raw)
                    streamf.flush()
        except Exception as e:
            print(f"[runner] stdout read error: {e}", file=sys.stderr)
        rc = proc.wait()

    if timed_out["flag"]:
        print(f"[runner] claude killed by wall timeout (rc={rc})", flush=True)
        return 124
    print(f"[runner] claude exited with rc={rc}")
    return rc


def run_claude_two_phase(work_dir: Path, env: dict, max_turns: int,
                         timeout_s: int,
                         solver_label: str | None = None) -> int:
    """Two-phase run: Phase 1 solve → result.json check → Phase 2 wrap-up.

    Phase 1 runs with (max_turns - SOFT_LANDING_TURNS), reserving the
    last SOFT_LANDING_TURNS for Phase 2 in case the solver loop hasn't
    written a valid result.json. Phase 2 instructs the agent to stop
    running new solvers and dump a best-effort answer from existing
    artifacts.

    Both phases share the same wall timeout - we don't split it
    proportionally because the wrap-up phase is read-only (reading files
    already on disk + writing one JSON) and should be fast. If Phase 1
    consumed most of the wall, Phase 2 may itself hit the timeout, but
    that's still better than scoring 0.0 on a near-complete trial.

    Returns the rc of whichever phase actually wrote the final state.
    """
    solve_prompt = solve_prompt_for(solver_label)
    # Reserve last N turns for wrap-up.
    if max_turns > SOFT_LANDING_TURNS:
        phase1_turns = max_turns - SOFT_LANDING_TURNS
    else:
        # max_turns too small to soft-land; just one-phase it.
        return run_claude(work_dir, env, max_turns, timeout_s,
                          prompt=solve_prompt)

    print(f"[runner] PHASE 1 — solve (solver={solver_label!r}, "
          f"max_turns={phase1_turns}, reserve={SOFT_LANDING_TURNS})")
    rc1 = run_claude(work_dir, env, phase1_turns, timeout_s,
                     prompt=solve_prompt)

    if _result_json_is_valid(work_dir):
        print("[runner] PHASE 1 produced valid result.json - skipping wrap-up")
        return rc1

    print(f"[runner] PHASE 1 ended without valid result.json (rc={rc1}); "
          f"running PHASE 2 wrap-up (max_turns={SOFT_LANDING_TURNS})")
    # Preserve Phase 1 logs by writing Phase 2 with suffix '.wrap'.
    rc2 = run_claude(work_dir, env, SOFT_LANDING_TURNS, timeout_s,
                     prompt=WRAP_UP_INSTRUCTION, log_suffix=".wrap")

    # Concatenate phase 1 + phase 2 logs into the canonical claude.log
    # so downstream tools (verifier, monitoring) see the full session.
    try:
        log1 = work_dir / "claude.log"
        log2 = work_dir / "claude.log.wrap"
        if log1.is_file() and log2.is_file():
            log1_bytes = log1.read_bytes()
            log2_bytes = log2.read_bytes()
            (work_dir / "claude.log.solve").write_bytes(log1_bytes)
            log1.write_bytes(log1_bytes + b"\n--- PHASE 2 WRAP-UP ---\n" + log2_bytes)
        stream1 = work_dir / "claude.stream.jsonl"
        stream2 = work_dir / "claude.stream.jsonl.wrap"
        if stream1.is_file() and stream2.is_file():
            stream1_bytes = stream1.read_bytes()
            stream2_bytes = stream2.read_bytes()
            (work_dir / "claude.stream.jsonl.solve").write_bytes(stream1_bytes)
            stream1.write_bytes(stream1_bytes + stream2_bytes)
    except Exception as e:
        print(f"[runner] WARN: log concat failed: {e}", file=sys.stderr)

    return rc2


def run_verifier(case_dir: Path, work_dir: Path) -> int:
    test_bat = case_dir / "tests" / "test.bat"
    if not test_bat.is_file():
        print(f"[runner] ERROR: {test_bat} not found", file=sys.stderr)
        return 2
    cmd = ["cmd", "/c", str(test_bat), str(work_dir)]
    print(f"[runner] verifier: {test_bat.name} {work_dir}", flush=True)
    # encoding='utf-8'/errors='replace' is critical on Chinese Windows.
    # text=True alone uses locale.getpreferredencoding() = cp936/GBK which
    # crashes UnicodeDecodeError when verifier stdout contains UTF-8 chars
    # (COMSOL .mph metadata, Chinese error messages from cmd.exe). The
    # crash aborts the runner BEFORE summarize() runs and post-hoc
    # forensics show "result.json present, reward.json missing".
    proc = subprocess.run(
        cmd, capture_output=True, timeout=120,
        encoding="utf-8", errors="replace",
    )
    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    return proc.returncode


def summarize(work_dir: Path) -> None:
    reward = work_dir / "reward.json"
    detail = work_dir / "reward_detail.json"
    print("-" * 60)
    if reward.is_file():
        try:
            data = json.loads(reward.read_text(encoding="utf-8"))
            print(f"  final score: {data.get('score')}")
        except Exception as e:
            print(f"  reward.json malformed: {e}")
    else:
        print("  reward.json: NOT WRITTEN")
    if detail.is_file():
        try:
            d = json.loads(detail.read_text(encoding="utf-8"))
            per = d.get("kpi_detail", {}).get("per_kpi", {})
            for name, info in per.items():
                value = info.get("value")
                why   = info.get("why") or info.get("physics_why") or "ok"
                fc    = info.get("failure_class")
                fc_str = f" [{fc}]" if fc else ""
                print(f"    {name}: kpi={info.get('kpi_score')} value={value} {why}{fc_str}")
        except Exception as e:
            print(f"  reward_detail.json malformed: {e}")
    print(f"  artifacts: {work_dir}")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, type=Path)
    ap.add_argument("--model",
                    help="ANTHROPIC_MODEL (overrides --env-file's value if both given). "
                         "Required unless --env-file supplies it.")
    ap.add_argument("--base-url", default="https://api.minimaxi.com/anthropic",
                    help="ANTHROPIC_BASE_URL (default: minimax). Ignored if --env-file given.")
    ap.add_argument("--api-key")
    ap.add_argument("--api-key-file", type=Path)
    ap.add_argument("--api-key-line", type=int)
    ap.add_argument("--env-file", type=Path,
                    help="JSON file with {\"env\": {...}} block. All keys merged into "
                         "subprocess env (e.g. ANTHROPIC_AUTH_TOKEN, ANTHROPIC_CUSTOM_HEADERS, "
                         "ANTHROPIC_MODEL). Use this for non-standard upstreams (custom "
                         "gateways with header auth) instead of --api-key/--base-url.")
    ap.add_argument("--max-turns", type=int, default=100)
    ap.add_argument("--timeout",   type=int, default=2400,
                    help="claude wall-clock timeout in seconds (default 40 min)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Override auto-generated work dir")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)

    case_dir = args.case.resolve()
    if not case_dir.is_dir():
        print(f"[runner] ERROR: case dir {case_dir} does not exist", file=sys.stderr)
        return 2

    # Build base env from --env-file (if given) or from --api-key/--base-url/--model.
    env_overrides: dict = {}
    if args.env_file:
        try:
            env_blob = json.loads(args.env_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[runner] ERROR: cannot parse {args.env_file}: {e}", file=sys.stderr)
            return 2
        env_overrides = dict(env_blob.get("env") or {})
        if not env_overrides:
            print(f"[runner] ERROR: {args.env_file} has no `env` block", file=sys.stderr)
            return 2
    else:
        if args.api_key:
            api_key = args.api_key
        elif args.api_key_file and args.api_key_line:
            api_key = read_api_key(args.api_key_file, args.api_key_line)
        else:
            print("[runner] ERROR: need --env-file OR --api-key OR (--api-key-file + --api-key-line)",
                  file=sys.stderr)
            return 2
        env_overrides = {
            "ANTHROPIC_BASE_URL": args.base_url,
            "ANTHROPIC_API_KEY":  api_key,
        }
        if args.model:
            env_overrides["ANTHROPIC_MODEL"] = args.model

    # --model arg overrides whatever the env-file said.
    if args.model:
        env_overrides["ANTHROPIC_MODEL"] = args.model

    model_name = env_overrides.get("ANTHROPIC_MODEL")
    if not model_name:
        print("[runner] ERROR: ANTHROPIC_MODEL not set (pass --model or include it in --env-file)",
              file=sys.stderr)
        return 2

    work_dir, solver_label = prepare_work_dir(case_dir, model_name, args.out_dir)
    print(f"[runner] work_dir:     {work_dir}")
    print(f"[runner] case:         {case_dir}")
    print(f"[runner] solver_label: {solver_label!r}")

    env = os.environ.copy()
    env.update(env_overrides)
    env["CLAUDE_CONFIG_DIR"] = str((work_dir / ".claude_config_dir").resolve())
    env["PATH"] = GIT_BASH_BIN + os.pathsep + env.get("PATH", "")
    # Match OF/LTspice configs: disable experimental beta features for
    # stability. Only set if caller didn't already supply a value.
    env.setdefault("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "1")
    # Force UTF-8 mode so verifier subprocess calls (run via test.bat)
    # don't crash on COMSOL's GBK-mojibake stdout under Chinese locale.
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # Always write reward.json before exiting — placeholder if nothing
    # else does. The orchestrator's poll uses reward.json existence as
    # the "trial complete" signal; a runner that crashes before writing
    # reward.json wedges the orchestrator until CAP_SECS (~5h wasted).
    # Bracket the whole solve+verify with try/finally so reward.json is
    # guaranteed even on uncaught exceptions.
    reward_path = work_dir / "reward.json"
    rc = 1
    rc_verify = 1
    try:
        rc = run_claude_two_phase(work_dir, env, args.max_turns,
                                   args.timeout, solver_label=solver_label)

        if args.no_verify:
            print(f"[runner] --no-verify; agent rc={rc}; skipping verifier",
                  flush=True)
            return rc

        rc_verify = run_verifier(case_dir, work_dir)
        summarize(work_dir)
        return 0 if rc_verify == 0 else rc_verify
    finally:
        if not reward_path.is_file():
            # Verifier crashed / timed out / never reached. Write
            # placeholder so orchestrator doesn't deadlock.
            try:
                reward_path.write_text(
                    json.dumps({"score": 0.0}, indent=2), encoding="utf-8"
                )
                detail_path = work_dir / "reward_detail.json"
                detail_path.write_text(json.dumps({
                    "schema_version": "reward-v3.2",
                    "case_id":   case_dir.name,
                    "final_score": 0.0,
                    "kpi_score":   0.0,
                    "anti_cheat":  None,
                    "kpi_detail":  {
                        "why": (
                            "runner exited without verifier writing reward.json "
                            f"(agent rc={rc}, verifier rc={rc_verify}); "
                            "placeholder reward written by try/finally guard"
                        ),
                    },
                }, indent=2), encoding="utf-8")
                print("[runner] WROTE PLACEHOLDER reward.json (score=0.0)",
                      flush=True)
            except Exception as e:
                print(f"[runner] CRITICAL: couldn't write placeholder reward: {e}",
                      file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
