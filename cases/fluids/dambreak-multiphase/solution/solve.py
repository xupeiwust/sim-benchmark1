#!/usr/bin/env python3
"""
Oracle for dambreak-multiphase.

Copies the ESI damBreak/damBreak tutorial verbatim, runs blockMesh +
setFields + interFoam to t=1s, then loads the latest U field and
reports max |U|.
"""

from __future__ import annotations
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def parse_log(log_text: str) -> dict:
    """Parse OpenFOAM solver log into structured residual / convergence info."""
    residuals: dict = {}
    final_time = None
    simple_converged = False
    continuity_errors = None

    residual_re = re.compile(
        r"Solving for ([\w.]+),\s*Initial residual\s*=\s*[\d.eE+-]+,\s*"
        r"Final residual\s*=\s*([\d.eE+-]+)"
    )
    time_re = re.compile(r"^Time\s*=\s*([\d.eE+-]+)\s*$")
    simple_re = re.compile(r"SIMPLE solution converged in\s+\d+\s+iterations?")
    continuity_re = re.compile(
        r"time step continuity errors\s*:\s*sum local\s*=\s*([\d.eE+-]+),?\s*"
        r"global\s*=\s*([\d.eE+-]+),?\s*cumulative\s*=\s*([\d.eE+-]+)"
    )

    for raw in log_text.splitlines():
        line = raw.strip()
        m = residual_re.search(line)
        if m:
            try:
                residuals[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
            continue
        m = time_re.match(line)
        if m:
            try:
                final_time = float(m.group(1))
            except ValueError:
                pass
            continue
        if simple_re.search(line):
            simple_converged = True
            continue
        m = continuity_re.search(line)
        if m:
            try:
                continuity_errors = {
                    "sum_local": float(m.group(1)),
                    "global": float(m.group(2)),
                    "cumulative": float(m.group(3)),
                }
            except ValueError:
                pass

    tail = log_text.rstrip().splitlines()[-5:] if log_text.strip() else []
    ended_normally = any(line.strip() == "End" for line in tail)

    return {
        "ended_normally": ended_normally,
        "final_time": final_time,
        "final_residuals": residuals,
        "simple_converged": simple_converged,
        "continuity_errors": continuity_errors,
    }


def converged_from_parsed(parsed: dict, is_steady: bool) -> bool:
    """Case-agnostic heuristic: solver printed `End` and residuals are tame.

    For steady (SIMPLE) solvers: also accept simple_converged=True as
    sufficient. For transient solvers: `End` alone is sufficient because
    it means the integration reached endTime without blow-up.
    """
    if not parsed.get("ended_normally"):
        return False
    if is_steady and parsed.get("simple_converged"):
        return True
    residuals = parsed.get("final_residuals") or {}
    if not residuals:
        # Solver ended but produced no residual lines — be lenient on
        # transient, strict on steady.
        return not is_steady
    return max(residuals.values()) < 1e-2


def main() -> int:
    tutorial = Path(__file__).resolve().parent / "tutorial-ref"
    if not tutorial.is_dir():
        print(f"ERROR: bundled tutorial-ref/ not found next to solve.py: {tutorial}", file=sys.stderr)
        return 2

    work = Path.cwd() / "dambreak_run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tutorial, work)

    if (work / "0.orig").exists() and not (work / "0").exists():
        shutil.copytree(work / "0.orig", work / "0")

    sh(["blockMesh"], cwd=work)
    sh(["setFields"], cwd=work)
    solver_proc = sh(["interFoam"], cwd=work)

    parsed = parse_log(solver_proc.stdout)
    converged = converged_from_parsed(parsed, is_steady=False)

    time_dirs = []
    for d in work.iterdir():
        if not d.is_dir():
            continue
        try:
            time_dirs.append((float(d.name), d))
        except ValueError:
            continue
    if not time_dirs:
        print("ERROR: no time directories found", file=sys.stderr)
        return 3
    _, latest = max(time_dirs, key=lambda t: t[0])

    u_file = latest / "U"
    if not u_file.is_file():
        print(f"ERROR: U file missing at {u_file}", file=sys.stderr)
        return 4

    text = u_file.read_text()
    m = re.search(
        r"internalField\s+nonuniform\s+List<vector>\s*\d+\s*\((.*?)\)\s*;",
        text, re.DOTALL,
    )
    if not m:
        print("ERROR: can't parse U internalField", file=sys.stderr)
        return 5

    body = m.group(1)
    max_mag = 0.0
    for vm in re.finditer(r"\(([-\deE.+]+)\s+([-\deE.+]+)\s+([-\deE.+]+)\)", body):
        ux, uy, uz = float(vm.group(1)), float(vm.group(2)), float(vm.group(3))
        mag = math.sqrt(ux * ux + uy * uy + uz * uz)
        if mag > max_mag:
            max_mag = mag

    result = {
        "RESULT": max_mag,
        "max_U_magnitude_m_s": max_mag,
        "latest_time": latest.name,
        "converged": converged,
        "sim_cli_parse": parsed,
    }
    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
