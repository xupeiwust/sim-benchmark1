#!/usr/bin/env python3
"""Report the reattachment length for this backward-facing-step run.

One way to satisfy the contract, not the required way. The downstream floor is
found from the sampled faces themselves -- it is the lowest wall at x >= 0 --
rather than from a patch name, because what a boundary is called is this
submission's choice and what it *does* is the geometry.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEP_HEIGHT = 0.0049


def main() -> int:
    hits = sorted(HERE.glob("postProcessing/*/*/*wallSurface*.raw"))
    if not hits:
        sys.exit("no postProcessing/wallSurface output -- the sampling did not run")
    path = max(hits, key=lambda p: float(p.parent.name))

    downstream = []
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
        if all(math.isfinite(v) for v in (x, y, tau_x)) and x >= -1e-8:
            downstream.append((x, y, tau_x))
    if not downstream:
        sys.exit(f"{path}: no downstream wall faces")

    floor = min(y for _x, y, _t in downstream)
    rows = sorted((x / STEP_HEIGHT, -2.0 * tau_x)
                  for x, y, tau_x in downstream
                  if abs(y - floor) <= 1e-3 * STEP_HEIGHT)

    previous = None
    for xh, cf in rows:
        if not 0.5 <= xh <= 30:
            previous = (xh, cf)
            continue
        if previous and previous[1] < 0 <= cf:
            x0, c0 = previous
            value = xh if cf == c0 else x0 - c0 * (xh - x0) / (cf - c0)
            (HERE / "results.csv").write_text(
                f"reattachment_length_xr_over_h\n{value:.9g}\n", encoding="utf-8")
            print(f"reattachment_length_xr_over_h = {value:.4f} from {len(rows)} floor faces", flush=True)
            return 0
        previous = (xh, cf)
    sys.exit("no negative-to-positive wall-shear crossing on the downstream floor")


if __name__ == "__main__":
    raise SystemExit(main())
