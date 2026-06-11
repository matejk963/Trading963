"""EPS-acceleration classifier (Writer-fed) — ported from
``update_classifications.py`` part 4 (lines 238-293).

Computes EPS growth acceleration per symbol from the actual EPS and the FY1/FY2
consensus means:

    g1 = eps_fy1 - eps_actual    # current-year growth
    g2 = eps_fy2 - eps_fy1       # next-year growth
    eps_accel = g2 - g1          # acceleration (>0 accelerating, <=0 decelerating)

A Writer-fed classifier (adr/0001): a separate unit the Writer runs alongside the
kernel. It consumes the ``Fundamentals`` form (not the price panel) — the Writer
passes ``data.fundamentals(ids, estimates=True)``. The stored ``eps_accel`` column
is the signed acceleration value; null where any input is missing.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("mktt.computed.classifiers.eps_accel")

COLUMN = "eps_accel"

# Fundamentals columns the classifier reads (MKFund schema, snake_case).
_EPS_ACTUAL = "eps_actual"
_FY1_EPS = "fy1_eps_mean"
_FY2_EPS = "fy2_eps_mean"


def classify(fundamentals: pd.DataFrame) -> pd.Series:
    """Return a per-symbol ``eps_accel`` value (Series indexed by symbol).

    Args:
        fundamentals: a ``Fundamentals`` frame (symbol-indexed) carrying
            ``eps_actual`` + ``fy1_eps_mean`` + ``fy2_eps_mean`` (the latter two
            attached via ``DataSource.fundamentals(..., estimates=True)``).
            Symbols missing any input get a null ``eps_accel`` (skipped).
    """
    if fundamentals is None or len(fundamentals) == 0:
        return pd.Series(dtype="float64", name=COLUMN)

    cols = fundamentals.columns
    if not {_EPS_ACTUAL, _FY1_EPS, _FY2_EPS}.issubset(cols):
        missing = {_EPS_ACTUAL, _FY1_EPS, _FY2_EPS} - set(cols)
        logger.debug("eps_accel: fundamentals missing %s — empty result", missing)
        return pd.Series(dtype="float64", name=COLUMN, index=pd.Index([], name="symbol"))

    eps_act = pd.to_numeric(fundamentals[_EPS_ACTUAL], errors="coerce")
    eps_fy1 = pd.to_numeric(fundamentals[_FY1_EPS], errors="coerce")
    eps_fy2 = pd.to_numeric(fundamentals[_FY2_EPS], errors="coerce")

    g1 = eps_fy1 - eps_act
    g2 = eps_fy2 - eps_fy1
    accel = g2 - g1

    accel.name = COLUMN
    # drop symbols where any input was missing (null acceleration)
    accel = accel[eps_act.notna() & eps_fy1.notna() & eps_fy2.notna()]
    logger.debug("eps_accel: %d symbols classified", len(accel))
    return accel
