"""DataSource provider — the RAW form-shaped facade (spec §4.4, §5.3).

The caller passes ids + params and **never a source**. A `(form, id)` registry
selects the submodule; the provider issues one batched call per submodule and
stitches the results into a single `symbol × date` multi-index `TimeSeries`.

Dependency injection (spec §8): the provider **receives** its registry (and
submodules through it) as constructor args, so tests pass fakes — there are no
module-global provider imports inside the logic.

Only `time_series` is implemented in this slice (Slice #1). `option_chain` and
`fundamentals` (spec §5.3) are later slices and intentionally absent here.
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
    # universe fetch — delegates to the single equity implementation
    # ------------------------------------------------------------------ #
    def fetch_universe(self, *args, **kwargs):
        """Delegate to the equity submodule's single `fetch_universe` (the one
        place `yf.screen` lives). Raises if no equity submodule was provided."""
        equity = self._equity or self._registry.resolve("time_series", "__equity_probe__")
        return equity.fetch_universe(*args, **kwargs)
