#!/usr/bin/env bash
# Oracle: produce a reference submission that scores ~1.0.
set -euo pipefail
HERE="$(dirname "$(realpath "$0")")"
SUB="${SIM_BENCH_SUBMISSION:-/tmp/agent/submission}"
mkdir -p "$SUB"
# One line, no continuation: `lint_case._submission_sources` reads the `cp`
# lines out of this script to learn what the submission is built from, and it
# matches per line -- a backslash continuation makes the destination read as
# `\` and the whole copy invisible to it.
cp "$HERE/pkg25d.py" "$HERE/case_baseline.json" "$HERE/case_modified.json" "$HERE/run_case.sh" "$SUB/"
chmod +x "$SUB/run_case.sh"
cd "$SUB"
bash ./run_case.sh
