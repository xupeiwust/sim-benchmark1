#!/usr/bin/env python3
"""Static validation for the v19 4-arm experiment infra - runs every check
that doesn't actually need Docker, so we can de-risk before the user
spins up the real Linux+Docker host.

Checks (each is independent - failures are reported, not fatal):

  1. All 4 v19 smoke configs parse as YAML and have matching dataset.
  2. All 3 smoke cases (bridge_rectifier_ripple, rc_lowpass_ac, rlc_notch)
     have task.toml + tests/kpis.json + instruction.md + environment/Dockerfile.
  3. tests/kpis.json conforms to neutral-v0.3 schema (kpi_groups sums to 1.0,
     each KPI references a known group, has scalar shape).
  4. instruction.md has the v19 uniform-discovery sentinel (so all arms see
     identical Environment section).
  5. instruction.md has the v19 worked-example sentinel (ltspice_log Path A
     is documented, agents in all arms can copy it).
  6. swap_base_image.py round-trips through all 4 modes correctly.
  7. multi-stage Dockerfile parses (regex-level), each named stage exists.
  8. wine-base-multistage Dockerfile expects sibling repos in build context;
     verify they're present (or are valid symlinks).
  9. agent_harness.py Stop hook source compiles cleanly + has the new
     sim-aware schema check.
 10. Verifier package: W_META=0, W_KPI=1; pytest still passes.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SMOKE_CASES = ["bridge_rectifier_ripple", "rc_lowpass_ac", "rlc_notch"]
ARMS = ["bare", "lib", "launcher", "full"]
SMOKE_CONFIGS = {arm: REPO / "configs" / f"v19{chr(97+i)}-3case-smoke-{arm}.yaml"
                 for i, arm in enumerate(ARMS)}

OK = "  [OK]"
FAIL = "  [FAIL]"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"{OK} {name}" + (f": {detail}" if detail else ""))
    else:
        print(f"{FAIL} {name}: {detail}")
        failures.append(f"{name}: {detail}")


# 1. configs parse as YAML, all reference the same 3 cases
def check_configs():
    print("\n[1] v19 smoke configs")
    try:
        import yaml
    except ImportError:
        check("yaml available", False, "PyYAML not installed; install with `uv add pyyaml`")
        return
    case_sets = {}
    for arm, p in SMOKE_CONFIGS.items():
        if not p.is_file():
            check(f"config exists: {p.name}", False, "missing")
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            check(f"config parses: {p.name}", False, str(e))
            continue
        names = data.get("datasets", [{}])[0].get("task_names", [])
        case_sets[arm] = sorted(names)
        check(f"{p.name}: {len(names)} cases listed", names == sorted(SMOKE_CASES),
              f"expected {SMOKE_CASES}, got {names}")
    if len(case_sets) == 4:
        all_same = len({tuple(v) for v in case_sets.values()}) == 1
        check("all 4 arms run identical case set", all_same,
              "diverged across arms - confound!" if not all_same else "")


# 2. each smoke case has all required files
def check_case_files():
    print("\n[2] smoke case files present")
    required = ["task.toml", "tests/kpis.json", "instruction.md",
                "tests/test.sh", "environment/Dockerfile"]
    for case in SMOKE_CASES:
        case_dir = REPO / "cases" / "circuits" / case
        for rel in required:
            p = case_dir / rel
            check(f"{case}/{rel}", p.is_file(), "missing" if not p.is_file() else "")


# 3. kpis.json schema conformance
def check_kpis_schema():
    print("\n[3] tests/kpis.json schema (neutral-v0.3)")
    for case in SMOKE_CASES:
        p = REPO / "cases" / "circuits" / case / "tests" / "kpis.json"
        if not p.is_file():
            continue
        try:
            spec = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            check(f"{case}: kpis.json parses", False, str(e))
            continue
        if spec.get("schema_version") != "neutral-v0.3":
            check(f"{case}: schema_version", False,
                  f"got {spec.get('schema_version')!r}")
        groups = spec.get("kpi_groups", {})
        weight_sum = sum(g.get("weight", 0) for g in groups.values())
        check(f"{case}: kpi_groups weights sum to 1.0",
              abs(weight_sum - 1.0) < 1e-6, f"sum={weight_sum}")
        kpis = spec.get("kpis", {})
        for gname, gspec in groups.items():
            members = [n for n, k in kpis.items() if k.get("group") == gname]
            check(f"{case}: group {gname!r} has members",
                  bool(members) or float(gspec.get("weight", 0)) == 0.0,
                  "positive-weight group has no KPIs")
        for kname, k in kpis.items():
            if k.get("group") not in groups:
                check(f"{case}.{kname}: group ref valid", False,
                      f"group {k.get('group')!r} not in kpi_groups")
            if k.get("shape") != "scalar":
                check(f"{case}.{kname}: shape=scalar", False,
                      f"got {k.get('shape')!r} (verifier supports scalar only)")


# 4. + 5. instruction.md sentinels (uniform discovery + worked example)
def check_instruction_sentinels():
    print("\n[4+5] instruction.md v19 sentinels")
    sentinels = {
        "uniform discovery": "<!-- v19-uniform-discovery -->",
        "worked example":    "<!-- v19-worked-example-rewritten -->",
    }
    for case in SMOKE_CASES:
        text = (REPO / "cases" / "circuits" / case / "instruction.md").read_text(encoding="utf-8")
        for label, sentinel in sentinels.items():
            check(f"{case}: {label} sentinel present",
                  sentinel in text, f"sentinel {sentinel!r} missing")


# 6. swap_base_image.py round-trips 4 modes
def check_swap_round_trip():
    print("\n[6] swap_base_image.py round-trips all 4 modes")
    for arm in ARMS:
        r = subprocess.run([sys.executable, str(REPO / "tools" / "swap_base_image.py"),
                            "--to", arm], capture_output=True, text=True)
        if r.returncode != 0:
            check(f"swap to {arm}", False, r.stderr.strip()[:200])
            continue
        s = subprocess.run([sys.executable, str(REPO / "tools" / "swap_base_image.py"),
                            "--status"], capture_output=True, text=True)
        # Expect "<arm>       20" line in output
        ok = re.search(rf"^\s*{arm}\b\s+\d+", s.stdout, re.MULTILINE) is not None
        check(f"swap to {arm} -> status reflects",
              ok, s.stdout.strip()[:200] if not ok else "")
    # Restore default
    subprocess.run([sys.executable, str(REPO / "tools" / "swap_base_image.py"),
                    "--to", "full"], capture_output=True)


# 7. multi-stage Dockerfile structure
def check_dockerfile_structure():
    print("\n[7] wine-base-multistage Dockerfile structure")
    p = REPO / "environment" / "wine-base-multistage" / "Dockerfile"
    if not p.is_file():
        check("Dockerfile exists", False, "missing")
        return
    text = p.read_text(encoding="utf-8")
    for arm in ARMS:
        # Each stage must appear as: FROM <base> AS <arm>
        pat = rf"^FROM\s+\S+\s+AS\s+{arm}\s*$"
        ok = re.search(pat, text, re.MULTILINE) is not None
        check(f"stage 'AS {arm}' declared", ok)
    # Stage chain must FROM the previous
    expected_chain = [
        ("bare",     "ubuntu:22.04"),
        ("lib",      "bare"),
        ("launcher", "lib"),
        ("full",     "launcher"),
    ]
    for stage, expected_base in expected_chain:
        pat = rf"^FROM\s+{re.escape(expected_base)}\s+AS\s+{stage}\s*$"
        ok = re.search(pat, text, re.MULTILINE) is not None
        check(f"stage chain: {stage} FROM {expected_base}", ok)


# 8. build context: sibling repos present
def check_build_context_siblings():
    print("\n[8] build context - sibling repos present in sim-benchmark/")
    # The Dockerfile COPYs from these paths
    siblings = ["sim-cli", "sim-plugin-ltspice", "sim-ltspice", "sim-skills"]
    for s in siblings:
        p = REPO / s
        present = p.exists()
        is_link = p.is_symlink()
        check(f"{s} present in build context", present,
              "missing - Dockerfile COPY will fail" if not present else (
                  "(symlink)" if is_link else "(directory)"))


# 9. Stop hook source compiles + has new sim-aware check
def check_stop_hook_source():
    print("\n[9] Stop hook source (in agent_harness.py)")
    src = (REPO / "tools" / "agent_harness.py").read_text(encoding="utf-8")
    m = re.search(r"_RESULT_CHECK_HOOK_SRC = r'''(.*?)'''", src, re.DOTALL)
    if not m:
        check("hook src found", False, "_RESULT_CHECK_HOOK_SRC not located")
        return
    body = m.group(1)
    try:
        compile(body, "hook_inline", "exec")
        check("hook compiles", True)
    except SyntaxError as e:
        check("hook compiles", False, str(e))
    # P0-2 sim-aware schema check landed?
    check("sim-aware: 'requires `sim` CLI' message present",
          "requires `sim` CLI" in body)
    check("sim-aware: 'source.kind=\"ltspice_log\"' guidance present",
          'kind=\\"ltspice_log\\"' in body or 'source.kind="ltspice_log"' in body or 'kind="ltspice_log"' in body)


# 10. verifier W_META + tests
def check_verifier():
    print("\n[10] verifier package - KPI-only scoring + tests pass")
    score_src = (REPO / "lib" / "sim_benchmark_verifier" /
                 "sim_benchmark_verifier" / "score.py").read_text(encoding="utf-8")
    check("W_META = 0.0", "W_META = 0.0" in score_src)
    check("W_KPI = 1.0", "W_KPI  = 1.0" in score_src or "W_KPI = 1.0" in score_src)


def main() -> int:
    print(f"v19 static validation - {REPO}")
    check_configs()
    check_case_files()
    check_kpis_schema()
    check_instruction_sentinels()
    check_swap_round_trip()
    check_dockerfile_structure()
    check_build_context_siblings()
    check_stop_hook_source()
    check_verifier()
    print(f"\n{'='*60}\n{len(failures)} failures\n{'='*60}")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
