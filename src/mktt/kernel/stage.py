"""Kernel — StageClassification (Weinstein 1-4, pure, source-blind).

:func:`compute` adds a single ``stage`` column (0=Unclassified, 1=Basing,
2=Uptrend, 3=Topping, 4=Declining) to a ``TimeSeries`` (``symbol × date``
multi-index). It **reuses** the moving-average / RS columns earlier pipeline
steps added — it never recomputes MAs (spec §5.2).

Ported behaviour-equivalent from ``stage_classifier.classify_all_stages``
(lines 114-194). The classification needs a few intermediates the spec does not
surface as kernel columns (52-week-high distance, distribution days, the
*annualized* MA150 slope %). These are derived **inside** stage.compute from the
``close`` / ``volume`` / ``ma_*`` columns already present — so the MA columns are
read, not recomputed, while stage stays a single-column enrichment.

Pure: no provider / DB / Flask / network imports. ``device="cpu"`` only
(GPU deferred — adr/0001).
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

ADDED_COLUMNS = ("stage",)

# Columns the classifier expects to already exist (produced by Indicators / RS).
_REQUIRED = ("close", "ma_50", "ma_150", "ma_200", "rs_rank")

# Intermediate windows (ported from the legacy kernel).
_HIGH_52W_WINDOW = 252
_HIGH_52W_MIN = 126
_SLOPE_PCT_LOOKBACK = 21
_SLOPE_PCT_ANNUALIZER = 12
_DIST_DAYS_WINDOW = 25
_VOLUME_MA_WINDOW = 50

STAGE_LABELS = {0: "Unclassified", 1: "Basing", 2: "Uptrend", 3: "Topping", 4: "Declining"}


def _g(panel: pd.DataFrame, col: str):
    return panel[col].groupby(level="symbol", sort=False)


def compute(ts: pd.DataFrame, device: str = "cpu") -> pd.DataFrame:
    """Add the Weinstein ``stage`` column, reusing prior ``ma_*``/``rs`` columns.

    Args:
        ts: ``symbol × date`` panel already enriched by
            :mod:`kernel.indicators` and :mod:`kernel.relative_strength`
            (and :func:`relative_strength.rank`) — must carry
            ``close, ma_50, ma_150, ma_200, rs_rank``.
        device: ``"cpu"`` only (GPU deferred — adr/0001).
    """
    if device != "cpu":
        raise NotImplementedError(
            f"stage.compute: device={device!r} not implemented "
            "(GPU deferred — adr/0001); use device='cpu'."
        )
    missing = [c for c in _REQUIRED if c not in ts.columns]
    if missing:
        raise ValueError(
            f"stage.compute: missing prerequisite columns {missing}; run "
            "indicators.compute → relative_strength.compute → .rank first "
            "(stage reuses ma_*/rs columns, it does not recompute them)."
        )

    out = ts.copy()
    if len(out) == 0:
        out["stage"] = pd.Series(index=out.index, dtype="int64")
        return out

    close = out["close"]
    ma50, ma150, ma200 = out["ma_50"], out["ma_150"], out["ma_200"]

    # --- intermediates derived from existing columns (no MA recompute) -------
    # Annualized MA150 slope % (legacy ma_150_slope_pct = pct_change(21)*12).
    ma150_slope_pct = _g(out, "ma_150").transform(
        lambda s: s.pct_change(_SLOPE_PCT_LOOKBACK) * _SLOPE_PCT_ANNUALIZER
    )

    # 52-week high distance ratio (legacy dist_52w_high = close / 252-bar max).
    high_52w = _g(out, "close").transform(
        lambda s: s.rolling(_HIGH_52W_WINDOW, min_periods=_HIGH_52W_MIN).max()
    )
    dist_52w_high = close / high_52w

    # Distribution days in trailing 25 bars (down day on above-average volume).
    if "volume" in out.columns:
        vol_ma = out.get("volume_ma")
        if vol_ma is None:
            vol_ma = _g(out, "volume").transform(
                lambda s: s.rolling(_VOLUME_MA_WINDOW).mean()
            )
        down_day = close < _g(out, "close").shift(1)
        above_avg_vol = out["volume"] > vol_ma
        dist_day = (down_day & above_avg_vol).astype(float)
        dist_days_25 = dist_day.groupby(level="symbol", sort=False).transform(
            lambda s: s.rolling(_DIST_DAYS_WINDOW).sum()
        )
    else:
        dist_days_25 = pd.Series(float("nan"), index=out.index)

    rs_rank = out["rs_rank"]

    # --- price/MA position ratios (legacy classify_all_stages) ---------------
    pct_vs_ma50 = (close / ma50 - 1) * 100
    pct_vs_ma150 = (close / ma150 - 1) * 100
    ma150_vs_ma200 = (ma150 / ma200 - 1) * 100

    # --- stage masks (ported verbatim) ---------------------------------------
    stage2 = (
        (close > ma50) & (close > ma150) & (ma50 > ma150)
        & (ma150_vs_ma200 > 0)
        & (ma150_slope_pct > 0.20)
        & (dist_52w_high >= 0.85)
        & (rs_rank >= 60)
        & (dist_days_25 < 5)
    )
    stage4 = (
        (close < ma50) & (close < ma150) & (ma50 < ma150)
        & (ma150_vs_ma200 < 0)
        & (ma150_slope_pct < -0.30)
        & (dist_52w_high < 0.65)
        & (rs_rank < 25)
    )
    stage3 = (
        (ma150_vs_ma200 > 0)
        & (pct_vs_ma50 < 5)
        & (dist_days_25 >= 4)
        & (dist_52w_high >= 0.60)
        & (rs_rank < 75)
    )
    stage1 = (
        (ma150_slope_pct.abs() < 0.40)
        & (pct_vs_ma150 > -20) & (pct_vs_ma150 < 20)
        & (ma150_vs_ma200 <= 0)
        & (dist_days_25 < 5)
        & (dist_52w_high <= 0.85)
        & (rs_rank < 70)
    )

    # Priority: S2 > S4 > S3 > S1 > 0 (legacy assignment order).
    stage = pd.Series(0, index=out.index, dtype="int64")
    stage[stage1.fillna(False)] = 1
    stage[stage3.fillna(False)] = 3
    stage[stage4.fillna(False)] = 4
    stage[stage2.fillna(False)] = 2

    out["stage"] = stage
    logger.debug(
        "stage.compute: rows=%d symbols=%d stage_counts=%s",
        len(out), out.index.get_level_values("symbol").nunique(),
        stage.value_counts().to_dict(),
    )
    return out
