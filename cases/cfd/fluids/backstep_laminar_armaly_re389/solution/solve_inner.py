"""backstep_laminar_armaly_re389 oracle.

Steady LAMINAR incompressible flow over a 2D backward-facing step matching the
Armaly et al. 1983 geometry (expansion ratio 1.94, Re = 389 based on 2 x step
height and mean inlet velocity). simpleFoam with simulationType=laminar (no
turbulence model). simpleFoam writes wallShearStress / p samples on the
lower-wall-downstream patch which the oracle uses to extract
reattachment_length_xr_over_h (the primary recirculation reattachment length on
the bottom wall, normalised by step height S).

Persisted artifacts in /tmp/agent/case:
  log.blockMesh / log.checkMesh / log.simpleFoam
  reattachment.dat   - the extracted xr/S single value
  cf_wall.dat        - (x_S cf) on lower_wall_downstream, sorted by x

Keywords blockMesh / simpleFoam in this comment make
OpenFOAMDriver.detect() pick this script up if --solver is omitted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/case"))

# Reference flow conditions (must match 0/U + transportProperties + blockMeshDict).
H_STEP = 0.0049       # step height S [m]
U_REF  = 1.0          # mean inlet velocity [m/s]


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


def latest_raw(case: Path, fname: str) -> Path:
    cands = list(case.glob(f"postProcessing/wallSurfaceSample/*/{fname}"))
    if not cands:
        raise RuntimeError(f"no postProcessing/wallSurfaceSample/*/{fname} found")
    return sorted(cands, key=lambda p: float(p.parent.name))[-1]


def build_cf_dat(case: Path) -> Path:
    """Read wallShearStress samples on lower_wall_downstream and write
    `cf_wall.dat` as `<x_S> <cf>` ASCII sorted ascending by x_S.

    OF v2412 wallShearStress sign convention: tau_x is NEGATIVE for normal +x
    attached flow (n . Reff). We negate so cf > 0 means attached, cf < 0 means
    recirculating. The reattachment point is the negative->positive zero crossing
    downstream of the step.
    """
    tau_raw = latest_raw(case, "wallShearStress_wallSurface.raw")

    # tau_raw columns: x y z tau_x tau_y tau_z
    tau_pairs: list[tuple[float, float]] = []
    for line in tau_raw.read_text().splitlines():
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
        if x >= -1e-6:
            tau_pairs.append((x, tau_x))
    tau_pairs.sort(key=lambda t: t[0])

    cf_path = case / "cf_wall.dat"
    with cf_path.open("w") as f:
        f.write("# x_S cf  (cf = -2 * tau_x / U_ref^2; positive=attached, negative=recirc)\n")
        for x, tau in tau_pairs:
            cf = -2.0 * tau / (U_REF * U_REF)
            f.write(f"{x / H_STEP:.10g} {cf:.10g}\n")

    return cf_path


def find_zero_crossing_xH(cf_path: Path,
                          x_min: float = 0.5,
                          x_max: float = 30.0) -> float:
    """Reattachment xr/S: first negative-to-positive cf zero crossing past x_min.
    x_min = 0.5 skips spurious step-corner Cf flickers; canonical Armaly Re=389
    laminar reattachment is around xr/S ~ 8."""
    rows = []
    for line in cf_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    rows.sort()
    prev_x = prev_cf = None
    for x_h, cf in rows:
        if x_h < x_min or x_h > x_max:
            prev_x, prev_cf = x_h, cf
            continue
        if prev_x is not None and prev_cf < 0 and cf >= 0:
            if cf == prev_cf:
                return x_h
            return prev_x + (0 - prev_cf) / (cf - prev_cf) * (x_h - prev_x)
        prev_x, prev_cf = x_h, cf
    raise RuntimeError("no zero crossing of cf found in cf_wall.dat within x_min..x_max")


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1", check=False)

    print("[oracle] simpleFoam (laminar, target endTime=3000)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    cf_path = build_cf_dat(CASE)
    xr_over_h = find_zero_crossing_xH(cf_path)

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

    # ---- outputs group: reattachment ---------------------------------------
    # Rebuild a deterministic single-value file the verifier extracts so the
    # source.path is stable.
    reatt_path = CASE / "reattachment.dat"
    reatt_path.write_text(
        f"# reattachment_length_xr_over_h (zero-Cf interpolation on lower_wall_downstream)\n"
        f"{xr_over_h:.6f}\n"
    )
    reatt_extract = "awk '!/^#/ {print $1; exit}'"
    reatt_value = float(run_pipeline(reatt_extract, reatt_path))

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
        "reattachment_length_xr_over_h": {
            "value": reatt_value,
            "source": {
                "kind": "file_extract",
                "path": str(reatt_path),
                "extract": reatt_extract,
            },
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
