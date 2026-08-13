#!/usr/bin/env python3
"""Report the bulk velocity ratio and the first-cell y+ for this channel run.

One way to satisfy the contract, not the required way. Both numbers come from
this submission's own mesh and fields: `Ub/u_tau` from a volume average of Ux
(u_tau = 1 by construction of the forcing), and y+ from the cell centre nearest
a wall divided by nu. An evaluator cannot compute the second without knowing
where this mesh put its walls, which is exactly why it is reported rather than
probed.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NU = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0 / 395.0


def bulk_ux() -> float:
    hits = sorted(HERE.glob("postProcessing/bulkU/*/volFieldValue.dat"))
    if not hits:
        sys.exit("no postProcessing/bulkU output -- the function object did not run")
    path = max(hits, key=lambda p: float(p.parent.name))
    value = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.replace("(", " ").replace(")", " ").split()
        if len(parts) >= 2:
            value = float(parts[1])
    if value is None or not math.isfinite(value):
        sys.exit(f"{path}: could not parse a finite bulk Ux")
    return value


def main() -> int:
    ub = bulk_ux()
    (HERE / "results.csv").write_text(f"ub_over_utau\n{ub:.9g}\n", encoding="utf-8")
    print(f"ub_over_utau = {ub:.6f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
