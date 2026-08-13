"""Private evaluator adapter for the canonical Ghia cavity family."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from .native_openfoam import (
    EvaluationResult,
    NativeOpenFOAMTask,
    dictionary_block,
    dictionary_text,
    evaluate,
    install_sample_dict,
    band_verdict,
    openfoam_command,
    reproduction_timeout_s,
)


_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_VECTOR = re.compile(rf"uniform\s*\(\s*({_NUM})\s+({_NUM})\s+({_NUM})\s*\)")


def _patch_entries(boundary_field: str) -> list[tuple[str, str]]:
    """(patch name, body) for each entry of a `boundaryField` block."""
    entries, index = [], 0
    while True:
        match = re.compile(r"([A-Za-z_][\w.\"|()-]*)\s*\{").search(boundary_field, index)
        if not match:
            return entries
        start, depth = boundary_field.find("{", match.start()), 0
        for i in range(start, len(boundary_field)):
            if boundary_field[i] == "{":
                depth += 1
            elif boundary_field[i] == "}":
                depth -= 1
                if depth == 0:
                    entries.append((match.group(1), boundary_field[start + 1:i]))
                    index = i + 1
                    break
        else:
            return entries


def _check_cavity_velocity_patches(velocity: str) -> None:
    """Every wall is stationary no-slip except one lid moving at (1 0 0).

    This checks the PHYSICS on each patch, not the spelling of one keyword, and
    the difference cost real trials. The previous form asked whether the literal
    token `noSlip;` appeared anywhere in `0/U`. OpenFOAM's older and entirely
    standard way of stating the same condition —

        type fixedValue; value uniform (0 0 0);

    — is what the tutorials used before `noSlip` existed and what a practitioner
    may still write. Two cavity trials submitted exactly that, converged, and
    were failed at `physics_validation` with "stationary walls must use no-slip
    velocity". Their setups were correct; the check was a dictionary-form quiz,
    and a case that scores whether the agent guessed our spelling measures
    nothing about driving a solver.

    The gate itself is not relaxed, and must not be: a stationary wall still has
    to be exactly zero velocity (a `slip` or `zeroGradient` wall changes the
    answer), and there still has to be exactly one lid at (1 0 0).
    """
    try:
        boundary = dictionary_block(velocity, "boundaryField")
    except RuntimeError:
        raise RuntimeError("0/U has no boundaryField block") from None

    moving, stationary, bad = [], [], []
    for name, body in _patch_entries(boundary):
        kind = re.search(r"\btype\s+(\w+)\s*;", body)
        kind = kind.group(1) if kind else ""
        if kind == "empty":
            continue
        if kind == "noSlip":
            stationary.append(name)
            continue
        vector = _VECTOR.search(body)
        if kind == "fixedValue" and vector:
            ux, uy, uz = (float(v) for v in vector.groups())
            if (ux, uy, uz) == (0.0, 0.0, 0.0):
                stationary.append(name)
            elif (ux, uy, uz) == (1.0, 0.0, 0.0):
                moving.append(name)
            else:
                bad.append(f"{name}: fixedValue ({ux:g} {uy:g} {uz:g})")
            continue
        bad.append(f"{name}: type {kind or '?'}")

    if bad:
        raise RuntimeError(
            "every velocity patch must be a stationary no-slip wall, the moving "
            "lid at (1 0 0), or empty; got " + "; ".join(sorted(bad)))
    if len(moving) != 1:
        raise RuntimeError(
            f"exactly one patch must move at (1 0 0); found {len(moving)}")
    if not stationary:
        raise RuntimeError("the stationary walls must be no-slip (zero velocity)")


def run_cavity(case_id: str, nu: float, tests_dir: Path) -> int:
    reward_dir = Path(os.environ.get("SIM_BENCH_REWARD_DIR", "/logs/verifier"))

    def validate_setup(case: Path) -> dict:
        transport = dictionary_text(case, "constant/transportProperties")
        match = re.search(r"\bnu\s+(?:\[[^\]]+\]\s*)?([-+0-9.eE]+)\s*;", transport)
        if not match or not math.isclose(float(match.group(1)), nu, rel_tol=1e-6):
            raise RuntimeError(f"kinematic viscosity must be nu={nu:.12g}")
        turbulence = dictionary_text(case, "constant/turbulenceProperties")
        if not re.search(r"\bsimulationType\s+laminar\s*;", turbulence):
            raise RuntimeError("simulationType must be laminar")
        velocity = dictionary_text(case, "0/U")
        if not re.search(r"\bempty\s*;", velocity):
            raise RuntimeError("spanwise velocity boundary must be empty")
        _check_cavity_velocity_patches(velocity)
        return {"nu": nu, "simulation_type": "laminar", "lid_velocity": [1, 0, 0]}

    def latest_profile(case: Path) -> Path:
        paths = list(case.glob("postProcessing/evaluatorSample/*/verticalCenterline_U.xy"))
        paths += list(case.glob("postProcessing/evaluatorSample/*/verticalCenterline_U.raw"))
        if not paths:
            raise RuntimeError("evaluator sampling produced no centerline profile")
        return max(paths, key=lambda path: float(path.parent.name))

    def extract_minimum(path: Path) -> tuple[float, int]:
        """Minimum Ux on the sampled vertical centerline.

        A `sets` entry with `axis y` and `setFormat raw` writes the axis
        coordinate followed by the field components -- `y Ux Uy Uz`, four
        columns, not the full `x y z Ux Uy Uz`. Reading columns 1 and 3
        instead returns Ux as the coordinate and Uz as the value, and Uz is
        identically zero in a 2D flow, so every case silently scores against
        u_min = 0.0 with a healthy-looking sample count.
        """
        values: list[float] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.replace("(", " ").replace(")", " ").split()
            if len(parts) < 2:
                continue
            try:
                y, ux = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            if math.isfinite(y) and math.isfinite(ux) and 0 <= y <= 1:
                values.append(ux)
        if len(values) < 100:
            raise RuntimeError(f"only {len(values)} valid centerline samples")
        return min(values), len(values)

    def extract_and_score(case: Path, solved_time: Path) -> EvaluationResult:
        # Place the sampling line at the submission's own mid-span rather than
        # at the z the template happens to carry. This family found that defect
        # first -- a hard-coded z put the line outside any slab that was not the
        # oracle's own, and cost three otherwise-correct submissions -- and then
        # fixed it only here, which left the same bug live in three other cases.
        # `install_sample_dict` is that fix, shared.
        install_sample_dict(
            case, tests_dir / "evaluator_sampleDict", "system/evaluatorSample", reward_dir
        )
        openfoam_command(
            case,
            "postProcess -func evaluatorSample -latestTime",
            timeout_s=120,
            log_path=reward_dir / "evaluator_postProcess.log",
        )
        value, sample_count = extract_minimum(latest_profile(case))
        private = json.loads((tests_dir / "kpis.json").read_text(encoding="utf-8"))["kpis"]
        spec = private["u_min_vertical_centerline"]
        error = abs(value - float(spec["gt_value"]))
        if value < float(spec["physics_min"]) or value > float(spec["physics_max"]):
            score, reason = 0.0, "outside physics range"
        else:
            score, reason = band_verdict(error, spec)
        return EvaluationResult(
            score=score,
            detail={
                "extraction": {
                    "solved_time": solved_time.name,
                    "sample_count": sample_count,
                    "u_min_vertical_centerline": value,
                },
                "scoring": {
                    "absolute_error": error,
                    "score": round(score, 4),
                    "reason": reason,
                },
            },
        )

    return evaluate(
        NativeOpenFOAMTask(
            case_id=case_id,
            solved_fields=("U", "p"),
            validate_setup=validate_setup,
            extract_and_score=extract_and_score,
            reproduction_timeout_s=reproduction_timeout_s(tests_dir),
        )
    )
