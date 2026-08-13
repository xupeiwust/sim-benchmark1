#!/usr/bin/env python3
"""Report the average hot-wall Nusselt number for this run.

One way to satisfy the contract, not the required way. Nu is the wall-normal
temperature gradient integrated over the hot wall and divided by that wall's own
area -- and the area is the point. The prompt fixes the unit square and leaves
the spanwise slab thickness free, as it must for a 2D problem, so the wall area
is a property of this mesh. Normalising by someone else's scored a 0.01 slab
exactly ten times too low (#21); normalising by your own cannot.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "log.gradTwall"


def parse(pattern: str) -> float:
    if not LOG.is_file():
        sys.exit(f"{LOG} missing -- the surfaceFieldValue function object did not run")
    value = None
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.search(pattern, line) and "=" in line:
            numbers = re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", line.split("=", 1)[1])
            if numbers:
                value = float(numbers[0])
    if value is None or not math.isfinite(value):
        sys.exit(f"could not parse a finite value matching {pattern!r} from {LOG.name}")
    return value


def main() -> int:
    integral = parse(r"areaIntegrate.*grad\(T\)")
    area = parse(r"\barea\b")
    if area <= 0:
        sys.exit(f"hot-wall area {area:.6g} is not positive")
    nu = abs(integral) / area
    (HERE / "results.csv").write_text(f"nu_avg_hot_wall\n{nu:.9g}\n", encoding="utf-8")
    print(f"nu_avg_hot_wall = {nu:.6f}  (integral {integral:.6g} over area {area:.6g})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
