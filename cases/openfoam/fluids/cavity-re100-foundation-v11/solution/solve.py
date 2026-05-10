#!/usr/bin/env python3
"""
Oracle for cavity-re100 on OpenFOAM Foundation v11.

Tutorial layout differs from ESI:
    ESI v2412 : incompressible/icoFoam/cavity/cavity   (icoFoam direct)
    Found v11 : incompressibleFluid/cavity             (foamRun + module)

File renames in v11:
    transportProperties  -> physicalProperties
    turbulenceProperties -> momentumTransport
"""

from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def parse_log(log_text: str) -> dict:
    """Inline minimal port of sim-cli's OpenFOAMDriver.parse_log.

    Foundation v11 ships a Python 3.8 base image on which sim-cli (which
    requires 3.10+) cannot be installed; this function duplicates the
    regexes and return shape so verifier contracts stay identical.
    """
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
        return not is_steady
    return max(residuals.values()) < 1e-2


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    tutorial = Path(__file__).resolve().parent / "tutorial-ref"
    if not tutorial.is_dir():
        print(f"ERROR: bundled tutorial-ref/ not found next to solve.py: {tutorial}", file=sys.stderr)
        return 2

    work = Path.cwd() / "cavity_run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tutorial, work)

    # Some tutorials use 0.orig; v11 cavity ships with 0/ directly. Handle both.
    if (work / "0.orig").exists() and not (work / "0").exists():
        shutil.copytree(work / "0.orig", work / "0")

    # Patch nu in physicalProperties (Foundation v11 file name).
    # v11 tutorial default is nu = 1e-05 (Re=10000); for Re=100 we need 0.001.
    # Regex matches ANY existing nu value so we don't depend on the tutorial's default.
    pp = work / "constant/physicalProperties"
    pp.write_text(
        re.sub(
            r"nu\s+(\[[^\]]+\]\s+)?[\deE.+-]+\s*;",
            r"nu              \g<1>0.001;",
            pp.read_text(),
        )
    )

    # endTime: cavity tutorial default in v11 is endTime=10 already (deltaT=0.005);
    # plenty for Re=100 to reach steady. Leave as-is.

    sh(["blockMesh"], cwd=work)
    solver_proc = sh(["foamRun"], cwd=work)

    parsed = parse_log(solver_proc.stdout)
    converged = converged_from_parsed(parsed, is_steady=False)
    # v11 has foamPostProcess but the 'sampleDict' loader path differs from ESI.
    # Simpler & version-agnostic: dump cell centres + read U directly, find the
    # cell nearest to (0.05, 0.05, 0.005) ourselves.
    sh(["foamPostProcess", "-func", "writeCellCentres", "-latestTime"], cwd=work)

    # Find latest time dir
    time_dirs = []
    for d in work.iterdir():
        if not d.is_dir():
            continue
        try:
            time_dirs.append((float(d.name), d))
        except ValueError:
            continue
    if not time_dirs:
        print("ERROR: no time directories", file=sys.stderr)
        return 3
    _, latest = max(time_dirs, key=lambda t: t[0])

    def parse_internal_field(path: Path, vector: bool):
        text = path.read_text()
        if vector:
            m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*\d+\s*\((.*?)\)\s*;", text, re.DOTALL)
            if not m:
                return None
            return [tuple(float(x) for x in v.groups())
                    for v in re.finditer(r"\(([-\deE.+]+)\s+([-\deE.+]+)\s+([-\deE.+]+)\)", m.group(1))]
        else:
            m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*\d+\s*\((.*?)\)\s*;", text, re.DOTALL)
            if not m:
                return None
            return [float(x) for x in m.group(1).split()]

    u_field = parse_internal_field(latest / "U", vector=True)
    c_field = parse_internal_field(latest / "C", vector=True)
    if not u_field or not c_field:
        print(
            f"ERROR: missing or unparseable U/C in {latest}; "
            f"files = {[p.name for p in latest.iterdir()]}",
            file=sys.stderr,
        )
        return 4

    target = (0.05, 0.05, 0.005)
    best_d2 = float("inf")
    u_at_center = None
    for c, u in zip(c_field, u_field):
        d2 = (c[0] - target[0]) ** 2 + (c[1] - target[1]) ** 2 + (c[2] - target[2]) ** 2
        if d2 < best_d2:
            best_d2 = d2
            u_at_center = u[0]  # u_x

    if u_at_center is None:
        print("ERROR: no cell found", file=sys.stderr)
        return 5

    result = {
        "RESULT": u_at_center,
        "u_centerline_at_y05": u_at_center,
        "reference_ghia_1982": -0.20581,
        "Re": 100,
        "fork": "Foundation v11",
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
