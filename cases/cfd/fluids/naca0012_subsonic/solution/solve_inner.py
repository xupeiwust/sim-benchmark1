#!/usr/bin/env python3
"""Oracle for naca0012_subsonic.

Solves NASA TMR's official 225x65 NACA 0012 C-grid -- the same mesh the agent
is handed -- at alpha = 10 deg with Spalart-Allmaras, then writes a
schema-conforming /tmp/agent/result.json with file_extract sources.

The model is SA and the freestream is nuTilda_inf = 3 nu_inf because that is
what TMR's published CFL3D/FUN3D/TAU series used. Ground truth is those
published values on this grid, so the oracle has to be asking the question
they answered.

Column positions in coefficient.dat have moved between OpenFOAM releases, so
the coefficients are located by parsing the file's own header rather than by a
fixed field index -- a wrong index here would swap drag for lift without
failing anything.

WHAT STOPS THIS RUN, AND WHY IT IS NOT A RESIDUAL THRESHOLD
-----------------------------------------------------------
This oracle used to declare `residualControl p 1e-8 / U 1e-9 / nuTilda 1e-9`
and never once meet it. On this case's own TMR 225x65 grid the residuals hit a
floor and stop moving in the first significant figure by iteration 7500,
sitting at Ux 3.6e-9, p 3.5e-8 and nuTilda 1.08e-5 all the way to 30000 -- so
no threshold this case could declare is both reachable and meaningful, and a
criterion that can never be met is the same defect as no criterion (#273).

The solution itself, however, IS settled: 6000 against 30000 iterations moves
CL by 0.0004% and CD by 0.005%. So the criterion is about the solution rather
than about the residuals -- **stop when the reported coefficients stop
moving** -- and it is evaluated on the coefficients themselves:

    run SETTLE_BLOCK iterations at a time; stop the first time BOTH Cd and Cl
    have changed by less than SETTLE_TOL relative over one whole block.

That measure is smooth and has no floor: it falls from 5.3e-3 at iteration
2000 through 2.0e-5 at 8000 to 9.2e-9 at 20000, six orders over the run, so
`SETTLE_TOL` sits three orders above where the measure ends rather than a
factor of 1.1 above a floor. Measured on the shipped grid it fires at 8000,
and every tolerance from 5e-6 to 2e-4 fires between 6000 and 9000 with the
reported drag inside 0.005% of `gt_value` -- which is what makes the fire
point's exact location not matter (#295, #336).

Two things were tried first and are recorded so they are not tried again.
Loosening the residualControl to something reachable moves where the oracle
lands, and its own `gt_value` with it: the four reachable candidates measured
in #312 move CD by 1.98% / 0.55% / 0.28% / 0.075%, and the tightest of them
sits 1.1x over the residual floor -- fragile in exactly the direction that
caused this defect. And OpenFOAM's own `runTimeControl` `average` condition on
(Cd Cl) cannot express the criterion here: measured on this grid it fires at
4230 with tolerance 1e-5 and at 4758 with 2e-6, and never inside 20000
iterations with 1e-6, so its measure floors out between 1e-6 and 2e-6 and no
setting of it has margin. The explicit block comparison below does.

`stopping.json` records what happened, and a run that reaches ITERATION_CAP
without settling FAILS rather than reporting -- the #273 rule, which is the
whole reason any of this is written down.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ALPHA_DEG = 10.0
NU = 1.6666667e-07          # U = 1, c = 1  ->  Re_c = 6e6
NUTILDA_INF = 3.0 * NU      # TMR's SA freestream

# The stopping rule. SETTLE_BLOCK/SETTLE_TOL are the criterion; ITERATION_CAP is
# the safety net. Measured on this grid the criterion fires at 8000, so the cap
# is 2.25x that rather than exactly 2x: the firing point is quantised to whole
# blocks, so 2x would sit on the boundary and one slower block would turn this
# into a capped run -- which is #273's failure, not its rule.
SETTLE_BLOCK = 1000
SETTLE_TOL = 2.0e-5
ITERATION_CAP = 18000

CASE = Path(os.environ.get("ORACLE_CASE", "/tmp/agent/case"))


def w(rel: str, text: str) -> None:
    p = CASE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def write_case() -> None:
    a = math.radians(ALPHA_DEG)
    ux, uy = math.cos(a), math.sin(a)

    w("0/U", f"""FoamFile {{ version 2.0; format ascii; class volVectorField; object U; }}
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({ux} {uy} 0);
boundaryField
{{
  aerofoil  {{ type noSlip; }}
  farfield  {{ type freestreamVelocity; freestreamValue uniform ({ux} {uy} 0); }}
  frontBack {{ type empty; }}
}}
""")
    w("0/p", """FoamFile { version 2.0; format ascii; class volScalarField; object p; }
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
  aerofoil  { type zeroGradient; }
  farfield  { type freestreamPressure; freestreamValue uniform 0; }
  frontBack { type empty; }
}
""")
    # The grid is wall-resolved (first spacing 8e-6 c). A wall-function mesh is
    # what put the superseded oracle 8x off in drag; nut is solved here, and
    # the Spalding form degrades gracefully if y+ ever drifts above 1.
    w("0/nut", """FoamFile { version 2.0; format ascii; class volScalarField; object nut; }
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
  aerofoil  { type nutUSpaldingWallFunction; value uniform 0; }
  farfield  { type calculated; value uniform 0; }
  frontBack { type empty; }
}
""")
    w("0/nuTilda", f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object nuTilda; }}
dimensions [0 2 -1 0 0 0 0];
internalField uniform {NUTILDA_INF};
boundaryField
{{
  aerofoil  {{ type fixedValue; value uniform 0; }}
  farfield  {{ type freestream; freestreamValue uniform {NUTILDA_INF}; }}
  frontBack {{ type empty; }}
}}
""")
    w("constant/transportProperties", f"""FoamFile {{ version 2.0; format ascii; class dictionary; object transportProperties; }}
transportModel Newtonian;
nu {NU};
""")
    mt = """FoamFile { version 2.0; format ascii; class dictionary; object momentumTransport; }
simulationType RAS;
RAS { model SpalartAllmaras; turbulence on; printCoeffs on; }
"""
    w("constant/momentumTransport", mt)
    w("constant/turbulenceProperties", mt)

    write_control_dict("startTime", SETTLE_BLOCK)
    w("system/fvSchemes", """FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes
{
  default none;
  div(phi,U) bounded Gauss linearUpwind grad(U);
  div(phi,nuTilda) bounded Gauss limitedLinear 1;
  div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
""")
    # The C-grid's trailing-edge region carries ~170 severely non-orthogonal
    # faces, hence two non-orthogonal correctors rather than the usual one.
    # NO residualControl, deliberately. The block that used to sit here declared
    # p 1e-8 / U 1e-9 / nuTilda 1e-9 and was structurally unreachable on this
    # grid -- nuTilda floors four orders above its threshold -- so the run always
    # stopped on endTime while the case announced a criterion. The stopping rule
    # is the settling check in main(); see the module docstring.
    w("system/fvSolution", """FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers
{
  p { solver GAMG; smoother GaussSeidel; tolerance 1e-10; relTol 0.01; }
  "(U|nuTilda)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-12; relTol 0.05; }
}
SIMPLE { nNonOrthogonalCorrectors 2; consistent yes; }
relaxationFactors { equations { U 0.7; nuTilda 0.7; } }
""")


