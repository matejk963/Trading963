"""Tests for the parity comparator + smoke test of a frozen golden fixture.

The comparator (`assert_parity`) is the contract every later refactor slice uses
to prove behavior parity against the baseline captured in
`tests/fixtures/golden/`. These are pure unit tests (no DB/net/Flask) plus one
smoke test that loads a real golden fixture and round-trips it through the
comparator.
"""
import json
import math
from pathlib import Path

import pytest

from parity import assert_parity, diff_parity, ParityError

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


# --------------------------------------------------------------------------- #
# Tolerant float compare
# --------------------------------------------------------------------------- #
def test_identical_scalars_pass():
    assert_parity({"a": 1, "b": "x", "c": True}, {"a": 1, "b": "x", "c": True})


def test_float_within_rel_tol_passes():
    assert_parity({"x": 100.0000001}, {"x": 100.0}, rel_tol=1e-6)


def test_float_outside_tol_fails():
    with pytest.raises(ParityError):
        assert_parity({"x": 100.5}, {"x": 100.0}, rel_tol=1e-9, abs_tol=1e-9)


def test_abs_tol_handles_near_zero():
    # rel_tol useless near 0; abs_tol must catch it.
    assert_parity({"x": 1e-12}, {"x": 0.0}, rel_tol=1e-6, abs_tol=1e-9)


def test_int_and_float_compared_tolerantly():
    assert_parity({"x": 5}, {"x": 5.0000000001})


# --------------------------------------------------------------------------- #
# NaN / None treated as a single "missing"
# --------------------------------------------------------------------------- #
def test_nan_equals_none():
    assert_parity({"x": float("nan")}, {"x": None})
    assert_parity({"x": None}, {"x": float("nan")})


def test_nan_equals_nan():
    assert_parity({"x": float("nan")}, {"x": float("nan")})


def test_value_vs_missing_fails():
    with pytest.raises(ParityError):
        assert_parity({"x": 1.0}, {"x": None})


# --------------------------------------------------------------------------- #
# Structure mismatches
# --------------------------------------------------------------------------- #
def test_missing_key_fails():
    diffs = diff_parity({"a": 1}, {"a": 1, "b": 2})
    assert any("b" in d for d in diffs)


def test_extra_key_fails():
    diffs = diff_parity({"a": 1, "b": 2}, {"a": 1})
    assert any("b" in d for d in diffs)


def test_list_length_mismatch_fails():
    with pytest.raises(ParityError):
        assert_parity([1, 2, 3], [1, 2])


def test_nested_list_of_dicts_pass():
    a = {"rows": [{"sym": "AAPL", "ma": 1.000001}, {"sym": "MSFT", "ma": 2.0}]}
    g = {"rows": [{"sym": "AAPL", "ma": 1.0}, {"sym": "MSFT", "ma": 2.0}]}
    assert_parity(a, g, rel_tol=1e-5)


def test_string_mismatch_fails():
    with pytest.raises(ParityError):
        assert_parity({"stage": "Uptrend"}, {"stage": "Basing"})


# --------------------------------------------------------------------------- #
# Smoke test — load a frozen golden fixture and round-trip it
# --------------------------------------------------------------------------- #
def test_golden_dir_exists():
    assert GOLDEN_DIR.is_dir(), f"golden fixtures dir missing: {GOLDEN_DIR}"


def test_kernel_golden_roundtrips_through_parity():
    path = GOLDEN_DIR / "kernel_stage.json"
    assert path.exists(), "kernel_stage.json golden fixture missing"
    golden = json.loads(path.read_text())
    # A fixture compared against itself is, by definition, in parity.
    assert_parity(golden, golden)


def test_kernel_golden_has_expected_shape():
    path = GOLDEN_DIR / "kernel_stage.json"
    golden = json.loads(path.read_text())
    assert "meta" in golden and "rows" in golden
    assert golden["meta"]["n_symbols"] == len(golden["rows"])
    assert golden["meta"]["n_symbols"] >= 30
    # Each row carries the kernel-equivalent columns this baseline freezes.
    sample = golden["rows"][0]
    for col in ("Symbol", "Stage", "MA50", "MA150", "MA200",
                "Mansfield_RS", "RS_Rank"):
        assert col in sample, f"row missing column {col}"


def test_kernel_golden_perturbation_is_caught():
    """A real divergence in the baseline must fail parity — guards against a
    no-op comparator."""
    path = GOLDEN_DIR / "kernel_stage.json"
    golden = json.loads(path.read_text())
    perturbed = json.loads(json.dumps(golden))
    # Bump one MA200 well beyond tolerance.
    perturbed["rows"][0]["MA200"] = (perturbed["rows"][0]["MA200"] or 0.0) + 100.0
    with pytest.raises(ParityError):
        assert_parity(perturbed, golden)


def test_gex_golden_roundtrips_if_present():
    """GEX golden is best-effort (needs option data at capture time). Skip if the
    generator could not reach option data."""
    path = GOLDEN_DIR / "gex_profile.json"
    if not path.exists():
        pytest.skip("gex_profile.json not captured (option data unreachable)")
    golden = json.loads(path.read_text())
    assert_parity(golden, golden)
