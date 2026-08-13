#!/usr/bin/env python3
"""Sample the vertical centreline and write results.csv.

One way to satisfy the contract, not the required way. The sampling line lives
in system/centerline and runs at this case's own spanwise position -- which is
the point: the slab is a free choice in a 2D problem, so where to sample it is
the submission's business and not something a grader can know.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def latest_profile() -> Path:
    hits = sorted(HERE.glob("postProcessing/centerline/*/verticalCenterline_U.xy")) \
        or sorted(HERE.glob("postProcessing/centerline/*/verticalCenterline_U.raw"))
    if not hits:
        sys.exit("no postProcessing/centerline output -- the sampling did not run")
    return max(hits, key=lambda p: float(p.parent.name))


def main() -> int:
    path = latest_profile()
    values = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.replace("(", " ").replace(")", " ").split()
        if len(parts) >= 4:
            values.append(float(parts[1]))
    if len(values) < 50:
        sys.exit(f"{path}: only {len(values)} centreline samples; the profile is not resolved")
    u_min = min(values)
    (HERE / "results.csv").write_text(
        f"u_min_vertical_centerline\n{u_min:.9g}\n", encoding="utf-8")
    print(f"u_min = {u_min:.6f} over {len(values)} samples", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