def write_control_dict(start_from: str, end_time: int) -> None:
    """One block of the run. `startTime` for the first, `latestTime` after.

    forceCoeffs is written every 20 iterations rather than every 100 because
    the settling check reads its last row, and a coarser interval would round
    the recorded firing point to something the block size did not choose.
    """
    a = math.radians(ALPHA_DEG)
    ux, uy = math.cos(a), math.sin(a)
    lx, ly = -math.sin(a), math.cos(a)
    w("system/controlDict", f"""FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}
application simpleFoam;
startFrom {start_from}; startTime 0; stopAt endTime; endTime {end_time};
deltaT 1; writeControl timeStep; writeInterval {SETTLE_BLOCK}; purgeWrite 2;
writeFormat ascii; writePrecision 10; runTimeModifiable false;
functions
{{
  forceCoeffs1
  {{
    type forceCoeffs; libs (forces); patches (aerofoil);
    rho rhoInf; rhoInf 1; magUInf 1.0; lRef 1.0; Aref 1.0;
    liftDir ({lx} {ly} 0); dragDir ({ux} {uy} 0);
    CofR (0.25 0 0); pitchAxis (0 0 1);
    writeControl timeStep; writeInterval 20;
  }}
}}
""")


def run(cmd: str, log: Path, mode: str = "w") -> int:
    with log.open(mode) as fh:
        return subprocess.run(["bash", "-lc", cmd], cwd=CASE,
                              stdout=fh, stderr=subprocess.STDOUT).returncode


def coeff_columns(path: Path) -> tuple[int, int]:
    """Locate the Cd and Cl columns by name, from the file's own header."""
    for line in path.read_text().splitlines():
        if line.startswith("#") and re.search(r"\bCd\b", line) and re.search(r"\bCl\b", line):
            cols = line.lstrip("#").split()
            return cols.index("Cd") + 1, cols.index("Cl") + 1
    raise SystemExit(f"no Cd/Cl header found in {path}")


