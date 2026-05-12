"""naca0012_subsonic oracle - alpha sweep.

Builds the airfoil OBJ, runs blockMesh + snappyHexMesh once, then for
each alpha in {0, 4, 8, 10, 12} deg, copies polyMesh + 0 fields into a
sub-case `alpha_<N>` with rotated freestream + rotated forceCoeffs
liftDir/dragDir, runs simpleFoam, and reads cl/cd. Final result.json
covers cell count + alpha=8 residual + per-alpha CL/CD + linear-
regression CL_alpha slope.

Keywords blockMesh / snappyHexMesh / simpleFoam in this comment make
OpenFOAMDriver.detect() pick this up if --solver is omitted.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/root/case"))

U_REF = 30.0          # arbitrary; coefficients are non-dimensional
ALPHAS = [0, 4, 8, 10, 12]


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


def sh(cmd: str, cwd: Path | None = None, check: bool = True) -> None:
    cwd_path = str(cwd) if cwd else str(CASE)
    subprocess.run(
        f"source {BASHRC_PATH} && cd {cwd_path} && {cmd}",
        shell=True, check=check, executable="/bin/bash",
    )


def run_pipeline(extract: str, source_path: Path) -> str:
    with open(source_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    proc = subprocess.run(
        ["bash", "-c", extract],
        input=text, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


U_FILE_TEMPLATE = """/*--------------------------------*- C++ -*----------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}

dimensions [0 1 -1 0 0 0 0];

internalField uniform ({Ux} {Uy} 0);

boundaryField
{{
    inlet
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux} {Uy} 0);
        value           uniform ({Ux} {Uy} 0);
    }}
    outlet
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux} {Uy} 0);
        value           uniform ({Ux} {Uy} 0);
    }}
    top
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux} {Uy} 0);
        value           uniform ({Ux} {Uy} 0);
    }}
    bottom
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux} {Uy} 0);
        value           uniform ({Ux} {Uy} 0);
    }}
    airfoil
    {{
        type            noSlip;
    }}
    frontAndBack
    {{
        type            slip;
    }}
}}
"""

CONTROLDICT_TEMPLATE = """/*--------------------------------*- C++ -*----------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}

application     simpleFoam;

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         {endTime};

deltaT          1;

writeControl    timeStep;
writeInterval   {writeInterval};

purgeWrite      2;

writeFormat     ascii;
writePrecision  8;
writeCompression off;

timeFormat      general;
timePrecision   6;

runTimeModifiable true;

functions
{{
    forces1
    {{
        type            forceCoeffs;
        libs            (forces);
        writeControl    timeStep;
        writeInterval   100;

        patches         (airfoil);
        rho             rhoInf;
        rhoInf          1.225;
        CofR            (0.25 0 0);
        liftDir         ({lift_x} {lift_y} 0);
        dragDir         ({drag_x} {drag_y} 0);
        pitchAxis       (0 0 1);
        magUInf         {U_ref};
        lRef            1.0;
        Aref            0.5;       // chord * span (0.5 m thick slab)
    }}
}}
"""


def write_alpha_files(alpha_deg: float, alpha_dir: Path) -> None:
    a = math.radians(alpha_deg)
    Ux = U_REF * math.cos(a)
    Uy = U_REF * math.sin(a)
    drag_x, drag_y = math.cos(a), math.sin(a)
    lift_x, lift_y = -math.sin(a), math.cos(a)
    (alpha_dir / "0" / "U").write_text(U_FILE_TEMPLATE.format(Ux=Ux, Uy=Uy))
    (alpha_dir / "system" / "controlDict").write_text(
        CONTROLDICT_TEMPLATE.format(
            endTime=1500,
            writeInterval=500,
            lift_x=lift_x, lift_y=lift_y,
            drag_x=drag_x, drag_y=drag_y,
            U_ref=U_REF,
        )
    )


def build_forcecoeffs_final(alpha_dir: Path) -> Path:
    for pattern in ("forces1/*/coefficient.dat", "forces1/*/forceCoeffs.dat"):
        cands = sorted(alpha_dir.glob(f"postProcessing/{pattern}"))
        for p in cands:
            for line in reversed(p.read_text().splitlines()):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    float(parts[1])
                except ValueError:
                    continue
                out = alpha_dir / "forceCoeffs_final.dat"
                out.write_text(line + "\n")
                return out
    raise RuntimeError(f"no usable row under {alpha_dir}/postProcessing/forces1/")


def main() -> int:
    t0 = time.time()

    print("[oracle] gen_airfoil_stl")
    sh("mkdir -p constant/triSurface && python3 gen_airfoil_stl.py constant/triSurface/airfoil.obj > log.gen_airfoil 2>&1")

    # Mesh once in CASE root.
    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] snappyHexMesh -overwrite")
    sh("snappyHexMesh -overwrite > log.snappyHexMesh 2>&1", check=False)
    sh("cp -f log.snappyHexMesh /logs/agent/log.snappyHexMesh 2>/dev/null || true", check=False)

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1", check=False)

    # No createPatch needed; frontAndBack stays as `patch` (slip BC in 0/).

    log_checkmesh = str(CASE / "log.checkMesh")
    cell_count_extract = "awk '/^[[:space:]]+cells:/ {print $NF; exit}'"
    cell_count = int(run_pipeline(cell_count_extract, CASE / "log.checkMesh"))

    cl_table: dict[int, float] = {}
    cd_table: dict[int, float] = {}
    forcecoeffs_paths: dict[int, Path] = {}

    final_residual_U = None

    for alpha in ALPHAS:
        alpha_dir = CASE / f"alpha_{alpha}"
        if alpha_dir.exists():
            shutil.rmtree(alpha_dir)
        alpha_dir.mkdir(parents=True)
        # Copy mesh + base 0 + constant + system
        for sub in ("constant", "system", "0"):
            shutil.copytree(CASE / sub, alpha_dir / sub)
        # Override U + controlDict for this alpha
        write_alpha_files(alpha, alpha_dir)

        print(f"[oracle] simpleFoam alpha={alpha}")
        sh(
            "simpleFoam > log.simpleFoam 2>&1",
            cwd=alpha_dir, check=False,
        )

        fpath = build_forcecoeffs_final(alpha_dir)
        forcecoeffs_paths[alpha] = fpath
        last = fpath.read_text().strip().split()
        cd_table[alpha] = float(last[1])
        cl_table[alpha] = float(last[4])
        print(f"  alpha={alpha}: cd={cd_table[alpha]:.4f} cl={cl_table[alpha]:.4f}")

        if alpha == 8:
            log_simplefoam = alpha_dir / "log.simpleFoam"
            final_resid_extract = (
                "grep 'Solving for Ux,' "
                "| tail -1 "
                "| sed 's/.*Final residual = //; s/,.*//'"
            )
            final_residual_U = float(run_pipeline(final_resid_extract, log_simplefoam))

    # CL_alpha slope on alpha = {0, 4, 8} via linear regression.
    xs = [0.0, 4.0, 8.0]
    ys = [cl_table[0], cl_table[4], cl_table[8]]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / den if den else 0.0

    cl_table_path = CASE / "CL_alpha_table.dat"
    cl_table_path.write_text(
        "# alpha_deg  CL  CD\n" + "\n".join(
            f"{a:g} {cl_table[a]:.6f} {cd_table[a]:.6f}" for a in ALPHAS
        ) + "\n"
    )

    cl_extract = "awk 'END {print $5}'"
    cd_extract = "awk 'END {print $2}'"
    slope_extract = (
        "awk 'NR==1 {a0=$1; CL0=$2} NR==3 {a8=$1; CL8=$2} "
        "END {printf \"%.6f\\n\", (CL8-CL0)/(a8-a0)}'"
    )
    # Slope path - rewrite a tabular version for awk that uses NR==1 NR==3:
    slope_table_path = CASE / "CL_alpha_slope_input.dat"
    slope_table_path.write_text(
        f"0 {cl_table[0]:.6f}\n"
        f"4 {cl_table[4]:.6f}\n"
        f"8 {cl_table[8]:.6f}\n"
    )

    log_alpha8_simplefoam = str(CASE / "alpha_8" / "log.simpleFoam")
    final_resid_extract = (
        "grep 'Solving for Ux,' "
        "| tail -1 "
        "| sed 's/.*Final residual = //; s/,.*//'"
    )

    result = {
        "mesh_cell_count": {
            "value": cell_count,
            "source": {"kind": "file_extract", "path": log_checkmesh, "extract": cell_count_extract},
        },
        "final_residual_U": {
            "value": final_residual_U,
            "source": {"kind": "file_extract", "path": log_alpha8_simplefoam, "extract": final_resid_extract},
        },
        "CL_at_alpha_4": {
            "value": cl_table[4],
            "source": {"kind": "file_extract", "path": str(forcecoeffs_paths[4]), "extract": cl_extract},
        },
        "CL_at_alpha_10": {
            "value": cl_table[10],
            "source": {"kind": "file_extract", "path": str(forcecoeffs_paths[10]), "extract": cl_extract},
        },
        "CL_at_alpha_12": {
            "value": cl_table[12],
            "source": {"kind": "file_extract", "path": str(forcecoeffs_paths[12]), "extract": cl_extract},
        },
        "CD_at_alpha_4": {
            "value": cd_table[4],
            "source": {"kind": "file_extract", "path": str(forcecoeffs_paths[4]), "extract": cd_extract},
        },
        "CD_at_alpha_10": {
            "value": cd_table[10],
            "source": {"kind": "file_extract", "path": str(forcecoeffs_paths[10]), "extract": cd_extract},
        },
        "CL_alpha_slope_per_deg": {
            "value": slope,
            "source": {"kind": "file_extract", "path": str(slope_table_path), "extract": slope_extract},
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(json.dumps({k: v["value"] for k, v in result.items()}, indent=2))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
