"""MA-position screen classifier (Writer-fed) — ported from
``update_classifications.py`` part 3 (lines 207-233).

Buckets each symbol by the latest close's position relative to its MA50 / MA200
into one of four categories. A Writer-fed classifier (adr/0001): a separate unit
the Writer runs alongside the kernel; produces the ``ma_screen`` column.

Pure: takes the kernel-enriched ``symbol × date`` panel (which already carries
``ma_50`` / ``ma_200`` from :mod:`kernel.indicators` — no MA recompute) and returns
a per-symbol code over the **latest** row per symbol.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("mktt.computed.classifiers.ma_screen")

COLUMN = "ma_screen"

# Bucket codes (stable, stored). Names preserve the legacy screener categories.
LABELS = {
    0: "Above Both",
    1: "Above 200 Below 50",
    2: "Below 200 Above 50",
    3: "Below Both",
}

_REQUIRED = ("close", "ma_50", "ma_200")


def _latest_per_symbol(panel: pd.DataFrame, cols) -> pd.DataFrame:
    """The last (by date) row per symbol, for the given columns."""
    sub = panel[list(cols)]
    # last row per symbol — index is symbol × date sorted; take tail(1) per group.
    last = sub.groupby(level="symbol", sort=False).tail(1)
    last.index = last.index.get_level_values("symbol")
    return last


def classify(panel: pd.DataFrame) -> pd.Series:
    """Return a per-symbol ``ma_screen`` code (Series indexed by symbol).

    Args:
        panel: kernel-enriched ``symbol × date`` panel carrying ``close``,
            ``ma_50``, ``ma_200``.
    """
    missing = [c for c in _REQUIRED if c not in panel.columns]
    if missing:
        raise ValueError(f"ma_screen.classify: missing columns {missing}")
    if len(panel) == 0:
        return pd.Series(dtype="float64", name=COLUMN)

    latest = _latest_per_symbol(panel, _REQUIRED)
    price = latest["close"]
    ma50 = latest["ma_50"]
    ma200 = latest["ma_200"]

    code = pd.Series(pd.NA, index=latest.index, dtype="object")
    above50 = price > ma50
    above200 = price > ma200
    code[(above200) & (above50)] = 0
    code[(above200) & (~above50)] = 1
    code[(~above200) & (above50)] = 2
    code[(~above200) & (~above50)] = 3
    # rows where ma is NaN stay NA
    code[ma50.isna() | ma200.isna()] = pd.NA

    out = pd.to_numeric(code, errors="coerce")
    out.name = COLUMN
    logger.debug("ma_screen: %d symbols classified", out.notna().sum())
    return out
