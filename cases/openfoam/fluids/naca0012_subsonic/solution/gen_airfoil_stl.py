#!/usr/bin/env python3
"""Build NACA 0012 airfoil OBJ for snappyHexMesh.

Closed-form NACA 0012 with sharp TE:
  y/c = 0.594689181 * [ 0.298222773 sqrt(x/c)
                      - 0.127125232 (x/c)
                      - 0.357907906 (x/c)^2
                      + 0.291984971 (x/c)^3
                      - 0.105174606 (x/c)^4 ]

Writes a closed prism (lateral wall + top/bottom caps) extending z in
[-0.5, +0.5] m so the airfoil sticks out of the 0.1 m background slab.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path


def naca0012(xc: float) -> float:
    return 0.594689181 * (
        0.298222773 * math.sqrt(xc)
        - 0.127125232 * xc
        - 0.357907906 * xc * xc
        + 0.291984971 * xc ** 3
        - 0.105174606 * xc ** 4
    )


def airfoil_loop(n_per_side: int = 120) -> list[tuple[float, float]]:
    """CCW closed loop: TE -> upper -> LE -> lower -> TE.

    Use cosine spacing for clustering near LE/TE.
    """
    pts: list[tuple[float, float]] = []
    # Upper surface from TE to LE (excluding LE because it's a vertex shared with lower).
    for i in range(n_per_side + 1):
        # cosine: i=0 -> xc=1 (TE), i=n -> xc=0 (LE)
        xc = 0.5 * (1.0 + math.cos(math.pi * i / n_per_side))
        pts.append((xc, +naca0012(xc)))
    # Lower surface from LE to TE (skip LE since just added; skip TE since first point).
    for i in range(1, n_per_side):
        xc = 0.5 * (1.0 - math.cos(math.pi * i / n_per_side))
        pts.append((xc, -naca0012(xc)))
    return pts


def write_obj(out: Path, pts2d: list[tuple[float, float]], thickness: float = 1.0) -> None:
    half = thickness / 2.0
    n = len(pts2d)
    lines: list[str] = ["o airfoil"]
    for x, y in pts2d:
        lines.append(f"v {x:.10f} {y:.10f} {-half:.10f}")
    for x, y in pts2d:
        lines.append(f"v {x:.10f} {y:.10f} {+half:.10f}")
    for i in range(n):
        i0 = i + 1
        i1 = (i + 1) % n + 1
        j0 = i0 + n
        j1 = i1 + n
        lines.append(f"f {i0} {i1} {j1}")
        lines.append(f"f {i0} {j1} {j0}")
    for i in range(1, n - 1):
        lines.append(f"f 1 {i + 2} {i + 1}")
    base = n + 1
    for i in range(1, n - 1):
        lines.append(f"f {base} {base + i} {base + i + 1}")
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    here = Path(__file__).resolve().parent
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (here / "case" / "constant" / "triSurface" / "airfoil.obj")
    out.parent.mkdir(parents=True, exist_ok=True)
    pts = airfoil_loop(n_per_side=120)
    write_obj(out, pts, thickness=1.0)
    print(f"[gen_airfoil_stl] {len(pts)} points -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
