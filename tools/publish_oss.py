#!/usr/bin/env python3
"""publish_oss.py — sync sim-benchmark (private) → the public hwe-bench mirror.

Single source of truth: the private repo. The oss mirror is rebuilt by
this script from explicit allowlists. Nothing in private is "private by
mistake" — anything not on a whitelist below stays private.

Usage:
    python tools/publish_oss.py [--dry-run] [--oss PATH] [--cases-allowlist FILE]
    python tools/publish_oss.py --check        # gate only; no mirror needed

By default:
    --oss             ../hwe-bench   (sibling repo)
    --cases-allowlist tools/oss-cases.allowlist

`--check` is the shop-window gate and it is what CI runs. It reads the
allowlist and the cases and nothing else, so it needs no mirror on disk:

  - every allowlist entry resolves to an existing case directory, on a live
    track, whose task.toml says `release_status = "public_runnable"`;
  - the number of live cases carrying `public_runnable` at all stays inside
    the `public-runnable-budget` recorded in the allowlist header.

Both directions can fail, and on 2026-08-06 the first did: all 39 entries had
pointed at nothing since the June 2026 tree rename, so this script published
zero cases for two months and produced no signal — the entries were counted as
`missing_src` and the run continued. That is why the check exits non-zero
rather than reporting.

The second direction is a tripwire and not a size policy. `release_status =
"public_runnable"` records publish-*readiness* — oracle at 1.0, anti-cheat
live, open-source solver — so most live cases carry it and that is the ruled
intent (#350); what makes a case public is an entry here, and the public sample
has no target size (#395). The budget exists because 50 markers moved in two
commits on 2026-07-26 with no artifact of the decision anywhere, and raising it
is a line a reviewer can see.

What this script does NOT do:
    - It does not touch oss/.git/. You commit + push from the oss repo
      yourself, after reviewing `git -C ../hwe-bench diff`.
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
import re
import shutil
import sys
import tomllib
from pathlib import Path
from collections.abc import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_cases_md  # noqa: E402  — same directory, not a package

from sim_benchmark_results import live_tracks  # noqa: E402


# Markdown internal-only block markers. Any text wrapped in
# `<!-- INTERNAL-ONLY -->...<!-- /INTERNAL-ONLY -->` (DOTALL, case-insensitive
# on the marker) is stripped when copying .md files into the OSS mirror.
# Use for README/CASES/RESULTS/LEADERBOARD sections that reference private
# cases (e.g. COMSOL ET trial scores) without forcing a separate private
# readme.
_INTERNAL_BLOCK_RE = re.compile(
    r"\n?[ \t]*<!--\s*INTERNAL-ONLY\s*-->.*?<!--\s*/INTERNAL-ONLY\s*-->[ \t]*\n?",
    flags=re.DOTALL | re.IGNORECASE,
)


# The project is HWE-bench to everyone outside and sim-benchmark to the
# codebase (CLAUDE.md, "The name"). This catches the brand leaking into public
# prose, and deliberately does not catch the identifiers that legitimately keep
# the old name: an image tag (`sim-benchmark-cfd-fullstack`), a task namespace
# (`sim-benchmark/<case>`), a package (`sim_benchmark_verifier`) or a URL path
# all carry a word character, `/`, `.` or `-` on one side.
_BARE_OLD_NAME_RE = re.compile(r"(?<![\w./-])sim-benchmark(?![\w./-])")


def find_brand_leaks(text: str) -> list[tuple[int, str]]:
    """Return (line number, line) for every bare `sim-benchmark` in prose.

    Fenced code blocks are skipped: a snippet quotes what a field literally
    contains, and those fields keep the old name on purpose."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and _BARE_OLD_NAME_RE.search(line):
            out.append((i, line.strip()))
    return out


def strip_internal_blocks(text: str) -> str:
    """Return `text` with all INTERNAL-ONLY blocks removed. Collapses the
    block's surrounding whitespace to a single newline so the resulting
    markdown does not gain a blank-line cluster where the block used to be."""
    return _INTERNAL_BLOCK_RE.sub("\n", text)


# This repo ignores the rendered catalog because a clone reads the cases
# instead. The mirror is the opposite case — it is the copy that exists to be
# read in a browser — so the stanza has to come out of the .gitignore we hand
# it, or the mirror would ignore the one file we generate into it.
_CATALOG_IGNORE_RE = re.compile(
    r"\n?# The case catalog is derived.*?\n/CASES\.md\n", flags=re.DOTALL)


