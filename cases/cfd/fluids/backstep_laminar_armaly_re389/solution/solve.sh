#!/usr/bin/env bash
# Oracle entry point for backstep_laminar_armaly_re389.
#
# Drives OpenFOAM through sim-cli so the run is recorded structurally
# the same way an agent's run would be. The Python orchestrator runs
# blockMesh + simpleFoam (laminar) + post-processing, then writes
# /tmp/agent/result.json with file_extract provenance.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
WORK="${AGENT_WORKDIR:-/tmp/agent}"
CASE_RUN="$WORK/submission"

mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"

export ORACLE_CASE="$CASE_RUN"

exec python3 "$HERE/solve_inner.py"
