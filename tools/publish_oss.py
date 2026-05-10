#!/usr/bin/env python3
"""publish_oss.py — sync sim-benchmark (private) → sim-benchmark-oss.

Single source of truth: the private repo. The oss mirror is rebuilt by
this script from explicit allowlists. Nothing in private is "private by
mistake" — anything not on a whitelist below stays private.

Usage:
    python tools/publish_oss.py [--dry-run] [--oss PATH] [--cases-allowlist FILE]

By default:
    --oss             ../sim-benchmark-oss   (sibling repo)
    --cases-allowlist tools/oss-cases.allowlist

What this script does NOT do:
    - It does not touch oss/.git/. You commit + push from the oss repo
      yourself, after reviewing `git -C ../sim-benchmark-oss diff`.
    - It does not delete oss case dirs that aren't on the allowlist —
      it only warns. Removing a case from the public set is a
      deliberate act (use `--prune-cases` to opt in to deletion).
    - It does not sync .git, jobs/, logs/, work_dir/, or any pycache.

Allowlist design:
    - SHARED_FILES / SHARED_DIRS / SHARED_GLOBS are hardcoded below; they
      change rarely and need code review.
    - Cases come from --cases-allowlist (a text file in the repo) so
      adding a new public case is a one-line PR.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Shared layer — code reviewed; anything new is private by default.
# ---------------------------------------------------------------------------

# Individual files relative to repo root.
SHARED_FILES: list[str] = [
    # Top-level
    ".gitattributes",
    ".gitignore",
    "CASES.md",
    "LEADERBOARD.md",
    "LICENSE",
    "ORACLE.md",
    "README.md",
    "RELEASE.md",
    "REPRODUCING.md",
    "RESULTS.md",
    "SCHEMA.md",
    "assets/banner.svg",

    # docs/ — only the public-facing subset; comsol/harbor docs stay private.
    "docs/architecture.md",
    "docs/experiment_with_vs_without_sim.md",
    "docs/hooks.md",

    # environment/ — only base + wine-base; nosim / multistage are
    # internal experimental variants.
    "environment/base/Dockerfile",
    "environment/base/README.md",
    "environment/wine-base/Dockerfile",

    # tools/ — runtime + verifier helpers used by the public benchmark.
    # Excludes private one-offs: fix_build_results, rserver-ccr-setup,
    # v19_rewrite_*, v19_uniform_*, windows_harness.
    "tools/agent_harness.py",
    "tools/aggregate_economics.py",
    "tools/aggregate_leaderboard.py",
    "tools/calibrate_detectors.py",
    "tools/classify_failures.py",
    "tools/cost_meter.py",
    "tools/lint_case.py",
    "tools/new_circuit_case.py",
    "tools/openai_usage_proxy.py",
    "tools/openfoam_field_kpi.py",
    "tools/oss-cases.allowlist",
    "tools/publish_oss.py",
    "tools/rescore.py",
    "tools/run_local_trial.py",
    "tools/swap_base_image.py",
    "tools/update_kpis_from_oracle.py",
    "tools/v19_static_validate.py",
    "tools/verify_template.py",
]

# Whole directories (recursive). Filter via DIR_EXCLUDES patterns.
SHARED_DIRS: list[str] = [
    ".github",
    ".claude/skills/readme-blueprint-generator",
    "lib/sim_benchmark_verifier",
    "results/v0.1",
    "results/v0.2",
    "tools/ccr-plugins",
]

# Glob patterns under configs/. Internal v*-* experiment configs stay
# private; only the currently-public release tag is auto-published.
# When bumping to a new release (v0.2, etc.) add its glob explicitly so
# you make a deliberate decision about which configs go public.
SHARED_GLOBS: list[str] = [
    "configs/release-v0.1-*.yaml",
    "configs/release-v0.2-*.yaml",
    "configs/template-*.yaml",
]

DIR_EXCLUDES: set[str] = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    ".DS_Store",
    "Thumbs.db",
}
DIR_EXCLUDE_PREFIXES: tuple[str, ...] = (".venv-",)
FILE_EXCLUDE_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo", ".bak")


def _excluded_dir_part(name: str) -> bool:
    return name in DIR_EXCLUDES or name.startswith(DIR_EXCLUDE_PREFIXES)


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------

def load_cases_allowlist(path: Path) -> list[str]:
    """Read `<physics>/<case-id>` lines, ignoring blanks and # comments."""
    if not path.exists():
        sys.exit(f"FATAL: cases allowlist not found: {path}")
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "/" not in line:
            sys.exit(f"FATAL: bad allowlist entry (no /): {line!r} in {path}")
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Sync primitives — collect actions first, execute (or dry-run) at the end.
# ---------------------------------------------------------------------------

class Action:
    __slots__ = ("kind", "src", "dst")
    def __init__(self, kind: str, src: Path | None, dst: Path):
        self.kind = kind  # "copy_new" | "copy_changed" | "skip_same" | "missing_src" | "warn_orphan"
        self.src = src
        self.dst = dst


