"""Small shared runtime for evaluator-owned OpenFOAM reproduction.

The shared layer deliberately knows nothing about a task's physics or KPI.
Each case supplies private callbacks for setup validation and field extraction;
this module only owns the stable lifecycle and reward interface.
"""
from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .detectors.openfoam import holds_a_written_field


FAILURE_CATEGORIES = {
    "invalid_submission",
    "reproduction_failed",
    # A budget the evaluator ran out of, not a defect it found. Folded into
    # `reproduction_failed` this was indistinguishable from a mesh that will
    # never build, which hid a case whose stored rows sorted by wall-clock
    # instead of by physics -- including its own oracle failing on a slow host.
    "reproduction_timeout",
    "invalid_physics_setup",
    "invalid_mesh",
    "extraction_failed",
    "under_resolved_mesh",
    "evaluator_error",
}


class EvaluationFailure(RuntimeError):
    """Expected submission failure with a stable public category."""

    def __init__(self, category: str, message: str):
        if category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown native OpenFOAM failure category: {category}")
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class EvaluationResult:
    score: float
    detail: dict[str, Any]


SetupValidator = Callable[[Path], dict[str, Any]]
Extractor = Callable[[Path, Path], EvaluationResult]


@dataclass(frozen=True)
class NativeOpenFOAMTask:
    case_id: str
    solved_fields: tuple[str, ...]
    extract_and_score: Extractor
    validate_setup: SetupValidator | None = None
    reproduction_timeout_s: int = 720
    command_timeout_s: int = 120
    extra_generated_paths: tuple[str, ...] = ()
    submission_env: str = "SIM_BENCH_SUBMISSION"
    reward_env: str = "SIM_BENCH_REWARD_DIR"


DEFAULT_REPRODUCTION_TIMEOUT_S = 720


def reproduction_timeout_s(tests_dir: Path) -> int:
    """The case's own reproduction budget, from `tests/spec.json`.

    **A reproduction budget is a ceiling, not a duration.** It costs nothing
    when it is not hit, so sizing it generously does not raise rollout cost --
    it only stops the guard firing on correct work. Sizing it *tightly* is what
    costs, and the price is a zero that looks like bad physics.

    One shared default was wrong because the cases differ by an order of
    magnitude in cost while the budget did not. Measured against each case's own
    recorded `oracle_wall_sec`, five cfd cases had under 2x margin and one --
    `ercoftac_periodic_hill_re10595`, oracle 710 s against a 720 s budget -- had
    1%. At Re=3200 the consequence is on record: two submissions timed out at
    exactly 600 s while the only one that passed used 522 s of it, and the
    case's own oracle costs 487 s, so the limit sat inside the noise band of its
    own reference solution.

    Size it as oracle cost x machine-speed spread (2.4x observed across this
    repo's hosts for one deterministic case) x room for a submission finer than
    the oracle, which on the harder cases is the point of the case.

    **The oracle is a weak proxy for what a correct submission costs, and it
    under-predicts.** Sizing at 5x the oracle was calibrated assuming a
    submission runs at most ~2x the reference; re-scoring measured one at 4.2x
    (`backstep_laminar_armaly_re389`: a 230 s oracle, a correct submission at
    963 s), which ate 80% of the budget that assumption produced. So where a
    correct submission has actually been timed, `measured_submission_wall_sec`
    records it and the budget is sized from *that* instead -- the oracle only
    sets the floor for cases nobody has measured yet. A budget a known-good
    submission fills past about 60% is one machine away from failing again.
    """
    spec = tests_dir / "spec.json"
    if not spec.is_file():
        return DEFAULT_REPRODUCTION_TIMEOUT_S
    try:
        value = json.loads(spec.read_text(encoding="utf-8")).get("reproduction_timeout_s")
    except json.JSONDecodeError:
        return DEFAULT_REPRODUCTION_TIMEOUT_S
    return int(value) if isinstance(value, (int, float)) else DEFAULT_REPRODUCTION_TIMEOUT_S


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def without_foam_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//.*?$", " ", text, flags=re.MULTILINE)