# Harbor routes a published task by the org prefix of `[task] name`, and the
# Hub org that exists is `hwe-bench`. The private tree keeps `sim-benchmark/`:
# that string is the key every stored trial and every `contract_hash` was
# computed against, and CLAUDE.md ("The name") is explicit that re-keying it is
# its own decision rather than a docs change. Rewriting it *on the way out*
# needs neither — the mirror is already a transformed copy, and the two names
# name two different artifacts that were never going to share a registry entry.
_TASK_ORG_RE = re.compile(r'^(\s*name\s*=\s*")sim-benchmark/', re.MULTILINE)


def mirror_text(src: Path) -> str | None:
    """The text this file should have in the mirror, or None if it is copied
    byte-for-byte."""
    if src.suffix == ".md":
        return strip_internal_blocks(src.read_text(encoding="utf-8"))
    if src.name == ".gitignore":
        return _CATALOG_IGNORE_RE.sub("\n", src.read_text(encoding="utf-8"))
    if src.name == "task.toml":
        return _TASK_ORG_RE.sub(r"\1hwe-bench/", src.read_text(encoding="utf-8"))
    return None

# ---------------------------------------------------------------------------
# Shared layer — code reviewed; anything new is private by default.
# ---------------------------------------------------------------------------

# Individual files relative to repo root.
SHARED_FILES: list[str] = [
    # Top-level
    ".gitattributes",
    ".gitignore",
    # CASES.md is absent on purpose — it is rendered into the mirror below
    # rather than copied, because this repo does not keep a copy.
    "LEADERBOARD.md",
    "LICENSE",
    "ORACLE.md",
    "README.md",
    "REPRODUCING.md",
    "SCHEMA.md",

    # docs/ — only the public-facing subset; comsol/harbor docs stay private.
    "docs/architecture.md",
    "docs/experiment_with_vs_without_sim.md",

    # environment/ — the images the published cases actually run in, and
    # nothing else. `base/` and `wine-base/` used to be here and are not the
    # answer: the first is the legacy substrate no live case names, and the
    # second backs `eda-analog`, which is not on the board. What a reader needs
    # is the three domain images the 68 published cases declare, the shared
    # harness their Dockerfiles source, and the manifest that says which
    # toolchain version each one ships. The dirs are in SHARED_DIRS below.
    "environment/domains/README.md",
    "environment/domains/VERSIONS.md",
    "environment/domains/build.sh",

    # tools/ — runtime + verifier helpers used by the public benchmark.
    # The private one-offs this used to exclude by name have since been
    # deleted outright, so there is nothing left to list; git has them.
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
    "tools/verify_template.py",
]

# Whole directories (recursive). Filter via DIR_EXCLUDES patterns.
SHARED_DIRS: list[str] = [
    ".github",
    ".claude/skills/readme-blueprint-generator",
    "lib/sim_benchmark_verifier",
    "tools/ccr-plugins",
    # One per track on the board, plus the harness installer every domain
    # Dockerfile sources. A domain image that no published case names is not
    # published: the tree holds eight, the board runs three.
    "environment/_common",
    "environment/domains/battery",
    "environment/domains/cfd",
    "environment/domains/combustion",
]

# Glob patterns for individual files to mirror. Empty since `configs/` went
# away with the self-built runner: those YAMLs named an `import_path` into
# `tools.agent_harness`, and this list was publishing them to the OSS mirror
# after that module was deleted. Harbor's launcher takes a model and a case on
# the command line, so there is nothing config-shaped left to share.
SHARED_GLOBS: list[str] = []

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
# The shop-window gate
# ---------------------------------------------------------------------------

# The budget lives in the allowlist header rather than in this file, because
# the size of the public sample and its contents are one decision and belong on
# one screen. It is written as a comment so `load_cases_allowlist` — and every
# other reader of this file, now and later — needs no knowledge of it.
_BUDGET_RE = re.compile(r"^#\s*public-runnable-budget:\s*(\d+)\s*$")


def load_public_runnable_budget(path: Path) -> int | None:
    """The ceiling on live `public_runnable` cases, from the allowlist header.

    `None` when the directive is absent, which the caller treats as a failure
    rather than as "unlimited". A check whose enforcement can be removed by
    deleting a comment is not a check, and this repo has now paid twice for a
    declaration that produced no signal (#339, #240)."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _BUDGET_RE.match(raw.strip())
        if m:
            return int(m.group(1))
    return None


def _release_status(task_toml: Path) -> str | None:
    try:
        with task_toml.open("rb") as fh:
            sim = (tomllib.load(fh).get("metadata") or {}).get("sim") or {}
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return sim.get("release_status")


def public_runnable_cases(private: Path) -> list[str]:
    """Every live-track case whose task.toml says `public_runnable`.

    Live is the directory convention -- a `cases/` directory whose name does
    not start with an underscore -- asked of `live_tracks()` rather than typed
    out, for the reason that function's own docstring gives."""
    out: list[str] = []
    for track in live_tracks(private):
        for task_toml in sorted((private / "cases" / track).rglob("task.toml")):
            if _release_status(task_toml) == "public_runnable":
                out.append(task_toml.parent.relative_to(private / "cases").as_posix())
    return out


