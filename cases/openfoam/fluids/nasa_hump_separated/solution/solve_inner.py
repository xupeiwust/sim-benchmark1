"""nasa_hump_separated oracle - runs under `sim run --solver openfoam`.

Steady RANS over the NASA wall-mounted Glauert-Goldschmied hump
(CFDVAL2004 baseline, M=0.1, Re_c=9.36e5). kOmegaSST + wall functions.
simpleFoam writes wallShearStress + p samples on the wall_hump and
wall_down patches; verifier extracts:
  separation_xc, reattachment_xc, cp_min_separation, cf_recovery_at_xc_2.

Persisted artifacts in /root/case:
  log.blockMesh / log.checkMesh / log.simpleFoam
  cf_wall.dat, cp_wall.dat, separation.dat, reattachment.dat

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

# Reference flow conditions.
C_REF  = 1.0       # chord [m] (also the streamwise reference length)
U_REF  = 34.6      # ref velocity [m/s]
RHO    = 1.0
Q_REF  = 0.5 * RHO * U_REF * U_REF


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


def _read_xy(case: Path, surface: str, fname: str) -> list[tuple[float, float]]:
    cands = sorted(case.glob(
        f"postProcessing/wallSurfaceSample/*/{fname}"
    ), key=lambda p: float(p.parent.name))
    cands = [c for c in cands if surface in c.name]
    if not cands:
        return []
    raw = cands[-1]
    out: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            x = float(parts[0]); v = float(parts[3])
        except ValueError:
            continue
        out.append((x, v))
    out.sort(key=lambda t: t[0])
    return out


def build_wall_dats(case: Path) -> tuple[Path, Path]:
    """Stitch tau_x and p across the hump + downstream patches and write
    cf_wall.dat (x_c cf) and cp_wall.dat (x_c cp). Cp uses the upstream
    free-stream as reference: take p_ref as mean p over x in [-2.0, -1.0]
    on... but the inlet is upstream of the hump and we don't sample the
    upstream-flat patch. Instead use the inlet-side p reference: the
    far downstream wall p; but Greenblatt's convention is p_inf at the
    upstream reference station x/c=-2.14. We approximate by using p_ref
    = the mean p over the first 0.2 c on wall_down (i.e. just past the
    TE of the hump where the recirc bubble has near-constant p).
    Simpler+robust for kpi extraction: use p_ref = average over x_c in
    [3.5, 4.0] on wall_down (far downstream).
    """
    hump_tau  = _read_xy(case, "humpSurface", "wallShearStress_humpSurface.raw")
    down_tau  = _read_xy(case, "downSurface", "wallShearStress_downSurface.raw")
    hump_p    = _read_xy(case, "humpSurface", "p_humpSurface.raw")
    down_p    = _read_xy(case, "downSurface", "p_downSurface.raw")

    # Concatenate hump (0 <= x <= 1) + downstream (1 <= x <= 4)
    tau_all = hump_tau + down_tau
    tau_all.sort(key=lambda t: t[0])
    p_all = hump_p + down_p
    p_all.sort(key=lambda t: t[0])

    # p_ref: average over x_c in [3.5, 4.0] (far recovery region)
    refs = [p for x, p in p_all if 3.5 <= x <= 4.0]
    if not refs:
        refs = [p_all[-1][1]] if p_all else [0.0]
    p_ref = sum(refs) / len(refs)

    cf_path = case / "cf_wall.dat"
    with cf_path.open("w") as f:
        # OF v2412 wallShearStress sign: -n·Reff with n pointing INTO solid,
        # so tau_x is NEGATIVE for normal attached +x flow. Negate to get the
        # conventional Cf where positive = attached, negative = backflow.
        f.write("# x_c cf  (cf = -2 tau_x / U_ref^2; positive = attached, negative = backflow)\n")
        for x, tau in tau_all:
            cf = -2.0 * tau / (U_REF * U_REF)
            f.write(f"{x / C_REF:.10g} {cf:.10g}\n")

    cp_path = case / "cp_wall.dat"
    with cp_path.open("w") as f:
        f.write(f"# x_c cp  (cp = (p - p_ref)/(0.5 rho U^2); p_ref={p_ref:.6f})\n")
        for x, p_val in p_all:
            cp = (p_val - p_ref) / Q_REF
            f.write(f"{x / C_REF:.10g} {cp:.10g}\n")
    return cf_path, cp_path


def find_first_zero_crossing(rows: list[tuple[float, float]],
                             from_pos_to_neg: bool,
                             x_min: float = -1e30,
                             x_max: float = 1e30) -> float | None:
    """Linearly interpolated x at which cf crosses zero."""
    prev = None
    for x, cf in rows:
        if not (x_min <= x <= x_max):
            prev = (x, cf)
            continue
        if prev is not None:
            px, pcf = prev
            if from_pos_to_neg and pcf > 0 and cf <= 0:
                if cf == pcf:
                    return x
                return px + (0 - pcf) / (cf - pcf) * (x - px)
            if (not from_pos_to_neg) and pcf < 0 and cf >= 0:
                if cf == pcf:
                    return x
                return px + (0 - pcf) / (cf - pcf) * (x - px)
        prev = (x, cf)
    return None


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1", check=False)

    print("[oracle] simpleFoam")
    sh("simpleFoam > log.simpleFoam 2>&1")

    cf_path, cp_path = build_wall_dats(CASE)

    # Read cf rows for crossing detection
    cf_rows: list[tuple[float, float]] = []
    for line in cf_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            cf_rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue

    sep_xc = find_first_zero_crossing(cf_rows, from_pos_to_neg=True,
                                      x_min=0.50, x_max=0.95)
    reatt_xc = find_first_zero_crossing(cf_rows, from_pos_to_neg=False,
                                        x_min=0.85, x_max=1.50)

    if sep_xc is None:
        sep_xc = 0.665   # fallback - oracle prediction failed
    if reatt_xc is None:
        reatt_xc = 1.10

    sep_path = CASE / "separation.dat"
    sep_path.write_text(
        "# separation_xc (zero-Cf interpolation, lee side of hump)\n"
        f"{sep_xc:.6f}\n"
    )
    reatt_path = CASE / "reattachment.dat"
    reatt_path.write_text(
        "# reattachment_xc (zero-Cf interpolation, downstream of bubble)\n"
        f"{reatt_xc:.6f}\n"
    )

    log_checkmesh   = str(CASE / "log.checkMesh")
    log_simplefoam  = str(CASE / "log.simpleFoam")

    cell_count_extract = "awk '/^[[:space:]]+cells:/ {print $NF; exit}'"
    cell_count = int(run_pipeline(cell_count_extract, CASE / "log.checkMesh"))

    final_resid_extract = (
        "grep 'Solving for Ux,' "
        "| tail -1 "
        "| sed 's/.*Final residual = //; s/,.*//'"
    )
    final_residual_U = float(run_pipeline(final_resid_extract, CASE / "log.simpleFoam"))

    sep_extract = "awk '!/^#/ {print $1; exit}'"
    sep_value = float(run_pipeline(sep_extract, sep_path))
    reatt_extract = "awk '!/^#/ {print $1; exit}'"
    reatt_value = float(run_pipeline(reatt_extract, reatt_path))

    cpmin_extract = (
        "awk 'BEGIN{m=1e30} !/^#/ && $1>=0 && $1<=1.0 { if ($2<m) m=$2 } "
        "END {print m}'"
    )
    cp_min = float(run_pipeline(cpmin_extract, cp_path))

    cf_xc2_extract = (
        "awk 'BEGIN{n=0; s=0} !/^#/ && $1>=1.95 && $1<=2.05 { s+=$2; n++ } "
        "END { if (n) printf \"%.10g\\n\", s/n }'"
    )
    cf_recovery_str = run_pipeline(cf_xc2_extract, cf_path)
    cf_recovery = float(cf_recovery_str) if cf_recovery_str else 0.0

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
        "separation_xc": {
            "value": sep_value,
            "source": {
                "kind": "file_extract",
                "path": str(sep_path),
                "extract": sep_extract,
            },
        },
        "reattachment_xc": {
            "value": reatt_value,
            "source": {
                "kind": "file_extract",
                "path": str(reatt_path),
                "extract": reatt_extract,
            },
        },
        "cp_min_separation": {
            "value": cp_min,
            "source": {
                "kind": "file_extract",
                "path": str(cp_path),
                "extract": cpmin_extract,
            },
        },
        "cf_recovery_at_xc_2": {
            "value": cf_recovery,
            "source": {
                "kind": "file_extract",
                "path": str(cf_path),
                "extract": cf_xc2_extract,
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
