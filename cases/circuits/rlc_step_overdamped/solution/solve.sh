#!/usr/bin/env bash
set -euo pipefail
HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"
mkdir -p "$CASE_RUN" /tmp/agent
cp -r "$HERE/case"/. "$CASE_RUN/"

cd "$CASE_RUN"
cp rlc_step_overdamped.net rlcstep.net
sim run --solver ltspice rlcstep.net
python3 "$HERE/build_result.py"
