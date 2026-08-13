"""MuJoCo-specific solver-stage detector + evidence check.

Mirrors ``calculix.py`` but with a caveat the others don't have: MuJoCo is
a **pure-Python physics engine** that writes no distinctive output file on
its own. Unlike OpenFOAM (polyMesh + time dirs), CalculiX (``.frd``) or
ngspice (``.raw``), a MuJoCo run leaves nothing on disk unless the script
explicitly dumps state. So the artifact-based gate here is **weaker by
construction** — this is the known multi-solver-anti-cheat gap parked for
v2 (memory: pure-Python solvers produce no distinctive artifact).

What we *can* gate on:
    Primary   — a **trajectory dump** the integrator can only produce by
                actually stepping: a multi-row numeric time series
                (``*.csv`` / ``*.dat`` / ``*.tsv`` with ≥3 rows of ≥2
                numeric columns), or a ``*.npy`` / ``*.npz`` whose name
                signals a trajectory (``traj`` / ``qpos`` / ``qvel`` /
                ``state`` / ``rollout``).
    Secondary — any ``*.log`` / ``*.txt`` carrying the MuJoCo banner.

NOT evidence: the MJCF model (``*.xml`` with ``<mujoco>``) — that is input,
writable without ever stepping the sim (same logic as CalculiX ``.inp``).

Because the artifact gate is weak, the **physics gate** (tight ``pass_tol``
against a high-fidelity / analytical ground truth, plus ``physics_min/max``
bounds) is the primary anti-cheat for MuJoCo pilot cases — a fabricated KPI
that did not come from an actual integration will not land inside a sharp
tolerance band. Cases on this solver should keep ``pass_tol`` tight.

Stage emitted:
    ``L2_solver_crash`` — no trajectory artifact at all, OR a log present
                          with a fatal marker.
When evidence is clean, returns ``None`` — the universal detector decides
L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# MuJoCo banner — what mujoco prints to stdout / a captured log.
_MUJOCO_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"MuJoCo\s+(?:version|Pro|\d)"
    r"|mj_step|mjModel|mjData"
    r"|<mujoco"
    r")"
)

# Fatal markers — engine started but the model/integration failed.
_MUJOCO_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"mjWARN|mj_warning"
    r"|nan\s+detected|inf\s+detected"
    r"|qacc.*(?:nan|inf)"
    r"|Engine\s+error"
    r"|XML\s+(?:Error|parse)"
    r"|unstable\s+simulation"
    r")"
)

# Trajectory-dump filename hints (for binary .npy/.npz we can't sniff content).
_TRAJ_NAME_RE = re.compile(r"(?i)(?:traj|qpos|qvel|qacc|state|rollout|history|sim_out)")


def _looks_like_timeseries(path: Path) -> bool:
    """True if a text file reads as a numeric time series: at least 3
    lines, each (after the first, to allow a header) carrying ≥2
    numeric tokens. Cheap head-only scan, no numpy dependency.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            rows = []
            for _ in range(64):
                line = fh.readline()
                if not line:
                    break
                rows.append(line)
    except OSError:
        return False

    numeric_rows = 0
    num_tok = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
    for line in rows:
        toks = re.split(r"[,\s;\t]+", line.strip())
        nums = [t for t in toks if t and num_tok.fullmatch(t)]
        if len(nums) >= 2:
            numeric_rows += 1
    return numeric_rows >= 3


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    """Walk ``case_dir`` for MuJoCo evidence. Returns a dict with:

        traj_files   — list of trajectory-dump paths (numeric time series
                       or trajectory-named .npy/.npz)
        mj_logs      — list of log/txt paths whose head has the banner
    """
    if case_dir is None or not case_dir.is_dir():
        return {"traj_files": [], "mj_logs": []}

    traj_files: list[Path] = []
    mj_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.endswith((".npy", ".npz")):
            if _TRAJ_NAME_RE.search(name_lower):
                traj_files.append(p)
            continue
        if name_lower.endswith((".csv", ".dat", ".tsv")):
            if _looks_like_timeseries(p):
                traj_files.append(p)
            continue
        if name_lower.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _MUJOCO_BANNER_RE.search(head):
                mj_logs.append(p)

    return {"traj_files": traj_files, "mj_logs": mj_logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence MuJoCo was actually stepped.

    A trajectory dump (numeric time series / trajectory-named array) or a
    MuJoCo-banner log must exist — an MJCF ``.xml`` alone is not evidence
    (it is input, writable without stepping the integrator).
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(artifacts["traj_files"] or artifacts["mj_logs"])


def _has_fatal_error(mj_logs: list[Path]) -> bool:
    """Check the most-recently-modified MuJoCo log for a fatal marker."""
    if not mj_logs:
        return False
    log = max(mj_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_MUJOCO_FATAL_RE.search(text))


class MuJoCoDetector:
    name = "mujoco"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "mujoco":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)

        # No trajectory artifact → integrator never stepped → L2.
        if not (artifacts["traj_files"] or artifacts["mj_logs"]):
            return "L2_solver_crash"

        # Artifact present but log shows a fatal error → L2.
        if _has_fatal_error(artifacts["mj_logs"]):
            return "L2_solver_crash"

        # Clean — let universal decide L5 / L6.
        return None


register(MuJoCoDetector())
