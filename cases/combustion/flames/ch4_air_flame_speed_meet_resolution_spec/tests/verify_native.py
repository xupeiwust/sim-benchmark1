#!/usr/bin/env python3
"""Thin per-case entry point.

All behaviour lives in the shared evaluator; this case contributes only its
spec.json and kpis.json. The resolution ladder this case's contract adds is a
`resolution_spec` block in spec.json, not code here.
"""
import sys
from pathlib import Path

from sim_benchmark_verifier.native_cantera import main_from_case

if __name__ == "__main__":
    raise SystemExit(main_from_case(Path(__file__).resolve().parent))
