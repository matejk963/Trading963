"""Kernel — RelativeStrength (pure, source-blind).

Two enrichment primitives over a ``TimeSeries`` (``symbol × date`` multi-index):

- :func:`compute` — **per-symbol** RS line vs a benchmark + Mansfield RS.
- :func:`rank`    — **cross-sectional** RS rank across the universe (needs >1
  symbol; null for a single symbol — see spec §5.2).

Ported behaviour-equivalent from ``stage_classifier.compute_all_derived_vectorized``:
    rs_line       = close / benchmark            (lines 79-81)
    mansfield_rs  = (rs_line / rs_line.rolling(252,min126).mean() - 1) * 100  (84-85)
    rs_rank       = close.pct_change(126).rank(pct=True) * 100   (cross-sectional, 100-102)

Pure: no provider / DB / Flask / network imports. ``device="cpu"`` only
(GPU deferred — adr/0001).
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Mansfield RS smoothing (legacy rs_sma): 252-bar mean, ≥126 bars required.
_RS_SMA_WINDOW = 252
_RS_SMA_MIN = 126
# Cross-sectional RS rank lookback (legacy returns_6m = pct_change(126)).
_RS_RANK_LOOKBACK = 126

COMPUTE_COLUMNS = ("rs_line", "mansfield_rs")
RANK_COLUMNS = ("rs_rank",)


def _benchmark_close(benchmark: pd.DataFrame) -> pd.Series:
    """Extract a single date-indexed close series from a benchmark TimeSeries.

    Accepts the benchmark as a ``symbol × date`` multi-index DataFrame (the
    canonical seam — one symbol) or a plain date-indexed frame/series.
    """
    if isinstance(benchmark, pd.Series):
        s = benchmark
    elif isinstance(benchmark, pd.DataFrame):
        if "close" not in benchmark.columns:
            raise ValueError(
                "relative_strength.compute: benchmark must have a 'close' column"
            )
        s = benchmark["close"]
    else:
        raise TypeError("relative_strength.compute: benchmark must be a DataFrame/Series")

    if isinstance(s.index, pd.MultiIndex):
        # Collapse the symbol level — benchmark is a single series over dates.
        s = s.droplevel([lvl for lvl in s.index.names if lvl != "date"])
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.index.name = "date"
    return s


def compute(ts: pd.DataFrame, benchmark, device: str = "cpu") -> pd.DataFrame:
    """Add per-symbol ``rs_line`` and ``mansfield_rs`` vs ``benchmark``.

    Args:
        ts: ``symbol × date`` panel with a ``close`` column.
        benchmark: a single-symbol benchmark ``TimeSeries`` (or date-indexed
            close series). Aligned to each date and forward-filled (legacy
            ``spy_close.reindex(...).ffill()``).
        device: ``"cpu"`` only (GPU deferred — adr/0001).
    """
    if device != "cpu":
        raise NotImplementedError(
            f"relative_strength.compute: device={device!r} not implemented "
            "(GPU deferred — adr/0001); use device='cpu'."
        )
    if "close" not in ts.columns:
        raise ValueError("relative_strength.compute: TimeSeries must have a 'close' column")

    bench = _benchmark_close(benchmark)
    out = ts.copy()

    if len(out) == 0:
        out["rs_line"] = pd.Series(index=out.index, dtype="float64")
        out["mansfield_rs"] = pd.Series(index=out.index, dtype="float64")
        return out

    # Align the benchmark to each row's date (ffill — legacy reindex+ffill).
    dates = out.index.get_level_values("date")
    bench_aligned = bench.reindex(bench.index.union(dates.unique())).ffill()
    bench_on_rows = bench_aligned.reindex(dates).to_numpy()

    out["rs_line"] = out["close"].to_numpy() / bench_on_rows

    # Mansfield RS — per symbol rolling mean of rs_line, then deviation %.
    rs_sma = out["rs_line"].groupby(level="symbol", sort=False).transform(
        lambda s: s.rolling(_RS_SMA_WINDOW, min_periods=_RS_SMA_MIN).mean()
    )
    out["mansfield_rs"] = (out["rs_line"] / rs_sma - 1) * 100

    logger.debug(
        "relative_strength.compute: rows=%d symbols=%d",
        len(out), out.index.get_level_values("symbol").nunique(),
    )
    return out


def rank(panel: pd.DataFrame, by: str = "mansfield_rs", device: str = "cpu") -> pd.DataFrame:
    """Add the **cross-sectional** ``rs_rank`` column (percentile, 0-100).

    Legacy parity: the rank is taken over each date's 126-bar trailing return
    (``close.pct_change(126)``), percentile-ranked across symbols × 100. The
    ``by`` argument selects the ranking signal (default mirrors the spec's
    ``by="mansfield_rs"``); ``by="returns_6m"`` reproduces the legacy basis
    used by the golden fixture.

    Cross-sectional → **not computable for a single symbol**: with one symbol
    per date ``rs_rank`` is null (spec §5.2 — Monitor reads it from the store).
    """
    if device != "cpu":
        raise NotImplementedError(
            f"relative_strength.rank: device={device!r} not implemented "
            "(GPU deferred — adr/0001); use device='cpu'."
        )

    out = panel.copy()
    if len(out) == 0:
        out["rs_rank"] = pd.Series(index=out.index, dtype="float64")
        return out

    n_symbols = out.index.get_level_values("symbol").nunique()

    if by == "returns_6m":
        # Legacy basis (golden fixture): trailing 126-bar return per symbol.
        signal = out["close"].groupby(level="symbol", sort=False).transform(
            lambda s: s.pct_change(_RS_RANK_LOOKBACK)
        )
    else:
        if by not in out.columns:
            raise ValueError(
                f"relative_strength.rank: ranking column {by!r} not present; "
                "run the producing primitive first."
            )
        signal = out[by]

    if n_symbols < 2:
        # Single symbol → no cross-section to rank against → null (spec §5.2).
        out["rs_rank"] = pd.Series(float("nan"), index=out.index, dtype="float64")
        logger.debug("relative_strength.rank: single symbol — rs_rank=NaN")
        return out

    # Percentile rank across symbols, per date (legacy rank(axis=1, pct=True)*100).
    out["rs_rank"] = signal.groupby(level="date", sort=False).transform(
        lambda s: s.rank(pct=True) * 100
    )
    logger.debug("relative_strength.rank: by=%s symbols=%d", by, n_symbols)
    return out
