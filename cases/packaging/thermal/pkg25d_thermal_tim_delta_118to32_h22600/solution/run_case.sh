#!/usr/bin/env bash
# Re-runs BOTH configurations from the files beside this script and rewrites
# results.csv as one two-row table.
#
# Two runs and not one, because the scored quantity is the difference between
# them. `pkg25d.py` reads `case.json` and overwrites a one-row `results.csv`, so
# each configuration's row is read back into a variable before the next run
# clobbers the file, and the whole table is written once at the end.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"

rows=""
for cfg in baseline modified; do
    rm -rf run analysis results.csv
    cp "case_${cfg}.json" case.json
    python3 pkg25d.py 1.0
    rows="${rows}${cfg},$(tail -n 1 results.csv)"$'\n'
done

{
    printf 'config,t_asic_max_c,t_hbm_w_max_c,t_hbm_e_max_c\n'
    printf '%s' "$rows"
} > results.csv
