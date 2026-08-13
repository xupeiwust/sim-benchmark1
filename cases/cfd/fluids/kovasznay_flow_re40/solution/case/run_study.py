#!/usr/bin/env python3
"""Reference solution: solve the Kovasznay flow on three grids and report the error.

This is one way to satisfy the contract, not the required way. It builds a
uniform mesh at each refinement level from the template in this directory, runs
`simpleFoam`, reads back the converged `U` field and the mesh's own cell centres,
and writes `grid_convergence.csv` in the submission root.

Cell centres come from `writeCellCentres` rather than from arithmetic on the
grid spacing. For a uniform mesh the two agree, but reading the mesh's own
answer is what keeps the error norm honest if the mesh is ever not what was
intended -- an arithmetic centre would silently compare the right exact value
against the wrong cell.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEVELS = (20, 40, 80)

RE = 40.0
LAM = RE / 2.0 - math.sqrt(RE * RE / 4.0 + 4.0 * math.pi**2)
X0, X1 = 0.0, 1.0
Y0, Y1 = -0.5, 0.5


def exact_u(x: float, y: float) -> float:
    return 1.0 - math.exp(LAM * x) * math.cos(2.0 * math.pi * y)


def block_mesh_dict(n: int) -> str:
    return f"""FoamFile {{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}

scale 1;

// One-cell-thick slab in z: the problem is two-dimensional and the spanwise
// faces are `empty`. The thickness is arbitrary and nothing scored depends on
// it -- the norm is over cell centres in the x-y plane.
vertices
(
    ({X0} {Y0} 0) ({X1} {Y0} 0) ({X1} {Y1} 0) ({X0} {Y1} 0)
    ({X0} {Y0} 0.01) ({X1} {Y0} 0.01) ({X1} {Y1} 0.01) ({X0} {Y1} 0.01)
);

blocks ( hex (0 1 2 3 4 5 6 7) ({n} {n} 1) simpleGrading (1 1 1) );

boundary
(
    sides
    {{
        type patch;
        faces
        (
            (0 4 7 3)   // x = {X0}
            (1 2 6 5)   // x = {X1}
            (0 1 5 4)   // y = {Y0}
            (3 7 6 2)   // y = {Y1}
        );
    }}
    frontAndBack
    {{
        type empty;
        faces ( (0 3 2 1) (4 5 6 7) );
    }}
);
"""


def run(case: Path, command: str) -> None:
    result = subprocess.run(
        f"cd {case} && {command}", shell=True, capture_output=True, text=True,
    )
    (case / f"log.{command.split()[0]}").write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    if result.returncode != 0:
        sys.stderr.write(f"FAIL: {command} in {case}\n{result.stdout[-2000:]}{result.stderr[-2000:]}\n")
        raise SystemExit(1)


_LIST = re.compile(r"internalField\s+nonuniform\s+List<(\w+)>\s*\n?\s*(\d+)\s*\(", re.S)


def read_internal_field(path: Path) -> list[tuple[float, ...]]:
    """Parse an OpenFOAM ascii volField's internal values.

    A `uniform` internal field is a legitimate answer shape but never a solved
    one, so it is rejected here rather than silently read as a single value.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    match = _LIST.search(text)
    if not match:
        raise SystemExit(f"{path} has no nonuniform internalField; the solve did not write one")
    count = int(match.group(2))
    body = text[match.end():]
    values: list[tuple[float, ...]] = []
    if match.group(1) == "scalar":
        for token in body.split(")", 1)[0].split():
            values.append((float(token),))
    else:
        for entry in re.finditer(r"\(([^()]*)\)", body):
            values.append(tuple(float(v) for v in entry.group(1).split()))
            if len(values) == count:
                break
    if len(values) != count:
        raise SystemExit(f"{path}: header says {count} values, parsed {len(values)}")
    return values


def latest_time(case: Path) -> Path:
    times = []
    for child in case.iterdir():
        if not child.is_dir():
            continue
        try:
            value = float(child.name)
        except ValueError:
            continue
        if value > 0 and (child / "U").is_file():
            times.append((value, child))
    if not times:
        raise SystemExit(f"{case}: no non-zero time directory with U -- the solver did not run")
    return max(times)[1]


def solve_level(n: int) -> float:
    case = HERE / f"grid{n}"
    shutil.rmtree(case, ignore_errors=True)
    case.mkdir(parents=True)
    for item in ("0", "constant", "system"):
        shutil.copytree(HERE / item, case / item)
    (case / "system" / "blockMeshDict").write_text(block_mesh_dict(n), encoding="utf-8")

    run(case, "blockMesh")
    run(case, "checkMesh -constant")
    run(case, "simpleFoam")

    time_dir = latest_time(case)
    run(case, f"postProcess -func writeCellCentres -time {time_dir.name}")

    u = read_internal_field(time_dir / "U")
    centres = read_internal_field(time_dir / "C")
    if len(u) != len(centres):
        raise SystemExit(f"grid{n}: {len(u)} velocities against {len(centres)} cell centres")

    total = sum((value[0] - exact_u(c[0], c[1])) ** 2 for value, c in zip(u, centres))
    return math.sqrt(total / len(u))


def main() -> int:
    rows = []
    for n in LEVELS:
        error = solve_level(n)
        rows.append((n, 1.0 / n, error))
        print(f"grid {n}x{n}: h={1.0/n:.6g} l2_error_u={error:.6e}", flush=True)

    out = HERE / "grid_convergence.csv"
    with out.open("w", encoding="utf-8") as handle:
        handle.write("n_cells_per_side,h,l2_error_u\n")
        for n, h, error in rows:
            handle.write(f"{n},{h:.10g},{error:.10e}\n")

    # Printed, not scored: the evaluator fits the slope itself from the file.
    # Having it in the log is what makes a failed run diagnosable at a glance.
    for (n0, h0, e0), (n1, h1, e1) in zip(rows, rows[1:]):
        print(f"observed order {n0}->{n1}: {math.log(e0/e1)/math.log(h0/h1):.4f}", flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
