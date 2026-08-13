"""The cavity setup gate must check the physics, not the dictionary's spelling.

It did not, and it cost trials. The check asked whether the literal token
`noSlip;` appeared anywhere in `0/U`. OpenFOAM's older and entirely standard way
of writing the same boundary condition is

    type fixedValue; value uniform (0 0 0);

which is what the tutorials used before `noSlip` existed. Two cavity submissions
wrote that, converged, and were failed at `physics_validation` with "stationary
walls must use no-slip velocity" — correct setups, rejected for their wording.
A case that scores whether the agent guessed our spelling measures nothing about
driving a solver.

The gate must nevertheless stay a gate: a `slip` wall, a missing lid, a lid at
the wrong speed and two moving lids are all different physics and must all still
fail.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_benchmark_verifier.native_openfoam import (  # noqa: E402
    DEFAULT_REPRODUCTION_TIMEOUT_S,
    reproduction_timeout_s,
)
from sim_benchmark_verifier.openfoam_cavity import (  # noqa: E402
    _check_cavity_velocity_patches as check,
)


def test_the_reproduction_budget_comes_from_the_case_not_the_family():
    """One budget for the family let a case fail on wall-clock, not on physics.

    Re=100's oracle runs in ~77 s and Re=3200's in ~487 s against a shared
    600 s limit, and the same Re=3200 oracle has been measured at 250 s and
    1180 s on different hosts -- so the limit sat inside its own reference
    solution's spread and the stored rows sorted by machine speed.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        tests = Path(temp_dir)
        (tests / "spec.json").write_text('{"reproduction_timeout_s": 2400}', encoding="utf-8")
        assert reproduction_timeout_s(tests) == 2400


def test_a_case_without_a_spec_keeps_the_old_budget():
    with tempfile.TemporaryDirectory() as temp_dir:
        assert reproduction_timeout_s(Path(temp_dir)) == DEFAULT_REPRODUCTION_TIMEOUT_S


def test_a_spec_without_a_budget_keeps_the_old_budget():
    with tempfile.TemporaryDirectory() as temp_dir:
        tests = Path(temp_dir)
        (tests / "spec.json").write_text('{"case_id": "x"}', encoding="utf-8")
        assert reproduction_timeout_s(tests) == DEFAULT_REPRODUCTION_TIMEOUT_S


def _field(*patches: str) -> str:
    return "boundaryField\n{\n" + "\n".join(patches) + "\n}\n"


LID = "  movingWall { type fixedValue; value uniform (1 0 0); }"
EMPTY = "  frontAndBack { type empty; }"


def test_the_modern_noSlip_spelling_passes():
    check(_field(LID, "  fixedWalls { type noSlip; }", EMPTY))


def test_the_classic_zero_fixedValue_spelling_passes_too():
    """The regression: identical physics, different words, previously rejected."""
    check(_field(
        "  top { type fixedValue; value uniform (1 0 0); }",
        "  bottom { type fixedValue; value uniform (0 0 0); }",
        "  left { type fixedValue; value uniform (0 0 0); }",
        "  right { type fixedValue; value uniform (0 0 0); }",
        "  front { type empty; }",
        "  back { type empty; }",
    ))


def test_zeros_written_with_decimal_points_are_still_zero():
    check(_field(LID, "  fixedWalls { type fixedValue; value uniform (0.0 0.0 0.0); }",
                 EMPTY))


def test_a_slip_wall_is_not_a_no_slip_wall():
    with pytest.raises(RuntimeError, match="stationary no-slip wall"):
        check(_field(LID, "  fixedWalls { type slip; }", EMPTY))


def test_a_zeroGradient_wall_is_rejected():
    with pytest.raises(RuntimeError, match="stationary no-slip wall"):
        check(_field(LID, "  fixedWalls { type zeroGradient; }", EMPTY))


def test_a_case_with_no_moving_lid_is_rejected():
    with pytest.raises(RuntimeError, match="exactly one patch must move"):
        check(_field("  top { type fixedValue; value uniform (0 0 0); }",
                     "  fixedWalls { type noSlip; }", EMPTY))


def test_a_lid_at_the_wrong_speed_is_rejected():
    with pytest.raises(RuntimeError, match="stationary no-slip wall"):
        check(_field("  top { type fixedValue; value uniform (2 0 0); }",
                     "  fixedWalls { type noSlip; }", EMPTY))


def test_two_moving_lids_are_rejected():
    with pytest.raises(RuntimeError, match="exactly one patch must move"):
        check(_field(LID, "  other { type fixedValue; value uniform (1 0 0); }",
                     "  fixedWalls { type noSlip; }", EMPTY))


def test_walls_that_are_all_lid_leave_no_stationary_wall():
    with pytest.raises(RuntimeError):
        check(_field(LID, EMPTY))


def test_a_field_without_a_boundaryField_block_is_an_error():
    with pytest.raises(RuntimeError, match="boundaryField"):
        check("internalField uniform (0 0 0);\n")
