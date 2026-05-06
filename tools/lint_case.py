#!/usr/bin/env python3
"""
lint_case.py — validate a sim-benchmark case against SCHEMA.md.

Usage:
    python tools/lint_case.py cases/<domain>/<case-id>
    python tools/lint_case.py cases/_template     # should pass (placeholders are "TODO" but fields exist)

Exit code 0 = all checks pass. Exit code 1 = one or more failures (diagnostics printed).

Checks:
    Structural — required files exist at the expected paths.
    task.toml  — schema_version, required sections, required fields, enum values.
    Executable — solve.sh and tests/test.sh have the executable bit (Unix only).

Does NOT check: that solve.sh runs green, that reward.json is produced. Those are
Phase 1 concerns (oracle run + harbor run), not schema lint.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tomllib
from pathlib import Path


REQUIRED_FILES = [
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "tests/test.sh",
]

REQUIRED_TASK_FIELDS = ["name", "description", "authors", "keywords"]
# Field names follow Harbor schema 1.1 + cases/_template (memory_gb,
# internet_access, timeout_s, execution_user). Per-KPI definitions live
# in tests/kpis.json (read by sim_benchmark_verifier), not in task.toml.
REQUIRED_ENV_FIELDS = ["cpus", "memory_gb", "internet_access"]
REQUIRED_AGENT_FIELDS = ["timeout_s", "execution_user"]
REQUIRED_VERIFIER_FIELDS = ["timeout_s", "execution_user"]
ORG_NAME_RE = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
REQUIRED_METADATA_SIM_FIELDS = [
    "solver",
    "source_type",
    "difficulty_tier",
    "release_status",
    "oracle_status",
    "score_template",
    "leakage_risk",
    "capability_target",
]

ENUMS = {
    # `neutral` = case is solver-agnostic (agent picks via sim --json check).
    # Concrete solver names allowed for cases that intentionally pin one.
    "solver": {"neutral", "openfoam", "ltspice", "comsol", "fluent", "calculix",
               "elmer", "su2", "lammps", "mapdl", "abaqus"},
    "source_type": {"paper", "vv_standard", "novel_variant", "tutorial"},
    "difficulty_tier": {"S", "M", "L", "H"},
    "release_status": {"public_runnable", "public_draft", "hidden_eval"},
    "oracle_status": {"available", "deferred", "not_applicable"},
    "score_template": {"measurement", "numerical", "workflow"},
    "capability_target": {"setup", "solver_execution", "numerical", "postprocess", "debugging", "physics"},
    # gt_type is optional these days (per-KPI ground truth lives in kpis.json).
    "gt_type": {"analytical", "experimental", "high-fidelity",
                "high-fidelity-solver", "paper-reported"},
}

SCHEMA_VERSION = "1.1"


def _metadata_sim_field(root: Path, field: str) -> str | None:
    p = root / "task.toml"
    if not p.is_file():
        return None
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return None
    metadata = data.get("metadata")
    sim = metadata.get("sim") if isinstance(metadata, dict) else None
    if isinstance(sim, dict):
        value = sim.get(field)
        if isinstance(value, str):
            return value
    return None


def check_files(root: Path, errors: list[str]) -> None:
    for rel in REQUIRED_FILES:
        p = root / rel
        if not p.is_file():
            errors.append(f"missing file: {rel}")
    if _metadata_sim_field(root, "oracle_status") == "available":
        solve = root / "solution" / "solve.sh"
        if not solve.is_file():
            errors.append("missing file: solution/solve.sh")


def check_executable(root: Path, errors: list[str]) -> None:
    if os.name == "nt":
        return
    for rel in ("solution/solve.sh", "tests/test.sh"):
        p = root / rel
        if not p.is_file():
            continue
        mode = p.stat().st_mode
        if not (mode & stat.S_IXUSR):
            errors.append(f"not executable (chmod +x needed): {rel}")


def check_fields(section: dict, required: list[str], path: str, errors: list[str]) -> None:
    for f in required:
        if f not in section:
            errors.append(f"{path}: missing field '{f}'")


def check_enum(value: object, field: str, path: str, errors: list[str]) -> None:
    allowed = ENUMS[field]
    if value not in allowed:
        errors.append(f"{path}.{field}: '{value!r}' not in {sorted(allowed)}")


def check_harbor_native_contract(root: Path, errors: list[str]) -> None:
    """Enforce the invariants of the current sim-cli capability instrument.

    Stripped invariants (no longer load-bearing):

    - "instruction.md must not mention OpenFOAM tutorials": removed when the
      tutorial-derived case set was archived (2026-04-26). The contamination
      risk it guarded against doesn't exist for the canonical neutral set;
      keeping the check forced bizarre wording on every new case.
    - "Dockerfile must install tmux + asciinema": those are Harbor terminus-2
      requirements; we run claude-code via the agent_harness path which
      doesn't shell out to tmux. Cases inherit from sim-benchmark-base which
      installs whatever Harbor needs.

    Remaining invariant:

    - tests/verify.py (or test.sh) is the verifier entry point. The newer
      cases delegate to lib/sim_benchmark_verifier via tests/test.sh and
      don't ship a verify.py — no need to enforce the I/O path string here
      since the verifier library encodes that contract centrally.
    """
    return  # all dynamic invariants now live in the verifier library


def check_task_toml(root: Path, errors: list[str]) -> None:
    p = root / "task.toml"
    if not p.is_file():
        return

    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        errors.append(f"task.toml: invalid TOML — {e}")
        return

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"task.toml: schema_version must be '{SCHEMA_VERSION}', got {data.get('schema_version')!r}"
        )

    for section_name, required in (
        ("task", REQUIRED_TASK_FIELDS),
        ("environment", REQUIRED_ENV_FIELDS),
        ("agent", REQUIRED_AGENT_FIELDS),
        ("verifier", REQUIRED_VERIFIER_FIELDS),
    ):
        section = data.get(section_name)
        if not isinstance(section, dict):
            errors.append(f"task.toml: missing or malformed [{section_name}] section")
            continue
        check_fields(section, required, f"task.toml [{section_name}]", errors)

    # NOTE: `internet_access` was previously required false for reproducibility,
    # but the current ccr+proxy harness needs internet at agent install time
    # (npm registry, pip aiohttp, paratera HTTPS). Trial-time isolation is
    # achieved by airgapping the solver step inside sim-cli, not by closing
    # the container's network. Lint no longer enforces this field.

    task = data.get("task")
    if isinstance(task, dict):
        name = task.get("name")
        if isinstance(name, str) and (not re.match(ORG_NAME_RE, name) or ".." in name):
            errors.append(
                f"task.toml [task].name: must match 'org/name' format (alphanumeric + -/_/., "
                f"single slash). Got: {name!r}"
            )
        authors = task.get("authors")
        if isinstance(authors, list):
            for i, a in enumerate(authors):
                if not isinstance(a, dict) or "name" not in a:
                    errors.append(
                        f"task.toml [task].authors[{i}]: each author must be a table like "
                        f"{{name=\"...\"}}, not a bare string"
                    )

    metadata = data.get("metadata")
    sim = metadata.get("sim") if isinstance(metadata, dict) else None
    if not isinstance(sim, dict):
        errors.append("task.toml: missing [metadata.sim] section")
        return

    check_fields(sim, REQUIRED_METADATA_SIM_FIELDS, "task.toml [metadata.sim]", errors)

    for enum_field in ENUMS:
        if enum_field in sim:
            check_enum(sim[enum_field], enum_field, "task.toml [metadata.sim]", errors)

    if "leakage_risk" in sim:
        risk = sim["leakage_risk"]
        if not isinstance(risk, int) or risk < 0 or risk > 3:
            errors.append("task.toml [metadata.sim].leakage_risk: must be an integer 0..3")

    if "tags" in sim and not (isinstance(sim["tags"], list) and all(isinstance(t, str) for t in sim["tags"])):
        errors.append("task.toml [metadata.sim].tags: must be a list of strings")

    # KPI definitions live in `tests/kpis.json` (read by sim_benchmark_verifier).
    # The legacy [[metadata.sim.kpis]] array in task.toml is no longer required;
    # cross-validate that tests/kpis.json exists and parses if present.
    kpis_json = root / "tests" / "kpis.json"
    if kpis_json.is_file():
        try:
            data_kpis = json.loads(kpis_json.read_text(encoding="utf-8"))
            kpis = data_kpis.get("kpis")
            groups = data_kpis.get("kpi_groups")
            if not isinstance(kpis, dict) or not kpis:
                errors.append("tests/kpis.json: top-level `kpis` must be a non-empty object")
            if not isinstance(groups, dict) or not groups:
                errors.append("tests/kpis.json: top-level `kpi_groups` must be a non-empty object")
            if isinstance(kpis, dict) and isinstance(groups, dict):
                total = sum(float(g.get("weight", 0)) for g in groups.values() if isinstance(g, dict))
                if abs(total - 1.0) > 1e-6:
                    errors.append(f"tests/kpis.json: kpi_groups weights must sum to 1.0, got {total}")
                for kname, kspec in kpis.items():
                    if not isinstance(kspec, dict):
                        errors.append(f"tests/kpis.json: kpi {kname!r} must be an object")
                        continue
                    group = kspec.get("group")
                    if group not in groups:
                        errors.append(
                            f"tests/kpis.json: kpi {kname!r} declares unknown group {group!r}"
                        )
                for gname, gspec in groups.items():
                    weight = float(gspec.get("weight", 0)) if isinstance(gspec, dict) else 0.0
                    members = [
                        kname
                        for kname, kspec in kpis.items()
                        if isinstance(kspec, dict) and kspec.get("group") == gname
                    ]
                    if weight > 0 and not members:
                        errors.append(
                            f"tests/kpis.json: kpi_group {gname!r} has positive weight but no KPIs"
                        )
        except json.JSONDecodeError as e:
            errors.append(f"tests/kpis.json: invalid JSON — {e}")
    else:
        errors.append("missing tests/kpis.json (verifier reads KPI specs from here)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint a sim-benchmark case against SCHEMA.md")
    parser.add_argument("case_dir", type=Path, help="Path to the case directory")
    args = parser.parse_args()

    root = args.case_dir
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    errors: list[str] = []
    check_files(root, errors)
    check_task_toml(root, errors)
    check_executable(root, errors)
    check_harbor_native_contract(root, errors)

    if errors:
        print(f"FAIL ({len(errors)} issue(s)) in {root}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
