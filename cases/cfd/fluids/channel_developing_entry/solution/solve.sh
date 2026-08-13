#!/usr/bin/env bash
# Oracle entry point for channel_developing_entry.
#
# This script proves the case is solvable with the toolchain in
# sim-benchmark-base. It goes through the same sim-cli path the agent
# must take, so the run_record.json produced here is structurally
# identical to what an agent would emit — the grader's authenticity
# check works unmodified.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
WORK="${AGENT_WORKDIR:-/tmp/agent}"
CASE_RUN="$WORK/submission"

# Copy the reference OpenFOAM case into the working location.
mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"

export ORACLE_CASE="$CASE_RUN"

# solve_inner.py shells out to blockMesh + simpleFoam, samples the
# centerline velocity, and writes /tmp/agent/result.json.
exec python3 "$HERE/solve_inner.py"
