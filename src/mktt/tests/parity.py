"""Parity comparator for the MKTT kernel-centric refactor.

`assert_parity(actual, golden, ...)` is the single tolerant-compare primitive
every later slice uses to prove behavior parity against the frozen golden
fixtures captured from the CURRENT code (see `tests/fixtures/golden/`).

It is deliberately I/O-free and dependency-light (stdlib only) so it can run in
any environment a slice's test runs in. It compares the JSON-shaped structures
the fixtures are stored as: nested dicts / lists / scalars, where floats are
compared tolerantly and NaN/None are treated as a single "missing" sentinel.

Tolerances:
    rel_tol — relative tolerance for floats (default 1e-6)
    abs_tol — absolute tolerance for floats (default 1e-9)

A float matches golden if it is within EITHER tolerance (abs OR rel), mirroring
`math.isclose`. Integers compare exactly unless they sit beside a float (then the
float rule applies). Strings/bools compare exactly.
"""
from __future__ import annotations

import math
from typing import Any


class ParityError(AssertionError):
    """Raised when actual diverges from golden beyond tolerance."""


# Sentinel for "value is missing" — unifies None / NaN so that a golden NaN and
# an actual None (both meaning "no value") are considered equal.
_MISSING = object()


def _canon(v: Any) -> Any:
    """Collapse None and float('nan') to a single MISSING sentinel."""
    if v is None:
        return _MISSING
    if isinstance(v, float) and math.isnan(v):
        return _MISSING
    return v


def _floatish(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _compare(actual: Any, golden: Any, path: str, rel_tol: float, abs_tol: float,
             diffs: list) -> None:
    a = _canon(actual)
    g = _canon(golden)

    # Both missing -> equal.
    if a is _MISSING and g is _MISSING:
        return
    if a is _MISSING or g is _MISSING:
        diffs.append(f"{path}: missing mismatch (actual={actual!r} golden={golden!r})")
        return

    # Dicts.
    if isinstance(g, dict):
        if not isinstance(a, dict):
            diffs.append(f"{path}: type mismatch (actual is {type(a).__name__}, golden is dict)")
            return
        gkeys, akeys = set(g.keys()), set(a.keys())
        for k in gkeys - akeys:
            diffs.append(f"{path}.{k}: missing in actual")
        for k in akeys - gkeys:
            diffs.append(f"{path}.{k}: unexpected in actual")
        for k in gkeys & akeys:
            _compare(a[k], g[k], f"{path}.{k}", rel_tol, abs_tol, diffs)
        return

    # Lists / tuples.
    if isinstance(g, (list, tuple)):
        if not isinstance(a, (list, tuple)):
            diffs.append(f"{path}: type mismatch (actual is {type(a).__name__}, golden is list)")
            return
        if len(a) != len(g):
            diffs.append(f"{path}: length mismatch (actual={len(a)} golden={len(g)})")
            return
        for i, (av, gv) in enumerate(zip(a, g)):
            _compare(av, gv, f"{path}[{i}]", rel_tol, abs_tol, diffs)
        return

    # Numbers — tolerant compare when either side is a non-bool number.
    if _floatish(a) and _floatish(g):
        if not math.isclose(float(a), float(g), rel_tol=rel_tol, abs_tol=abs_tol):
            diffs.append(
                f"{path}: float mismatch actual={a!r} golden={g!r} "
                f"(rel_tol={rel_tol}, abs_tol={abs_tol})"
            )
        return

    # Everything else (str, bool) — exact.
    if a != g:
        diffs.append(f"{path}: mismatch actual={a!r} golden={g!r}")


def diff_parity(actual: Any, golden: Any, rel_tol: float = 1e-6,
                abs_tol: float = 1e-9) -> list:
    """Return a list of human-readable difference strings (empty == parity)."""
    diffs: list = []
    _compare(actual, golden, "$", rel_tol, abs_tol, diffs)
    return diffs


def assert_parity(actual: Any, golden: Any, rel_tol: float = 1e-6,
                  abs_tol: float = 1e-9, max_report: int = 20) -> None:
    """Assert that `actual` matches `golden` within tolerance.

    Raises ParityError listing up to `max_report` divergences. Floats are
    compared with `math.isclose` (abs OR rel). None and NaN are interchangeable
    "missing" values.
    """
    diffs = diff_parity(actual, golden, rel_tol=rel_tol, abs_tol=abs_tol)
    if diffs:
        shown = diffs[:max_report]
        more = len(diffs) - len(shown)
        msg = f"parity failed: {len(diffs)} difference(s)\n  " + "\n  ".join(shown)
        if more > 0:
            msg += f"\n  ... and {more} more"
        raise ParityError(msg)
