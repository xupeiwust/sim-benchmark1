#!/usr/bin/env python3
"""
Oracle for cavity-re1000. Same shape as cavity-re100 but nu=0.0001, much longer endTime.
Reference: Ghia 1982 Table I, Re=1000, u_centerline at y=0.5 ≈ -0.06080.
"""

from __future__ import annotations
import json
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

    work = Path.cwd() / "cavity_run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tutorial, work)

    # Re=1000: nu = 0.0001 (vs tutorial default 0.01)
    tp = work / "constant/transportProperties"
    tp.write_text(tp.read_text().replace("nu              0.01;", "nu              0.0001;"))

    # Re=1000 requires substantial integration time AND a finer mesh.
    # We bump endTime to 15s and reduce deltaT for stability on the coarse mesh.
    cd = work / "system/controlDict"
    cd_text = cd.read_text()
    cd_text = cd_text.replace("endTime         0.5;", "endTime         15.0;")
    cd_text = cd_text.replace("deltaT          0.005;", "deltaT          0.0025;")
    cd.write_text(cd_text)

    (work / "system/sampleDict").write_text("""\
type sets;
libs (sampling);
interpolationScheme cellPoint;
setFormat raw;
sets
(
    centerline
    {
        type    uniform;
        axis    y;
        start   (0.05 0.0 0.005);
        end     (0.05 0.1 0.005);
        nPoints 100;
    }
);
fields (U);
""")

    sh(["blockMesh"], cwd=work)
    solver_proc = sh(["icoFoam"], cwd=work)
    sh(["postProcess", "-func", "sampleDict", "-latestTime"], cwd=work)

    parsed = parse_log(solver_proc.stdout)
    converged = converged_from_parsed(parsed, is_steady=False)

    pp_root = work / "postProcessing" / "sampleDict"
    latest_dir = sorted(pp_root.iterdir(), key=lambda p: float(p.name))[-1]
    xy_file = latest_dir / "centerline_U.xy"

    best_dy = float("inf")
    u_at_center = None
    for raw in xy_file.read_text().splitlines():
        parts = raw.split()
        if len(parts) < 4:
            continue
        try:
            y, ux, _uy, _uz = map(float, parts)
        except ValueError:
            continue
        dy = abs(y - 0.05)
        if dy < best_dy:
            best_dy = dy
            u_at_center = ux

    if u_at_center is None:
        print("ERROR: no valid sample extracted", file=sys.stderr)
        return 3

    result = {
        "RESULT": u_at_center,
        "u_centerline_at_y05": u_at_center,
        "reference_ghia_1982": -0.06080,
        "Re": 1000,
        "end_time": 15.0,
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