def latest_coefficients() -> tuple[Path, int, int, float, float]:
    """The newest coefficient.dat and its last row.

    Each restart opens a new `postProcessing/forceCoeffs1/<startTime>/`, so the
    directories are ordered by their start time as NUMBERS -- lexical order puts
    `10000` before `2000`, which would report a stale block as the answer.
    """
    files = sorted((CASE / "postProcessing" / "forceCoeffs1").glob("*/coefficient.dat"),
                   key=lambda q: float(q.parent.name))
    if not files:
        raise SystemExit("no coefficient.dat written")
    path = files[-1]
    cd_col, cl_col = coeff_columns(path)
    rows = [ln for ln in path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    if not rows:
        raise SystemExit(f"{path} has a header and no data")
    last = rows[-1].split()
    return path, cd_col, cl_col, float(last[cd_col - 1]), float(last[cl_col - 1])


def solve_until_settled(log: Path) -> dict:
    """Run in blocks until Cd and Cl stop moving; return the stopping record.

    The record is written to disk whichever way it ends, because "how did this
    run stop" has to be answerable from the case afterwards -- that is the whole
    #273 defect, and three cfd oracles could not answer it because they kept no
    solver log at all (#286).
    """
    log.unlink(missing_ok=True)
    iterations = 0
    previous: tuple[float, float] | None = None
    trace: list[dict] = []
    settled_at: int | None = None

    while iterations < ITERATION_CAP:
        iterations = min(iterations + SETTLE_BLOCK, ITERATION_CAP)
        write_control_dict("startTime" if previous is None else "latestTime", iterations)
        rc = run("simpleFoam", log, mode="a")
        if rc != 0:
            sys.stderr.write(log.read_text()[-2000:])
            raise SystemExit(f"simpleFoam failed with {rc} at iteration {iterations}")

        _, _, _, cd, cl = latest_coefficients()
        moved = None
        if previous is not None:
            moved = max(abs(cd - previous[0]) / abs(cd), abs(cl - previous[1]) / abs(cl))
        trace.append({"iteration": iterations, "Cd": cd, "Cl": cl,
                      "relative_change": moved})
        shown = "-" if moved is None else f"{moved:.3e}"
        print(f"[oracle] {iterations:6d}  Cd {cd:.10g}  Cl {cl:.10g}  moved {shown}",
              file=sys.stderr)
        previous = (cd, cl)
        if moved is not None and moved < SETTLE_TOL:
            settled_at = iterations
            break

    return {
        "criterion": (f"Cd and Cl each change by less than {SETTLE_TOL:g} relative "
                      f"over {SETTLE_BLOCK} iterations"),
        "converged": settled_at is not None,
        "criterion_met_at": settled_at,
        "iterations_run": iterations,
        "iteration_cap": ITERATION_CAP,
        "trace": trace,
    }


def main() -> int:
    t0 = time.time()
    write_case()

    logs = CASE / "log.simpleFoam"
    record = solve_until_settled(logs)
    (CASE / "stopping.json").write_text(json.dumps(record, indent=2))
    if not record["converged"]:
        raise SystemExit(
            f"the solution had not settled at the iteration cap "
            f"({record['iterations_run']} of {ITERATION_CAP}): Cd or Cl still "
            f"moved by {record['trace'][-1]['relative_change']:.3e} over the "
            f"last {SETTLE_BLOCK} iterations, against {SETTLE_TOL:g}. Refusing "
            f"to report a value the stopping rule did not produce (#273). "
            f"stopping.json has the whole trace.")

    fpath, cd_col, cl_col, cd, cl = latest_coefficients()

    run("checkMesh", CASE / "log.checkMesh")
    m = re.search(r"^\s*cells:\s+(\d+)", (CASE / "log.checkMesh").read_text(), re.M)
    cells = int(m.group(1)) if m else 0

    res_extract = ("awk -F'Final residual = ' '/Solving for Ux,/ {print $2}' "
                   "| awk '{print $1}' | tail -1 | tr -d ','")
    res = subprocess.run(["bash", "-lc", f"cat {logs} | {res_extract}"],
                         capture_output=True, text=True).stdout.strip()

    result = {
        "mesh_cell_count": {
            "value": cells,
            "source": {"kind": "file_extract", "path": str(CASE / "log.checkMesh"),
                       "extract": "awk '/^ *cells:/ {print $2}' | head -1"},
        },
        "final_residual_U": {
            "value": float(res),
            "source": {"kind": "file_extract", "path": str(logs), "extract": res_extract},
        },
        "CL_at_alpha_10": {
            "value": cl,
            "source": {"kind": "file_extract", "path": str(fpath),
                       "extract": f"grep -v '^#' | tail -1 | awk '{{print ${cl_col}}}'"},
        },
        "CD_at_alpha_10": {
            "value": cd,
            "source": {"kind": "file_extract", "path": str(fpath),
                       "extract": f"grep -v '^#' | tail -1 | awk '{{print ${cd_col}}}'"},
        },
    }

    sub = Path(os.environ.get("SIM_BENCH_SUBMISSION", "/tmp/agent/submission"))
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "results.csv").write_text(
        "CL_at_alpha_10,CD_at_alpha_10\n" + f"{result["CL_at_alpha_10"]["value"]:.9g}, {result["CD_at_alpha_10"]["value"]:.9g}\n", encoding="utf-8")
    out = Path("/tmp/agent/result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v["value"] for k, v in result.items()}, indent=2))
    print(f"[oracle] finished in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
