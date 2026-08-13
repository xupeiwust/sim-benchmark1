---
name: readme-blueprint-generator
description: Use when the user asks for a polished, eye-catching GitHub README for a software project. Project-local fork specialized for visually striking READMEs in the style of github.com/ConardLi/easy-dataset and github.com/HKUDS/CLI-Anything — centered text hero, colorful shields, emoji section headers, News timeline, demo GIF placeholder. Does not author image assets.
---

# README Blueprint Generator (visual-impact fork)

Goal: produce a `README.md` that **stops the scroll in 2 seconds** and **earns a star in 30 seconds**, while staying technically truthful.

This fork is tuned to match the visual language of high-traffic agent / dev-tool repos. Reference exemplars:

- https://github.com/ConardLi/easy-dataset — centered hero, banner PNG, shield wall, dated News, feature grid with emoji
- https://github.com/HKUDS/CLI-Anything — `<h1 align="center">` with icon, tagline on two lines, for-the-badge shield row, "Why X" section, expandable News `<details>`

## Sources (in priority order)

1. `CLAUDE.md` — authoritative on architecture, commands, intent
2. `pyproject.toml` / `package.json` / `Cargo.toml` — name, version, license, deps
3. `LICENSE` — SPDX
4. `src/` tree — confirm subcommands and modules actually exist
5. Existing `README.md` — preserve good wording, do not regress
6. Sibling repos referenced from CLAUDE.md (cross-link them)
7. `assets/` directory — if logo / banner / diagram images exist, USE them. **Do not create any.** See "Assets" below

**Iron rule:** never invent a feature, command, badge, link, version number, contributor count, or screenshot path that isn't backed by one of the above. Empty graphs and 404 image links are worse than no image at all.

## Required structure (visual-impact layout)

```
1.  Centered hero block
    - <div align="center"> ... </div>
    - H1 with the project name, as text
    - Bold one-liner tagline (≤ 14 words)
    - Two-line poetic subtitle if it fits the project's voice
    - Shield wall: 4–8 badges in `style=for-the-badge` for the headline metrics,
      then a row of `style=flat` badges for secondary metrics
    - Language selector if docs/README.<lang>.md exist
    - Section nav: [Features] · [Quick Start] · [Demo] · [Contributing]
2.  News timeline (optional, only if there are real dated events)
    - Most recent 5 items inline, older entries inside <details>
3.  "Why <project>?" — bullet list with bolded leads, each ≤ 1 sentence
4.  Architecture — a fenced ASCII diagram, or an existing SVG if the repo
    already ships one
5.  Quick Start — copy-pasteable, ≤ 12 lines, must work end-to-end
6.  Demo — an existing GIF/MP4 OR a placeholder block that says exactly
    which scenario to record
7.  Features at a glance — emoji-led bullet grid OR feature table
8.  Commands / API surface — table with `command | what | analogy`
9.  Comparison ("Why not X?") — only with a real incumbent
10. Supported backends / integrations — table with honest status column
11. Development — clone, install, test, lint
12. Project structure — pruned tree
13. Companion / related projects
14. Contributing / Star History note (only if repo has contributors)
15. License
```

## Hero block recipes

### Recipe A — h1-with-tagline (CLI-Anything style)

```markdown
<h1 align="center"><project-name>: <punchy-tagline></h1>

<p align="center">
  <strong>Line one of the poetic subtitle.<br>
  Line two that lands the value prop.</strong>
</p>
```

### Recipe B — centered text hero (easy-dataset style)

```markdown
<div align="center">

# <project-name>

**One-line tagline that fits in the social card preview**

</div>
```

If the repo already ships a banner or logo, put it above the H1 in Recipe B —
`<img src="assets/banner.svg" alt="<project> banner" width="820">`. If it does
not, leave the hero as text.

### Shield wall template

```markdown
<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-2_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-yellow?style=for-the-badge" alt="License"></a>
  <a href="#supported-solvers"><img src="https://img.shields.io/badge/Solvers-7_backends-green?style=for-the-badge" alt="Solvers"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8A2BE2?style=for-the-badge" alt="Skills"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click-green?logo=click&logoColor=white" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status">
</p>
```

## Assets — use what exists, author nothing

**Do not create `assets/`, and do not hand-write an SVG.** An earlier version of
this skill did, and this repo paid for it: a banner SVG whose whole content was
the project's name in a nice font had to be redrawn the first time the project
was renamed, for a picture that told a reader nothing the H1 did not. Text
renames itself with `sed`, is greppable, and is what people came for.

So:

- `assets/` already has a banner / logo / diagram → use it (banner ~820 px wide,
  logo ~72 px inline with the H1).
- It does not → the hero is text, the architecture section is a fenced ASCII
  diagram, and the README ships with no images beyond shields.
- A demo GIF is the one thing worth asking for, because a screen recording
  carries information prose cannot. Leave a placeholder block naming the exact
  command sequence to record, and say so in the final report.

Shields are the exception to all of this: they are generated by
img.shields.io from a URL, so nobody maintains them.

## Style rules

- **Emoji ARE allowed in section headers in this fork** (one per header max), to match the reference exemplars. But: never decorative — each emoji must clearly belong to its section's topic.
- **Tables beat prose.** "What / why / how" → table.
- **Active voice, present tense.** "sim launches solvers" not "solvers can be launched".
- **No marketing fluff.** Banned words: "seamless", "robust", "cutting-edge", "revolutionary", "powerful", "blazing fast" (unless backed by a number).
- **Numbers earn trust.** Driver count, supported versions, test count — pull real numbers from sources.
- **Code blocks are mentally tested.** Every shell snippet runs as written from a clean clone.
- **Link, don't duplicate.** CLAUDE.md and sub-repo READMEs get linked.
- **Centered hero, left-aligned body.** Don't center the whole document.

## Process

1. **Read sources** in priority order. Stop when every required section can be filled without guessing.
2. **Audit `assets/`.** Use whatever is there; if it is empty, plan a text hero and an ASCII architecture diagram. Do not author images.
3. **Draft section by section.**
4. **Self-review against the checklist below.**
5. **Write README.md** with the Write tool, replacing the existing file.
6. **Report** what changed and (importantly) what assets the user still needs to provide (e.g. demo.gif recording).

## Self-review checklist (must pass before writing)

- [ ] Centered hero block with name + tagline + shield wall
- [ ] No image authored by this run; every image link points to a file that already existed
- [ ] Quick Start ≤ 12 lines, runnable from clean clone
- [ ] Every command verified against `cli.py` (or equivalent)
- [ ] Every backend in the support table exists in the driver registry
- [ ] No banned marketing words
- [ ] No invented contributor counts, star counts, or "as featured in" badges
- [ ] News section has real dates or is omitted (no fake dates)
- [ ] Demo section has a real GIF or an explicit "to-record" placeholder block
- [ ] Length ≤ 350 lines

## Anti-patterns

| Don't | Why |
|---|---|
| Reference `./assets/foo.png` when no such file exists | Broken image kills credibility worse than no image |
| Hand-write a wordmark SVG of the project's name | It is the H1 in a nicer font, and it has to be redrawn every rename |
| Use `style=for-the-badge` for >8 badges in the headline row | Visual noise; reserve it for the top metrics |
| Claim "1,000+ stars" / "trusted by N teams" without data | Easily falsifiable, immediate trust collapse |
| Add a Trendshift / ProductHunt badge to a brand-new repo | Empty referral = obvious padding |
| Paste full architecture text from CLAUDE.md | Link CLAUDE.md instead |
| Promise "coming soon" features with no date | Roadmap noise |
| List every CLI flag | Belongs in `--help` |
