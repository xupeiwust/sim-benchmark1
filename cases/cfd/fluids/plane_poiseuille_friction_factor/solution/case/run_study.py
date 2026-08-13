#!/usr/bin/env python3
"""Reference solution: solve the plane channel on three grids and report the error.

This is one way to satisfy the contract, not the required way. It builds a
uniform mesh at each refinement level from the template in this directory, runs
`simpleFoam` to a residual floor, reads back the converged `U` field and the
mesh's own cell centres, and writes `grid_convergence.csv` in the submission
root.

Two choices here are load-bearing and both were measured rather than assumed
(#199).

Cell centres come from `writeCellCentres` rather than from arithmetic on the
grid spacing. For a uniform mesh the two agree, but reading the mesh's own
answer is what keeps the error norm honest if the mesh is ever not what was
intended -- an arithmetic centre would silently compare the right exact value
against the wrong cell.

The norm is taken on the profile **normalised by its own bulk mean**, not on the
raw velocity. The bulk mean this pressure-driven channel settles at is itself
grid-dependent (1.00125 / 1.00031 / 1.00008 on the three grids), so a raw norm
against a unit-mean parabola measures the flow-rate error rather than the
profile's, and the two are different quantities that happen to share an order
here. Normalising also makes the number independent of how the channel was
driven at all: imposing the exact parabola at the inlet instead of a pressure
difference reproduces this norm to seven significant figures.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (streamwise, wall-normal) cell counts. Fixed by the task: the observed order
# is only meaningful against the grid family the prompt names.
LEVELS = ((60, 20), (120, 40), (240, 80))

D = 1.0            # channel full gap; walls at y = -D/2 and y = +D/2
LENGTH = 30.0      # streamwise extent
STATION = 20.0     # where the profile is sampled -- fully developed here


def block_mesh_dict(nx: int, ny: int) -> str:
    return f"""FoamFile {{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}

scale 1;

// One-cell-thick slab in z: the problem is two-dimensional and the spanwise
// faces are `empty`. The thickness is arbitrary and nothing scored depends on
// it -- the norm is over a wall-normal column of cell centres.
vertices
(
    (0 {-D / 2} 0) ({LENGTH} {-D / 2} 0) ({LENGTH} {D / 2} 0) (0 {D / 2} 0)
    (0 {-D / 2} 0.1) ({LENGTH} {-D / 2} 0.1) ({LENGTH} {D / 2} 0.1) (0 {D / 2} 0.1)
);

blocks ( hex (0 1 2 3 4 5 6 7) ({nx} {ny} 1) simpleGrading (1 1 1) );

boundary
(
    inlet      {{ type patch; faces ((0 4 7 3)); }}
    outlet     {{ type patch; faces ((1 2 6 5)); }}
    bottomWall {{ type wall;  faces ((0 1 5 4)); }}
    topWall    {{ type wall;  faces ((3 7 6 2)); }}
    frontAndBack {{ type empty; faces ((0 3 2 1) (4 5 6 7)); }}
);
"""


def run(case: Path, command: str) -> str:
    result = subprocess.run(
        f"cd {case} && {command}", shell=True, capture_output=True, text=True,
    )
    (case / f"log.{command.split()[0]}").write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"FAIL: {command} in {case}\n{result.stdout[-2000:]}{result.stderr[-2000:]}\n")
        raise SystemExit(1)
    return result.stdout + result.stderr


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


def exact_normalised(y: float) -> float:
    """The fully developed profile divided by its own bulk mean."""
    return 1.5 * (1.0 - (2.0 * y / D) ** 2)


def profile_error(cells: list[tuple[float, float, float]], n_y: int) -> float:
    """Grid-normalised L2 norm of the normalised-profile error at the station."""
    xs = sorted({round(x, 9) for x, _, _ in cells})
    x_col = min(xs, key=lambda v: abs(v - STATION))
    column = sorted((y, u) for x, y, u in cells if abs(x - x_col) < 1e-9)
    if len(column) != n_y:
        raise SystemExit(
            f"station x={x_col} holds {len(column)} cells, expected {n_y}")

    # Bulk mean by the trapezoidal rule, closed at both walls where no-slip
    # makes u = 0 exact.
    ys = [-D / 2] + [y for y, _ in column] + [D / 2]
    us = [0.0] + [u for _, u in column] + [0.0]
    u_mean = sum(0.5 * (us[i] + us[i + 1]) * (ys[i + 1] - ys[i])
                 for i in range(len(ys) - 1)) / D
    if u_mean <= 0.0:
        raise SystemExit(f"bulk mean velocity came out {u_mean}; the solve is not a channel flow")

    total = sum((u / u_mean - exact_normalised(y)) ** 2 for y, u in column)
    return math.sqrt(total / len(column))


def solve_level(nx: int, ny: int) -> float:
    case = HERE / f"grid{nx}x{ny}"
    shutil.rmtree(case, ignore_errors=True)
    case.mkdir(parents=True)
    for item in ("0", "constant", "system"):
        shutil.copytree(HERE / item, case / item)
    (case / "system" / "blockMeshDict").write_text(block_mesh_dict(nx, ny), encoding="utf-8")

    run(case, "blockMesh")
    run(case, "checkMesh -constant")
    log = run(case, "simpleFoam")
    # The prompt requires each level to be converged far enough that iteration
    # error is small next to discretisation error. `residualControl` is how this
    # case asks for that, so a run that hit the iteration cap instead has not
    # satisfied it and must not be quietly reported as if it had.
    if "SIMPLE solution converged" not in log:
        raise SystemExit(
            f"grid {nx}x{ny}: simpleFoam hit its iteration cap without meeting "
            f"residualControl; the reported error would be the stopping "
            f"criterion rather than the discretisation")

    time_dir = latest_time(case)
    run(case, f"postProcess -func writeCellCentres -time {time_dir.name}")

    u = read_internal_field(time_dir / "U")
    centres = read_internal_field(time_dir / "C")
    if len(u) != len(centres):
        raise SystemExit(f"grid {nx}x{ny}: {len(u)} velocities against {len(centres)} cell centres")

    cells = [(c[0], c[1], value[0]) for value, c in zip(u, centres)]
    return profile_error(cells, ny)


def main() -> int:
    rows = []
    for nx, ny in LEVELS:
        error = solve_level(nx, ny)
        rows.append((ny, D / ny, error))
        print(f"grid {nx}x{ny}: h={D/ny:.6g} l2_error={error:.6e}", flush=True)

    out = HERE / "grid_convergence.csv"
    with out.open("w", encoding="utf-8") as handle:
        handle.write("n_cells_wall_normal,h,l2_error\n")
        for ny, h, error in rows:
            handle.write(f"{ny},{h:.10g},{error:.10e}\n")

    # Printed, not scored: the evaluator fits the slope itself from the file.
    # Having it in the log is what makes a failed run diagnosable at a glance.
    for (n0, h0, e0), (n1, h1, e1) in zip(rows, rows[1:]):
        print(f"observed order {n0}->{n1}: {math.log(e0/e1)/math.log(h0/h1):.4f}", flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
