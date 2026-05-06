#!/usr/bin/env bash
set -euo pipefail
cd /root/case 2>/dev/null || true
exec python3 -m sim_benchmark_verifier.score
