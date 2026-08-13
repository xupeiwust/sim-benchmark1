"""The emit-time guards in the two case generators.

These exist because both generators shipped a case that looked calibrated and
was not: `calibrate()` catches per case and continues, so a case whose oracle
raised reached `emit()` with `gt_value = None` and was written out with a
ground truth of 0.0, a tolerance band 0.0 wide, and
`oracle_status = local_tolerance_study_calibrated` on top. A guard that never
fires is worth nothing, so each branch is exercised here against the real
generator module rather than a copy of its logic.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name: str):
    """Import a generator by path; it is a script, not an installed package."""
    path = REPO / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pybamm_gen():
    return _load("gen_pybamm_cases")


@pytest.fixture(scope="module")
def cantera_gen():
    return _load("gen_cantera_cases")


def _pybamm_case(gen, **over):
    c = gen.CASES[0]
    from dataclasses import replace
    return replace(c, **over)


def _cantera_case(gen, **over):
    c = gen.CASES[0]
    from dataclasses import replace
    return replace(c, **over)


# ── an uncalibrated case must not reach the case tree ─────────────────────────

@pytest.mark.parametrize("missing", ["gt_value", "pass_tol", "gross_error_tol"])
def test_pybamm_refuses_uncalibrated(pybamm_gen, missing, tmp_path, monkeypatch):
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    fields = {"gt_value": 1.0, "pass_tol": 0.1, "gross_error_tol": 0.5, missing: None}
    c = _pybamm_case(pybamm_gen, **fields)
    with pytest.raises(RuntimeError, match="uncalibrated"):
        pybamm_gen.emit(c)
    assert not list(tmp_path.rglob("task.toml")), "wrote a case it had refused"


@pytest.mark.parametrize("missing", ["gt_value", "pass_tol", "gross_error_tol"])
def test_cantera_refuses_uncalibrated(cantera_gen, missing, tmp_path, monkeypatch):
    monkeypatch.setattr(cantera_gen, "CASES_ROOT", tmp_path)
    fields = {"gt_value": 1.0, "pass_tol": 0.1, "gross_error_tol": 0.5, missing: None}
    c = _cantera_case(cantera_gen, **fields)
    with pytest.raises(RuntimeError, match="uncalibrated"):
        cantera_gen.emit(c)
    assert not list(tmp_path.rglob("task.toml"))


# ── a band of zero width scores every submission against nothing ─────────────

@pytest.mark.parametrize("gt,t_good,t_bad", [
    (0.0, 0.0, 0.0),        # the shape both real failures took
    (5.0, 0.0, 1.0),        # no good band
    (5.0, 1.0, 1.0),        # gross_error_tol must be strictly wider than pass_tol
    (5.0, 2.0, 1.0),        # inverted
])
def test_pybamm_refuses_degenerate_band(pybamm_gen, gt, t_good, t_bad, tmp_path,
                                        monkeypatch):
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    c = _pybamm_case(pybamm_gen, gt_value=gt, pass_tol=t_good, gross_error_tol=t_bad)
    with pytest.raises(RuntimeError, match="degenerate tolerance band"):
        pybamm_gen.emit(c)


def test_cantera_refuses_degenerate_band(cantera_gen, tmp_path, monkeypatch):
    monkeypatch.setattr(cantera_gen, "CASES_ROOT", tmp_path)
    c = _cantera_case(cantera_gen, gt_value=0.0, pass_tol=0.0, gross_error_tol=0.0)
    with pytest.raises(RuntimeError, match="degenerate tolerance band"):
        cantera_gen.emit(c)


# ── the physics window is a hard gate, so gt has to be inside it ─────────────

def test_pybamm_refuses_gt_outside_physics_window(pybamm_gen, tmp_path, monkeypatch):
    """The real instance: a thermal case whose reference rise was 0.06 K against
    a declared floor of 0.5 K would have rejected its own correct answer."""
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    c = _pybamm_case(pybamm_gen, gt_value=0.06, pass_tol=0.002, gross_error_tol=0.012,
                     physics_min=0.5, physics_max=150.0)
    with pytest.raises(RuntimeError, match="outside the physics window"):
        pybamm_gen.emit(c)


def test_pybamm_refuses_gt_above_physics_window(pybamm_gen, tmp_path, monkeypatch):
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    c = _pybamm_case(pybamm_gen, gt_value=900.0, pass_tol=1.0, gross_error_tol=10.0,
                     physics_min=0.5, physics_max=150.0)
    with pytest.raises(RuntimeError, match="outside the physics window"):
        pybamm_gen.emit(c)


def test_cantera_refuses_gt_outside_physics_window(cantera_gen, tmp_path, monkeypatch):
    monkeypatch.setattr(cantera_gen, "CASES_ROOT", tmp_path)
    c = _cantera_case(cantera_gen, gt_value=1e-9, pass_tol=1e-11, gross_error_tol=1e-10,
                      physics_min=0.05, physics_max=200.0)
    with pytest.raises(RuntimeError, match="outside the physics window"):
        cantera_gen.emit(c)


# ── and a properly calibrated case still writes ──────────────────────────────

def test_pybamm_emits_a_calibrated_case(pybamm_gen, tmp_path, monkeypatch):
    """Without this the guards above would pass on a generator that refuses
    everything."""
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    c = _pybamm_case(pybamm_gen, gt_value=4.5, pass_tol=0.09, gross_error_tol=0.9,
                     physics_min=1.0, physics_max=8.0,
                     calibration={"method": "test"})
    pybamm_gen.emit(c)
    written = list(tmp_path.rglob("task.toml"))
    assert len(written) == 1, written


def test_cantera_emits_a_calibrated_case(cantera_gen, tmp_path, monkeypatch):
    monkeypatch.setattr(cantera_gen, "CASES_ROOT", tmp_path)
    c = _cantera_case(cantera_gen, gt_value=1.2, pass_tol=0.02, gross_error_tol=0.2,
                      physics_min=0.05, physics_max=200.0,
                      calibration={"method": "test"})
    cantera_gen.emit(c)
    assert len(list(tmp_path.rglob("task.toml"))) == 1


# ── the declaration that made a whole sweep unrunnable ───────────────────────

def test_generators_emit_a_network_mode_docker_can_enforce():
    """Harbor's docker provider aborts the run on `no-network` rather than
    downgrading, so a generator emitting it produces cases that cannot run at
    all. The verifier container's own isolation must survive the change."""
    for name in ("gen_pybamm_cases", "gen_cantera_cases"):
        src = (REPO / "tools" / f"{name}.py").read_text(encoding="utf-8")
        decls = [ln.strip() for ln in src.splitlines()
                 if ln.lstrip().startswith("network_mode") and "=" in ln]
        assert decls, f"{name}: no network_mode declaration found at all"
        for d in decls:
            assert '"no-network"' not in d, f"{name}: {d}"
        assert "network_mode: none" in src, (
            f"{name}: the verifier container lost its compose-level isolation")


