#!/usr/bin/env bash
# Paths come from sim_benchmark_verifier.contract — single source of truth.
# cd into /root/case first: sim-cli's `sim --json logs <id>` filters runs by
# CWD, and the verifier needs to fetch run stdout via that command. Without
# the cd, the verifier sees the run record but can't fetch its stdout for
# source-extract verification → all KPIs score 0.
set -euo pipefail
cd /root/case 2>/dev/null || true
exec python3 -m sim_benchmark_verifier.score
