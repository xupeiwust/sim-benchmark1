#!/usr/bin/env python3
"""Read the converged drag coefficient out of this run and write results.csv.

One way to satisfy the contract, not the required way. The normalisation lives
in system/controlDict's forceCoeffs block -- Aref = D * span -- and it is this
submission's own business: a case built with a different slab thickness needs a
different Aref, which is precisely what an evaluator cannot guess on the
submission's behalf.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def coefficient_file() -> Path:
    hits = sorted(HERE.glob("postProcessing/forceCoeffs1/*/coefficient.dat")) \
        or sorted(HERE.glob("postProcessing/forceCoeffs1/*/forceCoeffs.dat"))
    if not hits:
        sys.exit("no postProcessing/forceCoeffs1/*/coefficient.dat -- forceCoeffs did not run")
    return max(hits, key=lambda p: float(p.parent.name))


def main() -> int:
    path = coefficient_file()
    header, last = None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#"):
            if "Cd" in line.split():
                header = line.lstrip("# ").split()
            continue
        if line.strip():
            last = line.split()
    if header is None or last is None:
        sys.exit(f"{path}: no header naming Cd, or no data rows")
    try:
        column = header.index("Cd")
    except ValueError:
        sys.exit(f"{path}: header {header} does not name Cd")

    cd = float(last[column])
    (HERE / "results.csv").write_text(f"cd\n{cd:.9g}\n", encoding="utf-8")
    print(f"cd = {cd:.6f}  (from {path.relative_to(HERE)}, t = {last[0]})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