# ── the progress line must not be able to kill the emit (issue #37) ───────────

@pytest.mark.parametrize("gen_name", ["gen_pybamm_cases", "gen_cantera_cases"])
def test_a_path_outside_the_repo_is_reported_not_raised(gen_name, tmp_path):
    """`Path.relative_to` RAISES outside its argument, and this is a LOG line.

    Both generators ended their emit with
    `print(f"  emitted {c.dir.relative_to(REPO)}")`, so a `CASES_ROOT` outside
    the repo killed the generator while reporting work it had already
    finished. There is no `--out` flag; this suite reaches it by
    monkeypatching `CASES_ROOT` to its own `tmp_path`. Both emit-guard tests above
    failed on every host for exactly this reason, and nothing noticed because
    CI ran no pytest target under `lib/`.

    Asserted directly rather than only through those two, so the guard does not
    quietly evaporate if they are ever changed to emit inside the repo.
    """
    gen = _load(gen_name)
    inside = gen.REPO / "cases" / "x"
    assert gen._display_path(inside) == str(Path("cases") / "x")
    outside = tmp_path / "kinetics" / "some_case"
    assert gen._display_path(outside) == str(outside)


# ── --sync-metadata may not revert what the table does not know (issue #161) ──
#
# The first version of this mode re-rendered `task.toml` from the template,
# which is the obvious implementation and the wrong one: eleven published
# combustion cases carry an `oracle_wall_sec` measured on the image and a
# `release_status = "public_runnable"` decided per case for the public sample,
# and neither is in the spec table. A whole-file rewrite silently un-published
# eleven cases and deleted eleven measurements. The mode exists precisely so a
# metadata fix does not have to go through `--emit --calibrate`; a fix that
# reverts other fields is not safer than the thing it replaces.

