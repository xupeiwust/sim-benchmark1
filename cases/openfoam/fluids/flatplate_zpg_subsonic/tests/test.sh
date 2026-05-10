#!/usr/bin/env bash
# Paths come from sim_benchmark_verifier.contract — single source of truth.
set -euo pipefail
exec python3 -m sim_benchmark_verifier.score
