"""ETF / futures DataSource submodules (spec §4.4, §10 — FLAG-5).

Relocates the `streamlit_app` ETF/futures price fetchers (`fetch_etf_data` /
`fetch_futures_data`, streamlit_app.py:109-152) behind the `time_series` form. The
RRG section now calls `data.time_series(etf_ids)` instead of importing the streamlit
fetchers — killing the `sys.path` injection + faked `streamlit` module that the old
`macro/rrg_service.py:13-42` used.

Two submodules, one per asset class:
    EtfSubmodule       -> `(time_series, etf)`       — sector / index ETFs + benchmarks
    FuturesSubmodule   -> `(time_series, futures)`   — continuous futures contracts

Both fetch adjusted-close (and any requested OHLCV field) from yfinance and
normalize to the canonical `symbol × date` multi-index TimeSeries (spec §3). The
`yf.download` entry point is INJECTED (DI seam, spec §8) so the submodules are
unit-testable without the network; yfinance is imported lazily only when nothing
was injected and a live fetch is actually requested.

Debug logging is off by default (`MKTT_LOG_LEVEL=DEBUG`).
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

import pandas as pd

_DEFAULT_FIELDS = ("close", "volume")
_DEFAULT_PERIOD = "2y"

# yfinance OHLCV field-name (TitleCase) for each canonical lowercase field.
_YF_FIELD = {"close": "Close", "open": "Open", "high": "High", "low": "Low", "volume": "Volume"}

logger = logging.getLogger("mktt.datasource.rrg_yf")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


def _normalize_ids(ids) -> list:
    if isinstance(ids, str):
        return [ids]
    return list(ids)


def _empty_timeseries(fields: Sequence[str]) -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({f: pd.Series(dtype="float64") for f in fields}, index=idx)


def _field_frame(raw: pd.DataFrame, ids, yf_field: str) -> Optional[pd.DataFrame]:
    """Extract a `date × ticker` frame for one OHLCV field from a yf.download result.

    `yf.download(tickers)` returns either a column MultiIndex `(field, ticker)`
    (multiple tickers) or a flat OHLCV frame (single ticker). Ported from the
    column-untangling in streamlit_app.fetch_etf_data (lines 115-128).
    """
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0)
        if yf_field in lvl0:
            df = raw[yf_field].copy()
        else:
            return None
    else:
        # single-ticker flat OHLCV — build a one-column frame keyed by the id.
        if yf_field not in raw.columns:
            return None
        df = raw[[yf_field]].copy()
        df.columns = [ids[0]] if ids else df.columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    return df


class _YfTimeSeriesSubmodule:
    """Shared yfinance → `symbol × date` TimeSeries normalizer.

    Parameters
    ----------
    download:
        Injected `yf.download`-shaped callable (DI seam). When ``None`` yfinance is
        imported lazily on first live fetch.
    period:
        Default lookback period passed to ``download`` (yfinance period string).
    """

    def __init__(self, download=None, period: str = _DEFAULT_PERIOD) -> None:
        self._download = download
        self._period = period

    def _client(self):
        if self._download is not None:
            return self._download
        import yfinance as yf  # lazy — only when actually fetching
        return yf.download

    def time_series(
        self,
        ids,
        start=None,
        end=None,
        fields: Sequence[str] = _DEFAULT_FIELDS,
    ) -> pd.DataFrame:
        """ids + params -> `symbol × date` TimeSeries (columns = fields).

        Fetches via the injected ``download`` once (batched over all ids), then
        slices each requested field into per-symbol frames. Missing ids are
        tolerated (skipped). ``start``/``end`` slice the date window (inclusive).
        """
        ids = _normalize_ids(ids)
        fields = tuple(fields)
        if not ids:
            return _empty_timeseries(fields)

        download = self._client()
        logger.debug("rrg_yf.time_series ids=%d fields=%s period=%s", len(ids), fields, self._period)
        raw = download(ids, period=self._period, progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return _empty_timeseries(fields)

        # field -> date×ticker wide frame.
        field_frames = {}
        for f in fields:
            yf_f = _YF_FIELD.get(f)
            if yf_f is None:
                continue
            field_frames[f] = _field_frame(raw, ids, yf_f)

        frames = []
        for sym in ids:
            per_field = {}
            present = False
            for f in fields:
                wide = field_frames.get(f)
                if wide is not None and sym in wide.columns:
                    series = wide[sym]
                    per_field[f] = series
                    if series.notna().any():
                        present = True
                else:
                    per_field[f] = pd.Series(dtype="float64")
            if not present:
                logger.debug("missing id tolerated: %s", sym)
                continue
            frames.append(self._make_symbol_frame(sym, per_field, fields))

        if not frames:
            return _empty_timeseries(fields)

        panel = pd.concat(frames)
        panel = self._slice_dates(panel, start, end)
        return panel.sort_index(level=["symbol", "date"])

    @staticmethod
    def _make_symbol_frame(sym, per_field, fields):
        sub = pd.DataFrame({f: per_field[f] for f in fields})
        sub = sub.dropna(how="all")
        idx = sub.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        sub.index = pd.DatetimeIndex(idx, name="date")
        sub = pd.concat({sym: sub}, names=["symbol"])
        return sub

    @staticmethod
    def _slice_dates(panel: pd.DataFrame, start, end) -> pd.DataFrame:
        if start is None and end is None:
            return panel
        dates = panel.index.get_level_values("date")
        mask = pd.Series(True, index=panel.index)
        if start is not None:
            mask &= dates >= pd.Timestamp(start)
        if end is not None:
            mask &= dates <= pd.Timestamp(end)
        return panel[mask.to_numpy()]


class EtfSubmodule(_YfTimeSeriesSubmodule):
    """`(time_series, etf)` — sector/index ETFs + their benchmarks (RSP/URTH/^STOXX)."""


class FuturesSubmodule(_YfTimeSeriesSubmodule):
    """`(time_series, futures)` — continuous futures contracts (ZB=F, CL=F, …)."""
