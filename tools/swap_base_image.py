#!/usr/bin/env python3
"""Switch every circuits case Dockerfile between the 4 sim-ecosystem
layers used by the v19 with-sim-vs-without-sim 4-arm comparison study.

    python tools/swap_base_image.py --to bare      # L1: just LTspice + Claude Code + verifier
    python tools/swap_base_image.py --to lib       # L2: + sim-ltspice (Python parser library)
    python tools/swap_base_image.py --to launcher  # L3: + sim-cli core + sim-plugin-ltspice
    python tools/swap_base_image.py --to full      # L4: + sim-skills auto-loaded
    python tools/swap_base_image.py --status

All four resolve to a single multi-stage image
(`sim-benchmark-wine-base:<tag>`) — see
`environment/wine-base-multistage/Dockerfile`. This script just rewrites
the FROM line in every cases/circuits/<id>/environment/Dockerfile so
Harbor's docker env builds against the right tag for the current arm.

Why the script: this repo's pinned Harbor doesn't pass build-args from
YAML config through to per-case Dockerfiles. Source-level tag swap is
the simplest workaround. When Harbor adds build-arg passthrough this
script becomes redundant.

Backward-compat: the legacy `--to with-sim` / `--to without-sim` aliases
still work and map to `full` / `bare` respectively, for any v19a/b
references that linger.

Idempotent — safe to re-run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CIRCUITS_DIR = Path(__file__).resolve().parents[1] / "cases" / "circuits"

IMAGE_BASE = "svd-ai-lab/sim-benchmark-wine-base"

# Layer name → image tag. The multi-stage Dockerfile produces all four.
TAGS = {
    "bare":     f"{IMAGE_BASE}:bare",
    "lib":      f"{IMAGE_BASE}:lib",
    "launcher": f"{IMAGE_BASE}:launcher",
    "full":     f"{IMAGE_BASE}:full",
}

# Backward-compatible aliases for v19a/b legacy.
ALIASES = {
    "with-sim":    "full",
    "without-sim": "bare",
}

# Match any FROM line that points at this image with any tag, OR the
# legacy nosim image, so we can rewrite either.
LEGACY_NOSIM_IMAGE = "svd-ai-lab/sim-benchmark-wine-base-nosim"
FROM_RE = re.compile(
    r"^FROM\s+(\$\{BASE_REGISTRY\}/)(?:"
    + re.escape(IMAGE_BASE)
    + r"|"
    + re.escape(LEGACY_NOSIM_IMAGE)
    + r"):[\w.-]+\s*$",
    re.MULTILINE,
)


def list_cases() -> list[Path]:
    """Return every cases/circuits/<id>/environment/Dockerfile."""
    return sorted(p for p in CIRCUITS_DIR.glob("*/environment/Dockerfile") if p.is_file())


def detect(text: str) -> str | None:
    """Return the current layer name ('bare'|'lib'|'launcher'|'full') or
    None for unrecognised. Also recognises the two legacy image-name
    forms (treated as 'full'/'bare')."""
    for line in text.splitlines():
        if not line.startswith("FROM "):
            continue
        if LEGACY_NOSIM_IMAGE in line:
            return "bare"  # legacy image was effectively L1
        if IMAGE_BASE in line:
            for tag in TAGS:
                if line.endswith(f":{tag}") or line.endswith(f":{tag} "):
                    return tag
            # Match :latest or other tags from older state as full.
            return "full"
    return None


def rewrite(text: str, target: str) -> str:
    new_full = TAGS[target]

    def _sub(m: re.Match) -> str:
        return f"FROM {m.group(1)}{new_full}"

    return FROM_RE.sub(_sub, text)


def status() -> int:
    cases = list_cases()
    if not cases:
        print("no circuits case Dockerfiles found", file=sys.stderr)
        return 1
    counts: dict[str, int] = {k: 0 for k in TAGS}
    counts["unknown"] = 0
    for p in cases:
        s = detect(p.read_text(encoding="utf-8")) or "unknown"
        counts[s] = counts.get(s, 0) + 1
    print(f"circuits Dockerfile bases ({len(cases)} cases):")
    for k in ("bare", "lib", "launcher", "full", "unknown"):
        v = counts.get(k, 0)
        if v:
            print(f"  {k:<10s} {v}")
    return 0


def swap(target: str) -> int:
    target = ALIASES.get(target, target)
    if target not in TAGS:
        print(f"--to must be one of {list(TAGS)} (or legacy aliases {list(ALIASES)}), got {target!r}",
              file=sys.stderr)
        return 2
    cases = list_cases()
    if not cases:
        print("no circuits case Dockerfiles found", file=sys.stderr)
        return 1
    n_changed = 0
    n_already = 0
    n_skip = 0
    for p in cases:
        old = p.read_text(encoding="utf-8")
        new = rewrite(old, target)
        if old == new:
            cur = detect(old)
            if cur == target:
                n_already += 1
            else:
                # The Dockerfile uses an image we don't recognise — leave alone.
                rel = p.relative_to(CIRCUITS_DIR.parent.parent)
                print(f"  SKIP   {rel}  (FROM line not from a recognised base image)")
                n_skip += 1
        else:
            p.write_text(new, encoding="utf-8")
            n_changed += 1
    print(f"swap -> {target}: {n_changed} changed, {n_already} already-{target}, {n_skip} skipped")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--to", choices=list(TAGS) + list(ALIASES),
                   help="Rewrite all circuits Dockerfiles to FROM the named layer's image tag.")
    g.add_argument("--status", action="store_true",
                   help="Report current base of every circuits Dockerfile.")
    args = ap.parse_args(argv)
    if args.status:
        return status()
    return swap(args.to)


if __name__ == "__main__":
    sys.exit(main())
