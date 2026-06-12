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
        """Recompute and materialize ``stale_ids`` (returns the upsert row counts).

        **Cross-sectional correctness (rs_rank):** ``rs_rank`` and the PCA regime are
        *cross-sectional* — a symbol's percentile is defined relative to the **whole
        universe**, not the stale subset handed to this call. Ranking over only the
        stale ids would make ``rs_rank`` a percentile-within-subset and silently shift
        stage thresholds on an incremental run (review finding F1-1). So the enrichment
        pipeline runs over the **full universe panel**, and only the stale-symbol rows
        are upserted. When the universe cannot be resolved (e.g. a test stub without a
        universe seam) the call falls back to ranking over ``stale_ids`` alone.
        """
        ids = list(stale_ids)
        if not ids:
            logger.debug("Writer.run: no stale ids — nothing to do")
            return {}

        # ① resolve the cross-sectional universe — superset of the stale ids so the
        #    rank/regime see the full panel even on an incremental run.
        universe = self._cross_section_universe(ids)

        # ② read raw (DataSource) — universe + benchmark in one call.
        panel = self.data.time_series(universe + [self.benchmark], fields=_FIELDS)
        bench = self.data.time_series([self.benchmark], fields=("close",))
        # the benchmark is not a classified symbol — drop it from the universe panel.
        panel = self._drop_symbol(panel, self.benchmark)

        # ③ kernel enrichment pipeline (spec §5.2) — no recompute, columns added.
        #    rank/regime are cross-sectional → run over the FULL universe panel.
        panel = self.kernel.indicators.compute(panel)
        panel = self.kernel.relative_strength.compute(panel, bench)
        panel = self.kernel.relative_strength.rank(panel, by="returns_6m")
        panel = self.kernel.stage.compute(panel)

        # ④ Writer-fed classifiers — per-symbol latest columns, merged onto panel.
        #    pca_regime is cross-sectional too → pass the full panel, classify over it.
        panel = self._apply_classifiers(panel, universe)

        # ⑤ narrow the enriched panel back to the stale ids — we only persist those
        #    rows, but their cross-sectional values were computed universe-wide.
        write_panel = self._restrict_to(panel, ids)

        # ⑥ materialize (history append + current upsert, one txn).
        counts = self.computed.upsert(write_panel)
        logger.debug(
            "Writer.run: stale=%d universe=%d counts=%s", len(ids), len(universe), counts
        )
        return counts

    # ------------------------------------------------------------------ #
    # cross-sectional universe resolution (rs_rank correctness, finding F1-1)
    # ------------------------------------------------------------------ #
    def _cross_section_universe(self, stale_ids) -> list:
        """The full universe to rank against — a superset of ``stale_ids``.

        Resolves the materialized universe from the DataSource (every symbol with a
        last bar). Falls back to the stale ids alone when no universe seam exists
        (test stubs), preserving the old single-subset behaviour in that case.
        """
        resolved = self._resolve_universe()
        if not resolved:
            return list(stale_ids)
        # union: stale ids must be present even if absent from the materialized list.
        universe = list(dict.fromkeys(list(resolved) + list(stale_ids)))
        return [s for s in universe if s != self.benchmark]

    def _resolve_universe(self) -> list:
        getter = self._last_bar_getter()
        if getter is not None:
            try:
                mapping = getter()
                if mapping:
                    return list(mapping.keys())
            except Exception:  # pragma: no cover - defensive
                logger.debug("Writer._resolve_universe: last_bar_date failed", exc_info=True)
        return []

    def _last_bar_getter(self):
        """The DataSource's per-symbol last-bar-date callable, on the provider OR its
        equity submodule (the provider doesn't re-export it — datasource/provider.py)."""
        getter = getattr(self.data, "last_bar_date", None)
        if callable(getter):
            return getter
        equity = getattr(self.data, "_equity", None)
        eq_getter = getattr(equity, "last_bar_date", None)
        return eq_getter if callable(eq_getter) else None

    @staticmethod
    def _restrict_to(panel: pd.DataFrame, ids) -> pd.DataFrame:
        if panel is None or len(panel) == 0:
            return panel
        keep = set(ids)
        syms = panel.index.get_level_values("symbol")
        mask = pd.Series(syms, index=panel.index).isin(keep).to_numpy()
        return panel[mask]

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