def check_shop_window(private: Path, allowlist_path: Path) -> list[str]:
    """Return every reason the public sample is not in a publishable state.

    Two directions, because the two defects they catch are different and only
    one of them is about the allowlist:

    - **entry -> case.** An entry naming a directory that does not exist, or
      one parked under `_pending/` / `_phase2/` / `_deferred/`, or one whose
      own task.toml does not claim to be public, would publish something no
      case says may be published. All 39 entries failed the first of those for
      two months and the run reported `missing_src` and carried on.

    - **case -> budget.** `release_status` is not read by the case copy at all,
      so an inflated count leaks nothing *there*; it leaks through `CASES.md`,
      which this script renders into the mirror from exactly that field. The
      budget is what makes a bulk flip visible: 47 cases moved in two commits
      on 2026-07-26 and the only artifact of the decision was the commit
      message.

    Deliberately NOT checked: that every `public_runnable` case has an entry.
    That direction would fail 48 of today's 51 on the day it landed, and a
    check that fails most of the repo gets switched off rather than satisfied
    (the reasoning `lint_case.check_demand_record_is_linked` records). Which
    cases belong in the window is a product decision, not a lint."""
    problems: list[str] = []
    cases_root = private / "cases"
    live = set(live_tracks(private))

    for entry in load_cases_allowlist(allowlist_path):
        case_dir = cases_root / entry
        track = entry.split("/")[0]
        if track not in live:
            why = (
                "it is a staging directory (`_pending/` drafts, `_phase2/` out of "
                "scope, `_deferred/`), and a parked case is not shippable"
                if track.startswith("_")
                else "there is no such directory under cases/ -- the track was "
                     "renamed or removed, so repath the entry or drop it"
            )
            problems.append(
                f"allowlist entry {entry!r}: {track!r} is not a live track: {why}."
            )
            continue
        if not (case_dir / "task.toml").is_file():
            problems.append(
                f"allowlist entry {entry!r}: no case at cases/{entry}/task.toml. "
                "The directory was renamed or deleted; repath the entry or drop it."
            )
            continue
        status = _release_status(case_dir / "task.toml")
        if status != "public_runnable":
            problems.append(
                f"allowlist entry {entry!r}: task.toml says release_status = "
                f"{status!r}. The allowlist selects from the cases marked public; "
                "it does not overrule them."
            )

    budget = load_public_runnable_budget(allowlist_path)
    n = len(public_runnable_cases(private))
    if budget is None:
        problems.append(
            f"{allowlist_path.name}: no `# public-runnable-budget: <n>` line. It is "
            f"the only thing that makes a bulk release_status flip visible; put it "
            f"back (today's count is {n})."
        )
    elif n > budget:
        problems.append(
            f"{n} live cases carry release_status = \"public_runnable\", over the "
            f"budget of {budget} recorded in {allowlist_path.name}. The field is "
            "publish-readiness and a case that became ready is entitled to it "
            "(#350), so the usual fix is to raise the budget by the number of "
            "cases that became ready and say so in the commit. Read it before "
            "raising it by tens: that is the bulk flip the line exists to catch."
        )
    return problems


# ---------------------------------------------------------------------------
# Sync primitives — collect actions first, execute (or dry-run) at the end.
# ---------------------------------------------------------------------------

class Action:
    __slots__ = ("kind", "src", "dst", "text")
    def __init__(self, kind: str, src: Path | None, dst: Path,
                 text: str | None = None):
        self.kind = kind  # "copy_new" | "copy_changed" | "skip_same" | "missing_src"
                          # | "warn_orphan" | "write_text"
        self.src = src
        self.dst = dst
        # Only "write_text" uses this: content the mirror gets that has no file
        # behind it on the private side.
        self.text = text


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
    src_text = mirror_text(src)
    if src_text is not None:
        # Some files are rewritten on the way out (INTERNAL-ONLY blocks in
        # markdown, the catalog stanza in .gitignore), so compare the text the
        # mirror would get rather than the bytes on this side.
        if not dst.exists():
            return Action("copy_new", src, dst)
        try:
            dst_text = dst.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Action("copy_changed", src, dst)
        if dst_text == src_text:
            return Action("skip_same", src, dst)
        return Action("copy_changed", src, dst)
    if not dst.exists():
        return Action("copy_new", src, dst)
    if filecmp.cmp(src, dst, shallow=False):
        return Action("skip_same", src, dst)
    return Action("copy_changed", src, dst)