SYNC_KEYS = ("task_id", "source_url", "prototype_origin", "prototype_delta")


def _synced_case(cantera_gen, tmp_path, monkeypatch, extra_lines: str = ""):
    monkeypatch.setattr(cantera_gen, "CASES_ROOT", tmp_path)
    c = _cantera_case(cantera_gen, gt_value=1.2, pass_tol=0.02, gross_error_tol=0.2,
                      physics_min=0.05, physics_max=200.0,
                      calibration={"method": "test"})
    cantera_gen.emit(c)
    p = c.dir / "task.toml"
    if extra_lines:
        p.write_text(p.read_text(encoding="utf-8").replace(
            '[metadata.sim]\n', f'[metadata.sim]\n{extra_lines}'), encoding="utf-8")
    return c, p


def test_sync_metadata_keeps_fields_the_table_never_knew_about(
        cantera_gen, tmp_path, monkeypatch):
    hand_added = 'oracle_wall_sec   = 19\n'
    c, p = _synced_case(cantera_gen, tmp_path, monkeypatch, hand_added)
    p.write_text(p.read_text(encoding="utf-8").replace(
        'release_status    = "public_draft"',
        'release_status    = "public_runnable"'), encoding="utf-8")

    cantera_gen.sync_metadata(c)

    after = p.read_text(encoding="utf-8")
    assert "oracle_wall_sec   = 19" in after
    assert 'release_status    = "public_runnable"' in after


def test_sync_metadata_sets_every_key_it_owns(cantera_gen, tmp_path, monkeypatch):
    c, p = _synced_case(cantera_gen, tmp_path, monkeypatch)
    stripped = "".join(ln for ln in p.read_text(encoding="utf-8").splitlines(keepends=True)
                       if not ln.startswith(SYNC_KEYS))
    p.write_text(stripped, encoding="utf-8")

    assert cantera_gen.sync_metadata(c) is True
    after = p.read_text(encoding="utf-8")
    for key in SYNC_KEYS:
        assert f"\n{key}" in after, key
    # And it is a fixed point: a second run has nothing left to do.
    assert cantera_gen.sync_metadata(c) is False


def test_sync_metadata_replaces_a_stale_value_in_place(
        cantera_gen, tmp_path, monkeypatch):
    """The url this issue was opened about: every case pointed at the example
    *index* rather than at the one example it derives from."""
    c, p = _synced_case(cantera_gen, tmp_path, monkeypatch)
    p.write_text(p.read_text(encoding="utf-8").replace(
        c.prototype_url,
        "https://cantera.org/stable/examples/python/index.html"), encoding="utf-8")

    cantera_gen.sync_metadata(c)

    after = p.read_text(encoding="utf-8")
    assert "python/index.html" not in after
    assert c.prototype_url in after


