"""de_vahl_davis_natural_convection_ra1e4 oracle.

Steady-state LAMINAR buoyancy-driven flow in a 2D differentially-heated SQUARE
cavity (de Vahl Davis 1983 benchmark), non-dimensional Boussinesq setup:

    Ra = g*beta*dT*L^3 / (nu*alpha) = 1e4 ,  Pr = nu/alpha = 0.71
    L = 1, dT = T_hot - T_cold = 1 - 0 = 1, g*beta = 1
      => nu*alpha = 1/Ra = 1e-4
         nu    = sqrt(Pr * 1e-4) = 8.4261498e-3
         alpha = nu / Pr         = 1.1868521e-2

Solver: buoyantBoussinesqSimpleFoam (ESI v2412), simulationType=laminar.

KPI:
  nu_avg_hot_wall = average Nusselt number on the hot wall (x=0). De Vahl
  Davis (1983), Table V, gives the benchmark value 2.243 at Ra=1e4. This is a
  PUBLISHED reference quantity, NOT this solver's own output; the oracle
  reproduces it within the calibrated tolerance.

  Nu is computed from OpenFOAM's wallHeatFlux function object, which writes the
  patch-integrated KINEMATIC heat flow Q = integral(alphaEff * dT/dn) dA over
  the hot wall. The average Nusselt number is

      Nu_avg = Q / (alpha * (dT / L) * A)

  with alpha = nu/Pr = 1.1868521e-2, dT = 1, L = 1, A = hot-wall area = 1*0.1
  (the unit-square wall is one cell (z=0.1) thick). alpha and A are known
  exactly from the case definition, so Nu reduces to a deterministic scaling
  of the solver's integrated wall flux.

Persisted artifacts in /tmp/agent/case (anti-cheat openfoam detector reads the
polyMesh + non-zero time dir; these logs are auxiliary):
  log.blockMesh                 - mesh build log
  log.checkMesh                 - checkMesh -allGeometry output
  log.buoyantBoussinesqSimpleFoam - solver iteration log
  log.wallHeatFlux              - postProcess wallHeatFlux log
  nu_avg.txt                    - single line: the average hot-wall Nusselt number

Keywords `blockMesh` / `buoyantBoussinesqSimpleFoam` in this comment make
OpenFOAMDriver.detect() happy if someone invokes without --solver.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/case"))

# Case-definition constants (see transportProperties / blockMeshDict).
NU = 8.4261498e-3
PR = 0.71
ALPHA = NU / PR            # 1.1868521e-2
DT = 1.0                   # T_hot - T_cold
L = 1.0                    # cavity side
AREA = 1.0 * 0.1           # hot-wall area: unit height * z-thickness (0.1)


def discover_openfoam_bashrc() -> str:
    """Locate OpenFOAM's etc/bashrc without depending on any launcher.

    Prefers an already-sourced environment, then the usual install roots. This
    is a path lookup, not a solve step: nothing about the case depends on how
    OpenFOAM was found.
    """
    candidates = []
    env_root = os.environ.get("WM_PROJECT_DIR")
    if env_root:
        candidates.append(Path(env_root) / "etc" / "bashrc")
    for root in ("/usr/lib/openfoam", "/opt", "/usr/share"):
        candidates += sorted(Path(root).glob("openfoam*/etc/bashrc"))
        candidates += sorted(Path(root).glob("OpenFOAM*/etc/bashrc"))
    for c in candidates:
        if c.is_file():
            return str(c)
    raise RuntimeError("could not locate OpenFOAM etc/bashrc")


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


def hot_wall_gradT_integral(case: Path) -> float:
    """Parse the surfaceFieldValue log for the hot-wall integral of dT/dx.

    The incompressible buoyantBoussinesqSimpleFoam solver cannot use the
    wallHeatFlux function object (it needs a compressible turbulence model in
    the registry). Instead we post-process `grad(T)` and areaIntegrate its
    x-component over the hotWall patch with surfaceFieldValue, which logs:

        areaIntegrate(hotWall) of grad(T) = (gx gy gz)

    We read gx = integral( dT/dx ) over the hot wall [K*m^2]. The average
    Nusselt number is then

        Nu_avg = -L / (dT * A) * gx

    (minus sign: on the hot wall x=0 the temperature decreases into the cavity,
    dT/dx < 0, so Nu > 0). alpha cancels exactly against the conduction
    reference, so Nu is a pure temperature-gradient quantity.
    """
    log = case / "log.gradTwall"
    text = log.read_text(errors="replace")

    gx = None
    for line in text.splitlines():
        # surfaceFieldValue prints e.g.:
        #   areaIntegrate(hotWall) of grad(T) = (-0.224 1.3e-09 0)
        if "areaIntegrate" in line and "grad(T)" in line and "=" in line:
            rhs = line.split("=", 1)[1]
            nums = re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", rhs)
            if len(nums) >= 1:
                gx = float(nums[0])
    if gx is None:
        raise RuntimeError("could not parse areaIntegrate grad(T) from log.gradTwall")
    return gx


def normalise_line_endings(case: Path) -> None:
    """Strip CR bytes from every OpenFOAM dictionary in the case.

    The case is tarred from a Windows working copy and shipped to the Linux
    runner; the tar pipeline can re-introduce CRLF into the extension-less
    OpenFOAM dicts (the validate script only de-CRLFs *.sh). OpenFOAM's
    tokenizer then mis-parses, so blockMesh dies before meshing. Normalise in
    place - cheap and idempotent on already-LF files.
    """
    for sub in ("system", "constant", "0"):
        d = case / sub
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            raw = f.read_bytes()
            if b"\r" in raw:
                f.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def main() -> int:
    t0 = time.time()

    normalise_line_endings(CASE)

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1", check=False)

    print("[oracle] buoyantBoussinesqSimpleFoam (laminar, Boussinesq, endTime=3000)")
    sh("buoyantBoussinesqSimpleFoam > log.buoyantBoussinesqSimpleFoam 2>&1")

    print("[oracle] postProcess -func 'grad(T)' -latestTime")
    sh("postProcess -func 'grad(T)' -latestTime > log.gradT 2>&1")

    # Area-integrate the x-component of grad(T) over the hot wall (x=0). The
    # surfaceFieldValue config integrates the grad(T) vector; we read its
    # x-component from the log.
    sfv = (
        "surfaceFieldValue with "
        "type=surfaceFieldValue "
        "regionType=patch name=hotWall "
        "operation=areaIntegrate fields='(grad(T))' writeFields=false"
    )
    _ = sfv  # documentation only; the actual dict is written below
    sfv_dict = CASE / "system" / "gradTwall"
    sfv_dict.write_text(
        "type            surfaceFieldValue;\n"
        "libs            (fieldFunctionObjects);\n"
        "regionType      patch;\n"
        "name            hotWall;\n"
        "operation       areaIntegrate;\n"
        "writeFields     false;\n"
        "writeArea       false;\n"
        "fields          ( grad(T) );\n"
    )
    print("[oracle] postProcess -func gradTwall -latestTime (areaIntegrate grad(T) on hotWall)")
    sh("postProcess -func gradTwall -latestTime > log.gradTwall 2>&1")

    # Nu_avg = -L / (dT * A) * integral( dT/dx ) over the hot wall.
    gx_integral = hot_wall_gradT_integral(CASE)
    nu_avg = -L / (DT * AREA) * gx_integral

    # Persist a clean single-number file the result.json extract reads. Round
    # to 3 decimals so the rounded result.json value EXACTLY matches nu_avg.txt.
    nu_rounded = round(nu_avg, 3)
    nu_path = CASE / "nu_avg.txt"
    nu_path.write_text(f"{nu_rounded}\n")

    # Deterministic extract over the single-number file. NOTE: the verifier's
    # source sandbox splits the extract on "|" to find pipe stages, so an awk
    # "||" operator would be shattered (No closing quotation). Use a single
    # guarded rule with bare `print`, no "|" inside awk, no printf.
    nu_awk = (
        'BEGIN { have=0 } '
        '/^[^#]/ && NF >= 1 { '
        '  v=$1+0.0; '
        '  if (have==0) { val=v; have=1 } '
        '} '
        'END { if (have) print val }'
    )
    nu_extract = "awk '" + nu_awk + "'"
    nu_check = float(run_pipeline(nu_extract, nu_path))

    result = {
        "nu_avg_hot_wall": {
            "value": nu_check,
            "source": {
                "kind": "file_extract",
                "path": str(nu_path),
                "extract": nu_extract,
            },
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(json.dumps({k: v["value"] for k, v in result.items()}))
    print(f"[oracle] Nu_avg(hot wall) = {nu_rounded}  (raw {nu_avg:.5f})", file=sys.stderr)
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
