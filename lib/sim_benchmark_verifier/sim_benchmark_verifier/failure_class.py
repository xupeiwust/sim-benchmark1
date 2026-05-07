"""Classify a per-KPI scoring outcome into a small failure-mode enum.

The verifier already records *why* each KPI scored what it did (in
``per_kpi[name]["why"]`` / ``physics_why``). This module reduces those
free-text reasons to a stable enum so leaderboard / aggregation tooling can
group failures by class.

The talk-derived design says: don't just tell users "you scored 0.7"; tell
them whether they got the physics wrong, the meshing wrong, or just the
provenance paperwork wrong. Different failure classes route to different
fixes (data, driver, hook, model).

Per-KPI classes (set by this module):
    null               KPI passed (kpi_score == 1.0)
    physics            value outside [physics_min, physics_max]
    convergence        physics ok, but |pred − gt| > T_bad — model converged
                       to the wrong value
    provenance_path    source.path missing / not a file / not absolute
    extract_runnable   source.extract failed to run (sandbox reject, exit
                       != 0, timeout, etc.)
    extract_format     extract ran fine, but the extracted value differs
                       from agent's claim (paperwork / cherry-pick failure)
    hallucination      KPI absent from result.json, or claim has no
                       ``source`` field, or unknown/invalid source.kind, or
                       extractor returned non-numeric
    spec_error         the case's kpis.json or extract config is itself
                       broken (e.g. unknown source.query) — reported but
                       not the agent's fault

Trial-level classes (NOT set here; populated post-hoc by an aggregator
from harbor / claude-code transcripts):
    wall_time          trial wall hit harbor's cap
    turn_cap           agent hit max_turns
    infra              container / network / license failure

This split is deliberate: per-KPI classes need only the verifier's output,
trial-level classes need the harness transcript. Keeping the boundary
explicit lets the verifier ship its layer without depending on harbor.
"""
from __future__ import annotations


# Public enum (also documented in SCHEMA.md).
PER_KPI_CLASSES = (
    "null",
    "physics",
    "convergence",
    "provenance_path",
    "extract_runnable",
    "extract_format",
    "hallucination",
    "spec_error",
)


def classify_kpi(kpi_result: dict, claim) -> str:
    """Reduce a per-KPI score dict to a failure_class string.

    Inputs
    ------
    kpi_result
        The dict that ``_score_one_kpi`` returns — must have
        ``kpi_score``, ``why`` (when scored 0), and ideally
        ``physics_pass`` / ``t_decay`` / ``physics_why``.
    claim
        The agent's KPI claim from result.json (dict or None) — used to
        spot the "absent / unwrapped value" hallucination shapes.

    Returns
    -------
    One of ``PER_KPI_CLASSES``. Always a string; never None.
    """
    if kpi_result.get("kpi_score", 0.0) == 1.0:
        return "null"

    why = (kpi_result.get("why") or "").lower()

    # ── provenance path — runs first because some "must be absolute"
    #    messages overlap with the generic "must be" hallucination check.
    if "source file not found" in why or "could not be read" in why:
        return "provenance_path"
    if "must be absolute" in why:
        return "provenance_path"

    # ── hallucination — claim-shape problems ───────────────────────────
    if claim is None or "kpi absent from result.json" in why:
        return "hallucination"
    if "kpi claim must be an object" in why or "missing source field" in why:
        return "hallucination"
    if "unknown source.kind" in why:
        return "hallucination"
    if "extracted not numeric" in why or "extractor returned no number" in why:
        return "hallucination"
    # Source object is malformed (e.g. missing path, missing query, bad type).
    # Treat any "source.X missing/must be" message as a claim-side hallucination.
    if " must be " in why and "source." in why:
        return "hallucination"
    if "source.path missing" in why or "source.path may not contain" in why:
        return "hallucination"

    # ── extract runnability ────────────────────────────────────────────
    if "extractor rejected" in why:
        return "extract_runnable"
    if "extractor exited" in why or "extractor timed out" in why:
        return "extract_runnable"

    # ── extract format / value mismatch ────────────────────────────────
    if "value mismatch" in why or "differs from extracted" in why:
        return "extract_format"
    if "extracted value" in why and ("mismatch" in why or "differs" in why):
        return "extract_format"

    # ── spec error — case author's fault, reported but isolated ────────
    if "must be 'completed', 'measure', or 'step_param'" in why:
        return "spec_error"

    # ── physics vs convergence (only reachable when source verified) ───
    if kpi_result.get("source_verified") == 1.0:
        if kpi_result.get("physics_pass") == 0.0:
            return "physics"
        if kpi_result.get("t_decay") == 0.0 and kpi_result.get("physics_pass") == 1.0:
            return "convergence"
        # Partial t_decay (0 < score < 1) — call it convergence too, since
        # the model converged to a value within physics but not within the
        # tolerance window.
        return "convergence"

    # ── catch-all: unknown verifier-internal failure ───────────────────
    # Don't lie with a class we don't actually know — fall back to
    # extract_runnable since most remaining cases are extract pipeline
    # failures we haven't enumerated.
    return "extract_runnable"


def annotate_per_kpi(per_kpi: dict, result_obj: dict) -> dict[str, int]:
    """Mutate ``per_kpi`` in place: add a ``failure_class`` field to each
    entry. Return a class → count distribution for quick aggregation.
    """
    counts: dict[str, int] = {c: 0 for c in PER_KPI_CLASSES}
    for name, kpi_result in per_kpi.items():
        cls = classify_kpi(kpi_result, result_obj.get(name))
        kpi_result["failure_class"] = cls
        counts[cls] = counts.get(cls, 0) + 1
    return counts
