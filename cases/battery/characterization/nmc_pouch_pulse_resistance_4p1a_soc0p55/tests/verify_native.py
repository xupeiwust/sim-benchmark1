#!/usr/bin/env python3
"""Thin per-case entry point.

All behaviour lives in the shared evaluator; this case contributes only its
spec.json and kpis.json. Adding a new operating point or a new cell means
editing the generator's table, not writing another grader.
"""
from pathlib import Path

from sim_benchmark_verifier.native_pybamm import main_from_case

if __name__ == "__main__":
    raise SystemExit(main_from_case(Path(__file__).resolve().parent))
