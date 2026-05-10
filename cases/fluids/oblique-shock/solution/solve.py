#!/usr/bin/env python3
"""
Oracle for oblique-shock (FoamBench obliqueShock/1).

2D compressible flow producing an oblique shock, rhoCentralFoam,
normalized gas (R=0.7143, Cp=2.5, μ=0), end t=10 s.
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
    residual_re = re.compile(
        r"Solving for ([\w.]+),\s*Initial residual\s*=\s*[\d.eE+-]+,\s*"
        r"Final residual\s*=\s*([\d.eE+-]+)"
    )
    time_re = re.compile(r"^Time\s*=\s*([\d.eE+-]+)\s*$")
    residuals, final_time = {}, None
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
    ended = any(l.strip() == "End" for l in log_text.rstrip().splitlines()[-5:])
    return {"ended_normally": ended, "final_time": final_time, "final_residuals": residuals}


def converged_from_parsed(parsed: dict, is_steady: bool) -> bool:
    if not parsed.get("ended_normally"):
        return False
    r = parsed.get("final_residuals") or {}
    if not r:
        return not is_steady
    return max(r.values()) < 1e-2


def probe_field_stats(field_path: Path):
    if not field_path.is_file():
        return None
    try:
        text = field_path.read_text()
    except UnicodeDecodeError:
        return {"binary": True}
    m = re.search(r"internalField\s+nonuniform\s+List<(\w+)>\s*\d+\s*\((.*?)\)\s*;", text, re.DOTALL)
    if m:
        kind, body = m.group(1), m.group(2)
        if kind == "vector":
            mags = [math.sqrt(float(x)**2 + float(y)**2 + float(z)**2)
                    for x, y, z in re.findall(r"\((-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\)", body)]
            if not mags:
                return None
            return {"max_mag": max(mags), "min_mag": min(mags), "mean_mag": sum(mags)/len(mags)}
        vals = [float(v) for v in body.split() if re.match(r"-?[\d.eE+-]+", v)]
        if not vals:
            return None
        return {"max": max(vals), "min": min(vals), "mean": sum(vals)/len(vals)}
    m = re.search(r"internalField\s+uniform\s+([^;]+);", text)
    if m:
        v = m.group(1).strip()
        mv = re.match(r"\(([^)]+)\)", v)
        if mv:
            x, y, z = (float(t) for t in mv.group(1).split())
            mag = math.sqrt(x*x + y*y + z*z)
            return {"max_mag": mag, "min_mag": mag, "mean_mag": mag}
        try:
            vv = float(v)
        except ValueError:
            return None
        return {"max": vv, "min": vv, "mean": vv}
    return None


def main() -> int:
    tutorial = Path(__file__).resolve().parent / "tutorial-ref"
    if not tutorial.is_dir():
        print(f"ERROR: tutorial-ref/ not found: {tutorial}", file=sys.stderr)
        return 2

    work = Path.cwd() / "oblique_shock_run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tutorial, work)

    cd = work / "system" / "controlDict"
    cd.write_text(cd.read_text().replace("writeFormat     binary", "writeFormat     ascii"))

    allrun = work / "Allrun"
    os.chmod(allrun, os.stat(allrun).st_mode | 0o111)
    proc = subprocess.run(["bash", "-c", f"cd {work} && ./Allrun 2>&1"],
                          capture_output=True, text=True)
    solver_log_file = work / "log.rhoCentralFoam"
    log_text = solver_log_file.read_text() if solver_log_file.exists() else proc.stdout
    parsed = parse_log(log_text)
    converged = converged_from_parsed(parsed, is_steady=False)

    time_dirs = [p for p in work.iterdir()
                 if p.is_dir() and p.name.replace(".", "").isdigit()]
    if not time_dirs:
        print("ERROR: no time directory found", file=sys.stderr)
        return 3
    latest = max(time_dirs, key=lambda p: float(p.name))

    p_stats = probe_field_stats(latest / "p")
    rho_stats = probe_field_stats(latest / "rho")
    if not p_stats or not rho_stats:
        print(f"ERROR: failed to parse fields in {latest}: p={p_stats} rho={rho_stats}", file=sys.stderr)
        return 4

    kpis = {
        "max_p":   p_stats.get("max"),
        "max_rho": rho_stats.get("max"),
    }
    result = {
        "kpis":          kpis,
        "RESULT":        kpis["max_p"],
        "converged":     converged,
        "final_time":    float(latest.name),
        "sim_cli_parse": parsed,
    }
    out = Path("/tmp/agent/result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
