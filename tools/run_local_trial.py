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


def install_skills(work_dir: Path) -> None:
    """Copy comsol + sim-cli skill bundles under <work_dir>/.claude/skills/.

    We copy rather than symlink because Windows symlinks require Developer
    Mode or admin. Bundles are small (~1 MB) so the cost is negligible.
    """
    skills_dst = work_dir / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    comsol_src = resolve_comsol_skill_dir()
    print(f"[runner] copying COMSOL skill: {comsol_src}")
    shutil.copytree(comsol_src, skills_dst / "comsol", dirs_exist_ok=True)
    if SIM_CLI_SKILL_SRC.is_dir():
        print(f"[runner] copying sim-cli skill: {SIM_CLI_SKILL_SRC}")
        shutil.copytree(SIM_CLI_SKILL_SRC, skills_dst / "sim-cli", dirs_exist_ok=True)
    else:
        print(f"[runner] WARNING: sim-cli skill not found at {SIM_CLI_SKILL_SRC}; skipping")


def install_hooks(work_dir: Path) -> None:
    """Drop the Stop-hook script + a settings.json that references it."""
    hooks_dir = work_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    result_path = (work_dir / "result.json").resolve()
    sentinel    = (work_dir / ".claude" / ".stop-hook-fired").resolve()

    hook_src = (
        _STOP_HOOK_TEMPLATE
        .replace("__RESULT_PATH__", str(result_path).replace("\\", "/"))
        .replace("__SENTINEL__",    str(sentinel).replace("\\", "/"))
    )
    (hooks_dir / "result_check.py").write_text(hook_src, encoding="utf-8")

    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f'py -3 "{hooks_dir / "result_check.py"}"',
                }],
            }],
        },
    }
    settings_path = work_dir / ".claude" / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"[runner] installed Stop hook: {settings_path}")


def prepare_work_dir(case_dir: Path, model: str, out_dir: "Path | None") -> Path:
    if out_dir is None:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = DEFAULT_TRIAL_ROOT / f"{ts}-{slugify(model)}-{case_dir.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    instr_src = case_dir / "instruction.md"
    if not instr_src.is_file():
        raise FileNotFoundError(f"{instr_src} not found")
    shutil.copy(instr_src, out_dir / "instruction.md")
    (out_dir / ".claude_config_dir").mkdir(parents=True, exist_ok=True)
    install_skills(out_dir)
    install_hooks(out_dir)
    return out_dir


def run_claude(work_dir: Path, env: dict, max_turns: int, timeout_s: int) -> int:
    prompt = (
        "Read instruction.md in your current working directory and complete "
        "the task it describes. Use the tools available to you (Bash, Write, "
        "Read, Edit, etc.) to drive COMSOL and write your KPI results to "
        "result.json in this directory. The COMSOL skill is available at "
        ".claude/skills/comsol/SKILL.md - read it before writing your model. "
        "When result.json is written and validated by the Stop hook, you may "
        "stop."
    )
    log_path    = work_dir / "claude.log"
    stream_path = work_dir / "claude.stream.jsonl"

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


def run_verifier(case_dir: Path, work_dir: Path) -> int:
    test_bat = case_dir / "tests" / "test.bat"
    if not test_bat.is_file():
        print(f"[runner] ERROR: {test_bat} not found", file=sys.stderr)
        return 2
    cmd = ["cmd", "/c", str(test_bat), str(work_dir)]
    print(f"[runner] verifier: {test_bat.name} {work_dir}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
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

def main(argv: "list[str] | None" = None) -> int:
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

    work_dir = prepare_work_dir(case_dir, model_name, args.out_dir)
    print(f"[runner] work_dir: {work_dir}")
    print(f"[runner] case:     {case_dir}")

    env = os.environ.copy()
    env.update(env_overrides)
    env["CLAUDE_CONFIG_DIR"] = str((work_dir / ".claude_config_dir").resolve())
    env["PATH"] = GIT_BASH_BIN + os.pathsep + env.get("PATH", "")

    rc = run_claude(work_dir, env, args.max_turns, args.timeout)

    if args.no_verify:
        print(f"[runner] --no-verify; agent rc={rc}; skipping verifier")
        return rc

    rc_verify = run_verifier(case_dir, work_dir)
    summarize(work_dir)
    return 0 if rc_verify == 0 else rc_verify


if __name__ == "__main__":
    sys.exit(main())
