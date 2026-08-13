"""cylinder_schafer_turek_2d1_cd oracle.

Steady LAMINAR incompressible flow around a circular cylinder in a 2.2 x 0.41 m
channel matching the Schäfer & Turek (1996) DFG benchmark 2D-1 (Re = 20,
parabolic inlet, cylinder D = 0.1 m at (0.2, 0.2)). simpleFoam with
simulationType=laminar (no turbulence model). The forceCoeffs function object
writes the drag/lift coefficients on the cylinder patch; the oracle extracts the
converged drag coefficient cD.

The published committee reference (FeatFlow DFG benchmark 2D-1) is
cD = 5.57953523384 — that is the ground-truth the verifier scores against, NOT
this solver output. The bundled mesh reproduces it within the T_good band.

Persisted artifacts in /tmp/agent/case:
  log.blockMesh / log.checkMesh / log.simpleFoam
  postProcessing/forceCoeffs1/0/coefficient.dat   - Cd/Cl time history
  cd.txt   - the extracted converged cD single value

Keywords blockMesh / simpleFoam in this comment make OpenFOAMDriver.detect()
pick this script up if --solver is omitted.
"""
from __future__ import annotations

import json
import os
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


def latest_coeff_file(case: Path) -> Path:
    cands = list(case.glob("postProcessing/forceCoeffs1/*/coefficient.dat"))
    if not cands:
        # older OF naming: forceCoeffs.dat
        cands = list(case.glob("postProcessing/forceCoeffs1/*/forceCoeffs.dat"))
    if not cands:
        raise RuntimeError("no postProcessing/forceCoeffs1/*/coefficient.dat found")
    return sorted(cands, key=lambda p: float(p.parent.name))[-1]


def cd_column_index(coeff_path: Path) -> int:
    """Find the 0-based column index of Cd from the commented header.

    OF v2412 coefficient.dat header looks like:
      # Time  Cd  Cs  Cl  CmRoll CmPitch CmYaw Cd(f) Cd(r) ...
    We locate the token 'Cd' (exact) among the header names, then account for the
    leading '#'/'Time' offset so the index maps onto whitespace-split data rows
    (which have no '#').
    """
    header_tokens: list[str] = []
    for line in coeff_path.read_text().splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        toks = s.lstrip("#").split()
        # the header row is the one that contains 'Cd'
        if "Cd" in toks:
            header_tokens = toks
    if not header_tokens:
        raise RuntimeError("no header row with 'Cd' in coefficient.dat")
    # header_tokens[0] should be 'Time'; data rows are Time c1 c2 ...
    return header_tokens.index("Cd")


def extract_cd(coeff_path: Path) -> tuple[float, int]:
    idx = cd_column_index(coeff_path)
    # last non-comment row, idx-th whitespace field (1-based awk = idx+1)
    awk_field = idx + 1
    extract = f"grep -v '^#' | tail -1 | awk '{{print ${awk_field}}}'"
    val = run_pipeline(extract, coeff_path)
    return float(val), awk_field


def main() -> int:
    t0 = time.time()

    print("[oracle] blockMesh")
    sh("blockMesh > log.blockMesh 2>&1")

    print("[oracle] checkMesh -allGeometry")
    sh("checkMesh -allGeometry > log.checkMesh 2>&1", check=False)

    print("[oracle] simpleFoam (laminar, target endTime=3000)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    coeff_path = latest_coeff_file(CASE)
    cd_value, awk_field = extract_cd(coeff_path)

    # Write a stable single-value file so the verifier's source.path is fixed and
    # the rounded value EXACTLY matches result.json.
    cd_path = CASE / "cd.txt"
    cd_path.write_text(
        "# cylinder drag coefficient cD (Schäfer-Turek 2D-1, steady laminar Re=20)\n"
        f"{cd_value:.6f}\n"
    )
    cd_extract = "awk '!/^#/ {print $1; exit}'"
    cd_reextract = float(run_pipeline(cd_extract, cd_path))

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

    result = {
        "mesh_cell_count": {
            "value": cell_count,
            "source": {
                "kind": "file_extract",
                "path": str(CASE / "log.checkMesh"),
                "extract": cell_count_extract,
            },
        },
        "final_residual_U": {
            "value": final_residual_U,
            "source": {
                "kind": "file_extract",
                "path": str(CASE / "log.simpleFoam"),
                "extract": final_resid_extract,
            },
        },
        "cd": {
            "value": round(cd_reextract, 6),
            "source": {
                "kind": "file_extract",
                "path": str(cd_path),
                "extract": cd_extract,
            },
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(json.dumps({k: v["value"] for k, v in result.items()}, indent=2))
    print(f"[oracle] cD extracted from column {awk_field} of {coeff_path.name}",
          file=sys.stderr)
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
