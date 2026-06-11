"""Equity DataSource submodule (spec §4.4).

Owns raw equity price access behind the `time_series` form interface, plus the
single canonical equity-universe fetch (`yf.screen`/`EquityQuery`). It serves both
the screening universe (wide `{field}.parquet` panels) and the benchmark
(`spy.parquet`) — the benchmark is just an equity id with a `benchmark` tag, read
from its own file (spec §3, FLAG-1).

Ported from `data_manager.py`:
- parquet loaders + mtime-keyed in-memory cache (lines 233-309),
- the incremental delta-fetch *concept* — `last_bar_date()` exposes the per-symbol
  last-bar-date that the price refresh regime (spec §4.4, §7) keys on,
- the `yf.screen`/`EquityQuery` pagination loop (the loop that was duplicated in
  `screener.py:89-101` and `data_manager.py:54-61`) — implemented here ONCE.

Debug logging is off by default (set `MKTT_LOG_LEVEL=DEBUG`).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd

# data/mktt lives at repo_root/data/mktt — this file is at
# repo_root/src/mktt/datasource/submodules/equity.py → up 4 to repo root.
DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "mktt"

# Wide price panels keyed by yfinance field name. close/high/low/volume are the
# canonical TimeSeries fields; "open" is not stored for the universe.
_FIELD_FILES = {
    "close": "close.parquet",
    "high": "high.parquet",
    "low": "low.parquet",
    "volume": "volume.parquet",
}

# spy.parquet is OHLCV in TitleCase columns (Close/High/Low/Open/Volume).
_BENCHMARK_FILE = "spy.parquet"
_BENCHMARK_IDS = {"SPY"}

_DEFAULT_FIELDS = ("close", "volume")

US_EXCHANGES = ["NMS", "NYQ", "ASE", "NCM", "NGM"]

logger = logging.getLogger("mktt.datasource.equity")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logging.basicConfig(level=logging.DEBUG)
    logger.setLevel(logging.DEBUG)


def _normalize_ids(ids) -> list:
    """Accept a single string id or an iterable of ids; return a list."""
    if isinstance(ids, str):
        return [ids]
    return list(ids)


def _empty_timeseries(fields: Sequence[str]) -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({f: pd.Series(dtype="float64") for f in fields}, index=idx)


class EquitySubmodule:
    """Reads local parquet, normalizes to the `symbol × date` TimeSeries form.

    Parameters
    ----------
    data_dir:
        Where the parquet files live (defaults to ``data/mktt``).
    screen / equity_query:
        Injected yfinance entry points for the universe fetch (DI — keeps the
        submodule unit-testable without network; lazily imports ``yfinance`` only
        when a universe fetch is actually requested and nothing was injected).
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        screen=None,
        equity_query=None,
    ) -> None:
        self._dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self._screen = screen
        self._equity_query = equity_query
        # mtime-keyed in-memory cache: {path_str: (mtime, df)}.
        self._mem_cache: dict = {}

    # ------------------------------------------------------------------ #
    # parquet loading (ported from data_manager._load_parquet_cached)
    # ------------------------------------------------------------------ #
    def _load_parquet_cached(self, path: Path) -> Optional[pd.DataFrame]:
        if not path.exists():
            logger.debug("parquet absent: %s", path)
            return None
        mtime = path.stat().st_mtime
        key = str(path)
        cached = self._mem_cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        df = pd.read_parquet(path)
        self._mem_cache[key] = (mtime, df)
        return df

    def _load_field_panel(self, field: str) -> Optional[pd.DataFrame]:
        fname = _FIELD_FILES.get(field)
        if fname is None:
            logger.debug("unknown field for universe panel: %s", field)
            return None
        return self._load_parquet_cached(self._dir / fname)

    def _load_benchmark(self) -> Optional[pd.DataFrame]:
        return self._load_parquet_cached(self._dir / _BENCHMARK_FILE)

    # ------------------------------------------------------------------ #
    # the TimeSeries form (spec §5.3)
    # ------------------------------------------------------------------ #
    def time_series(
        self,
        ids,
        start=None,
        end=None,
        fields: Sequence[str] = _DEFAULT_FIELDS,
    ) -> pd.DataFrame:
        """Return a `symbol × date` multi-index DataFrame for ``ids``.

        - Universe ids read from the wide ``{field}.parquet`` panels.
        - Benchmark ids (SPY) read from ``spy.parquet`` (TitleCase OHLCV).
        - Missing ids are tolerated (silently skipped).
        - ``start``/``end`` slice the date window (inclusive).
        """
        ids = _normalize_ids(ids)
        fields = tuple(fields)
        logger.debug("time_series ids=%d start=%s end=%s fields=%s",
                     len(ids), start, end, fields)

        universe_ids = [i for i in ids if i not in _BENCHMARK_IDS]
        benchmark_ids = [i for i in ids if i in _BENCHMARK_IDS]

        frames = []
        frames.extend(self._universe_frames(universe_ids, fields))
        frames.extend(self._benchmark_frames(benchmark_ids, fields))

        if not frames:
            return _empty_timeseries(fields)

        panel = pd.concat(frames)
        panel = self._slice_dates(panel, start, end)
        return panel

    def _universe_frames(self, ids, fields):
        if not ids:
            return []
        # Load each requested field panel once; assemble per-symbol frames.
        field_panels = {}
        for f in fields:
            field_panels[f] = self._load_field_panel(f)

        frames = []
        for sym in ids:
            per_field = {}
            present = False
            for f in fields:
                wide = field_panels.get(f)
                if wide is not None and sym in wide.columns:
                    series = wide[sym]
                    per_field[f] = series
                    if series.notna().any():
                        present = True
                else:
                    per_field[f] = pd.Series(dtype="float64")
            if not present:
                logger.debug("missing universe id tolerated: %s", sym)
                continue
            frames.append(self._make_symbol_frame(sym, per_field, fields))
        return frames

    def _benchmark_frames(self, ids, fields):
        if not ids:
            return []
        bench = self._load_benchmark()
        if bench is None:
            logger.debug("benchmark parquet absent — skipping %s", ids)
            return []
        # spy.parquet columns are TitleCase (Close/High/Low/Open/Volume).
        col_map = {c.lower(): c for c in bench.columns}
        frames = []
        for sym in ids:
            per_field = {}
            present = False
            for f in fields:
                src = col_map.get(f.lower())
                if src is not None:
                    series = bench[src]
                    per_field[f] = series
                    if series.notna().any():
                        present = True
                else:
                    per_field[f] = pd.Series(dtype="float64")
            if not present:
                continue
            frames.append(self._make_symbol_frame(sym, per_field, fields))
        return frames

    @staticmethod
    def _make_symbol_frame(sym, per_field, fields):
        sub = pd.DataFrame({f: per_field[f] for f in fields})
        sub = sub.dropna(how="all")
        idx = sub.index
        # Strip timezone so windows compare cleanly against naive Timestamps.
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

    # ------------------------------------------------------------------ #
    # incremental delta-fetch concept (spec §4.4, §7) — freshness signal
    # ------------------------------------------------------------------ #
    def last_bar_date(self, ids=None) -> dict:
        """Per-symbol last-bar-date — the freshness signal a price refresh keys on.

        Ported concept from ``data_manager.update_prices`` (which computed the
        global last date to delta-fetch). Here it is exposed per-symbol so the
        refresh regime can fetch only what each symbol is missing.
        """
        close = self._load_field_panel("close")
        out: dict = {}
        if close is None:
            return out
        cols = close.columns if ids is None else [i for i in _normalize_ids(ids) if i in close.columns]
        for sym in cols:
            last = close[sym].dropna().index.max()
            if pd.isna(last):
                continue
            if getattr(last, "tz", None) is not None:
                last = last.tz_localize(None)
            out[sym] = pd.Timestamp(last)
        return out

    # ------------------------------------------------------------------ #
    # universe fetch — the ONE place yf.screen lives (dedupe target)
    # ------------------------------------------------------------------ #
    def fetch_universe(
        self,
        exchanges: Optional[Iterable[str]] = None,
        min_avg_vol: float = 1000,
        extra_filters: Optional[list] = None,
    ) -> list:
        """Fetch all liquid quotes from ``exchanges`` via ``yf.screen``.

        This is the single canonical implementation of the screener pagination
        loop that previously lived in both ``screener.fetch_exchange_quotes`` and
        ``data_manager.fetch_liquid_universe``. Returns a list of quote dicts.

        ``screen``/``equity_query`` are injected for tests; otherwise yfinance is
        imported lazily here (the only place the dependency is needed).
        """
        screen, EquityQuery = self._screen_client()
        exchanges = list(exchanges) if exchanges is not None else list(US_EXCHANGES)

        filters = [
            EquityQuery("is-in", ["exchange"] + exchanges),
            EquityQuery("gt", ["avgdailyvol3m", min_avg_vol]),
        ]
        if extra_filters:
            filters.extend(extra_filters)
        q = EquityQuery("and", filters)

        all_quotes: list = []
        offset = 0
        while True:
            result = screen(q, sortField="intradaymarketcap", sortAsc=False,
                            size=250, offset=offset)
            quotes = result.get("quotes", [])
            if not quotes:
                break
            all_quotes.extend(quotes)
            offset += 250
        logger.debug("fetch_universe: %d quotes from %s", len(all_quotes), exchanges)
        return all_quotes

    def _screen_client(self):
        if self._screen is not None and self._equity_query is not None:
            return self._screen, self._equity_query
        import yfinance as yf  # lazy — only when actually fetching the universe
        screen = self._screen or yf.screen
        equity_query = self._equity_query or yf.EquityQuery
        return screen, equity_query
