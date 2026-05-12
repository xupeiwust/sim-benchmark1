#!/usr/bin/env bash
# Oracle entry point for nasa_hump_separated.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"

mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"

export ORACLE_CASE="$CASE_RUN"

exec sim run --solver openfoam "$HERE/solve_inner.py"