def dictionary_text(case: Path, relative_path: str) -> str:
    """Read an expanded OpenFOAM dictionary when foamDictionary is available."""
    path = case / relative_path
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing OpenFOAM dictionary: {relative_path}")
    if shutil.which("foamDictionary"):
        proc = subprocess.run(
            ["foamDictionary", "-expand", relative_path],
            cwd=case,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return without_foam_comments(proc.stdout)
    return without_foam_comments(path.read_text(encoding="utf-8", errors="replace"))


def dictionary_block(text: str, name: str) -> str:
    """Return a named OpenFOAM dictionary block using balanced braces."""
    match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*\{{", text)
    if not match:
        raise RuntimeError(f"missing OpenFOAM dictionary block: {name}")
    start = text.find("{", match.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise RuntimeError(f"unterminated OpenFOAM dictionary block: {name}")


def boundary_field_blocks(field_text: str) -> dict[str, str]:
    """patch name -> its `boundaryField` sub-block, for one `0/<field>` file."""
    boundary = dictionary_block(field_text, "boundaryField")
    return {
        name: dictionary_block(boundary, name)
        for name in re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", boundary)
    }


def boundary_field_types(field_text: str) -> dict[str, str]:
    """patch name -> its `boundaryField` type, for one `0/<field>` file."""
    result: dict[str, str] = {}
    for name, block in boundary_field_blocks(field_text).items():
        match = re.search(r"\btype\s+([A-Za-z0-9_]+)\s*;", block)
        if match:
            result[name] = match.group(1)
    return result


def sole_patch(candidates: list[str], role: str, saw: dict[str, str]) -> str:
    """The one patch filling a role, or a failure that says what the role IS.

    Boundary-patch *names* are the submission's to choose: nothing in a case's
    problem statement mandates them, so a verifier that requires a spelling is
    testing vocabulary, not engineering -- and it fails a correct run for calling
    the far field `topWall` instead of `top`. Roles are discovered from what each
    patch does; what stays enforced is that each role is filled exactly once, so
    a submission with no free-stream boundary still fails, and now says so.
    """
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one {role} boundary, found {sorted(candidates)} "
            f"among patches {saw}"
        )
    return candidates[0]


def poly_mesh_bounds(case: Path) -> tuple[float, float, float, float, float, float]:
    """Read reproduced native polyMesh point bounds without trusting logs."""
    points = case / "constant/polyMesh/points"
    if not points.is_file() or points.stat().st_size == 0:
        raise RuntimeError("reproduced case has no polyMesh points")
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    vectors = re.findall(
        rf"\(\s*({number})\s+({number})\s+({number})\s*\)",
        points.read_text(encoding="utf-8", errors="replace"),
    )
    if len(vectors) < 8:
        raise RuntimeError("could not parse reproduced polyMesh points")
    xyz = [(float(x), float(y), float(z)) for x, y, z in vectors]
    return (
        min(point[0] for point in xyz), max(point[0] for point in xyz),
        min(point[1] for point in xyz), max(point[1] for point in xyz),
        min(point[2] for point in xyz), max(point[2] for point in xyz),
    )


def poly_mesh_boundary_patch_types(case: Path) -> dict[str, str]:
    """Read patch name -> type from the reproduced native polyMesh boundary file.

    Cyclic/wall/empty are mesh-level patch properties fixed at blockMesh time,
    so this is authoritative regardless of how a submitted 0/<field> groups
    patches into boundaryField entries (e.g. one merged regex entry covering
    a cyclic pair, which a raw string count over the field file would miss).
    """
    boundary = case / "constant/polyMesh/boundary"
    if not boundary.is_file() or boundary.stat().st_size == 0:
        raise RuntimeError("reproduced case has no polyMesh boundary file")
    text = without_foam_comments(
        boundary.read_text(encoding="utf-8", errors="replace")
    )
    result: dict[str, str] = {}
    for name in re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", text):
        block = dictionary_block(text, name)
        match = re.search(r"\btype\s+([A-Za-z0-9_]+)\s*;", block)
        if match:
            result[name] = match.group(1)
    return result


def bounds_from_check_mesh_output(
    text: str,
) -> tuple[float, float, float, float, float, float]:
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    match = re.search(
        rf"(?:Overall\s+domain\s+)?bounding box\s*\(\s*({number})\s+({number})\s+({number})\s*\)\s*"
        rf"\(\s*({number})\s+({number})\s+({number})\s*\)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise RuntimeError("could not parse bounding box from evaluator checkMesh output")
    x0, y0, z0, x1, y1, z1 = map(float, match.groups())
    return x0, x1, y0, y1, z0, z1


def reproduced_mesh_bounds(
    case: Path, reward_dir: Path, timeout_s: int = 120
) -> tuple[float, float, float, float, float, float]:
    """Read ASCII points directly, or ask OpenFOAM for binary-mesh bounds."""
    try:
        return poly_mesh_bounds(case)
    except RuntimeError:
        log_path = reward_dir / "evaluator_checkMesh_bounds.log"
        openfoam_command(
            case,
            "checkMesh",
            timeout_s=timeout_s,
            log_path=log_path,
            check=False,
        )
        return bounds_from_check_mesh_output(
            log_path.read_text(encoding="utf-8", errors="replace")
        )


AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def sample_dict_on_mid_plane(text: str, low: float, high: float, axis: str = "z") -> str:
    """Move every sample coordinate in an evaluator dictionary onto a mid-plane.

    A 2D case states its in-plane domain and asks for "a one-cell-thick slab";
    the slab's *spanwise* extent is therefore the submission's to choose, and
    both conventions are correct -- z in [0, t] like the OpenFOAM tutorials, or
    z in [-t/2, +t/2] centred on zero. An evaluator dictionary that names a
    literal spanwise coordinate silently assumes one of them: the point lands
    outside the other's mesh, `cloud` sampling reports `did not found 1 points
    out of 1`, and a converged, mesh-clean, physically correct run scores zero
    for a convention nothing in its instruction pinned down.

    So the spanwise coordinate is not read from the dictionary but computed from
    the reproduced mesh. Every 3-vector's `axis` component is replaced; the
    in-plane components, which the contract *does* fix, are left untouched.
    These dictionaries hold sample geometry and nothing else, so rewriting all
    of them is the whole intent rather than a broad-brush approximation.

    A case that genuinely constrains the spanwise extent (and enforces it, as
    `turbulent_channel_flow_retau590` enforces its mesh bounds) does not need
    this -- there the literal coordinate is part of a contract the submission
    was told about.
    """
    if axis not in AXIS_INDEX:
        raise ValueError(f"unknown sampling axis: {axis!r}")
    index = AXIS_INDEX[axis]
    mid = repr(0.5 * (low + high))
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

    def replace(match: re.Match[str]) -> str:
        parts = list(match.groups())
        parts[index] = mid
        return "(" + " ".join(parts) + ")"

    return re.sub(rf"\(\s*({number})\s+({number})\s+({number})\s*\)", replace, text)


def install_sample_dict(
    case: Path,
    source: Path,
    destination: str,
    reward_dir: Path,
    *,
    axis: str = "z",
    timeout_s: int = 120,
) -> dict[str, Any]:
    """Install an evaluator sample dictionary onto the reproduced mesh's mid-plane.

    Replaces the plain copy each case used to do. See `sample_dict_on_mid_plane`
    for why the spanwise coordinate cannot be a literal.
    """
    bounds = reproduced_mesh_bounds(case, reward_dir, timeout_s=timeout_s)
    low, high = bounds[2 * AXIS_INDEX[axis]], bounds[2 * AXIS_INDEX[axis] + 1]
    target = case / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        sample_dict_on_mid_plane(
            source.read_text(encoding="utf-8", errors="replace"), low, high, axis=axis
        ),
        encoding="utf-8",
    )
    return {
        "dictionary": destination,
        "axis": axis,
        "mesh_extent": [low, high],
        "sample_plane": 0.5 * (low + high),
    }


def band_verdict(error: float, spec: dict) -> tuple[float, str]:
    """Binary tolerance-band verdict, with the reason spelled out.

    The single implementation lives in `score.band_score`; this wrapper
    exists only to pull `pass_tol` out of the KPI spec (accepting the
    historical `T_good` spelling) and to phrase the reason for
    reward_detail.json.
    """
    from .score import band_score, pass_tol

    tol = pass_tol(spec)
    if band_score(error, tol) == 1.0:
        return 1.0, f"inside the tolerance band (|err| {error:.6g} <= pass_tol {tol:.6g})"
    return 0.0, f"outside the tolerance band (|err| {error:.6g} > pass_tol {tol:.6g})"


def discover_openfoam_bashrc() -> Path | None:
    if shutil.which("checkMesh"):
        return None
    candidates = [Path("/usr/lib/openfoam/openfoam2412/etc/bashrc")]
    candidates.extend(sorted(Path("/usr/lib/openfoam").glob("openfoam*/etc/bashrc")))
    candidates.extend(sorted(Path("/opt").glob("openfoam*/etc/bashrc")))
    for bashrc in candidates:
        if bashrc.is_file():
            return bashrc
    raise RuntimeError("OpenFOAM runtime is unavailable")


def is_case_root(path: Path) -> bool:
    """An OpenFOAM case root, identified by its `system/` directory.

    Anchoring on `system/` rather than on "looks numeric" is what keeps a
    stripper from deleting a directory that merely has a numeric name somewhere
    else in the submission -- a grid-study driver may well keep `20/`, `40/`,
    `80/` as *inputs* one level up from any case (#199).
    """
    return (path / "system").is_dir()


def every_directory(root: Path) -> list[Path]:
    """`root` and every directory under it, parents before children.

    Sorted, so a parent is always visited before its children and a stripper
    that deletes a child never revisits it as a live directory. Callers still
    have to skip entries that a previous iteration removed.
    """
    return sorted(p for p in [root, *root.rglob("*")] if p.is_dir())


def is_time_directory(path: Path) -> bool:
    """One run's output at one time, as opposed to an input that looks numeric.

    Three conditions, and the last is what keeps a whole-tree strip from eating
    inputs. Numerically named and past zero, because that is what OpenFOAM calls
    a time directory. **Not itself a case root**, because a grid study's levels
    are legitimately named `20/ 40/ 80/` and deleting those cost a submission
    that matched the oracle to ten significant figures (#199). And either it
    sits directly in a case root -- where every numeric child is a time
    directory by construction, which is what the cfd track has always assumed --
    or it holds a file named as a field the solver writes, which is the same
    question `detectors.openfoam` asks before it will accept a solution. A
    `meshes/20/` holding a `blockMeshDict` is an input under both readings.
    """
    try:
        value = float(path.name)
    except ValueError:
        return False
    if value <= 0 or is_case_root(path):
        return False
    return is_case_root(path.parent) or holds_a_written_field(path)


GENERATED_DIRECTORY_NAMES = ("postProcessing", "polyMesh")


def is_generated(path: Path) -> bool:
    """True iff `path` is something an OpenFOAM run wrote, not something it read.

    The four shapes a run leaves behind, and the reason the list is here rather
    than inline in two strippers: `detectors.openfoam` reads `polyMesh` and time
    directories with `rglob` from the submission root, so any disagreement
    between what that predicate can see and what the strippers delete is a
    shipped solution the rerun is never asked to reproduce.
    """
    if path.is_dir():
        return (path.name in GENERATED_DIRECTORY_NAMES
                or path.name.startswith("processor")
                or is_time_directory(path))
    return path.is_file() and path.name.startswith("log.")


CASE_INPUT_DIRECTORIES = ("0", "constant", "system")


def case_input_roots(case: Path) -> list[Path]:
    """Every directory under `case` -- `case` included -- that holds a case.

    "Holds a case" is the same triple this check has always asked for,
    `0/ constant/ system/`; what moved is that it may sit anywhere rather than
    at the submission root. A KPI defined as a *relation between runs* needs two
    configurations solved and compared, so its submission has one `system/` per
    configuration and nothing at the root -- and the layout is the submission's
    to choose, which is precisely what "The output interface" leaves free.

    Note this is a stricter test than :func:`is_case_root`, and the two are
    deliberately different questions. This one asks "did the agent hand over
    something runnable"; that one asks "are this directory's numeric children
    time directories", which only needs `system/` to answer.
    """
    return [
        path for path in every_directory(case)
        if all((path / name).is_dir() for name in CASE_INPUT_DIRECTORIES)
    ]


def validate_submission(case: Path) -> None:
    """The handover is runnable: an entry point, and a case for it to run.

    `Allrun` stays pinned to the submission root because the evaluator's rerun
    is literally `bash ./Allrun` from there. The case directories are not: see
    :func:`case_input_roots`.
    """
    missing: list[str] = []
    allrun = case / "Allrun"
    if not allrun.is_file() or allrun.stat().st_size == 0:
        missing.append("Allrun")
    if not case_input_roots(case):
        missing.append(
            "a case directory holding " + ", ".join(f"{n}/" for n in CASE_INPUT_DIRECTORIES)
        )
    if missing:
        raise EvaluationFailure(
            "invalid_submission", "missing reproducible case inputs: " + ", ".join(missing)
        )


def clean_generated_artifacts(
    case: Path, extra_generated_paths: tuple[str, ...] = ()
) -> list[str]:
    """Delete only generated state in an evaluator-owned copy.

    **The reach has to be the whole tree, because the reach of the check this
    feeds is the whole tree.** `detectors.openfoam` globs `polyMesh` and numeric
    time directories with `rglob` from the submission root, so a strip that
    walked one level left `solved/run_a/constant/polyMesh` and
    `solved/run_a/1000/U` in place for an entry point to copy back -- the gate
    read further than the strip did. Since `validate_submission` no longer pins
    the case to the submission root, that gap would have been reachable by
    simply nesting.

    `extra_generated_paths` gets the same treatment: an author names a relative
    path and it is matched at any depth, rather than at the one level they
    happened to be thinking of.
    """
    removed: list[str] = []
    for directory in every_directory(case):
        if not directory.is_dir():  # a previous iteration removed it
            continue
        for child in sorted(directory.iterdir()):
            if is_generated(child):
                removed.append(child.relative_to(case).as_posix())
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    for relative in extra_generated_paths:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"unsafe generated path: {relative!r}")
        for target in [case / path, *case.rglob(path.as_posix())]:
            if target.exists():
                removed.append(target.relative_to(case).as_posix())
                shutil.rmtree(target) if target.is_dir() else target.unlink()
    return sorted(set(removed))


def openfoam_command(
    case: Path,
    command: str,
    *,
    timeout_s: int,
    log_path: Path,
    check: bool = True,
) -> dict[str, Any]:
    bashrc = discover_openfoam_bashrc()
    prefix = (
        f"set +e; set +u; source {shell_quote(str(bashrc))}; "
        "set -e; set -u; command -v checkMesh >/dev/null && "
        if bashrc
        else ""
    )
    script = f"{prefix}cd {shell_quote(str(case))} && {command}"
    started = time.monotonic()
    proc = subprocess.Popen(
        ["bash", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        # Terminate the complete process group, not only the parent shell.
        # OpenFOAM's solver is a child of Allrun; killing just bash lets the
        # solver retain the output pipes and makes the configured deadline
        # appear tens of seconds longer in practice.
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGTERM)
            else:  # Unit-test/diagnostic fallback; evaluators run on Linux.
                proc.terminate()
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, getattr(signal, "SIGKILL", 9))
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        output = (stdout or "") + (stderr or "")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
        raise RuntimeError(f"command timed out after {timeout_s}s: {command}") from exc
    output = (stdout or "") + (stderr or "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {proc.returncode}: {command}; {output[-800:]}"
        )
    return {
        "command": command,
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": proc.returncode,
        "log": log_path.name,
    }


def latest_solved_time(case: Path, solved_fields: tuple[str, ...]) -> Path:
    candidates: list[tuple[float, Path]] = []
    for path in case.iterdir():
        if not path.is_dir():
            continue
        try:
            time_value = float(path.name)
        except ValueError:
            continue
        if time_value <= 0:
            continue
        if all((path / field).is_file() and (path / field).stat().st_size for field in solved_fields):
            candidates.append((time_value, path))
    if not candidates:
        raise RuntimeError(
            "Allrun produced no non-zero time containing non-empty " + ", ".join(solved_fields)
        )
    return max(candidates, key=lambda item: item[0])[1]


def check_mesh(case: Path, reward_dir: Path, timeout_s: int) -> dict[str, Any]:
    """Gate topology/geometry failures while treating pure cell stretching diagnostically."""
    basic_log = reward_dir / "evaluator_checkMesh.log"
    basic = openfoam_command(
        case, "checkMesh", timeout_s=timeout_s, log_path=basic_log
    )
    output = basic_log.read_text(encoding="utf-8", errors="replace")
    failed = re.search(r"Failed\s+(\d+)\s+mesh checks", output)
    failed_count = int(failed.group(1)) if failed else 0
    mesh_ok_marker = "Mesh OK." in output
    required_validity_markers = (
        "Boundary definition OK.",
        "Cell to face addressing OK.",
        "Point usage OK.",
        "Face vertices OK.",
        "Number of regions: 1 (OK).",
        "Cell volumes OK.",
        "Non-orthogonality check OK.",
        "Face pyramids OK.",
    )
    high_aspect_ratio_only = (
        failed_count == 1
        and "High aspect ratio cells found" in output
        and all(marker in output for marker in required_validity_markers)
        and re.search(r"Max skewness\s*=.*\bOK\.", output) is not None
    )
    if not ((mesh_ok_marker and failed_count == 0) or high_aspect_ratio_only):
        raise RuntimeError("default checkMesh did not report a valid mesh")

    extended_log = reward_dir / "evaluator_checkMesh_allGeometry.log"
    extended = openfoam_command(
        case,
        "checkMesh -allGeometry",
        timeout_s=timeout_s,
        log_path=extended_log,
        check=False,
    )
    extended_output = extended_log.read_text(encoding="utf-8", errors="replace")
    failed = re.search(r"Failed\s+(\d+)\s+mesh checks", extended_output)
    return {
        **basic,
        "mesh_ok": True,
        "mesh_ok_marker": mesh_ok_marker,
        "failed_check_count": failed_count,
        "accepted_diagnostic": "high_aspect_ratio_only" if high_aspect_ratio_only else None,
        "all_geometry_diagnostic": {
            **extended,
            "mesh_ok_marker": "Mesh OK." in extended_output,
            "failed_check_count": int(failed.group(1)) if failed else 0,
            "hard_gate": False,
        },
    }


def write_reward(reward_dir: Path, score: float, detail: dict[str, Any]) -> None:
    reward_dir.mkdir(parents=True, exist_ok=True)
    (reward_dir / "reward.json").write_text(
        json.dumps({"score": round(score, 4)}, indent=2), encoding="utf-8"
    )
    (reward_dir / "reward_detail.json").write_text(
        json.dumps(detail, indent=2), encoding="utf-8"
    )


def evaluate(task: NativeOpenFOAMTask) -> int:
    submission = Path(os.environ.get(task.submission_env, "/tmp/agent/submission"))
    reward_dir = Path(os.environ.get(task.reward_env, "/logs/verifier"))
    detail: dict[str, Any] = {
        "schema_version": "native-openfoam-v2.2",
        "case_id": task.case_id,
        "evaluator_owned_reproduction": True,
        "evaluator_owned_extraction": True,
        "status": "running",
        "stage": "submission_validation",
        "checks": {},
    }
    try:
        validate_submission(submission)
        detail["checks"]["reproducible_case_inputs"] = "passed"
        with tempfile.TemporaryDirectory(prefix=f"{task.case_id}-evaluator-") as temp_dir:
            eval_case = Path(temp_dir) / "case"
            shutil.copytree(submission, eval_case)
            removed = clean_generated_artifacts(
                eval_case, task.extra_generated_paths
            )

            detail["stage"] = "reproduction"
            try:
                reproduction = openfoam_command(
                    eval_case,
                    "bash ./Allrun",
                    timeout_s=task.reproduction_timeout_s,
                    log_path=reward_dir / "evaluator_Allrun.log",
                )
                solved_time = latest_solved_time(eval_case, task.solved_fields)
            except Exception as exc:
                category = ("reproduction_timeout" if "timed out after" in str(exc)
                            else "reproduction_failed")
                raise EvaluationFailure(category, str(exc)) from exc
            detail["reproduction"] = {
                **reproduction,
                "timeout_s": task.reproduction_timeout_s,
                "removed_prior_artifacts": removed,
                "latest_solved_time": solved_time.name,
                "required_fields": list(task.solved_fields),
            }

            if task.validate_setup:
                detail["stage"] = "physics_validation"
                try:
                    detail["physics_setup"] = task.validate_setup(eval_case)
                except EvaluationFailure:
                    raise
                except Exception as exc:
                    raise EvaluationFailure("invalid_physics_setup", str(exc)) from exc
                detail["checks"]["physics_setup"] = "passed"

            detail["stage"] = "mesh_validation"
            try:
                detail["mesh"] = check_mesh(
                    eval_case, reward_dir, task.command_timeout_s
                )
            except Exception as exc:
                raise EvaluationFailure("invalid_mesh", str(exc)) from exc
            detail["checks"]["mesh"] = "passed"

            detail["stage"] = "extraction"
            try:
                result = task.extract_and_score(eval_case, solved_time)
            except EvaluationFailure:
                raise
            except Exception as exc:
                raise EvaluationFailure("extraction_failed", str(exc)) from exc
            detail.update(result.detail)
            detail["status"] = "completed"
            detail["stage"] = "complete"
            write_reward(reward_dir, result.score, detail)
            return 0
    except EvaluationFailure as exc:
        detail["status"] = "failed"
        detail["failure_category"] = exc.category
        detail["error"] = str(exc)
        write_reward(reward_dir, 0.0, detail)
        return 0
    except Exception as exc:  # evaluator bugs must stay distinguishable
        detail["status"] = "failed"
        detail["failure_category"] = "evaluator_error"
        detail["error"] = f"{type(exc).__name__}: {exc}"
        write_reward(reward_dir, 0.0, detail)
        return 0
