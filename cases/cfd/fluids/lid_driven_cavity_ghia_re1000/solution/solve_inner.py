"""lid_driven_cavity_ghia_re1000 oracle.

Steady-state laminar incompressible flow in a 2D lid-driven SQUARE cavity
(unit side L=1). The top wall (lid) moves at Ux=1; the other three walls are
stationary no-slip. Re = U_lid*L/nu = 1*1/0.001 = 1000. simpleFoam with
simulationType=laminar (no turbulence model).

KPI:
  u_min_vertical_centerline = min over the vertical centerline (x=0.5) of the
  normalised streamwise velocity Ux/U_lid. For the Ghia, Ghia & Shin (1982)
  Re=1000 benchmark this minimum is u ~ -0.38289 at y ~ 0.1719 (Table I).
  This is a benchmark/reference quantity, NOT this solver's own output; the
  oracle reproduces it within the calibrated tolerance.

Persisted artifacts in /tmp/agent/case (anti-cheat openfoam detector reads
the polyMesh + non-zero time dir; these logs are auxiliary):
  log.blockMesh    - mesh build log
  log.checkMesh    - checkMesh -allGeometry output
  log.simpleFoam   - solver iteration log
  stopping.json    - what stopped simpleFoam: the criterion, or the iteration cap
  centerline_U.dat - (y  Ux) sampled along x=0.5, sorted by y

Keywords `blockMesh` / `simpleFoam` in this comment make
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

# Normalisation: U_lid = 1 m/s, so Ux is already Ux/U_lid.
U_LID = 1.0


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


_BASHRC_PATH: str | None = None


def bashrc_path() -> str:
    """`discover_openfoam_bashrc()`, resolved on first use rather than at import.

    Resolving it at import made this module unloadable anywhere OpenFOAM is not
    installed, which is every host the test suite runs on. The stopping check
    below is worth a unit test, and a test cannot import a module that raises
    while being imported.
    """
    global _BASHRC_PATH
    if _BASHRC_PATH is None:
        _BASHRC_PATH = discover_openfoam_bashrc()
    return _BASHRC_PATH


def sh(cmd: str, check: bool = True) -> None:
    subprocess.run(
        f"source {bashrc_path()} && cd {CASE} && {cmd}",
        shell=True, check=check, executable="/bin/bash",
    )


# ── what stopped the solver ─────────────────────────────────────────────────
#
# `simpleFoam` exits 0 whether `residualControl` fired or the run simply
# reached `endTime`, and the fields it leaves behind look the same either way.
# The difference is only in the log, and this case shipped for two months in
# the second state: `endTime 3000` against a criterion first met at iteration
# 3454 (#266, #273). The value it published was 0.096% from the converged one
# and no stored score moved -- which is luck, not design. The oracle is the
# centre of this case's band, and a centre produced by an *undeclared* stopping
# rule moves whenever the cap, the host or the OpenFOAM build moves, with
# nothing to warn anyone.

def stopping_record(log_text: str, cap: float) -> dict:
    """What stopped the run, read out of `log.simpleFoam`."""
    hit = re.search(r"SIMPLE solution converged in (\d+) iterations", log_text)
    times = re.findall(r"^Time = ([0-9.eE+-]+)", log_text, re.MULTILINE)
    return {
        "converged": hit is not None,
        "criterion_met_at": int(hit.group(1)) if hit else None,
        "iterations_run": float(times[-1]) if times else 0.0,
        "iteration_cap": cap,
    }


def iteration_cap(case: Path) -> float:
    """`endTime` from the case's own controlDict. `deltaT` is 1, so it is an
    iteration count."""
    text = (case / "system" / "controlDict").read_text(encoding="utf-8", errors="replace")
    found = re.search(r"^\s*endTime\s+([0-9.eE+-]+)\s*;", text, re.MULTILINE)
    if found is None:
        raise SystemExit("[oracle] controlDict declares no endTime")
    return float(found.group(1))


def assert_stopped_on_the_criterion(case: Path) -> dict:
    """Record the stopping rule as an artifact, and fail if the cap is what fired.

    The two available repairs are not interchangeable, and only one of them is
    right here. Raising `endTime` costs iterations and leaves the *declared*
    criterion doing the stopping. Loosening `residualControl` until the cap
    satisfies it makes the criterion follow the cap -- the same defect wearing
    a tidier name. Loosening is correct only where the criterion is
    structurally unreachable, which is #199's `plane_poiseuille`: `Uy` is
    physically ~0 there, so its normalised residual floors at 0.06 and no run
    length reaches 1e-6.

    This case is not that, and the difference was measured rather than assumed
    (#273, Re=100, the oracle's own 128x128 grid): the declared 1e-6 fires at
    iteration 3454, and even 1e-10 fires -- at 19145 iterations, 177 s. So
    nothing here was unreachable; the cap had simply been set below the
    criterion. #266 reported `p` flooring near 5e-10 under a 1e-10 criterion,
    but that was the 64x64 level of a grid study, not this case's grid.
    **Reachability is a property of the discretisation, not of the case**, so
    it cannot be carried across a mesh change -- and a criterion that cannot be
    met is the same defect as no criterion, caught by this same check.

    What the declared criterion leaves behind is worth recording: stopping at
    1e-6 gives -0.21344591 against 1e-10's -0.21359259, so the residual
    iteration error is 0.07% of |gt| -- an order of magnitude under this
    oracle's own 1.21% distance from the published reference.
    """
    record = stopping_record(
        (case / "log.simpleFoam").read_text(encoding="utf-8", errors="replace"),
        iteration_cap(case),
    )
    (case / "stopping.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("[oracle] stopping: " + json.dumps(record))
    if not record["converged"]:
        raise SystemExit(
            "[oracle] simpleFoam stopped at the iteration cap "
            f"({record['iterations_run']:g} of endTime {record['iteration_cap']:g}) "
            "without meeting the residualControl this case declares, so the "
            "value it would report is a property of the cap rather than of the "
            "declared stopping rule. Raise endTime until the criterion fires; "
            "loosen residualControl only if the criterion is structurally "
            "unreachable (#199, #273)."
        )
    return record


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
    """Find the latest vertical-centerline sample, dump (y Ux) sorted by y.

    The case's sampleDict declares the `verticalCenterline` set which writes
    `postProcessing/sampleDict/<t>/verticalCenterline_U.xy` with columns
    y U_x U_y U_z (raw setFormat with `axis y`). We dump only y and U_x,
    sorted by y, to a stable `/tmp/agent/case/centerline_U.dat` so the
    result.json's `extract` pipeline can stay simple awk over a deterministic
    file.
    """
    candidates = list(case.glob(
        "postProcessing/sampleDict/*/verticalCenterline_U.xy"
    ))
    if not candidates:
        candidates = list(case.glob(
            "postProcessing/sampleDict/*/verticalCenterline_U.raw"
        ))
    if not candidates:
        raise RuntimeError("no verticalCenterline sample found in postProcessing/")
    raw = sorted(candidates, key=lambda p: float(p.parent.name))[-1]

    pairs: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # With `axis y` the raw set writes the AXIS coord then the field
        # components: columns are  y Ux Uy Uz  (4 cols, NOT x y z Ux Uy Uz).
        # So y = parts[0], Ux = parts[1].
        if len(parts) < 4:
            continue
        try:
            y = float(parts[0])
            ux = float(parts[1])
        except ValueError:
            continue
        if 0.0 <= y <= 1.0:
            pairs.append((y, ux))
    pairs.sort(key=lambda t: t[0])

    out = case / "centerline_U.dat"
    out.write_text(
        "# y Ux  (vertical centerline x=0.5; sorted by y)\n"
        + "\n".join(f"{y:.10g} {ux:.10g}" for y, ux in pairs)
        + "\n"
    )
    return out


def normalise_line_endings(case: Path) -> None:
    """Strip CR bytes from every OpenFOAM dictionary in the case.

    The case is tarred from a Windows working copy and shipped to the
    Linux runner; the tar pipeline can re-introduce CRLF into the
    extension-less OpenFOAM dicts (the validate script only de-CRLFs
    *.sh). OpenFOAM's tokenizer then mis-parses, so blockMesh dies before
    meshing. Normalise in place — cheap and idempotent on already-LF files.
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

    print(f"[oracle] simpleFoam (laminar, iteration cap {iteration_cap(CASE):g})")
    sh("simpleFoam > log.simpleFoam 2>&1")
    assert_stopped_on_the_criterion(CASE)

    print("[oracle] postProcess -func sampleDict -latestTime")
    sh("postProcess -func sampleDict -latestTime > log.postProcess 2>&1")

    centerline_path = build_centerline_dat(CASE)

    # u_min_vertical_centerline: minimum Ux over the centerline, divided by
    # U_lid (= 1). Deterministic awk over the (y Ux) dat file.
    # NOTE: the extractor string is re-run by the verifier's source-verification
    # sandbox, which splits the command on "|" to find pipe stages. An awk "||"
    # operator would be shattered by that split (No closing quotation). Avoid
    # both "|" and embedded double quotes: use two guarded rules instead of
    # `if (!have || ux < m)`, and `print` instead of `printf "..."`.
    umin_awk = (
        'BEGIN { have=0 } '
        '/^[^#]/ && NF >= 2 { '
        '  ux=$2+0.0; '
        '  if (have==0) { m=ux; have=1 } '
        '  else if (ux < m) { m=ux } '
        '} '
        'END { if (have) print m / %(ul)g }'
    ) % {"ul": U_LID}
    umin_extract = "awk '" + umin_awk + "'"
    u_min = float(run_pipeline(umin_extract, centerline_path))

    result = {
        "u_min_vertical_centerline": {
            "value": u_min,
            "source": {
                "kind": "file_extract",
                "path": str(centerline_path),
                "extract": umin_extract,
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
