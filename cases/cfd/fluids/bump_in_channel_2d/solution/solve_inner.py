"""bump_in_channel_2d oracle.

Steady RANS over a NASA TMR 2D smooth bump in a channel at M=0.2,
Re_Lref=3e6 (incompressible approximation), kOmegaSST, simpleFoam.

Writes a schema-conforming /tmp/agent/result.json with file_extract
provenance against artifacts persisted in /tmp/agent/case:

  /tmp/agent/case/log.blockMesh
  /tmp/agent/case/log.checkMesh
  /tmp/agent/case/log.simpleFoam
  /tmp/agent/case/log.yPlus
  /tmp/agent/case/wallShearStress.dat       - x, tau_x sorted by x (bump region)
  /tmp/agent/case/forceCoeffs_final.dat     - last forceCoeffs row, single line

Keywords blockMesh / simpleFoam in this comment make
OpenFOAMDriver.detect() pick this script up if --solver is omitted.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/case"))


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
    with open(source_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    proc = subprocess.run(
        ["bash", "-c", extract],
        input=text, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def build_wallshear_dat(case: Path) -> Path:
    """Latest wallShearStress sample, dumped as (x tau_x) sorted by x.

    The wallSurfaceSample functionObject writes
    `postProcessing/wallSurfaceSample/<t>/wallShearStress_wallSurface.raw`
    with columns (x y z tau_x tau_y tau_z). We dump x, tau_x for x in
    the bump region (0..1.5) so the verifier extracts stay simple.
    """
    candidates = list(case.glob(
        "postProcessing/wallSurfaceSample/*/wallShearStress_wallSurface.raw"
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
            tau_x = float(parts[3])
        except ValueError:
            continue
        if 0.0 <= x <= 1.5:
            pairs.append((x, tau_x))
    pairs.sort(key=lambda t: t[0])

    out = case / "wallShearStress.dat"
    out.write_text(
        "# x tau_x  (sorted by x; subset 0 <= x <= 1.5 = bump region)\n"
        + "\n".join(f"{x:.10g} {tau:.10g}" for x, tau in pairs)
        + "\n"
    )
    return out


def build_forcecoeffs_final(case: Path) -> Path:
    """Last data row from postProcessing/forces1/<t>/coefficient.dat."""
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
                    float(parts[1])
                except ValueError:
                    continue
                out = case / "forceCoeffs_final.dat"
                out.write_text(line + "\n")
                return out
    raise RuntimeError("no usable row in postProcessing/forces1/*/coefficient.dat")


def find_forces_pressure_viscous(case: Path) -> tuple[float, float]:
    """Parse the LAST `forceCoeffs forces1 write:` block from log.simpleFoam
    and return (Cd_pressure, Cd_viscous).

    OF v2412 prints the breakdown in the solver log every writeInterval:
        forceCoeffs forces1 write:
            Coefficient    Total       Pressure        Viscous     Internal
            Cd:    0.00229    0.000272    0.00202    0
            Cd(f): ...
            ...
    The columns in coefficient.dat itself are (Cd, Cd(f), Cd(r), ...) - no
    pressure/viscous breakdown - so the log is the only file source.
    """
    log = case / "log.simpleFoam"
    if not log.is_file():
        raise RuntimeError(f"{log} not found")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    # Find the LAST 'forceCoeffs forces1 write:' marker
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "forceCoeffs forces1 write:" in lines[i]:
            start_idx = i
            break
    if start_idx is None:
        raise RuntimeError("no 'forceCoeffs forces1 write:' block in log.simpleFoam")
    # The 'Cd:' row appears within ~3 lines after the marker.
    for j in range(start_idx, min(start_idx + 10, len(lines))):
        line = lines[j].strip()
        if line.startswith("Cd:"):
            parts = line.split()
            # parts: ['Cd:', total, pressure, viscous, internal]
            if len(parts) < 4:
                raise RuntimeError(f"malformed Cd: row: {line!r}")
            return float(parts[2]), float(parts[3])
    raise RuntimeError("no 'Cd:' row found after forceCoeffs marker")


def write_cd_breakdown_log_excerpt(case: Path, cd_p: float, cd_v: float) -> Path:
    """Emit a minimal deterministic file the verifier's awk extract can hit.

    Mirrors flatplate_zpg_subsonic's pattern of stable filenames so the
    file_extract source.path stays free of glob / time-stamp dependencies.
    """
    out = case / "cd_breakdown.dat"
    out.write_text(
        "# cd_pressure  cd_viscous  (parsed from log.simpleFoam forceCoeffs block)\n"
        f"{cd_p:.10g} {cd_v:.10g}\n"
    )
    return out


def main() -> int:
    t0 = time.time()

    # No blockMesh here. solve.sh has already put NASA's official 177x81 grid
    # in constant/polyMesh, and blockMesh would silently overwrite it with the
    # self-built mesh this case used before it was rebuilt on the official
    # grid -- which is exactly what happened once: the ground truth moved to
    # the published CFL3D/FUN3D values while the oracle stayed on the old
    # 49400-cell mesh, and the case scored 0 against its own reference.
    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1")

    print("[oracle] simpleFoam (target 5000 iterations)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1", check=False)

    print("[oracle] simpleFoam -postProcess -func yPlus -latestTime")
    sh(
        "simpleFoam -postProcess -func yPlus -latestTime > log.yPlus 2>&1",
        check=False,
    )

    wallshear_path = build_wallshear_dat(CASE)
    forcecoeffs_path = build_forcecoeffs_final(CASE)
    cd_pressure, cd_viscous = find_forces_pressure_viscous(CASE)

    log_checkmesh   = str(CASE / "log.checkMesh")
    log_simplefoam  = str(CASE / "log.simpleFoam")

    # ---- mesh group --------------------------------------------------------
    cell_count_extract = "awk '/^[[:space:]]+cells:/ {print $NF; exit}'"
    cell_count = int(run_pipeline(cell_count_extract, CASE / "log.checkMesh"))

    # ---- numerical group ---------------------------------------------------
    final_resid_extract = (
        "grep 'Solving for Ux,' "
        "| tail -1 "
        "| sed 's/.*Final residual = //; s/,.*//'"
    )
    final_residual_U = float(run_pipeline(final_resid_extract, CASE / "log.simpleFoam"))

    # ---- outputs group: cd_total -------------------------------------------
    cd_total_extract = "awk '{print $2}'"
    cd_total = float(run_pipeline(cd_total_extract, forcecoeffs_path))

    # ---- pressure / viscous breakdown stored as a deterministic file -------
    cd_breakdown_path = write_cd_breakdown_log_excerpt(CASE, cd_pressure, cd_viscous)
    cd_pressure_extract = "awk '/^[^#]/ {print $1; exit}'"
    cd_viscous_extract  = "awk '/^[^#]/ {print $2; exit}'"

    # ---- Cf at three stations: linear interp tau_x then 2*|tau_x|/U^2 ------
    def cf_awk(xt: float) -> str:
        return (
            f'BEGIN {{ xt={xt}; have=0 }} '
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
    cf63_extract = "awk '" + cf_awk(0.63) + "'"
    cf75_extract = "awk '" + cf_awk(0.75) + "'"
    cf87_extract = "awk '" + cf_awk(0.87) + "'"
    cf63 = float(run_pipeline(cf63_extract, wallshear_path))
    cf75 = float(run_pipeline(cf75_extract, wallshear_path))
    cf87 = float(run_pipeline(cf87_extract, wallshear_path))

    result = {
        "mesh_cell_count": {
            "value": cell_count,
            "source": {
                "kind": "file_extract",
                "path": log_checkmesh,
                "extract": cell_count_extract,
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
        "cd_total": {
            "value": cd_total,
            "source": {
                "kind": "file_extract",
                "path": str(forcecoeffs_path),
                "extract": cd_total_extract,
            },
        },
        "cd_pressure": {
            "value": cd_pressure,
            "source": {
                "kind": "file_extract",
                "path": str(cd_breakdown_path),
                "extract": cd_pressure_extract,
            },
        },
        "cd_viscous": {
            "value": cd_viscous,
            "source": {
                "kind": "file_extract",
                "path": str(cd_breakdown_path),
                "extract": cd_viscous_extract,
            },
        },
        "cf_at_x_063": {
            "value": cf63,
            "source": {
                "kind": "file_extract",
                "path": str(wallshear_path),
                "extract": cf63_extract,
            },
        },
        "cf_at_x_075": {
            "value": cf75,
            "source": {
                "kind": "file_extract",
                "path": str(wallshear_path),
                "extract": cf75_extract,
            },
        },
        "cf_at_x_087": {
            "value": cf87,
            "source": {
                "kind": "file_extract",
                "path": str(wallshear_path),
                "extract": cf87_extract,
            },
        },
    }

    sub = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "results.csv").write_text(
        "cd_total\n" + f"{result["cd_total"]["value"]:.9g}\n", encoding="utf-8")
    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(json.dumps({k: v["value"] for k, v in result.items()}, indent=2))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
