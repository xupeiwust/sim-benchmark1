"""Flat plate ZPG oracle - runs under `sim run --solver openfoam`.

Steady-state RANS over a 2 m flat plate with Spalart-Allmaras turbulence.
Writes a schema-conforming /tmp/agent/result.json with `file_extract`
provenance against real OpenFOAM artifacts persisted in /root/case:

  /root/case/log.blockMesh                 - mesh build log
  /root/case/log.checkMesh                 - checkMesh -allGeometry output
  /root/case/log.simpleFoam                - solver iteration log
  /root/case/log.yPlus                     - simpleFoam -postProcess -func yPlus output
  /root/case/wallShearStress.dat           - copy of wall sample (deterministic name, sorted by x)
  /root/case/forceCoeffs_final.dat         - copy of last forceCoeffs row (deterministic name)

Keywords `blockMesh` / `simpleFoam` in this comment make
OpenFOAMDriver.detect() happy if someone invokes without --solver.
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


def sh(cmd: str, check: bool = True) -> None:
    subprocess.run(
        f"source {BASHRC_PATH} && cd {CASE} && {cmd}",
        shell=True, check=check, executable="/bin/bash",
    )


def run_pipeline(extract: str, source_path: Path) -> str:
    """Re-run the verifier-style extract: cat file | bash -c '<extract>'."""
    with open(source_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    proc = subprocess.run(
        ["bash", "-c", extract],
        input=text, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def build_wallshear_dat(case: Path) -> Path:
    """Find the latest wallShearStress sample, dump (x tau_x) sorted by x.

    The case's controlDict already declares `wallSurfaceSample` (or the
    standard `surfaces` FO) which writes
    `postProcessing/wallSurfaceSample/<t>/wallShearStress_wallSurface.raw`
    with columns  x y z tau_x tau_y tau_z.

    We dump only x and tau_x, sorted by x, to a stable
    `/root/case/wallShearStress.dat` so the result.json's `extract`
    pipeline can stay simple awk over a deterministic file.
    """
    candidates = list(case.glob(
        "postProcessing/wallSurfaceSample/*/wallShearStress_wallSurface.raw"
    ))
    if not candidates:
        candidates = list(case.glob(
            "postProcessing/sampleDict/*/wall_line_wallShearStress.xy"
        ))
    if not candidates:
        raise RuntimeError("no wallShearStress sample found in postProcessing/")
    raw = sorted(candidates, key=lambda p: float(p.parent.name))[-1]

    pairs: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            x = float(parts[0])
            tau_x = float(parts[3]) if len(parts) >= 6 else float(parts[1])
        except ValueError:
            continue
        if 0.0 <= x <= 2.0:
            pairs.append((x, tau_x))
    pairs.sort(key=lambda t: t[0])

    out = case / "wallShearStress.dat"
    out.write_text(
        "# x tau_x  (sorted by x; subset 0 <= x <= 2)\n"
        + "\n".join(f"{x:.10g} {tau:.10g}" for x, tau in pairs)
        + "\n"
    )
    return out


def build_forcecoeffs_final(case: Path) -> Path:
    """Pull the last data row from postProcessing/forces1/<t>/coefficient.dat
    (or forceCoeffs.dat for older OF) into a stable single-line file."""
    for pattern in ("forces1/*/coefficient.dat", "forces1/*/forceCoeffs.dat"):
        cands = sorted(case.glob(f"postProcessing/{pattern}"))
        for p in cands:
            for line in reversed(p.read_text().splitlines()):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    float(parts[1])  # Cd valid?
                except ValueError:
                    continue
                out = case / "forceCoeffs_final.dat"
                out.write_text(line + "\n")
                return out
    raise RuntimeError("no usable row in postProcessing/forces1/*/coefficient.dat")


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1")

    print("[oracle] simpleFoam (target 3000 iterations)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    print("[oracle] simpleFoam -postProcess -func yPlus -latestTime")
    sh(
        "simpleFoam -postProcess -func yPlus -latestTime > log.yPlus 2>&1",
        check=False,
    )

    wallshear_path = build_wallshear_dat(CASE)
    forcecoeffs_path = build_forcecoeffs_final(CASE)

    log_blockmesh   = str(CASE / "log.blockMesh")
    log_checkmesh   = str(CASE / "log.checkMesh")
    log_simplefoam  = str(CASE / "log.simpleFoam")
    log_yplus       = str(CASE / "log.yPlus")

    # ---- mesh group --------------------------------------------------------
    cell_count_extract = "awk '/^[[:space:]]+cells:/ {print $NF; exit}'"
    cell_count = int(run_pipeline(cell_count_extract, CASE / "log.checkMesh"))

    nonorth_extract = "awk '/Mesh non-orthogonality Max:/ {print $4; exit}'"
    max_nonorth = float(run_pipeline(nonorth_extract, CASE / "log.checkMesh"))

    # log.yPlus typical line:
    #   patch wall y+ : min = 0.123 max = 1.456 average = 0.987
    # or with commas. Tolerate both via tr ',' ' '.
    yplus_extract = (
        "grep 'patch' "
        "| grep 'y+' "
        "| tr ',' ' ' "
        "| awk '{ for (i=1;i<=NF;i++) if ($i==\"max\") { print $(i+2); exit } }'"
    )
    y_plus_max = float(run_pipeline(yplus_extract, CASE / "log.yPlus"))

    # ---- numerical group ---------------------------------------------------
    final_resid_extract = (
        "grep 'Solving for Ux,' "
        "| tail -1 "
        "| sed 's/.*Final residual = //; s/,.*//'"
    )
    final_residual_U = float(run_pipeline(final_resid_extract, CASE / "log.simpleFoam"))

    # ---- outputs group -----------------------------------------------------
    # cf at x=0.97: linear interp tau_x at x=0.97, then cf = 2 |tau_x|.
    cf_awk = (
        'BEGIN { xt=0.97; have=0 } '
        '/^[^#]/ && NF >= 2 { '
        '  x=$1+0.0; tau=$2+0.0; '
        '  if (have && px <= xt && xt <= x) { '
        '    if (x == px) tau_at = ptau; '
        '    else tau_at = ptau + (xt - px) / (x - px) * (tau - ptau); '
        '    if (tau_at < 0) tau_at = -tau_at; '
        '    printf "%.10g\\n", 2.0 * tau_at; '
        '    exit '
        '  } '
        '  px=x; ptau=tau; have=1 '
        '}'
    )
    cf_extract = "awk '" + cf_awk + "'"
    cf_x097 = float(run_pipeline(cf_extract, wallshear_path))

    # forceCoeffs final row: "time Cd Cs Cl ..." → field 2.
    drag_extract = "awk '{print $2}'"
    drag_coefficient = float(run_pipeline(drag_extract, forcecoeffs_path))

    # ---- assemble ----------------------------------------------------------
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
        "y_plus_max": {
            "value": y_plus_max,
            "source": {
                "kind": "file_extract",
                "path": log_yplus,
                "extract": yplus_extract,
            },
        },
        "final_residual_U": {
            "value": final_residual_U,
            "source": {
                "kind": "file_extract",
                "path": log_simplefoam,
                "extract": final_resid_extract,
            },
        },
        "cf_x097": {
            "value": cf_x097,
            "source": {
                "kind": "file_extract",
                "path": str(wallshear_path),
                "extract": cf_extract,
            },
        },
        "drag_coefficient": {
            "value": drag_coefficient,
            "source": {
                "kind": "file_extract",
                "path": str(forcecoeffs_path),
                "extract": drag_extract,
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