def test_every_emitted_instruction_still_matches_the_template_that_made_it(cantera_gen):
    """The prompt on disk and the prompt the generator renders must be one thing.

    They were not. `dd4be98e` added a paragraph to all fifty combustion
    instructions and never touched the template, so re-emitting a case would
    have silently deleted it — and because `emit()` refuses to run without a
    `gt_value`, nobody could re-emit and find out. The contract is the one part
    of a published case that gets fixed without re-deriving ground truth
    (#189), which makes this the drift that costs the most and shows the least.

    A byte comparison rather than a substring one: a paragraph that reaches
    `cases/` and not `tools/` is exactly what this has to catch.
    """
    drifted = []
    for c in cantera_gen.CASES:
        p = c.dir / "instruction.md"
        if not p.is_file():
            continue
        if p.read_text(encoding="utf-8") != cantera_gen.render_instruction(c):
            drifted.append(str(p.relative_to(REPO)))
    assert not drifted, (
        "these instructions were hand-edited away from the generator template; "
        "fold the change into `INSTRUCTION` and re-run "
        "`tools/gen_cantera_cases.py --sync-instruction`: " + ", ".join(drifted)
    )


def test_every_case_in_the_table_can_name_its_prototype(cantera_gen):
    for c in cantera_gen.CASES:
        assert c.prototype_origin.startswith("cantera:samples/python/")
        assert c.prototype_url.startswith("https://cantera.org/stable/examples/python/")
        assert c.prototype_url != "https://cantera.org/stable/examples/python/index.html"
        assert len(c.prototype_delta) > 200


# ── the same three, for the battery generator (issue #202) ───────────────────
#
# Not a copy for symmetry's sake: the trap is bigger here. Twenty of these
# fifty carry `oracle_wall_sec` and `release_status = "public_runnable"`, and
# all fifty carried a hand-added instruction paragraph the template did not
# have — so before #202 the battery generator could reproduce neither its own
# prompts nor its own metadata, and `--emit` was the only mode it had.

def _synced_pybamm_case(pybamm_gen, tmp_path, monkeypatch, extra_lines: str = ""):
    monkeypatch.setattr(pybamm_gen, "CASES_ROOT", tmp_path)
    c = _pybamm_case(pybamm_gen, gt_value=5.0, pass_tol=0.25, gross_error_tol=1.0,
                     calibration={"method": "test"})
    pybamm_gen.emit(c)
    p = c.dir / "task.toml"
    if extra_lines:
        p.write_text(p.read_text(encoding="utf-8").replace(
            '[metadata.sim]\n', f'[metadata.sim]\n{extra_lines}'), encoding="utf-8")
    return c, p


def test_pybamm_sync_metadata_keeps_fields_the_table_never_knew_about(
        pybamm_gen, tmp_path, monkeypatch):
    hand_added = 'oracle_wall_sec   = 20\n'
    c, p = _synced_pybamm_case(pybamm_gen, tmp_path, monkeypatch, hand_added)
    p.write_text(p.read_text(encoding="utf-8").replace(
        'release_status    = "public_draft"',
        'release_status    = "public_runnable"'), encoding="utf-8")

    pybamm_gen.sync_metadata(c)

    after = p.read_text(encoding="utf-8")
    assert "oracle_wall_sec   = 20" in after
    assert 'release_status    = "public_runnable"' in after


def test_pybamm_sync_metadata_sets_every_key_it_owns(pybamm_gen, tmp_path, monkeypatch):
    c, p = _synced_pybamm_case(pybamm_gen, tmp_path, monkeypatch)
    stripped = "".join(ln for ln in p.read_text(encoding="utf-8").splitlines(keepends=True)
                       if not ln.startswith(SYNC_KEYS))
    p.write_text(stripped, encoding="utf-8")

    assert pybamm_gen.sync_metadata(c) is True
    after = p.read_text(encoding="utf-8")
    for key in SYNC_KEYS:
        assert f"\n{key}" in after, key
    assert pybamm_gen.sync_metadata(c) is False


