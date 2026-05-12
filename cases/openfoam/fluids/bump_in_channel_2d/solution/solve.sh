#!/usr/bin/env bash
# Oracle entry point for bump_in_channel_2d.
#
# Drives OpenFOAM through sim-cli so the run is recorded structurally
# the same way an agent's run would be. The Python orchestrator runs
# blockMesh + simpleFoam + post-processing, then writes
# /tmp/agent/result.json with file_extract provenance.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"

mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"

# blockMeshDict ships pre-generated; if the gen script is present and
# the user wants to regenerate, they can run it manually. Skipping at
# oracle time keeps the run deterministic.

export ORACLE_CASE="$CASE_RUN"

exec sim run --solver openfoam "$HERE/solve_inner.py"