def _walk_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel_parts = p.relative_to(root).parts
        if any(_excluded_dir_part(part) for part in rel_parts[:-1]):
            continue
        if p.name.endswith(FILE_EXCLUDE_SUFFIXES):
            continue
        yield p


def plan_file_copy(src: Path, dst: Path) -> Action:
    if not src.exists():
        return Action("missing_src", src, dst)
    if not dst.exists():
        return Action("copy_new", src, dst)
    if filecmp.cmp(src, dst, shallow=False):
        return Action("skip_same", src, dst)
    return Action("copy_changed", src, dst)


def plan_dir_sync(src_root: Path, dst_root: Path) -> list[Action]:
    actions: list[Action] = []
    if not src_root.exists():
        actions.append(Action("missing_src", src_root, dst_root))
        return actions
    src_files = sorted(_walk_files(src_root))
    src_rels = {p.relative_to(src_root) for p in src_files}
    for src in src_files:
        rel = src.relative_to(src_root)
        actions.append(plan_file_copy(src, dst_root / rel))
    # Orphans in dst that are missing from src — warn but don't delete by default.
    if dst_root.exists():
        for dst in _walk_files(dst_root):
            rel = dst.relative_to(dst_root)
            if rel not in src_rels:
                actions.append(Action("warn_orphan", None, dst))
    return actions


def execute(actions: list[Action], dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in actions:
        counts[a.kind] = counts.get(a.kind, 0) + 1
        if dry_run:
            continue
        if a.kind in ("copy_new", "copy_changed"):
            a.dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a.src, a.dst)
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oss", default="../sim-benchmark-oss",
                    help="path to the open-source mirror tree (default: ../sim-benchmark-oss)")
    ap.add_argument("--cases-allowlist", default="tools/oss-cases.allowlist",
                    help="path to the cases allowlist (default: tools/oss-cases.allowlist)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; touch nothing")
    ap.add_argument("--quiet", action="store_true",
                    help="only print summary, skip per-action lines")
    args = ap.parse_args()

    private = Path(__file__).resolve().parent.parent
    oss = (private / args.oss).resolve() if not Path(args.oss).is_absolute() else Path(args.oss).resolve()
    if not oss.exists():
        sys.exit(f"FATAL: oss path does not exist: {oss}")
    if not (oss / ".git").exists():
        print(f"WARN: {oss} does not look like a git repo (no .git/). Continuing anyway.", file=sys.stderr)

    cases_allowlist = load_cases_allowlist(private / args.cases_allowlist)

    actions: list[Action] = []

    # 1) Individual shared files.
    for rel in SHARED_FILES:
        actions.append(plan_file_copy(private / rel, oss / rel))

    # 2) Whole shared directories.
    for rel in SHARED_DIRS:
        actions.extend(plan_dir_sync(private / rel, oss / rel))

    # 3) Glob-matched configs.
    for pattern in SHARED_GLOBS:
        for src in private.glob(pattern):
            if not src.is_file():
                continue
            actions.append(plan_file_copy(src, oss / src.relative_to(private)))

    # 4) Cases on the allowlist.
    for case_path in cases_allowlist:
        src_dir = private / "cases" / case_path
        dst_dir = oss / "cases" / case_path
        if not src_dir.exists():
            actions.append(Action("missing_src", src_dir, dst_dir))
            continue
        actions.extend(plan_dir_sync(src_dir, dst_dir))

    # 5) Cases present in oss but not on allowlist — warn.
    if (oss / "cases").exists():
        for solver_dir in (oss / "cases").iterdir():
            if not solver_dir.is_dir():
                continue
            for case_dir in solver_dir.iterdir():
                if not case_dir.is_dir():
                    continue
                rel = f"{solver_dir.name}/{case_dir.name}"
                if rel not in cases_allowlist:
                    actions.append(Action("warn_orphan_case", None, case_dir))

    # Reporting + execution.
    counts = execute(actions, dry_run=args.dry_run)

    if not args.quiet:
        for a in actions:
            if a.kind == "skip_same":
                continue
            tag = {
                "copy_new":         "ADD ",
                "copy_changed":     "UPD ",
                "missing_src":      "MISS",
                "warn_orphan":      "WARN",
                "warn_orphan_case": "ORPH",
            }.get(a.kind, a.kind)
            try:
                shown = a.dst.relative_to(oss)
            except ValueError:
                shown = a.dst
            print(f"  {tag}  {shown}")

    print()
    print(f"{'Would sync' if args.dry_run else 'Synced'} private → {oss}")
    print(f"  add:        {counts.get('copy_new', 0)}")
    print(f"  update:     {counts.get('copy_changed', 0)}")
    print(f"  unchanged:  {counts.get('skip_same', 0)}")
    print(f"  missing src:{counts.get('missing_src', 0)}  (private file/dir on whitelist not present)")
    print(f"  orphan files:{counts.get('warn_orphan', 0)}  (in oss but not in synced source)")
    print(f"  orphan cases:{counts.get('warn_orphan_case', 0)}  (in oss/cases but not in allowlist)")
    if args.dry_run:
        print("\nDry run only; nothing written. Re-run without --dry-run to apply.")
    else:
        print("\nNext: cd into the oss repo, review `git diff`, then commit + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
