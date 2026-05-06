"""Flat plate ZPG oracle — runs under `sim run --solver openfoam`.

sim-cli invokes this script as a Python subprocess. The script shells
out to blockMesh + simpleFoam, parses OpenFOAM's postProcessing output,
and writes /tmp/agent/result.json. stdout emits one JSON line at the
end so sim-cli's parse_output() can pick up the KPIs too (redundant
but cheap).

Keywords `blockMesh` / `simpleFoam` in this file's top comment make
OpenFOAMDriver.detect() happy if someone invokes without --solver.
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
    """Ask sim-cli where OpenFOAM lives in THIS container.

    Returns the absolute path to etc/bashrc for the first installed
    OpenFOAM instance. Fails loudly if none is installed — an oracle
    that cannot find its solver should not produce a silent fallback.
    """
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
    """Run a bash command with the OpenFOAM environment sourced."""
    subprocess.run(
        f"source {BASHRC_PATH} && cd {CASE} && {cmd}",
        shell=True,
        check=True,
        executable="/bin/bash",
    )


def extract_drag(case: Path) -> float | None:
    """Take the final C_d from forceCoeffs postProcessing output."""
    # ESI >= 2206 writes coefficient.dat; older releases write forceCoeffs.dat.
    for pattern in ("forces1/*/coefficient.dat", "forces1/*/forceCoeffs.dat"):
        for p in sorted(case.glob(f"postProcessing/{pattern}")):
            for line in reversed(p.read_text().splitlines()):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                try:
                    return float(parts[1])  # time, Cd, ...
                except (IndexError, ValueError):
                    continue
    return None


def extract_cf_at_x(case: Path, target_x: float) -> float | None:
    """Read wallShearStress on the wall and compute C_f at target_x.

    The `surfaces` function object (`wallSurfaceSample`) writes
    `postProcessing/wallSurfaceSample/<t>/wallShearStress_wallSurface.raw`
    with columns  x y z  tau_x tau_y tau_z  one row per wall face.
    C_f = tau_w / (0.5 * rho * U^2) = 2 |tau_x|  (rho=1, U=1 reference).

    Linearly interpolates to target_x between the two bracketing faces.
    """
    candidates = list(case.glob(
        "postProcessing/wallSurfaceSample/*/wallShearStress_wallSurface.raw"
    ))
    if not candidates:
        # Fallback: postProcess -func sampleDict output (if the FO didn't run)
        candidates = list(case.glob(
            "postProcessing/sampleDict/*/wall_line_wallShearStress.xy"
        ))
    if not candidates:
        return None
    raw = sorted(candidates, key=lambda p: float(p.parent.name))[-1]

    pts: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            x = float(parts[0])
            # .raw: x y z tau_x ... (col index 3)
            # .xy : x tau_x ...     (col index 1)
            tau_x = float(parts[3]) if len(parts) >= 6 else float(parts[1])
        except ValueError:
            continue
        if 0.0 <= x <= 2.0:
            pts.append((x, tau_x))
    if not pts:
        return None
    pts.sort(key=lambda t: t[0])

    tau_at: float | None = None
    for i in range(len(pts) - 1):
        x0, t0 = pts[i]
        x1, t1 = pts[i + 1]
        if x0 <= target_x <= x1:
            if x1 == x0:
                tau_at = t0
            else:
                w = (target_x - x0) / (x1 - x0)
                tau_at = t0 + w * (t1 - t0)
            break
    if tau_at is None:
        nearest = min(pts, key=lambda t: abs(t[0] - target_x))
        tau_at = nearest[1]
    return abs(2.0 * tau_at)


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] simpleFoam (target 3000 iterations)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    # Post-run sampling: read wallShearStress along a wall-parallel line.
    # The wallShearStress field was written to each time dir by the FO
    # (writeFields true). `postProcess -func sets -latestTime` runs the
    # system/sampleDict on the latest converged time step.
    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    cf = extract_cf_at_x(CASE, 0.97)
    cd = extract_drag(CASE)

    out = {}
    if cf is not None:
        out["cf_x097"] = cf
    if cd is not None:
        out["drag_coefficient"] = cd

    agent_result = Path("/tmp/agent/result.json")
    agent_result.parent.mkdir(parents=True, exist_ok=True)
    agent_result.write_text(json.dumps(out, indent=2))

    # Final line to stdout is a JSON object — OpenFOAMDriver.parse_output()
    # picks it up and sim-cli stores it alongside the RunResult.
    print(json.dumps(out))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
