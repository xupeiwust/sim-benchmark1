#!/usr/bin/env python3
"""Build NACA 4412 airfoil OBJ for snappyHexMesh.

NACA 4-digit construction:
  m = 0.04 (4% max camber)
  p = 0.4  (max camber at 40% chord)
  t = 0.12 (12% max thickness)

Camber line:
  y_c = (m/p^2) * (2 p x - x^2),               x in [0, p]
  y_c = (m/(1-p)^2)*((1-2p) + 2 p x - x^2),    x in [p, 1]

Thickness distribution (closed-TE variant):
  y_t = (t/0.2) * (0.2969 sqrt(x)
                  - 0.1260 x
                  - 0.3516 x^2
                  + 0.2843 x^3
                  - 0.1036 x^4)

Surface (with camber rotation):
  x_u = x - y_t sin(theta);  y_u = y_c + y_t cos(theta)
  x_l = x + y_t sin(theta);  y_l = y_c - y_t cos(theta)
  where theta = atan(dy_c / dx)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

M = 0.04
P = 0.4
T = 0.12


def y_camber(x: float) -> float:
    if x <= P:
        return (M / P ** 2) * (2 * P * x - x ** 2)
    return (M / (1 - P) ** 2) * ((1 - 2 * P) + 2 * P * x - x ** 2)


def dy_camber_dx(x: float) -> float:
    if x <= P:
        return (M / P ** 2) * (2 * P - 2 * x)
    return (M / (1 - P) ** 2) * (2 * P - 2 * x)


def y_thickness(x: float) -> float:
    # Closed-TE NACA 4-digit (last coefficient -0.1036 instead of -0.1015 for sharp TE).
    return (T / 0.2) * (
        0.2969 * math.sqrt(max(x, 0.0))
        - 0.1260 * x
        - 0.3516 * x * x
        + 0.2843 * x ** 3
        - 0.1036 * x ** 4
    )


def airfoil_loop(n_per_side: int = 150) -> list[tuple[float, float]]:
    """CCW closed loop: TE -> upper -> LE -> lower -> TE."""
    pts: list[tuple[float, float]] = []
    # Upper surface from TE (i=0, xc=1) to LE (i=n, xc=0)
    for i in range(n_per_side + 1):
        xc = 0.5 * (1.0 + math.cos(math.pi * i / n_per_side))
        yc = y_camber(xc)
        yt = y_thickness(xc)
        theta = math.atan(dy_camber_dx(xc))
        x = xc - yt * math.sin(theta)
        y = yc + yt * math.cos(theta)
        pts.append((x, y))
    # Lower surface from LE (i=1) to TE (i=n_per_side - 1) — exclude shared LE+TE.
    for i in range(1, n_per_side):
        xc = 0.5 * (1.0 - math.cos(math.pi * i / n_per_side))
        yc = y_camber(xc)
        yt = y_thickness(xc)
        theta = math.atan(dy_camber_dx(xc))
        x = xc + yt * math.sin(theta)
        y = yc - yt * math.cos(theta)
        pts.append((x, y))
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
    pts = airfoil_loop(n_per_side=150)
    write_obj(out, pts, thickness=1.0)
    print(f"[gen_airfoil_stl] {len(pts)} points -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
