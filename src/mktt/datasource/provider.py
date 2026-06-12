"""DataSource provider — the RAW form-shaped facade (spec §4.4, §5.3).

The caller passes ids + params and **never a source**. A `(form, id)` registry
selects the submodule; the provider issues one batched call per submodule and
stitches the results into a single `symbol × date` multi-index `TimeSeries`.

Dependency injection (spec §8): the provider **receives** its registry (and
submodules through it) as constructor args, so tests pass fakes — there are no
module-global provider imports inside the logic.

`time_series` (Slice #1), `fundamentals` (Slice #4) and `option_chain` (Slice #10)
are implemented; each routes through the `(form, id)` registry to its submodule.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

import pandas as pd

from .registry import Registry

_DEFAULT_FIELDS = ("close", "volume")

logger = logging.getLogger("mktt.datasource.provider")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


def _normalize_ids(ids) -> list:
    if isinstance(ids, str):
        return [ids]
    return list(ids)


def _empty_timeseries(fields: Sequence[str]) -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({f: pd.Series(dtype="float64") for f in fields}, index=idx)


class DataSource:
    """RAW data provider. Sections call it directly (no unified facade — spec §5.3).

    Parameters
    ----------
    registry:
        The `(form, id)` registry resolving each id to a submodule. This is the
        DI seam — the registry holds the submodules; the provider holds the
        registry.
    _equity:
        Optional convenience handle to the equity submodule (e.g. for the
        deduped universe fetch). Not used by `time_series` routing — that goes
        through the registry. Accepted so callers/tests can reach
        `data.fetch_universe(...)` without re-resolving.
    """

    def __init__(self, registry: Registry, _equity=None) -> None:
        self._registry = registry
        self._equity = _equity

    # ------------------------------------------------------------------ #
    # time_series (spec §5.3)
    # ------------------------------------------------------------------ #
    def time_series(
        self,
        ids,
        start=None,
        end=None,
        fields: Sequence[str] = _DEFAULT_FIELDS,
    ) -> pd.DataFrame:
        """ids + params -> `symbol × date` TimeSeries (columns = fields).

        Routing is config: each id -> asset_class -> submodule (via the registry).
        Ids served by the same submodule are batched into one call. Missing ids
        are tolerated by the submodules (skipped); an all-missing request returns
        an empty, correctly-shaped frame.
        """
        ids = _normalize_ids(ids)
        fields = tuple(fields)
        if not ids:
            return _empty_timeseries(fields)

        frames = []
        for submodule, group in self._registry.group_by_submodule("time_series", ids):
            sub_ts = submodule.time_series(group, start=start, end=end, fields=fields)
            if sub_ts is not None and not sub_ts.empty:
                frames.append(sub_ts)

        if not frames:
            return _empty_timeseries(fields)

        panel = pd.concat(frames)
        # Stable ordering: symbol then date.
        panel = panel.sort_index(level=["symbol", "date"])
        return panel

    # ------------------------------------------------------------------ #
    # fundamentals (spec §5.3) — reads MKFund via the registered submodule
    # ------------------------------------------------------------------ #
    def fundamentals(self, ids, fields=None, estimates: bool = False):
        """ids + optional field projection -> `Fundamentals` (symbol × attributes).

        Routes every id through the `(fundamentals, *)` registry row to the MKFund
        submodule (asset class is irrelevant — one fundamentals table per symbol).
        `fields=None` returns all columns; `estimates=True` attaches FY1/FY2 curves.
        """
        ids = _normalize_ids(ids)
        if not ids:
            sub = self._registry._submodules.get(("fundamentals", "*"))
            if sub is None:
                import pandas as _pd
                df = _pd.DataFrame()
                df.index.name = "symbol"
                return df
            return sub.fundamentals([], fields=fields, estimates=estimates)
        # one submodule serves all fundamentals ids; resolve via the first id.
        submodule = self._registry.resolve("fundamentals", ids[0])
        return submodule.fundamentals(ids, fields=fields, estimates=estimates)

    # ------------------------------------------------------------------ #
    # quarterly (spec §5.3) — long quarterly actuals for growth derivation
    # ------------------------------------------------------------------ #
    def quarterly(self, ids, fields=None):
        """ids → long ``MKFund.quarterly`` frame (symbol × report_date).

        Routes through the ``(fundamentals, *)`` registry row to the MKFund
        submodule (one quarterly table per symbol). The Screener uses this to
        derive TTM / YoY EPS & Revenue growth from quarterly actuals.
        """
        ids = _normalize_ids(ids)
        if not ids:
            return self.fundamentals([]).iloc[0:0]
        submodule = self._registry.resolve("fundamentals", ids[0])
        return submodule.quarterly(ids, fields=fields)

    # ------------------------------------------------------------------ #
    # option_chain (spec §5.3) — routes through the (option_chain, *) row
    # ------------------------------------------------------------------ #
    def option_chain(self, symbol, n_exp=4, expirations=None, force_refresh=False):
        """symbol + params -> `OptionChain` (spec §3, §5.3).

        Routes through the `(option_chain, *)` registry row to the options
        submodule (asset-class blind — every symbol's chain comes from one source).
        The submodule owns fetch/normalize/cache/backoff and the stale-cache
        fallback; this provider method is the thin form-shaped seam sections call.
        """
        submodule = self._registry.resolve("option_chain", symbol)
        return submodule.option_chain(
            symbol, n_exp=n_exp, expirations=expirations, force_refresh=force_refresh
        )

    # ------------------------------------------------------------------ #
    # vectorized screener technicals — delegates to the equity submodule
    # ------------------------------------------------------------------ #
    def panel_technicals(self, ids, **kwargs):
        """Vectorized screener technicals straight off the wide parquet panels
        (the perf path that avoids the per-symbol ``time_series`` reassembly).

        Delegates to the equity submodule (the one owner of the wide panels).
        Benchmark ids (SPY) are not screener members and are skipped upstream.
        """
        equity = self._equity or self._registry.resolve("time_series", "__equity_probe__")
        return equity.panel_technicals(ids, **kwargs)

    # ------------------------------------------------------------------ #
    # universe fetch — delegates to the single equity implementation
    # ------------------------------------------------------------------ #
    def fetch_universe(self, *args, **kwargs):
        """Delegate to the equity submodule's single `fetch_universe` (the one
        place `yf.screen` lives). Raises if no equity submodule was provided."""
        equity = self._equity or self._registry.resolve("time_series", "__equity_probe__")
        return equity.fetch_universe(*args, **kwargs)
