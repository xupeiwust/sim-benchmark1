"""Developing-channel-entry oracle.

Steady-state laminar incompressible flow in a 2D plane channel of full
height D = 2H = 1, Re = u_mean*D/nu = 100. A uniform (plug) inlet profile
develops toward the parabolic Poiseuille profile downstream. Writes a
schema-conforming /tmp/agent/result.json with `file_extract` provenance
against real OpenFOAM artifacts persisted in /tmp/agent/case:

  /tmp/agent/case/log.blockMesh        - mesh build log
  /tmp/agent/case/log.checkMesh        - checkMesh -allGeometry output
  /tmp/agent/case/log.simpleFoam       - solver iteration log
  /tmp/agent/case/centerline_U.dat     - (x  Ux) sampled along y=0, sorted by x

KPI:
  u_centerline_ratio = U_x(centerline, x = 0.01*Re*(2H) = 1.0) / u_mean,
  with u_mean = 1.0. The fully developed plane-Poiseuille centerline is
  exactly 1.5*u_mean (closed form), but at x = 1.0 the flow is still
  DEVELOPING: the value is strictly between 1.0 (uniform inlet) and 1.5,
  and has no simple closed form (it is the Navier-Stokes entrance solution).

Keywords `blockMesh` / `simpleFoam` in this comment make
OpenFOAMDriver.detect() happy if someone invokes without --solver.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/case"))

# Physics constants for the KPI station and normalisation.
U_MEAN = 1.0          # mean (= uniform inlet) velocity, m/s
X_STATION = 1.0       # x = 0.01 * Re * (2H) = 0.01 * 100 * 1.0


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


def build_centerline_dat(case: Path) -> Path:
    """Find the latest centerline sample, dump (x Ux) sorted by x.

    The case's sampleDict declares the `centerline` set which writes
    `postProcessing/sampleDict/<t>/centerline_U.xy` with columns
    x y z U_x U_y U_z (raw setFormat). We dump only x and U_x, sorted by x,
    to a stable `/tmp/agent/case/centerline_U.dat` so the result.json's
    `extract` pipeline can stay simple awk over a deterministic file.
    """
    candidates = list(case.glob(
        "postProcessing/sampleDict/*/centerline_U.xy"
    ))
    if not candidates:
        candidates = list(case.glob(
            "postProcessing/sampleDict/*/centerline_U.raw"
        ))
    if not candidates:
        raise RuntimeError("no centerline sample found in postProcessing/")
    raw = sorted(candidates, key=lambda p: float(p.parent.name))[-1]

    pairs: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # With `axis x` the raw set writes the AXIS coord then the field
        # components: columns are  x Ux Uy Uz  (4 cols, NOT x y z Ux Uy Uz).
        # So x = parts[0], Ux = parts[1].
        if len(parts) < 4:
            continue
        try:
            x = float(parts[0])
            ux = float(parts[1])
        except ValueError:
            continue
        if 0.0 <= x <= 6.0:
            pairs.append((x, ux))
    pairs.sort(key=lambda t: t[0])

    out = case / "centerline_U.dat"
    out.write_text(
        "# x Ux  (centerline y=0; sorted by x)\n"
        + "\n".join(f"{x:.10g} {ux:.10g}" for x, ux in pairs)
        + "\n"
    )
    return out


def normalise_line_endings(case: Path) -> None:
    """Strip CR bytes from every OpenFOAM dictionary in the case.

    The case is tarred from a Windows working copy and shipped to the
    Linux runner; the tar pipeline can re-introduce CRLF into the
    extension-less OpenFOAM dicts (the validate script only de-CRLFs
    *.sh). OpenFOAM's tokenizer then mis-parses multi-grading blocks
    ("expected word, found ';'"), so blockMesh dies before meshing.
    Normalise in place — cheap and idempotent on already-LF files.
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
    sh("checkMesh -allGeometry > log.checkMesh 2>&1")

    print("[oracle] simpleFoam (target 2000 iterations)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    centerline_path = build_centerline_dat(CASE)

    # u_centerline_ratio at x = X_STATION: linear interp Ux at x=1.0,
    # then divide by U_MEAN.
    ratio_awk = (
        'BEGIN { xt=%(xt)g; umean=%(um)g; have=0 } '
        '/^[^#]/ && NF >= 2 { '
        '  x=$1+0.0; ux=$2+0.0; '
        '  if (have && px <= xt && xt <= x) { '
        '    if (x == px) ux_at = pux; '
        '    else ux_at = pux + (xt - px) / (x - px) * (ux - pux); '
        '    printf "%%.10g\\n", ux_at / umean; '
        '    exit '
        '  } '
        '  px=x; pux=ux; have=1 '
        '}'
    ) % {"xt": X_STATION, "um": U_MEAN}
    ratio_extract = "awk '" + ratio_awk + "'"
    u_centerline_ratio = float(run_pipeline(ratio_extract, centerline_path))

    result = {
        "u_centerline_ratio": {
            "value": u_centerline_ratio,
            "source": {
                "kind": "file_extract",
                "path": str(centerline_path),
                "extract": ratio_extract,
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
