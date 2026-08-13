"""taylor_green_vortex_2d_re100 oracle.

Transient, incompressible, laminar 2D flow reproducing the Taylor-Green (1937)
decaying-vortex exact unsteady Navier-Stokes solution on a doubly-periodic box.
pisoFoam with simulationType=laminar (no turbulence model). The exact field is

    nu      = 1/Re                                    (Re=100 -> nu=0.01)
    Ux(x,y,t) = -cos(x)*sin(y)*exp(-2*nu*t)
    Uy(x,y,t) =  sin(x)*cos(y)*exp(-2*nu*t)

on 0<=x<=2*pi, 0<=y<=2*pi with all four side patches cyclic (doubly-periodic).
The t=0 Taylor-Green field is imposed with `setExprFields`; pisoFoam evolves the
transient field to t-star = 5. The whole vortex amplitude decays uniformly by
exp(-2*nu*t), so the peak x-velocity magnitude at t-star is the decayed value.

KPI:
  u_peak_at_tstar = max over the domain of |Ux| at t-star = 5. For the
  Taylor-Green Re=100 exact solution this is exp(-2*nu*5) = exp(-0.1)
  ~ 0.904837. This is the PUBLISHED analytical reference quantity, NOT this
  solver's own output; the oracle reproduces it within the calibrated tolerance.

Persisted artifacts in /tmp/agent/case (anti-cheat openfoam detector reads the
polyMesh + non-zero time dir; these logs are auxiliary):
  log.blockMesh      - mesh build log
  log.checkMesh      - checkMesh -allGeometry output
  log.setExprFields  - initial-condition imposition log
  log.pisoFoam       - solver time-step log
  upeak_tstar.dat    - the extracted peak |Ux| single value

Keywords `blockMesh` / `pisoFoam` in this comment make OpenFOAMDriver.detect()
happy if someone invokes without --solver.
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

# Normalisation: U_ref = 1, so |Ux| is already |Ux|/U_ref.
U_REF = 1.0

# t-star at which the peak x-velocity is scored.
T_STAR = 5.0


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


def latest_time_dir(case: Path) -> Path:
    """Return the non-zero time directory with the largest numeric name."""
    times = []
    for d in case.iterdir():
        if not d.is_dir():
            continue
        try:
            t = float(d.name)
        except ValueError:
            continue
        if t > 0.0 and (d / "U").is_file():
            times.append((t, d))
    if not times:
        raise RuntimeError("no non-zero time dir with a U field found")
    return sorted(times, key=lambda tv: tv[0])[-1][1]


def parse_peak_ux(u_file: Path) -> float:
    """Read the internalField vector list of U and return max |Ux|.

    A binary or ascii volVectorField writes its internalField as a
    `nonuniform List<vector>` block:

        internalField   nonuniform List<vector>
        4096
        (
        (ux uy uz)
        ...
        )

    We scan every '(ux uy uz)' triple inside that list and track the largest
    |ux|. Robust to writePrecision and avoids any point-sample interpolation.
    """
    text = u_file.read_text()
    # Isolate the internalField list (stop before boundaryField).
    start = text.find("internalField")
    if start == -1:
        raise RuntimeError("U file has no internalField")
    end = text.find("boundaryField", start)
    if end == -1:
        end = len(text)
    body = text[start:end]

    triple = re.compile(r"\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)")
    peak = None
    for m in triple.finditer(body):
        try:
            ux = float(m.group(1))
        except ValueError:
            continue
        a = abs(ux)
        if peak is None or a > peak:
            peak = a
    if peak is None:
        raise RuntimeError("could not parse any Ux triple from internalField")
    return peak


def build_upeak_dat(case: Path) -> Path:
    tdir = latest_time_dir(case)
    peak = parse_peak_ux(tdir / "U")
    out = case / "upeak_tstar.dat"
    out.write_text(
        "# u_peak_at_tstar  (max |Ux| over the domain at t-star=5)\n"
        + f"{peak / U_REF:.10g}\n"
    )
    return out


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

    print("[oracle] setExprFields (impose t=0 Taylor-Green field)")
    sh("setExprFields > log.setExprFields 2>&1")

    print("[oracle] pisoFoam (laminar, transient to t-star=5)")
    sh("pisoFoam > log.pisoFoam 2>&1")

    upeak_path = build_upeak_dat(CASE)

    # u_peak_at_tstar: the max |Ux| over the domain at t-star, divided by U_ref.
    # Deterministic awk over the single-value dat file.
    # NOTE: the extractor string is re-run by the verifier's source-verification
    # sandbox, which splits the command on "|" to find pipe stages. An awk "||"
    # operator would be shattered by that split. Avoid both "|" and embedded
    # double quotes: bare print of the first non-comment field, no printf.
    up_extract = "awk '!/^#/ { print $1; exit }'"
    u_peak = float(run_pipeline(up_extract, upeak_path))

    result = {
        "u_peak_at_tstar": {
            "value": u_peak,
            "source": {
                "kind": "file_extract",
                "path": str(upeak_path),
                "extract": up_extract,
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
