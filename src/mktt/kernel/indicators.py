"""Kernel — Indicators (pure, source-blind).

Adds moving-average / slope / return / volume columns to a `TimeSeries`
(a pandas ``symbol × date`` multi-index DataFrame). Each primitive takes the
panel-so-far and returns it with **exactly** its own columns appended
(``TimeSeries → TimeSeries(+cols)``), so the kernel composes as an enrichment
pipeline (spec §5.2).

Ported from ``stage_classifier.compute_all_derived_vectorized`` (lines 39-107),
kept behaviour-equivalent: ``ma_50/150/200`` are simple rolling means, the
exposed ``ma_150_slope`` is the 21-day difference of MA150 (the legacy
``ma_150_slope_21d`` surfaced in ``build_results`` as ``MA150_Slope``).

Pure: no DataSource / DB / Flask / network imports. ``device="cpu"`` keeps a
clean device-agnostic seam; only the CPU/pandas path is implemented (GPU is
deferred — adr/0001).
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Rolling windows (calendar-bar counts), ported verbatim from the legacy kernel.
_MA_WINDOWS = (50, 150, 200)
_SLOPE_LOOKBACK = 21        # MA150 slope = diff over 21 bars (legacy ma_150_slope_21d)
_VOLUME_MA_WINDOW = 50      # legacy volume_ma_50

# Columns this primitive owns. Asserted in tests ("adds exactly its columns").
ADDED_COLUMNS = ("ma_50", "ma_150", "ma_200", "ma_150_slope", "returns", "volume_ma")


def _per_symbol(panel: pd.DataFrame, col: str):
    """Group a wide column by the ``symbol`` index level for per-symbol rolling."""
    return panel[col].groupby(level="symbol", sort=False)


def compute(ts: pd.DataFrame, device: str = "cpu") -> pd.DataFrame:
    """Enrich a ``TimeSeries`` with indicator columns.

    Args:
        ts: ``symbol × date`` multi-index DataFrame; must carry a ``close``
            column (``volume`` optional — ``volume_ma`` is NaN-filled when absent).
        device: compute seam. Only ``"cpu"`` is implemented (pandas); other
            values raise (GPU backend deferred — adr/0001).

    Returns:
        The same panel with :data:`ADDED_COLUMNS` appended, index unchanged.
    """
    if device != "cpu":
        raise NotImplementedError(
            f"indicators.compute: device={device!r} not implemented "
            "(GPU backend deferred — adr/0001); use device='cpu'."
        )
    if "close" not in ts.columns:
        raise ValueError("indicators.compute: TimeSeries must have a 'close' column")

    logger.debug(
        "indicators.compute: rows=%d symbols=%d device=%s",
        len(ts), ts.index.get_level_values("symbol").nunique() if len(ts) else 0, device,
    )

    out = ts.copy()
    close = _per_symbol(out, "close")

    # Moving averages — simple rolling means, per symbol (legacy d['ma_50/150/200']).
    for w in _MA_WINDOWS:
        out[f"ma_{w}"] = close.transform(lambda s, _w=w: s.rolling(_w).mean())

    # MA150 slope — 21-bar difference (legacy d['ma_150_slope_21d'] -> MA150_Slope).
    out["ma_150_slope"] = (
        out["ma_150"].groupby(level="symbol", sort=False).transform(
            lambda s: s.diff(_SLOPE_LOOKBACK)
        )
    )

    # Daily returns — per symbol pct_change (a genuinely shared indicator).
    out["returns"] = close.transform(lambda s: s.pct_change())

    # Volume moving average (legacy d['volume_ma_50']).
    if "volume" in out.columns:
        out["volume_ma"] = (
            out["volume"].groupby(level="symbol", sort=False).transform(
                lambda s: s.rolling(_VOLUME_MA_WINDOW).mean()
            )
        )
    else:
        out["volume_ma"] = pd.Series(index=out.index, dtype="float64")

    return out