def test_pybamm_sync_metadata_replaces_the_example_index_url_in_place(
        pybamm_gen, tmp_path, monkeypatch):
    """Every battery case pointed at the PyBaMM example *index*, like combustion."""
    c, p = _synced_pybamm_case(pybamm_gen, tmp_path, monkeypatch)
    p.write_text(p.read_text(encoding="utf-8").replace(
        c.prototype_url,
        "https://docs.pybamm.org/en/latest/source/examples/index.html"),
        encoding="utf-8")

    pybamm_gen.sync_metadata(c)

    after = p.read_text(encoding="utf-8")
    assert "examples/index.html" not in after
    assert c.prototype_url in after


def test_every_emitted_battery_instruction_still_matches_its_template(pybamm_gen):
    """All fifty had drifted: the scratch-directories paragraph was in every
    case on disk and in none of the template, so `--emit` would have deleted it
    from fifty published prompts. Byte comparison, for the reason #189 gives.
    """
    drifted = []
    for c in pybamm_gen.CASES:
        p = c.dir / "instruction.md"
        if not p.is_file():
            continue
        if p.read_text(encoding="utf-8") != pybamm_gen.render_instruction(c):
            drifted.append(str(p.relative_to(REPO)))
    assert not drifted, (
        "these instructions were hand-edited away from the generator template; "
        "fold the change into `INSTRUCTION` and re-run "
        "`tools/gen_pybamm_cases.py --sync-instruction`: " + ", ".join(drifted)
    )


def test_every_battery_case_in_the_table_can_name_its_prototype(pybamm_gen):
    for c in pybamm_gen.CASES:
        tool, _, path = c.prototype_origin.partition(":")
        assert tool == "pybamm", c.prototype_origin
        assert path.startswith(("examples/", "docs/source/examples/")), c.prototype_origin
        assert path.endswith((".py", ".ipynb")), c.prototype_origin
        assert c.prototype_url.startswith((
            "https://github.com/pybamm-team/PyBaMM/blob/main/",
            "https://docs.pybamm.org/en/latest/source/examples/notebooks/"))
        assert not c.prototype_url.endswith("examples/index.html")
        assert len(c.prototype_delta) > 200


def test_a_battery_delta_cannot_collide_with_its_own_reference_value(pybamm_gen):
    """No number of three or more significant digits in any delta.

    `tools/lint_agent_visible.py` scans `[metadata.sim]` strings (W2) for a
    value inside a KPI's diagnostic band, and the charge-time cases' references
    are in the thousands of seconds — so writing the O'Regan notebook's year
    into a cccv delta would have landed inside one. The deltas name it without
    the year for exactly that reason; this pins the property rather than the
    wording.
    """
    lav = _load("lint_agent_visible")
    for c in pybamm_gen.CASES:
        offenders = [t for t in lav.NUM_RE.findall(c.prototype_delta)
                     if lav.sig_digits(t) >= 3]
        assert offenders == [], f"{c.slug}: {offenders} in prototype_delta"


# ── the same drift, in the file that carries the numbers (issue #611) ────────
#
# The two sweeps above compare `instruction.md` against the template that
# renders it, and there was no equivalent for `tests/kpis.json`. That is why
# #610's eight hand-edited prompts were refused by CI while its eight
# hand-edited `kpis.json`, in the same commit, went through — and `kpis.json`
# is the file carrying `gt_value`, `pass_tol` and the physics window, so it is
# the more expensive of the two to leave open.
#
# It cannot be re-rendered from the table the way an instruction is: three of
# its inputs are what a solver run measured. So the *oracle* is replayed rather
# than re-run — `_run_variant` and `_measure_ocv_envelope` hand back the
# numbers the file itself records — and the generator's own `calibrate()` and
# `emit()` rebuild the whole file from them. Everything downstream of those
# three inputs is therefore re-derived by the code that writes it rather than
# re-implemented here: the band arithmetic, the rendered description, the
# physics window, the `METHODS` / `DESCRIPTIONS` prose, the module constants
# and the `spec.json` bound all have to come back identical.
#
# What the replay cannot see is whether the recorded variant values are the
# ones the oracle really produced; that needs the solver, and nothing in this
# file has it. What it does see is every edit made to a generated case after
# the fact, which is the whole of what #610 got away with.

