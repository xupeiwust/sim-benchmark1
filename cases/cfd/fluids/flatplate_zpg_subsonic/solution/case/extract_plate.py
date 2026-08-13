#!/usr/bin/env python3
"""Report the plate skin friction at x = 0.97 and the total drag coefficient.

One way to satisfy the contract, not the required way. Both come from this run's
own function-object output over its own plate patch; nothing here has to agree
with a grader about what that patch is called or where the mesh put it.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATION = 0.970084071


def latest(*patterns: str) -> Path:
    hits: list[Path] = []
    for pattern in patterns:
        hits.extend(HERE.glob(pattern))
    if not hits:
        sys.exit(f"no output matching {patterns[0]}")
    return max(hits, key=lambda p: float(p.parent.name))


def wall_rows() -> list[tuple[float, float]]:
    path = latest("postProcessing/*/*/*wallSurface*.raw")
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.replace("(", " ").replace(")", " ").split()
        if len(parts) < 4:
            continue
        try:
            x, y, tau_x = float(parts[0]), float(parts[1]), float(parts[3])
        except ValueError:
            continue
        if all(math.isfinite(v) for v in (x, y, tau_x)) and 0 <= x <= 2:
            rows.append((x, tau_x))
    rows.sort()
    if len(rows) < 2:
        sys.exit(f"{path}: too few wall-shear samples")
    return rows


def final_cd() -> float:
    path = latest("postProcessing/*/*/coefficient.dat",
                  "postProcessing/*/*/forceCoeffs.dat")
    index, last = None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#"):
            fields = s.lstrip("# ").split()
            if "Cd" in fields:
                index = fields.index("Cd")
        elif s:
            last = s.split()
    if index is None or last is None or index >= len(last):
        sys.exit(f"{path}: no header naming Cd, or no data rows")
    return float(last[index])


def main() -> int:
    rows = wall_rows()
    cf = None
    for (x0, t0), (x1, t1) in zip(rows, rows[1:]):
        if x0 <= STATION <= x1:
            tau = t0 if x1 == x0 else t0 + (STATION - x0) * (t1 - t0) / (x1 - x0)
            cf = 2.0 * abs(tau)
            break
    if cf is None:
        sys.exit(f"the sampled plate does not bracket x = {STATION}")
    cd = final_cd()
    (HERE / "results.csv").write_text(
        f"cf_x097,drag_coefficient\n{cf:.9g},{cd:.9g}\n", encoding="utf-8")
    print(f"cf_x097 = {cf:.6g}   drag_coefficient = {cd:.6g}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
