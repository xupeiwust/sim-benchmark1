#!/usr/bin/env python3
"""Generate boilerplate for a new circuits/<id>/ case.

Usage:
    python new_circuit_case.py <case_id> "<description>"

Creates:
    cases/circuits/<case_id>/
        environment/Dockerfile
        solution/solve.sh
        solution/build_result.py            # stub; edit KPI names
        tests/test.sh

Does NOT create — they're case-specific and must be authored by hand:
    task.toml
    instruction.md
    solution/case/<id>.net
    tests/kpis.json
"""
from __future__ import annotations

import sys
from pathlib import Path
import os
import stat

DOCKERFILE = """\
ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-wine-base:latest

WORKDIR /root/case
"""

SOLVE_SH = """\
#!/usr/bin/env bash
set -euo pipefail
HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"
mkdir -p "$CASE_RUN" /tmp/agent
cp -r "$HERE/case"/. "$CASE_RUN/"

cd "$CASE_RUN"
sim run --solver ltspice {netlist}
python3 "$HERE/build_result.py"
"""

TEST_SH = """\
#!/usr/bin/env bash
set -euo pipefail
cd /root/case 2>/dev/null || true
exec python3 -m sim_benchmark_verifier.score
"""

BUILD_RESULT = '''"""{case_id} oracle — emit /tmp/agent/result.json from .meas results."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def latest_ltspice_run() -> dict:
    out = subprocess.check_output(["sim", "--json", "logs"], text=True)
    payload = json.loads(out)
    if isinstance(payload, list):
        runs = payload
    elif isinstance(payload, dict):
        runs = payload.get("data", {{}}).get("runs") or payload.get("runs") or []
    else:
        runs = []
    runs = [r for r in runs if r.get("solver") == "ltspice"]
    if not runs:
        raise RuntimeError("no ltspice run record yet")
    return runs[-1]


def main() -> int:
    rec = latest_ltspice_run()
    run_id = str(rec.get("run_id"))
    parsed = rec.get("parsed_output") or {{}}
    measures = parsed.get("measures") or {{}}
    errors = parsed.get("errors") or []

    sim_completed = 0 if errors else 1

    # EDIT HERE: per-KPI extraction
    result = {{
        "sim_completed": {{
            "value": sim_completed,
            "source": {{
                "kind": "sim_run_stdout",
                "run_id": run_id,
                "extract": "tail -1 | jq -r 'if .errors == [] then 1 else 0 end'",
            }},
        }},
        # add KPI entries here, e.g.:
        # "kpi_name": {{
        #     "value": float(measures.get("kpi_name", {{}}).get("value")),
        #     "source": {{
        #         "kind": "sim_run_stdout",
        #         "run_id": run_id,
        #         "extract": "tail -1 | jq -r '.measures.kpi_name.value'",
        #     }},
        # }},
    }}

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({{k: v["value"] for k, v in result.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main():
    if len(sys.argv) < 2:
        print("usage: new_circuit_case.py <case_id> [<netlist_basename>]")
        return 1
    case_id = sys.argv[1]
    netlist = sys.argv[2] if len(sys.argv) > 2 else f"{case_id}.net"

    base = Path(f"cases/circuits/{case_id}")
    if base.exists():
        print(f"refusing to overwrite existing dir {base}")
        return 1

    (base / "environment").mkdir(parents=True)
    (base / "solution" / "case").mkdir(parents=True)
    (base / "tests").mkdir(parents=True)

    (base / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (base / "solution" / "solve.sh").write_text(SOLVE_SH.format(netlist=netlist))
    (base / "solution" / "build_result.py").write_text(BUILD_RESULT.format(case_id=case_id))
    (base / "tests" / "test.sh").write_text(TEST_SH)

    if os.name != "nt":
        for p in (base / "solution" / "solve.sh", base / "tests" / "test.sh"):
            mode = p.stat().st_mode
            p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"created scaffold {base}/")
    print("now author:")
    print(f"  {base}/task.toml")
    print(f"  {base}/instruction.md")
    print(f"  {base}/solution/case/{netlist}")
    print(f"  {base}/tests/kpis.json")
    print(f"  + edit per-KPI extraction in {base}/solution/build_result.py")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