# This file used to carry two exceptions here — `RULED_THERMAL_PASS_TOL_BASIS`
# and `PRE_193_GROSS_ERROR_TOL_BASIS`, the two documentation keys the tree and
# the generators disagreed about because `calibrate()` was the only writer of
# `oracle_provenance` and re-derived `gt_value` on the way past. #613 built
# `--sync-basis`, which writes those keys without touching a number, and both
# exceptions are gone: the generators now hold what the tree holds, so the
# sweep below compares every field with no allowance at all. Deleting them was
# the point, and their absence is what says the sync worked.
#
# `pass_tol_basis` is per-kind in the generator now
# (`PASS_TOL_BASIS_BY_KIND`), which is where the scope check moved to: #488's
# correction is about the particle mesh on a thermal rise and is false of the
# other 42 battery cases, so it reaches 8 cases because the generator says
# `thermal` and not because a test lists them.

# Floats are compared with a relative tolerance rather than exactly. 40 of the
# 99 stored `pass_tol` values sit one ULP away from
# `abs(gt_value) * PASS_TOL_FRACTION` recomputed today — measured maximum
# relative difference 2.2e-16, an artefact of how the number was first derived
# rather than a drift. 1e-9 is still seven orders tighter than the smallest
# band change anyone could mean by one.
FLOAT_REL_TOL = 1e-9


def _differences(got, want, path: str = "") -> list[str]:
    """Every field where `got` and `want` disagree, named by its json path."""
    if isinstance(want, dict) and isinstance(got, dict):
        out = []
        for key in sorted(set(want) | set(got)):
            here = f"{path}.{key}" if path else key
            if key not in got:
                out.append(f"{here}: missing (the generator writes {want[key]!r})")
            elif key not in want:
                out.append(f"{here}: {got[key]!r} is not a field the generator writes")
            else:
                out += _differences(got[key], want[key], here)
        return out
    if isinstance(want, float) and isinstance(got, (int, float)) \
            and not isinstance(got, bool):
        if math.isclose(got, want, rel_tol=FLOAT_REL_TOL, abs_tol=0.0):
            return []
        return [f"{path}: {got!r} != {want!r} (generator)"]
    if got != want:
        return [f"{path}: {got!r} != {want!r} (generator)"]
    return []


def _regenerate(gen, case, root: Path, monkeypatch, version_attr: str,
                recorded_provenance: dict):
    """Re-run `calibrate()` + `emit()` with the oracle replaced by its record.

    Returns the `kpis.json` and `spec.json` the generator writes for this case
    given the numbers the case's own provenance block reports.
    """
    # Plain assignment, undone by the caller's `finally`. `monkeypatch.setattr`
    # records whatever it finds each time it is called, so patching this once
    # per case would have it "restore" the module to the previous case's
    # scratch tree — and the generator fixtures are module-scoped, so that
    # outlives the test.
    gen.CASES_ROOT = root
    monkeypatch.setattr(
        gen, "_run_variant",
        lambda c, workdir, **kw: recorded_provenance["variants"][workdir.name]["value"])
    monkeypatch.setattr(
        gen, version_attr,
        lambda: recorded_provenance[version_attr.lstrip("_")])
    if hasattr(gen, "_measure_ocv_envelope"):
        monkeypatch.setattr(gen, "_measure_ocv_envelope",
                            lambda c, workdir: recorded_provenance["ocv_envelope"])

    fresh = replace(case)          # the table rows are module-level and shared
    with contextlib.redirect_stdout(io.StringIO()):
        gen.calibrate(fresh, root / "scratch")
        gen.emit(fresh)
    return (json.loads((fresh.dir / "tests" / "kpis.json").read_text(encoding="utf-8")),
            json.loads((fresh.dir / "tests" / "spec.json").read_text(encoding="utf-8")))


