"""backstep_driver_seegmiller_turbulent oracle - runs under `sim run --solver openfoam`.

Steady RANS over a 2D backward-facing step matching Driver & Seegmiller 1985
(M=0.128, Re_H=36000, expansion ratio 1.125, H=0.0127 m). kOmegaSST + wall functions.
simpleFoam writes wallShearStress / p samples on the lower-wall-downstream patch
which the verifier uses to extract reattachment_length_xH, cp_min_in_recirculation
and cf_recovery_at_xH_20.

Persisted artifacts in /root/case:
  log.blockMesh / log.checkMesh / log.simpleFoam
  reattachment.dat   - (x_H cf) on lower-wall-downstream, sorted by x
  cp_wall.dat        - (x_H cp) on lower-wall-downstream
  cf_wall.dat        - (x_H cf) on lower-wall-downstream

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

CASE = Path(os.environ.get("ORACLE_CASE", "/root/case"))

# Reference flow conditions (must match 0/U + transportProperties).
H_STEP = 0.0127       # step height [m]
U_REF  = 44.2         # ref velocity [m/s]
RHO    = 1.0          # incompressible reference density (p in m^2/s^2)
Q_REF  = 0.5 * RHO * U_REF * U_REF  # = 976.82 m^2/s^2; for Cp = (p - p_ref) / Q_REF


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


def build_wall_dats(case: Path) -> tuple[Path, Path]:
    """Read the wallShearStress + p samples on lower_wall_downstream and
    write `cf_wall.dat` and `cp_wall.dat`, both as `<x_H> <value>` ASCII
    sorted ascending by x_H.

    Reference shift convention: Cp = (p(x) - p(x_H=40)) / (0.5 rho U^2).
    Pick the last sample on the patch closest to x_H = 40 as p_ref;
    the patch ends at x_H = 50 so that interpolation is well-defined.
    """
    tau_raw = latest_raw(case, "wallShearStress_wallSurface.raw")
    p_raw   = latest_raw(case, "p_wallSurface.raw")

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
        # only the floor patch (y = -H) - lower_wall_downstream
        if x >= -1e-6:
            tau_pairs.append((x, tau_x))
    tau_pairs.sort(key=lambda t: t[0])

    cf_path = case / "cf_wall.dat"
    with cf_path.open("w") as f:
        # OF v2412 wallShearStress sign: tau_x is negative for normal +x attached
        # flow. Negate so cf > 0 means attached, cf < 0 means recirc.
        f.write("# x_H cf  (cf = -2 * tau_x / U_ref^2; positive=attached, negative=recirc)\n")
        for x, tau in tau_pairs:
            cf = -2.0 * tau / (U_REF * U_REF)
            f.write(f"{x / H_STEP:.10g} {cf:.10g}\n")

    # p_raw columns: x y z p
    p_pairs: list[tuple[float, float]] = []
    for line in p_raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            x = float(parts[0])
            p_val = float(parts[3])
        except ValueError:
            continue
        if x >= -1e-6:
            p_pairs.append((x, p_val))
    p_pairs.sort(key=lambda t: t[0])

    # p_ref = mean p over x_H in [38, 42]: matches the Driver-Seegmiller
    # convention "Cp = 0 at x/H ~ 40".
    refs = [p for x, p in p_pairs
            if 38.0 * H_STEP <= x <= 42.0 * H_STEP]
    if not refs:
        # fallback: last point
        refs = [p_pairs[-1][1]]
    p_ref = sum(refs) / len(refs)

    cp_path = case / "cp_wall.dat"
    with cp_path.open("w") as f:
        f.write(f"# x_H cp  (cp = (p - p_ref) / (0.5 rho U^2);"
                f" p_ref={p_ref:.6f}, Q_REF={Q_REF:.6f})\n")
        for x, p_val in p_pairs:
            cp = (p_val - p_ref) / Q_REF
            f.write(f"{x / H_STEP:.10g} {cp:.10g}\n")

    return cf_path, cp_path


def find_zero_crossing_xH(cf_path: Path,
                          x_min: float = 2.0,
                          x_max: float = 15.0) -> float:
    """Reattachment x_H: first negative-to-positive cf zero crossing past x_min.
    x_min = 2.0 skips spurious step-corner Cf flickers; canonical Driver-Seegmiller
    reattachment is around x_H = 6."""
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

    print("[oracle] simpleFoam (target endTime=5000)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    cf_path, cp_path = build_wall_dats(CASE)
    x_reattach = find_zero_crossing_xH(cf_path)

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

    # ---- outputs group: reattachment, cp_min, cf_recovery ------------------
    # Reattachment: keep computed value; rebuild a deterministic single-value
    # file the verifier extracts so the source.path is stable.
    reatt_path = CASE / "reattachment.dat"
    reatt_path.write_text(
        f"# reattachment_length_xH (zero-Cf interpolation on lower_wall_downstream)\n"
        f"{x_reattach:.6f}\n"
    )
    reatt_extract = "awk '!/^#/ {print $1; exit}'"
    reatt_value = float(run_pipeline(reatt_extract, reatt_path))

    # cp_min over 0 <= x_H <= 6
    cpmin_extract = (
        "awk 'BEGIN{m=1e30} !/^#/ && $1>=0 && $1<=6 { if ($2<m) m=$2 } "
        "END {print m}'"
    )
    cp_min = float(run_pipeline(cpmin_extract, cp_path))

    # cf at x_H ~ 20 - mean over [19.8, 20.2]
    cf20_extract = (
        "awk 'BEGIN{n=0; s=0} !/^#/ && $1>=19.8 && $1<=20.2 "
        "{ s+=$2; n++ } END { if (n) printf \"%.10g\\n\", s/n }'"
    )
    cf_recovery = float(run_pipeline(cf20_extract, cf_path))

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
        "reattachment_length_xH": {
            "value": reatt_value,
            "source": {
                "kind": "file_extract",
                "path": str(reatt_path),
                "extract": reatt_extract,
            },
        },
        "cp_min_in_recirculation": {
            "value": cp_min,
            "source": {
                "kind": "file_extract",
                "path": str(cp_path),
                "extract": cpmin_extract,
            },
        },
        "cf_recovery_at_xH_20": {
            "value": cf_recovery,
            "source": {
                "kind": "file_extract",
                "path": str(cf_path),
                "extract": cf20_extract,
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
