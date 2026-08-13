"""CadQuery / OpenCascade-specific solver-stage detector + evidence check.

Mirrors ``calculix.py``. The "solver" in the CAD domain is the geometry
kernel (OpenCascade, driven through CadQuery / FreeCAD, or Gmsh for the
mesh side). Two responsibilities:

1. **Solver-stage detection**: scan the workspace for kernel output
   artifacts and emit a stage label.

2. **Evidence check** (anti-cheat): expose ``has_solver_evidence(ctx)``
   so the grader can hard-zero analytical shortcuts. CAD KPIs (volume,
   mass, centre of mass, moments of inertia) are *exact* kernel
   quantities an LLM can sometimes approximate by hand for simple
   primitives; this gate forces an actual kernel build.

Evidence taxonomy (kernel **outputs**, not the build *script* — a
``.py`` CadQuery script or ``.scad`` source can be written without ever
running the kernel):
    Primary   — a B-rep / exchange export the kernel can only write after
                building the solid: ``*.step`` / ``*.stp`` / ``*.brep`` /
                ``*.iges`` / ``*.igs`` / ``*.fcstd`` (FreeCAD document with
                a recomputed shape) / ``*.msh`` (Gmsh mesh of the solid).
    Secondary — ``*.stl`` (tessellated export — weaker, trimesh can write
                one without OCC, but still a produced-geometry artifact)
                and any ``*.log`` / ``*.txt`` carrying the OCC / CadQuery /
                FreeCAD / Gmsh banner.

Stage emitted:
    ``L2_solver_crash`` — no geometry artifact at all, OR a log present
                          with a fatal kernel marker (BRep build failed,
                          null shape, …).
When evidence is clean, returns ``None`` — the universal detector decides
L5 / L6 from KPI fields.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import TrialContext, register


# Strong B-rep / exchange exports — only writable after a real kernel build.
# NB: a mesh (.msh) is the MESHER's output, not the CAD kernel's — excluded so
# that in a CAD->CFD/FEM chain a stray mesh can't masquerade as CAD evidence.
_CAD_PRIMARY_EXTS = (".step", ".stp", ".brep", ".iges", ".igs", ".fcstd")
# Weaker tessellated export.
_CAD_SECONDARY_EXTS = (".stl",)

# Kernel banner — what CadQuery / FreeCAD / Gmsh / OCP write to a log.
_CAD_BANNER_RE = re.compile(
    r"(?i)(?:"
    r"cadquery"
    r"|opencascade|open\s*cascade|OCP\b|OCCT\b"
    r"|FreeCAD"
    r"|Gmsh\s+\d"
    r"|GProp|mass\s+propert"
    r")"
)

# Fatal kernel markers — build started but produced no valid solid.
_CAD_FATAL_RE = re.compile(
    r"(?i)(?:"
    r"BRep_API:\s*command\s+not\s+done"
    r"|null\s+shape"
    r"|standard_(?:null|constructionerror)"
    r"|failed\s+to\s+(?:build|fuse|cut|loft)"
    r"|StdFail_NotDone"
    r"|no\s+such\s+(?:face|edge|solid)"
    r")"
)


def _scan_for_artifacts(case_dir: Path | None) -> dict:
    """Walk ``case_dir`` for CAD-kernel evidence. Returns a dict with:

        primary    — list of B-rep/exchange/mesh export paths
        secondary  — list of *.stl tessellated export paths
        cad_logs   — list of log/txt paths whose head has the kernel banner
    """
    if case_dir is None or not case_dir.is_dir():
        return {"primary": [], "secondary": [], "cad_logs": []}

    primary: list[Path] = []
    secondary: list[Path] = []
    cad_logs: list[Path] = []

    for p in case_dir.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.endswith(_CAD_PRIMARY_EXTS):
            primary.append(p)
            continue
        if name_lower.endswith(_CAD_SECONDARY_EXTS):
            secondary.append(p)
            continue
        if name_lower.endswith((".log", ".txt", ".out")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:32 * 1024]
            except OSError:
                continue
            if _CAD_BANNER_RE.search(head):
                cad_logs.append(p)

    return {"primary": primary, "secondary": secondary, "cad_logs": cad_logs}


def has_solver_evidence(ctx: TrialContext) -> bool:
    """Return True iff there's artifact evidence the CAD kernel was run.

    A produced-geometry export (``.step`` / ``.brep`` / ``.stl`` / ``.msh``
    …) or a kernel-banner log must exist — a ``.py`` build script or
    ``.scad`` source alone is not evidence (it is input, writable without
    running the kernel).
    """
    if ctx.case_dir is None:
        return False
    artifacts = _scan_for_artifacts(ctx.case_dir)
    return bool(
        artifacts["primary"]
        or artifacts["secondary"]
        or artifacts["cad_logs"]
    )


def _has_fatal_error(cad_logs: list[Path]) -> bool:
    """Check the most-recently-modified kernel log for a fatal marker."""
    if not cad_logs:
        return False
    log = max(cad_logs, key=lambda p: p.stat().st_mtime)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_CAD_FATAL_RE.search(text))


class CadQueryDetector:
    name = "cadquery"
    STAGES: tuple[str, ...] = ("L2_solver_crash",)

    def applicable(self, ctx: TrialContext) -> bool:
        if ctx.solver_label == "cadquery":
            return True
        if ctx.case_dir is None:
            return False
        return has_solver_evidence(ctx)

    def detect(self, kpi_result: dict, ctx: TrialContext) -> str | None:
        if ctx.case_dir is None:
            return None
        artifacts = _scan_for_artifacts(ctx.case_dir)

        # No geometry artifact → kernel never produced a solid → L2.
        if not (artifacts["primary"] or artifacts["secondary"]
                or artifacts["cad_logs"]):
            return "L2_solver_crash"

        # Artifact present but log shows a fatal kernel error → L2.
        if _has_fatal_error(artifacts["cad_logs"]):
            return "L2_solver_crash"

        # Clean — let universal decide L5 / L6.
        return None


register(CadQueryDetector())
