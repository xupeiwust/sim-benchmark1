#!/usr/bin/env bash
# Oracle entry point for flatplate_zpg_subsonic.
#
# This script proves the case is solvable with the toolchain in
# sim-benchmark-base. It goes through the same sim-cli path the agent
# must take, so the run_record.json produced here is structurally
# identical to what an agent would emit — the grader's authenticity
# check works unmodified.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"

# Copy the reference OpenFOAM case into the working location.
mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"

export ORACLE_CASE="$CASE_RUN"

# Drive OpenFOAM through sim-cli so it records the run in $SIM_DIR/runs/.
# solve_inner.py shells out to blockMesh + simpleFoam, parses the
# wall-shear and drag outputs, and writes /tmp/agent/result.json.
exec sim run --solver openfoam "$HERE/solve_inner.py"