def plan_dir_sync(src_root: Path, dst_root: Path,
                  extra_rels: frozenset[str] = frozenset()) -> list[Action]:
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
            if rel not in src_rels and rel.as_posix() not in extra_rels:
                actions.append(Action("warn_orphan", None, dst))
    return actions


def execute(actions: list[Action], dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in actions:
        counts[a.kind] = counts.get(a.kind, 0) + 1
        if dry_run:
            continue
        if a.kind == "write_text":
            a.dst.parent.mkdir(parents=True, exist_ok=True)
            if not a.dst.exists() or a.dst.read_text(encoding="utf-8") != a.text:
                a.dst.write_text(a.text, encoding="utf-8")
        elif a.kind in ("copy_new", "copy_changed"):
            a.dst.parent.mkdir(parents=True, exist_ok=True)
            rewritten = mirror_text(a.src)
            if rewritten is not None:
                a.dst.write_text(rewritten, encoding="utf-8")
                # Preserve mtime so subsequent runs don't churn unrelated files.
                shutil.copystat(a.src, a.dst)
            else:
                shutil.copy2(a.src, a.dst)
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # `--help` prints this module's docstring, which draws its pipeline with
    # U+2192; a Windows console encodes stdout as cp1252 and cannot carry it, so
    # without this the tool cannot even state its own usage there.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oss", default="../hwe-bench",
                    help="path to the open-source mirror tree (default: ../hwe-bench)")
    ap.add_argument("--cases-allowlist", default="tools/oss-cases.allowlist",
                    help="path to the cases allowlist (default: tools/oss-cases.allowlist)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; touch nothing")
    ap.add_argument("--check", action="store_true",
                    help="run only the shop-window gate (no mirror needed); "
                         "exit 1 if the allowlist and the cases disagree")
    ap.add_argument("--quiet", action="store_true",
                    help="only print summary, skip per-action lines")
    args = ap.parse_args()

    private = Path(__file__).resolve().parent.parent
    allowlist_path = private / args.cases_allowlist

    # The gate runs before anything else on every path, `--dry-run` included: a
    # dry run that reports what it would publish is worth nothing if the list
    # it read is stale, and a stale list is exactly what went unnoticed.
    problems = check_shop_window(private, allowlist_path)
    if problems:
        print(f"FAIL: the public sample is not in a publishable state "
              f"({len(problems)} problem(s)):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if args.check:
        n = len(public_runnable_cases(private))
        print(f"OK  {len(load_cases_allowlist(allowlist_path))} allowlist entr"
              f"(ies), all live and public_runnable; {n} live case(s) marked "
              f"public_runnable, budget {load_public_runnable_budget(allowlist_path)}.")
        return 0

    oss = (private / args.oss).resolve() if not Path(args.oss).is_absolute() else Path(args.oss).resolve()
    if not oss.exists():
        sys.exit(f"FATAL: oss path does not exist: {oss}")
    if not (oss / ".git").exists():
        print(f"WARN: {oss} does not look like a git repo (no .git/). Continuing anyway.", file=sys.stderr)

    cases_allowlist = load_cases_allowlist(allowlist_path)

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

    # 4) Cases on the allowlist. `check_shop_window` has already refused an
    #    entry with no case behind it, so the only `missing_src` that can reach
    #    the summary below now comes from SHARED_FILES / SHARED_DIRS.
    for case_path in cases_allowlist:
        no_env = not (private / "cases" / case_path / "environment").is_dir()
        actions.extend(plan_dir_sync(
            private / "cases" / case_path, oss / "cases" / case_path,
            extra_rels=frozenset({"environment/README.md"}) if no_env else frozenset()))
        # Harbor's `Task.is_valid_dir` requires `environment/` even when the
        # case runs on its domain image unmodified, so a case without one
        # cannot be published at all -- 55 of these 68 are in that state.
        # Stage a marker rather than an empty directory, and name the case in
        # it: `environment_content_hash` falls back to hashing the
        # `docker_image` string when the directory is empty, which collapses
        # every fixture-less case in a track onto ONE container identity and
        # has already graded one case against a sibling's contract.
        #
        # Mirror-side, like the org rewrite above. Adding it to the private
        # tree would move every one of those cases' `task.digest` and
        # `task_checksum`, which is a contract-identity change and its own
        # decision; the marker is inert either way -- it is not copied into
        # the image and it changes nothing the agent or the verifier reads.
        if no_env:
            actions.append(Action(
                "write_text", None, oss / "cases" / case_path / "environment" / "README.md",
                f"This case runs on its domain image unmodified and ships no "
                f"fixtures.\n\nThis file exists so the directory is not empty: "
                f"Harbor requires an\n`environment/` to recognise a task at all, "
                f"and hashes an empty one as the\n`docker_image` string, which "
                f"gives every fixture-less case in a track the\nsame container "
                f"identity.\n\ncase: {case_path}\n"))

    # 5) Cases present in oss but not on allowlist — warn.
    # Layout is solver/physics/case-id, so walk three levels.
    if (oss / "cases").exists():
        for solver_dir in (oss / "cases").iterdir():
            if not solver_dir.is_dir():
                continue
            for physics_dir in solver_dir.iterdir():
                if not physics_dir.is_dir():
                    continue
                for case_dir in physics_dir.iterdir():
                    if not case_dir.is_dir():
                        continue
                    rel = f"{solver_dir.name}/{physics_dir.name}/{case_dir.name}"
                    if rel not in cases_allowlist:
                        actions.append(Action("warn_orphan_case", None, case_dir))

    # 6) The case catalog, rendered rather than copied. This repo does not keep
    #    a CASES.md: a clone reads the cases, and a committed derived file only
    #    buys a regeneration step on every case PR. The mirror is where the
    #    rendered table earns its keep, so it is written here, from the same
    #    cases this run is publishing.
    # Rendered over the cases this run is PUBLISHING, not over the live tree.
    # `collect()` returns every live case marked public, which is the readiness
    # marker rather than the publishing decision — so the unfiltered catalog
    # listed 121 cases beside 68 published directories, naming the case ids,
    # KPIs and operating points of everything held back, plus a count of what
    # sits in `_pending/`. That is the inventory this repo sells, printed in
    # the shop window.
    allow = set(cases_allowlist)
    catalog = gen_cases_md.render(
        [r for r in gen_cases_md.collect()
         if f"{r['domain']}/{r['subdomain']}/{r['case_id']}" in allow],
        public_mirror=True)
    catalog_dst = oss / "CASES.md"
    catalog_state = "unchanged"
    if not catalog_dst.exists():
        catalog_state = "new"
    elif catalog_dst.read_text(encoding="utf-8") != catalog:
        catalog_state = "updated"
    if catalog_state != "unchanged" and not args.dry_run:
        catalog_dst.write_text(catalog, encoding="utf-8")
    if not args.quiet and catalog_state != "unchanged":
        print(f"  {'ADD ' if catalog_state == 'new' else 'UPD '}  CASES.md (rendered)")

    # 7) Brand check on the shop-window markdown. Warning only: a leak is a
    #    wording bug, not a reason to refuse the sync.
    leaks = 0
    for rel in SHARED_FILES:
        src = private / rel
        if src.suffix != ".md" or not src.exists():
            continue
        for lineno, line in find_brand_leaks(
                strip_internal_blocks(src.read_text(encoding="utf-8"))):
            leaks += 1
            print(f"  NAME  {rel}:{lineno}: {line}", file=sys.stderr)
    if leaks:
        print("  NAME  ^ public prose says 'sim-benchmark'; the outward name is "
              "HWE-bench (see CLAUDE.md, 'The name').", file=sys.stderr)

    # Reporting + execution.
    counts = execute(actions, dry_run=args.dry_run)

    # The stanza that ignores the catalog here must not survive into the mirror,
    # or the one file rendered above would be the one file git refuses to track.
    # `mirror_text` strips it; this is the check that can actually fail if the
    # .gitignore is reworded out from under that. Read after the sync, so it
    # judges the .gitignore this run just wrote.
    mirror_ignore = oss / ".gitignore"
    if not args.dry_run and mirror_ignore.exists() and any(
            line.strip().lstrip("/") == "CASES.md"
            for line in mirror_ignore.read_text(encoding="utf-8").splitlines()):
        print("  WARN  the mirror's .gitignore ignores CASES.md — the rendered "
              "catalog will not be committable there", file=sys.stderr)

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
    print(f"  name leaks: {leaks}  (public prose still saying 'sim-benchmark')")
    print(f"  catalog:    CASES.md {catalog_state}  (rendered from the cases)")
    if args.dry_run:
        print("\nDry run only; nothing written. Re-run without --dry-run to apply.")
    else:
        print("\nNext: cd into the oss repo, review `git diff`, then commit + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
