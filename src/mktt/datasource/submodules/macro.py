"""Macro (FRED) DataSource submodule (spec §4.4, §10 — FLAG-5).

Relocates the macro-series sourcing the old `macro/liquidity_service.py` did inline
(`data.loader.load_cached_data` over `data/liquidity/us_liquidity_raw.csv`) behind
the `time_series` form. The Macro section now calls `data.time_series(fred_ids)`
instead of reaching into `src/analysis/liquidity_monitoring/data/loader` via a
`sys.path` injection + a faked `streamlit` module — killing that leak.

Each FRED code is one macro `TimeSeries` symbol; the raw level lands in the `value`
field (macro series are single-valued, not OHLCV). The CSV reader is INJECTED (DI
seam, spec §8) so the submodule is unit-testable without touching disk; a default
reader loads the cached CSV lazily.

Asset class is metadata, not structure (spec §3): a FRED macro series is a
`TimeSeries` like any equity, differing only by the `macro` tag that routes it here.

Debug logging is off by default (`MKTT_LOG_LEVEL=DEBUG`).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

_DEFAULT_FIELDS = ("value",)

logger = logging.getLogger("mktt.datasource.macro")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


def _normalize_ids(ids) -> list:
    if isinstance(ids, str):
        return [ids]
    return list(ids)


def _empty_timeseries(fields: Sequence[str]) -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({f: pd.Series(dtype="float64") for f in fields}, index=idx)


def _default_cache_path() -> Path:
    # repo_root/data/liquidity/us_liquidity_raw.csv (mktt is at src/mktt).
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "data" / "liquidity" / "us_liquidity_raw.csv"


class MacroSubmodule:
    """`(time_series, macro)` — FRED macro series from the cached raw CSV.

    Parameters
    ----------
    reader:
        Injected zero-arg callable returning a `date × FRED-code` wide DataFrame
        (DatetimeIndex). The DI seam — tests pass a fake returning a small fixture.
        When ``None`` the cached CSV is read lazily on first fetch.
    cache_path:
        Override for the default CSV path (used only by the default reader).
    """

    def __init__(self, reader=None, cache_path: Optional[Path] = None) -> None:
        self._reader = reader
        self._cache_path = cache_path

    def _load(self) -> Optional[pd.DataFrame]:
        if self._reader is not None:
            return self._reader()
        path = self._cache_path or _default_cache_path()
        if not Path(path).exists():
            logger.warning("macro cache not found: %s", path)
            return None
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df

    def time_series(
        self,
        ids,
        start=None,
        end=None,
        fields: Sequence[str] = _DEFAULT_FIELDS,
    ) -> pd.DataFrame:
        """FRED ids + params -> `symbol × date` TimeSeries (symbol == FRED code).

        The raw level for each code lands in the requested value field (the first
        field, default ``"value"``). Codes absent from the cache are tolerated
        (skipped). ``start``/``end`` slice the date window (inclusive).
        """
        ids = _normalize_ids(ids)
        fields = tuple(fields)
        if not ids:
            return _empty_timeseries(fields)

        raw = self._load()
        if raw is None or raw.empty:
            return _empty_timeseries(fields)

        value_field = fields[0]
        idx = pd.DatetimeIndex(raw.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)

        frames = []
        for code in ids:
            if code not in raw.columns:
                logger.debug("missing macro id tolerated: %s", code)
                continue
            series = raw[code]
            sub = pd.DataFrame(index=idx)
            for f in fields:
                sub[f] = series.values if f == value_field else float("nan")
            sub = sub.dropna(how="all")
            if sub.empty:
                continue
            sub.index = pd.DatetimeIndex(sub.index, name="date")
            sub = pd.concat({code: sub}, names=["symbol"])
            frames.append(sub)

        if not frames:
            return _empty_timeseries(fields)

        panel = pd.concat(frames)
        panel = self._slice_dates(panel, start, end)
        return panel.sort_index(level=["symbol", "date"])

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
