#!/usr/bin/env python3
"""Sample the channel centreline and report the velocity ratio at x = 1.

One way to satisfy the contract, not the required way. The sampling line is in
system/centerline and runs at this case's own spanwise position, which is the
point: where to sample a 2D slab is the submission's business.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATION = 1.0


def profile() -> list[tuple[float, float]]:
    hits = sorted(HERE.glob("postProcessing/centerline/*/centerline_U.xy")) \
        or sorted(HERE.glob("postProcessing/centerline/*/centerline_U.raw"))
    if not hits:
        sys.exit("no postProcessing/centerline output -- the sampling did not run")
    path = max(hits, key=lambda p: float(p.parent.name))
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.replace("(", " ").replace(")", " ").split()
        if len(parts) >= 2:
            rows.append((float(parts[0]), float(parts[1])))
    rows.sort()
    if len(rows) < 100:
        sys.exit(f"{path}: only {len(rows)} centreline samples")
    return rows


def main() -> int:
    rows = profile()
    value = None
    for (x0, u0), (x1, u1) in zip(rows, rows[1:]):
        if x0 <= STATION <= x1:
            value = u0 + (u1 - u0) * (STATION - x0) / (x1 - x0)
            break
    if value is None:
        sys.exit(f"the sampled centreline does not bracket x = {STATION}")
    (HERE / "results.csv").write_text(
        f"u_centerline_ratio\n{value:.9g}\n", encoding="utf-8")
    print(f"u_centerline_ratio = {value:.6f} from {len(rows)} samples", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
