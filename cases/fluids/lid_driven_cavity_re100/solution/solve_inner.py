"""Lid-driven cavity Re=100 oracle.

simpleFoam (laminar) — steady-state driven cavity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/root/case"))


def discover_openfoam_bashrc() -> str:
    r = subprocess.run(
        ["sim", "--json", "check", "openfoam"],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(r.stdout)
    installs = data.get("data", {}).get("installs", [])
    if not installs:
        raise RuntimeError("sim check openfoam reported no installations")
    install_path = installs[0]["path"]
    bashrc = Path(install_path) / "etc" / "bashrc"
    if not bashrc.is_file():
        raise RuntimeError(f"etc/bashrc not found under {install_path}")
    return str(bashrc)


BASHRC_PATH = discover_openfoam_bashrc()


def sh(cmd: str) -> None:
    subprocess.run(
        f"source {BASHRC_PATH} && cd {CASE} && {cmd}",
        shell=True, check=True, executable="/bin/bash",
    )


def read_centerline(case: Path) -> list[tuple[float, float]]:
    """Read the latest sampled U along x=0.5 centreline, return (y, u_x)."""
    candidates = list(case.glob("postProcessing/sampleDict/*/centerline_x0p5_U.xy"))
    if not candidates:
        return []
    xy = sorted(candidates, key=lambda p: float(p.parent.name))[-1]

    pts: list[tuple[float, float]] = []
    for line in xy.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            y = float(parts[0])
            u_x = float(parts[1])
            pts.append((y, u_x))
        except ValueError:
            continue
    return pts


def interp_u_at_y(pts: list[tuple[float, float]], y_target: float) -> float | None:
    pts = sorted(pts, key=lambda t: t[0])
    for i in range(len(pts) - 1):
        y0, u0 = pts[i]
        y1, u1 = pts[i + 1]
        if y0 <= y_target <= y1:
            if y1 == y0:
                return u0
            w = (y_target - y0) / (y1 - y0)
            return u0 + w * (u1 - u0)
    return None


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] simpleFoam")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    pts = read_centerline(CASE)
    u_at_center = interp_u_at_y(pts, 0.5)
    u_min = min((u for _, u in pts), default=None)

    out: dict = {}
    if u_at_center is not None:
        out["u_centerline_y0p5"] = u_at_center
    if u_min is not None:
        out["u_min_along_x0p5"] = u_min

    result_path = Path("/tmp/agent/result.json")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(out, indent=2))

    print(json.dumps(out))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
