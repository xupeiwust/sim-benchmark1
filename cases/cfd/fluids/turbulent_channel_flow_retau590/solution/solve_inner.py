"""turbulent_channel_flow_retau590 oracle using native OpenFOAM commands.

Steady-state, fully-developed turbulent plane-channel flow at friction Reynolds
number Re_tau = u_tau*delta/nu = 590, half-channel height delta = 1, solved with
RANS (k-omega SST, wall-resolved y+<1) by simpleFoam. The streamwise direction
is periodic (cyclic); the flow is driven by a UNIFORM streamwise body force
(constant/fvOptions, gradP = u_tau^2/delta = 1), so by the global x-momentum
balance over the full channel (height 2*delta, two walls)

    gradP * (2*delta) = 2 * tau_w   =>   tau_w = gradP * delta = u_tau^2,

which with gradP = 1 and delta = 1 fixes u_tau = 1 exactly. The kinematic
viscosity nu = u_tau*delta/Re_tau = 1/590 then sets Re_tau = 590.

KPI:
  ub_over_utau = U_b / u_tau, the bulk-mean velocity normalised by the friction
  velocity. U_b is the height-average of the streamwise velocity,

      U_b = (1/(2*delta)) * integral_{-delta}^{+delta} Ux(y) dy,

  obtained from the sampled wall-normal profile (uProfile cloud) by trapezoidal
  integration, with Ux = 0 enforced at both no-slip walls. Since u_tau = 1 by
  construction, ub_over_utau = U_b numerically. The external V&V anchor is
  derived from the Moser, Kim & Mansour official chan590 DNS mean-profile data:

      U_b / u_tau = integral_0^1 U+(y/delta) d(y/delta)
                    = 18.653932352

  This value is derived by trapezoidal integration of the 129-point official
  `chan590.means` half-channel profile (Re_tau=587.19), not quoted from a paper
  table. The dataset is described by Moser, Kim & Mansour, Phys. Fluids
  11(4):943-945. The OpenFOAM oracle must be calibrated independently.

Persisted artifacts in /tmp/agent/submission:
  log.blockMesh    - mesh build log
  log.checkMesh    - checkMesh -allGeometry output
  log.simpleFoam   - solver iteration log
  log.postProcess  - sampling log
  ub_over_utau.dat - the single extracted U_b/u_tau value

"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/submission"))

# Geometry / driving constants matching the case dicts.
DELTA = 1.0       # channel half-height (full height 2*delta)
GRADP = 1.0       # uniform streamwise body force (constant/fvOptions)
# Friction velocity fixed by the global momentum balance: u_tau = sqrt(gradP*delta).
U_TAU = (GRADP * DELTA) ** 0.5


def discover_openfoam_bashrc() -> str:
    candidates = [Path("/usr/lib/openfoam/openfoam2412/etc/bashrc")]
    candidates.extend(sorted(Path("/usr/lib/openfoam").glob("openfoam*/etc/bashrc")))
    candidates.extend(sorted(Path("/opt").glob("openfoam*/etc/bashrc")))
    for bashrc in candidates:
        if bashrc.is_file():
            return str(bashrc)
    raise RuntimeError("no packaged OpenFOAM bashrc found")


BASHRC_PATH = discover_openfoam_bashrc()


def sh(cmd: str, check: bool = True) -> None:
    subprocess.run(
        f"source {BASHRC_PATH} && cd {CASE} && {cmd}",
        shell=True, check=check, executable="/bin/bash",
    )


def latest_sample(case: Path, set_name: str):
    """Return the latest postProcessing/sampleDict/<t>/<set_name>_*.(xy|raw) path.

    ESI OpenFOAM v2412 writes ONE file per sampled set with ALL requested
    fields concatenated, named <set>_<field>... (here, with `fields (U)`, the
    file is `<set>_U.xy`), columns x y z Ux Uy Uz. Match by set-name prefix.
    """
    candidates = list(case.glob(f"postProcessing/sampleDict/*/{set_name}_*.xy"))
    if not candidates:
        candidates = list(case.glob(f"postProcessing/sampleDict/*/{set_name}_*.raw"))
    if not candidates:
        raise RuntimeError(f"no {set_name} sample found in postProcessing/")
    return sorted(candidates, key=lambda p: float(p.parent.name))[-1]


def measure_ub(case: Path) -> float:
    """Trapezoidal height-average of Ux over the full channel height.

    The combined v2412 cloud file (fields U) has columns x y z Ux Uy Uz, so
    y = col 2 (parts[1]) and Ux = col 4 (parts[3]). Points are ordered
    bottom-to-top; Ux = 0 is enforced at both walls (y = -delta, +delta).
    U_b = (1/(2*delta)) * integral Ux dy.
    """
    raw = latest_sample(case, "uProfile")
    pairs: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            y = float(parts[1])
            ux = float(parts[3])
        except ValueError:
            continue
        pairs.append((y, ux))
    if len(pairs) < 2:
        raise RuntimeError("not enough uProfile samples to integrate U_b")
    pairs.sort(key=lambda t: t[0])
    # Extend to the walls with no-slip Ux = 0 at y = -delta and y = +delta.
    ys = [-DELTA] + [y for y, _ in pairs] + [DELTA]
    us = [0.0] + [u for _, u in pairs] + [0.0]
    integral = 0.0
    for i in range(len(ys) - 1):
        integral += 0.5 * (us[i] + us[i + 1]) * (ys[i + 1] - ys[i])
    return integral / (2.0 * DELTA)


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
    sh("checkMesh -allGeometry > log.checkMesh 2>&1")

    print("[oracle] simpleFoam (k-omega SST, periodic channel, target endTime=5000)")
    sh("simpleFoam > log.simpleFoam 2>&1")

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    ub = measure_ub(CASE)
    ub_over_utau = ub / U_TAU

    # This diagnostic is useful to the benchmark author, but the evaluator does
    # not trust it: it re-samples the submitted U field with a private dict.
    value_rounded = round(ub_over_utau, 6)
    dat = CASE / "ub_over_utau.dat"
    dat.write_text(
        "# ub_over_utau  (bulk-mean velocity / friction velocity)\n"
        + f"{value_rounded:.6f}\n"
    )

    print(
        f"[oracle] U_b={ub:.6g} u_tau={U_TAU:.6g} "
        f"U_b/u_tau={value_rounded:.6g} "
        f"in {time.time() - t0:.1f}s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
