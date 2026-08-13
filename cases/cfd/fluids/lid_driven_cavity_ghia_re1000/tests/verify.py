#!/usr/bin/env python3
"""Thin per-case entry point. All behaviour is in the shared track evaluator."""
from pathlib import Path

from sim_benchmark_verifier.openfoam_interface import main_from_case

if __name__ == "__main__":
    raise SystemExit(main_from_case(Path(__file__).resolve().parent))