def _sweep_generated_kpis(gen, tmp_path, monkeypatch,
                          version_attr: str) -> tuple[int, list[str]]:
    # `Case.dir` reads the module-level `CASES_ROOT`, which `_regenerate` has
    # to repoint at a scratch tree — so the paths in the real tree are resolved
    # here, once, before anything is patched. Reading them inside the loop
    # instead made every case after the first resolve into the previous case's
    # scratch directory, find no `kpis.json`, and skip: the whole sweep passed
    # in 0.36 s having checked one case. Hence the count the callers assert on.
    real_root = gen.CASES_ROOT
    on_disk_paths = [(case, case.dir / "tests" / "kpis.json",
                      case.dir / "tests" / "spec.json") for case in gen.CASES]

    checked, drifted = 0, []
    try:
        for i, (case, kpis_path, spec_path) in enumerate(on_disk_paths):
            if not kpis_path.is_file():
                continue
            checked += 1
            on_disk = json.loads(kpis_path.read_text(encoding="utf-8"))
            provenance = on_disk.get("oracle_provenance", {})
            if "variants" not in provenance:
                drifted.append(f"{case.slug}: oracle_provenance records no variant study")
                continue

            kpis, spec = _regenerate(gen, case, tmp_path / str(i), monkeypatch,
                                     version_attr, provenance)

            for line in _differences(on_disk, kpis, "kpis.json"):
                drifted.append(f"{case.slug}: {line}")
            if spec_path.is_file():
                for line in _differences(
                        json.loads(spec_path.read_text(encoding="utf-8")),
                        spec, "spec.json"):
                    drifted.append(f"{case.slug}: {line}")
    finally:
        gen.CASES_ROOT = real_root
    return checked, drifted


_DRIFT_HINT = (
    "these generated cases were edited away from the generator that writes "
    "them. `kpis.json` carries the scored contract, so the repair is never to "
    "hand-edit it back: fold the change into the generator and re-render. "
    "For the two documentation keys that is `--sync-basis`, which writes prose "
    "without touching a number (#613); for anything else it is `--calibrate "
    "--emit`, which re-derives `gt_value` and is a contract change.\n  "
)

# A sweep that visits nothing passes, which is how the first version of this
# guard came back green in 0.36 s having checked one case of fifty. Both tracks
# emit every row of their table today, so the count is asserted rather than
# assumed. A row with no case directory fails here, and `--missing-only` is the
# mode that fixes it.
_COVERAGE_HINT = ("swept {checked} of the {total} cases in the generator table; "
                  "a row with no emitted case is a case that does not exist")


def test_every_emitted_battery_kpis_still_matches_the_generator(
        pybamm_gen, tmp_path, monkeypatch):
    """#610 hand-edited eight of these and CI said nothing."""
    checked, drifted = _sweep_generated_kpis(
        pybamm_gen, tmp_path, monkeypatch, "_pybamm_version")
    assert not drifted, _DRIFT_HINT + "\n  ".join(drifted)
    assert checked == len(pybamm_gen.CASES), _COVERAGE_HINT.format(
        checked=checked, total=len(pybamm_gen.CASES))
    assert pybamm_gen.CASES_ROOT == REPO / "cases" / "battery", (
        "the sweep left the module pointing at its scratch tree, and the "
        "generator fixture is module-scoped")


def test_every_emitted_combustion_kpis_still_matches_the_generator(
        cantera_gen, tmp_path, monkeypatch):
    """The same sweep on the track whose `PASS_TOL_BASIS_BY_KIND` is empty.

    Worth having as the control arm: combustion's `pass_tol_basis` matches its
    shared constant on every case, so this half exercises the per-kind lookup
    in the branch where it finds nothing and still has to come back clean.
    """
    checked, drifted = _sweep_generated_kpis(
        cantera_gen, tmp_path, monkeypatch, "_cantera_version")
    assert not drifted, _DRIFT_HINT + "\n  ".join(drifted)
    assert checked == len(cantera_gen.CASES), _COVERAGE_HINT.format(
        checked=checked, total=len(cantera_gen.CASES))
    assert cantera_gen.CASES_ROOT == REPO / "cases" / "combustion"
