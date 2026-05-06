"""Lid-driven cavity Re=1000 oracle.

simpleFoam (laminar) on a finer cavity mesh than Re=100 — same shape, same
oracle structure as cases/fluids/lid_driven_cavity_re100/solution/solve_inner.py.
Writes a schema-conforming /tmp/agent/result.json with `file_extract`
provenance against real OpenFOAM artifacts persisted in /root/case.
"""
from __future__ import annotations

import json
import os
import shutil
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


def run_awk(prog: str, source_path: Path) -> str:
    with open(source_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    proc = subprocess.run(
        ["awk", prog],
        input=text, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1")

    print("[oracle] simpleFoam")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    centerline_src_candidates = sorted(
        CASE.glob("postProcessing/sampleDict/*/centerline_x0p5_U.xy"),
        key=lambda p: float(p.parent.name),
    )
    if not centerline_src_candidates:
        raise RuntimeError("postProcess did not produce centerline_x0p5_U.xy")
    centerline_src = centerline_src_candidates[-1]
    centerline_dst = CASE / "centerline_x0p5_U.xy"
    shutil.copy(centerline_src, centerline_dst)

    cell_count_extract = "awk '/^[[:space:]]+cells:/ {print $NF; exit}'"
    cell_count = int(run_awk(
        "/^[[:space:]]+cells:/ {print $NF; exit}",
        CASE / "log.checkMesh",
    ))

    nonorth_extract = "awk '/Mesh non-orthogonality Max:/ {print $4; exit}'"
    max_nonorth = float(run_awk(
        "/Mesh non-orthogonality Max:/ {print $4; exit}",
        CASE / "log.checkMesh",
    ))

    final_resid_extract = (
        "grep 'Solving for p,' "
        "| tail -1 "
        "| sed 's/.*Final residual = //; s/,.*//'"
    )
    proc = subprocess.run(
        ["bash", "-c", final_resid_extract],
        input=(CASE / "log.simpleFoam").read_text(),
        capture_output=True, text=True, check=True,
    )
    final_residual_p = float(proc.stdout.strip())

    u_centre_awk = (
        'BEGIN { yt=0.5; have=0 } '
        '/^[^#]/ && NF >= 2 { '
        '  y=$1+0.0; u=$2+0.0; '
        '  if (have && py <= yt && yt <= y) { '
        '    if (y == py) print pu; '
        '    else printf "%.10g\\n", pu + (yt - py) / (y - py) * (u - pu); '
        '    exit '
        '  } '
        '  py=y; pu=u; have=1 '
        '}'
    )
    u_centre_extract = "awk '" + u_centre_awk + "'"
    u_centerline_y0p5 = float(run_awk(u_centre_awk, centerline_dst))

    u_min_awk = (
        'BEGIN { mn=1e9 } '
        '/^[^#]/ && NF >= 2 { if ($2+0.0 < mn) mn=$2+0.0 } '
        'END { printf "%.10g\\n", mn }'
    )
    u_min_extract = "awk '" + u_min_awk + "'"
    u_min_along_x0p5 = float(run_awk(u_min_awk, centerline_dst))

    log_blockmesh   = str(CASE / "log.blockMesh")
    log_checkmesh   = str(CASE / "log.checkMesh")
    log_simplefoam  = str(CASE / "log.simpleFoam")
    centerline_path = str(centerline_dst)

    result = {
        "mesh_cell_count": {
            "value": cell_count,
            "source": {
                "kind": "file_extract",
                "path": log_checkmesh,
                "extract": cell_count_extract,
            },
        },
        "max_non_orthogonality": {
            "value": max_nonorth,
            "source": {
                "kind": "file_extract",
                "path": log_checkmesh,
                "extract": nonorth_extract,
            },
        },
        "final_residual_p": {
            "value": final_residual_p,
            "source": {
                "kind": "file_extract",
                "path": log_simplefoam,
                "extract": final_resid_extract,
            },
        },
        "u_centerline_y0p5": {
            "value": u_centerline_y0p5,
            "source": {
                "kind": "file_extract",
                "path": centerline_path,
                "extract": u_centre_extract,
            },
        },
        "u_min_along_x0p5": {
            "value": u_min_along_x0p5,
            "source": {
                "kind": "file_extract",
                "path": centerline_path,
                "extract": u_min_extract,
            },
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(json.dumps({k: v["value"] for k, v in result.items()}))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
