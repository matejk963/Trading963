"""Writer — materialization-only orchestrator (spec §7, adr/0001).

The Writer (was ``update_classifications.py``) owns **neither** the compute (kernel),
**nor** the schedule (external), **nor** the consumption (providers) — it is pure
orchestration:

    def run(stale_ids):
        panel = data.time_series(stale_ids + benchmark)   # read raw (DataSource)
        panel = indicators.compute(panel)                 # kernel enrichment …
        panel = relative_strength.compute(panel, bench)
        panel = relative_strength.rank(panel)
        panel = stage.compute(panel)
        panel = <merge Writer-fed classifiers>            # regime / ma_screen / eps_accel
        computed.upsert(panel)                            # history + current, one txn

Dependency injection (spec §8): the Writer **receives** ``data`` (DataSource),
``computed`` (ComputedStore), ``kernel`` (the 3 primitives) and ``classifiers``
(the Writer-fed units) — tests pass stubs and assert the materialization happened
without any real compute/DB.

It holds **no compute logic of its own** beyond wiring: every formula lives in the
kernel or a classifier; every fetch lives in the providers; every write lives in
the store.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

import pandas as pd

logger = logging.getLogger("mktt.computed.writer")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

DEFAULT_BENCHMARK = "SPY"
# Raw fields the pipeline needs (close/volume for the kernel + high/low for PCA).
_FIELDS = ("close", "high", "low", "volume")


class _KernelFacade:
    """Bundle of the 3 kernel primitives, so the Writer takes one ``kernel`` arg.

    Accepts either the ``kernel`` package (which exposes ``indicators`` /
    ``relative_strength`` / ``stage``) or any object with those attributes.
    """

    def __init__(self, kernel):
        self.indicators = kernel.indicators
        self.relative_strength = kernel.relative_strength
        self.stage = kernel.stage


class Writer:
    """Orchestrates raw → kernel → classifiers → store (spec §7).

    Parameters
    ----------
    data:
        DataSource — provides ``time_series(ids, fields=…)`` (+ ``fundamentals``
        for the EPS classifier).
    computed:
        ComputedStore — provides ``upsert(panel)``.
    kernel:
        The kernel package / facade exposing ``indicators``,
        ``relative_strength``, ``stage`` (the enrichment pipeline, spec §5.2).
    classifiers:
        Iterable of Writer-fed classifier units (adr/0001). Each exposes
        ``COLUMN`` and ``classify(...)``; the Writer dispatches the inputs each
        needs. Defaults to :data:`classifiers.DEFAULT_CLASSIFIERS`.
    benchmark:
        Benchmark id for ``relative_strength.compute`` (default ``"SPY"``).
    """

    def __init__(self, data, computed, kernel, classifiers=None, benchmark: str = DEFAULT_BENCHMARK) -> None:
        self.data = data
        self.computed = computed
        self.kernel = _KernelFacade(kernel)
        if classifiers is None:
            from .classifiers import DEFAULT_CLASSIFIERS
            classifiers = DEFAULT_CLASSIFIERS
        self.classifiers = list(classifiers)
        self.benchmark = benchmark

    # ------------------------------------------------------------------ #
    # run — the recipe (spec §7)
    # ------------------------------------------------------------------ #
    def run(self, stale_ids: Sequence[str]) -> dict:
        """Recompute and materialize ``stale_ids`` (returns the upsert row counts)."""
        ids = list(stale_ids)
        if not ids:
            logger.debug("Writer.run: no stale ids — nothing to do")
            return {}

        # ① read raw (DataSource) — universe + benchmark in one call.
        panel = self.data.time_series(ids + [self.benchmark], fields=_FIELDS)
        bench = self.data.time_series([self.benchmark], fields=("close",))
        # the benchmark is not a classified symbol — drop it from the universe panel.
        panel = self._drop_symbol(panel, self.benchmark)

        # ② kernel enrichment pipeline (spec §5.2) — no recompute, columns added.
        panel = self.kernel.indicators.compute(panel)
        panel = self.kernel.relative_strength.compute(panel, bench)
        panel = self.kernel.relative_strength.rank(panel, by="returns_6m")
        panel = self.kernel.stage.compute(panel)

        # ③ Writer-fed classifiers — per-symbol latest columns, merged onto panel.
        panel = self._apply_classifiers(panel, ids)

        # ④ materialize (history append + current upsert, one txn).
        counts = self.computed.upsert(panel)
        logger.debug("Writer.run: ids=%d counts=%s", len(ids), counts)
        return counts

    # ------------------------------------------------------------------ #
    # classifier dispatch — orchestration only (no formulas here)
    # ------------------------------------------------------------------ #
    def _apply_classifiers(self, panel: pd.DataFrame, ids) -> pd.DataFrame:
        for unit in self.classifiers:
            col = getattr(unit, "COLUMN")
            series = self._run_classifier(unit, panel, ids)
            panel = self._merge_per_symbol(panel, col, series)
        return panel

    def _run_classifier(self, unit, panel, ids) -> pd.Series:
        """Call a classifier with the inputs it needs (orchestration wiring).

        - ``pca_regime`` needs the wide OHLCV panels + benchmark close.
        - ``eps_accel`` needs the Fundamentals form.
        - ``ma_screen`` (and any default) needs the kernel-enriched panel.
        """
        name = getattr(unit, "__name__", "").rsplit(".", 1)[-1]
        if name == "pca_regime":
            close, high, low, volume = self._wide_ohlcv(panel)
            bench_close = self._benchmark_close()
            return unit.classify(close, high, low, volume, bench_close)
        if name == "eps_accel":
            fundamentals = self._fundamentals(ids)
            return unit.classify(fundamentals)
        return unit.classify(panel)

    # ------------------------------------------------------------------ #
    # input adapters (shape conversions — not compute)
    # ------------------------------------------------------------------ #
    def _wide_ohlcv(self, panel: pd.DataFrame):
        """Long ``symbol × date`` raw panel → wide (dates × tickers) per field."""
        def wide(field):
            if field not in panel.columns:
                return pd.DataFrame()
            return panel[field].unstack(level="symbol")
        return wide("close"), wide("high"), wide("low"), wide("volume")

    def _benchmark_close(self) -> pd.Series:
        bench = self.data.time_series([self.benchmark], fields=("close",))
        if bench is None or bench.empty:
            return pd.Series(dtype="float64")
        s = bench["close"]
        if isinstance(s.index, pd.MultiIndex):
            s = s.droplevel("symbol")
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s

    def _fundamentals(self, ids):
        getter = getattr(self.data, "fundamentals", None)
        if getter is None:
            return pd.DataFrame()
        try:
            return getter(ids, estimates=True)
        except TypeError:
            return getter(ids)

    @staticmethod
    def _merge_per_symbol(panel: pd.DataFrame, col: str, series: pd.Series) -> pd.DataFrame:
        """Broadcast a per-symbol classifier value across that symbol's date rows.

        The classifier returns one value per symbol (the latest cross-section); the
        store later picks the latest row per symbol for ``current`` and writes the
        broadcast value for ``history``.
        """
        out = panel.copy()
        if series is None or len(series) == 0:
            out[col] = pd.Series(pd.NA, index=out.index)
            return out
        sym_level = out.index.get_level_values("symbol")
        mapped = pd.Series(sym_level, index=out.index).map(series.to_dict())
        out[col] = mapped.to_numpy()
        return out

    @staticmethod
    def _drop_symbol(panel: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if panel is None or len(panel) == 0:
            return panel
        syms = panel.index.get_level_values("symbol")
        return panel[syms != symbol]
