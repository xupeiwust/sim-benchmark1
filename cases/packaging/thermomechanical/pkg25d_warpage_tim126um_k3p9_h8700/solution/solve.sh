#!/usr/bin/env bash
# Oracle: produce a reference submission that scores ~1.0.
set -euo pipefail
HERE="$(dirname "$(realpath "$0")")"
SUB="${SIM_BENCH_SUBMISSION:-/tmp/agent/submission}"
mkdir -p "$SUB"
cp "$HERE/pkg25d.py" "$HERE/case.json" "$HERE/run_case.sh" "$SUB/"
chmod +x "$SUB/run_case.sh"
cd "$SUB"
bash ./run_case.sh
