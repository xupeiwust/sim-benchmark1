"""CalculiX-specific solver-stage detector + evidence checks.

Mirrors ``comsol.py``. Two responsibilities:

1. **Solver-stage detection**: scan the agent's workspace for CalculiX
   output artifacts and emit a stage label.

2. **Evidence checks** (anti-cheat), in two strengths, and which one an
   evaluator reaches for is the whole point of the split:

   * :func:`has_solver_evidence` — **permissive**. "Did this workspace ever
     see CalculiX?" It accepts a banner in a text file, which is right for
     triage on a tree nobody controlled and wrong when the answer decides a
     score.
   * :func:`has_result_database` — **strict**, and the only one admissible as
     a gate. It accepts nothing that is not the solver's own result
     serialisation.

   The same split exists in ``openfoam.py`` (``has_solver_evidence`` vs
   ``has_mesh_and_solution``), for the same reason and after the same
   measurement: ``calculix_interface`` gated on the permissive one, and a
   submission whose ``run_case.sh`` was a bare ``printf`` of the right answer
   scored **1.000** once a two-line ``notes.txt`` reading ``CalculiX Version
   2.17`` was dropped beside it (#304).

Evidence taxonomy (CalculiX **outputs**, not the ``.inp`` input — the input
deck can be written without ever solving):
    Result database — ``*.frd`` (the mesh ccx assembled, plus any ``*NODE
                FILE`` / ``*EL FILE`` result blocks) and ``*.dat``
                (``*EL PRINT`` / ``*NODE PRINT`` output). This is what
                :func:`has_result_database` reads, and it reads their
                *structure*, not their names.
    Banner      — any ``*.log`` / ``*.txt`` / ``*.out`` containing the
                CalculiX banner ("CalculiX Version" / "Job finished") within
                the first ~32 KB. Permissive only; never a gate.

Stage emitted:
    ``L2_solver_crash`` — no output artifact at all, OR a log present with a
                          fatal marker (``*ERROR``, singular matrix, …).
When evidence is clean, returns ``None`` — the universal detector decides
L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# CalculiX banner — what ccx writes to stdout / a captured log.
_CALCULIX_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"CalculiX\s+Version"
    r"|This\s+is\s+CalculiX"
    r"|Job\s+finished"
    r"|Total\s+CalculiX\s+Time"
    r")"
)

# Fatal-error markers — solver started but died (L2 even if a stub .dat
# was written).
_CALCULIX_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"\*ERROR"
    r"|nonpositive\s+jacobian"
    r"|negative\s+jacobian"
    r"|singular\s+(?:matrix|equation)"
    r"|increment\s+too\s+small"
    r"|did\s+not\s+converge"
    r"|too\s+many\s+iterations"
    r"|out\s+of\s+memory"
    r")"
)


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    """Walk ``case_dir`` for CalculiX evidence. Returns a dict with:

        frd_files    — list of *.frd result paths
        dat_files    — list of *.dat output paths
        ccx_logs     — list of log/txt/out paths whose head has the banner
    """
    if case_dir is None or not case_dir.is_dir():
        return {"frd_files": [], "dat_files": [], "ccx_logs": []}

    frd_files: list[Path] = []
    dat_files: list[Path] = []
    ccx_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.endswith(".frd"):
            frd_files.append(p)
            continue
        if name_lower.endswith(".dat"):
            dat_files.append(p)
            continue
        if name_lower.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _CALCULIX_BANNER_RE.search(head):
                ccx_logs.append(p)

    return {
        "frd_files": frd_files,
        "dat_files": dat_files,
        "ccx_logs":  ccx_logs,
    }


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence CalculiX was actually run.

    A ``.frd`` or ``.dat`` output (or a CalculiX-banner log) must exist — an
    ``.inp`` alone is not evidence (it is input, writable without solving).

    **This is the permissive form, and the banner branch is why.** A banner is
    nine characters of text in a file whose name the writer chooses; ``printf
    'CalculiX Version 2.17' > notes.txt`` satisfies it. That is tolerable when
    the question is *"did this workspace ever see a solver?"* on a tree nobody
    controlled. It is not tolerable when the answer decides a score, so an
    evaluator gating on evidence wants :func:`has_result_database` instead.
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(
        artifacts["frd_files"]
        or artifacts["dat_files"]
        or artifacts["ccx_logs"]
    )


# ── the strict predicate ────────────────────────────────────────────────────
#
# The two suffixes below are the *only* ones `has_result_database` will open.
# An evaluator that gates on it must delete every one of them before its rerun
# — otherwise a file the submission shipped satisfies the gate that the rerun
# was supposed to satisfy. `calculix_interface.GENERATED_SUFFIXES` is built
# from this tuple rather than repeating it, because #304 is exactly what two
# hand-maintained lists drifting apart costs.

RESULT_DATABASE_SUFFIXES: tuple[str, ...] = (".frd", ".dat")

# An FRD block opens with `<n>C` in the first few columns: `2C` is the nodal
# block, `3C` the element block, `100C` a result block. Records inside a block
# are ` -1` (a datum), ` -2` (its continuation) and ` -3` (block end).
_FRD_BLOCK_RE = re.compile(r"^ {1,6}(\d+)C")


def _frd_blocks(path: Path) -> dict[str, tuple[int | None, int]]:
    """Parse an FRD into ``{block: (declared_count, records_found)}``.

    ``declared_count`` is the count ccx writes into the ``2C`` / ``3C`` header
    itself; it is ``None`` for blocks that do not carry one. Reading both is
    what turns "a file named ``.frd`` exists" into "this file is a serialised
    CalculiX model", and the check is a *format* one — ccx's own counts always
    agree with its own records, so it cannot fail a real run however coarse or
    fine the mesh is.
    """
    blocks: dict[str, tuple[int | None, int]] = {}
    current: str | None = None
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return blocks
    with handle:
        for line in handle:
            header = _FRD_BLOCK_RE.match(line)
            if header:
                current = header.group(1)
                fields = line.split()
                declared: int | None = None
                if len(fields) > 1:
                    try:
                        declared = int(fields[1])
                    except ValueError:
                        declared = None
                blocks[current] = (declared, 0)
                continue
            if current is None:
                continue
            if line.startswith(" -3"):
                current = None
            elif line.startswith(" -1"):
                declared, seen = blocks[current]
                blocks[current] = (declared, seen + 1)
    return blocks


def _frd_holds_the_model(blocks: dict[str, tuple[int | None, int]]) -> bool:
    """True iff the FRD carries the discretisation ccx actually assembled.

    Nodes and elements, each block holding as many records as its own header
    says it does, and at least one of each — a model with no nodes is not a
    model. This is the CalculiX analogue of OpenFOAM's ``polyMesh/`` with
    ``points`` and ``faces``.
    """
    for block in ("2", "3"):
        declared, seen = blocks.get(block, (None, 0))
        if declared is None or declared < 1 or seen != declared:
            return False
    return True


def _dat_holds_printed_results(path: Path) -> bool:
    """True iff a ``.dat`` holds a CalculiX print block: a caption line naming
    what was printed, then at least one whitespace-separated numeric record.

    Deliberately not keyed on which quantity the caption names. What is printed
    is the answerer's choice — ``*NODE PRINT``, ``*EL PRINT``, a contact or
    section print — and a gate that enumerated the captions it had seen would
    zero a legal submission the first time one printed something else. The
    strength here comes from the FRD anchor, not from this.
    """
    caption_seen = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        try:
            [float(f) for f in fields]
        except ValueError:
            caption_seen = True
            continue
        if caption_seen and len(fields) >= 2:
            return True
    return False


def _sibling_dat(frd: Path) -> Path | None:
    """The ``.dat`` ccx writes beside an ``.frd`` for the same job."""
    for candidate in frd.parent.iterdir():
        if (candidate.is_file()
                and candidate.stem == frd.stem
                and candidate.suffix.lower() == ".dat"):
            return candidate
    return None


def has_result_database(ctx: TrialContext) -> bool:
    """Return True iff the tree holds a CalculiX **result database**: the model
    ccx assembled, together with values it solved for.

    Concretely — an ``.frd`` whose ``2C`` and ``3C`` blocks are internally
    consistent (the discretisation), plus either result blocks inside that same
    ``.frd`` (``*NODE FILE`` / ``*EL FILE``) or the ``.dat`` ccx wrote beside it
    (``*NODE PRINT`` / ``*EL PRINT``). Both halves are required for the same
    reason OpenFOAM's strict predicate wants a mesh *and* a non-zero time
    directory: ccx writes the model into the FRD before the step results, so a
    solve that died leaves the first half without the second.

    Three properties are what make this the one admissible as a gate.

    * **Text is not evidence.** No banner branch, at any suffix. The measured
      hole (#304) was not that ``.txt`` was missing from a strip list; it was
      that a *string* counted as proof a solver ran. Removing the branch closes
      every spelling of it at once — ``.md``, no extension, a comment line
      inside ``results.csv`` — rather than the one that happened to be tried.
    * **Nothing on the image satisfies it.** The domain image ships plenty of
      ``.dat`` files (matplotlib and scipy test data; ``Norris.dat`` is caption
      lines followed by numeric rows, which is exactly the shape of a print
      block), so a ``run_case.sh`` that copied one in would pass a ``.dat``-only
      check. It ships **no** ``.frd`` at all, which is why the FRD is the
      anchor and the ``.dat`` only ever the second half.
    * **What it accepts, an evaluator can strip.** Both suffixes are in
      :data:`RESULT_DATABASE_SUFFIXES`, and the packaging evaluator's strip
      list is built from that tuple, so anything able to satisfy this predicate
      is deleted before the rerun by construction.

    What it is *not* is unforgeable: the entry point is arbitrary shell, and a
    submission determined enough to emit a self-consistent FRD by hand can
    still satisfy it. No artifact predicate survives that, openfoam's included
    — the evaluator's own strip-and-rerun is the defence, and this is what
    closes the one hole rerunning leaves.
    """
    if ctx.case_dir is None or not ctx.case_dir.is_dir():
        return False
    for path in ctx.case_dir.rglob("*"):
        if not path.is_file() or not path.name.lower().endswith(".frd"):
            continue
        blocks = _frd_blocks(path)
        if not _frd_holds_the_model(blocks):
            continue
        if blocks.get("100", (None, 0))[1] > 0:
            return True
        dat = _sibling_dat(path)
        if dat is not None and _dat_holds_printed_results(dat):
            return True
    return False


def _has_fatal_error(ccx_logs: list[Path]) -> bool:
    """Check the most-recently-modified CalculiX log for a fatal marker."""
    if not ccx_logs:
        return False
    log = max(ccx_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_CALCULIX_FATAL_RE.search(text))


class CalculiXDetector:
    name = "calculix"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "calculix":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)

        # No output artifact → ccx never produced results → L2.
        if not (artifacts["frd_files"] or artifacts["dat_files"]
                or artifacts["ccx_logs"]):
            return "L2_solver_crash"

        # Output present but log shows a fatal error → L2.
        if _has_fatal_error(artifacts["ccx_logs"]):
            return "L2_solver_crash"

        # Clean — let universal decide L5 / L6.
        return None


register(CalculiXDetector())
