#!/usr/bin/env python3
"""Report the peak |Ux| in the final field.

One way to satisfy the contract, not the required way: it reads this run's own
last time directory, so nothing about where the fields are has to be agreed with
a grader beyond the file this writes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def latest_time() -> Path:
    times = [p for p in HERE.iterdir() if p.is_dir() and (p / "U").is_file()]
    times = [p for p in times if _as_float(p.name) is not None and _as_float(p.name) > 0]
    if not times:
        sys.exit("no non-zero time directory holding U -- the solver did not run")
    return max(times, key=lambda p: float(p.name))


def _as_float(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    path = latest_time() / "U"
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"internalField\s+nonuniform\s+List<vector>\s+\d+\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        sys.exit(f"{path}: no nonuniform internalField -- a uniform field is not a solved one")
    vectors = re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", match.group(1))
    if not vectors:
        sys.exit(f"{path}: could not parse any velocity vectors")
    peak = max(abs(float(v[0])) for v in vectors)
    (HERE / "results.csv").write_text(f"u_peak_at_tstar\n{peak:.9g}\n", encoding="utf-8")
    print(f"u_peak_at_tstar = {peak:.6f} over {len(vectors)} cells (t = {path.parent.name})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
