#!/usr/bin/env python3
"""Thin per-case entry point.

All behaviour lives in the shared track evaluator; this case contributes only
its spec.json and kpis.json. A case that needs code here has an interface
problem, not a grading problem.
"""
from pathlib import Path

from sim_benchmark_verifier.openfoam_interface import main_from_case

if __name__ == "__main__":
    raise SystemExit(main_from_case(Path(__file__).resolve().parent))
