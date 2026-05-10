#!/usr/bin/env python3
"""
Oracle for pitzdaily-bfs-rans.

Runs the standard ESI OpenFOAM `pitzDaily` tutorial (k-epsilon RANS,
incompressible, simpleFoam) verbatim. After convergence, samples the
streamwise velocity component along a line just above the lower wall
downstream of the step, and finds the reattachment x = first x > 0
at which U_x crosses from negative to positive.

The step in the pitzDaily geometry is at x = 0 with step height
h = 0.0254 m; the lower wall extends from x ≈ 0 to x ≈ 0.290 m.

Final stdout line: {"RESULT": x_r/h, ...}.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

H = 0.0254  # step height [m]
# pitzDaily geometry (system/blockMeshDict, scale=0.001):
#   inlet section x ∈ [-0.0206, 0], y ∈ [0, 0.0254]   (lower wall y=0)
#   STEP at x=0, drops from y=0 to y=-0.0254
#   after-step main x ∈ [0, 0.206], y ∈ [-0.0254, 0.0254]   (lower wall y=-0.0254)
#   outlet narrows beyond x=0.206; stop sampling well before that
LOWER_WALL_Y = -0.0254
SAMPLE_Y = LOWER_WALL_Y + 0.0005   # 0.5 mm above the after-step lower wall
LOWER_WALL_X_START = 0.005         # 5 mm downstream of step corner — skip
                                   # the corner-noise region where ux can be
                                   # mixed-sign before the recirculation settles
LOWER_WALL_X_END = 0.18            # safely inside the after-step main section
N_SAMPLES = 400


def sh(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
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

    work = Path.cwd() / "pitzdaily_run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tutorial, work)

    # sampleDict: a 400-point line sitting SAMPLE_Y above the lower wall, from
    # the step (x=0) to the outlet. The pitzDaily mesh is in the z = 0..0.001 m
    # slab (2D-equivalent); use mid-z for sampling.
    # z-mid: pitzDaily mesh slab is z ∈ [-0.0005, 0.0005]; sample at z=0.
    (work / "system/sampleDict").write_text(f"""\
type sets;
libs (sampling);
interpolationScheme cellPoint;
setFormat raw;
sets
(
    nearLowerWall
    {{
        type    uniform;
        axis    x;
        start   ({LOWER_WALL_X_START} {SAMPLE_Y} 0.0);
        end     ({LOWER_WALL_X_END}   {SAMPLE_Y} 0.0);
        nPoints {N_SAMPLES};
    }}
);
fields (U);
""")

    sh(["blockMesh"], cwd=work)
    solver_proc = sh(["simpleFoam"], cwd=work)
    sh(["postProcess", "-func", "sampleDict", "-latestTime"], cwd=work)

    parsed = parse_log(solver_proc.stdout)
    converged = converged_from_parsed(parsed, is_steady=True)

    pp_root = work / "postProcessing" / "sampleDict"
    latest_dir = sorted(pp_root.iterdir(), key=lambda p: float(p.name))[-1]
    xy_file = latest_dir / "nearLowerWall_U.xy"

    samples: list[tuple[float, float]] = []
    for raw in xy_file.read_text().splitlines():
        parts = raw.split()
        if len(parts) < 4:
            continue
        try:
            x, ux, _uy, _uz = map(float, parts)
        except ValueError:
            continue
        samples.append((x, ux))

    if len(samples) < 10:
        print(f"ERROR: only {len(samples)} samples extracted", file=sys.stderr)
        return 3

    # Debug: dump the ux profile in chunks so we can sanity-check the flow shape.
    print(
        f"DEBUG ux profile (every 20th sample): "
        + ", ".join(f"x={x:.3f}/ux={ux:+.3f}" for x, ux in samples[::20]),
        file=sys.stderr,
    )

    # Find first x > 0 where U_x changes from negative to positive.
    x_reattach = None
    for i in range(1, len(samples)):
        x_prev, ux_prev = samples[i - 1]
        x_curr, ux_curr = samples[i]
        if x_curr <= 0:
            continue
        if ux_prev < 0 and ux_curr >= 0:
            # Linear interpolation between the two samples
            frac = -ux_prev / (ux_curr - ux_prev)
            x_reattach = x_prev + frac * (x_curr - x_prev)
            break

    if x_reattach is None:
        print(
            f"ERROR: no negative-to-positive U_x crossing found in samples "
            f"(first ux={samples[0][1]:.4f}, last ux={samples[-1][1]:.4f})",
            file=sys.stderr,
        )
        return 4

    x_over_h = x_reattach / H

    result = {
        "RESULT": x_over_h,
        "x_reattach_m": x_reattach,
        "step_height_m": H,
        "n_samples": len(samples),
        "k_epsilon_typical_range": [5.0, 7.0],
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
