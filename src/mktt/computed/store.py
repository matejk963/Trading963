"""ComputedStore — Postgres-backed derived store (spec §4.5, §5.3, §6).

A current/history split over ``MKCompStore`` (Option B, spec §6) — keeps the
Screener's read **fixed-size** regardless of history growth:

    classification_current   PK symbol         -> Screener cross-section
    classification_history   PK (symbol, date) -> Monitor stage/RS evolution

The Writer is the **only** writer (adr/0001); this store exposes the reads sections
use plus the ``upsert`` the Writer calls.

API (spec §5.3):
    cross_section(filters=None) -> CrossSection   # DISTINCT ON (symbol) latest current
    history(symbol, start, end) -> TimeSeries      # classification_history
    ensure_fresh(ids)           -> None            # diff last-bar-date, Writer for stale
    upsert(panel)               -> dict            # history append + current upsert, 1 txn

Design (spec §8): **dependency injection** — the store takes a ``conn_factory``
(zero-arg callable -> fresh psycopg2 connection) and a ``schema``; tests inject a
factory pointed at a disposable schema. No module globals, no implicit connection.

Reads **auto-ensure-fresh** (spec §5.3): ``cross_section`` / ``history`` call
``ensure_fresh`` first when a Writer hook is wired, so a caller always gets fresh
data; the cold-miss recompute is the documented exception.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger("mktt.computed.store")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

DEFAULT_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"
DEFAULT_SCHEMA = "MKCompStore"

ConnFactory = Callable[[], "object"]

# Derived columns carried by both tables (spec §6). Order = table column order.
VALUE_COLUMNS = (
    "stage", "rs_rank", "mansfield_rs",
    "ma_50", "ma_150", "ma_200", "ma_150_slope",
    "regime", "ma_screen", "eps_accel",
)
# Integer-typed derived columns (the rest are double precision).
_INT_COLUMNS = {"stage", "regime", "ma_screen"}

CURRENT_COLS = ("symbol", "date") + VALUE_COLUMNS
HISTORY_COLS = ("symbol", "date") + VALUE_COLUMNS


def build_conn_factory(dsn: Optional[str] = None) -> ConnFactory:
    """Zero-arg psycopg2 connection factory from a DSN (explicit → ``MKTT_PG_DSN``
    → :data:`DEFAULT_DSN`). Each call opens a fresh connection."""
    resolved = dsn or os.environ.get("MKTT_PG_DSN") or DEFAULT_DSN

    def _factory():
        import psycopg2
        return psycopg2.connect(resolved)

    return _factory


def ddl(schema: str) -> str:
    """DDL for the two ``MKCompStore`` tables (spec §6) — used by integration tests
    to build a disposable schema and for first-run creation against the real schema."""
    def _coltype(c: str) -> str:
        return "integer" if c in _INT_COLUMNS else "double precision"

    value_cols = ",\n    ".join(f"{c} {_coltype(c)}" for c in VALUE_COLUMNS)
    return f"""
CREATE TABLE "{schema}".classification_current (
    symbol text PRIMARY KEY,
    date date,
    {value_cols},
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "{schema}".classification_history (
    symbol text NOT NULL,
    date date NOT NULL,
    {value_cols},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS classification_history_symbol_idx
    ON "{schema}".classification_history (symbol);
"""


class ComputedStore:
    """Derived current/history store backed by ``<schema>.classification_*``.

    Parameters
    ----------
    conn_factory:
        Zero-arg callable returning a fresh DB connection (DI seam). Defaults to
        one built from ``MKTT_PG_DSN`` / :data:`DEFAULT_DSN`.
    schema:
        Schema holding the tables (default ``"MKCompStore"``; tests pass a
        disposable schema).
    refresher:
        Optional callable ``refresher(stale_ids) -> None`` invoked by
        :meth:`ensure_fresh` to recompute stale symbols (the Writer's ``run``).
        Reads auto-ensure-fresh through it; if unset, freshness is a no-op
        (reads return whatever is materialized).
    """

    def __init__(
        self,
        conn_factory: Optional[ConnFactory] = None,
        schema: str = DEFAULT_SCHEMA,
        refresher: Optional[Callable[[Sequence[str]], None]] = None,
        last_bar_provider: Optional[Callable[[Sequence[str]], Dict]] = None,
    ) -> None:
        self._conn_factory = conn_factory or build_conn_factory()
        self.schema = schema
        self._refresher = refresher
        # Optional freshness seam (finding F1-5): a callable ``f(ids)->{sym: last_bar}``
        # (the DataSource's ``last_bar_date``). When wired, ``ensure_fresh`` flags a
        # symbol stale not only when it has NO history but when its stored MAX(date)
        # lags the source last bar — so a *stale* (not just empty) symbol refreshes.
        self._last_bar_provider = last_bar_provider
        self._current = f'"{schema}".classification_current'
        self._history = f'"{schema}".classification_history'
        # cross_section in-process cache (finding F1-3) — the cross-section is
        # one-row-per-symbol and changes ONLY on a Writer upsert, yet the Screener
        # re-runs the full-table DISTINCT ON every request. Cache the built frame,
        # keyed by the filter map, with a short TTL; ``upsert`` invalidates it so a
        # fresh write is never served stale.
        self._xs_cache: Dict = {}
        self._xs_cache_ttl = float(os.environ.get("MKTT_CROSS_SECTION_TTL", "30"))
        # Monotonic in-proc freshness token for the cross-section (Slice 1). The
        # cross-section changes ONLY on a Writer ``upsert``; this counter bumps there
        # so downstream caches (the Screener pipeline cache) key on it and a fresh
        # write is never served stale. Starts at 1 so a token is always truthy.
        self._xs_version = 1

    def set_refresher(self, refresher: Callable[[Sequence[str]], None]) -> None:
        """Wire the Writer's ``run`` as the auto-ensure-fresh hook (spec §5.3)."""
        self._refresher = refresher

    def set_last_bar_provider(self, provider: Callable[[Sequence[str]], Dict]) -> None:
        """Wire the DataSource's ``last_bar_date`` as the staleness signal (finding F1-5)."""
        self._last_bar_provider = provider

    # ------------------------------------------------------------------ #
    # connection helper
    # ------------------------------------------------------------------ #
    def _query(self, sql: str, params=None) -> List[tuple]:
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            conn.commit()
            return rows, cols
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # cross_section (spec §5.3) — Screener, fixed-size
    # ------------------------------------------------------------------ #
    def cross_section(self, filters: Optional[Dict] = None, auto_fresh: bool = True) -> pd.DataFrame:
        """Latest classification row per symbol as a ``CrossSection`` (symbol-indexed).

        Uses ``DISTINCT ON (symbol) ... ORDER BY symbol, date DESC`` so the read is
        **fixed-size** — one row per symbol — regardless of history growth. (The
        ``classification_current`` table is already one-row-per-symbol; DISTINCT ON
        makes the contract explicit and lets ``filters`` narrow the universe.)

        ``filters`` is an optional ``{column: value}`` equality map over the value
        columns (the ✏️ filter map wiring happens in the Screener slice — here we
        support simple equality so the store is filterable).
        """
        if auto_fresh:
            self._maybe_refresh(None)

        key = self._xs_cache_key(filters)
        cached = self._xs_cache_get(key)
        if cached is not None:
            logger.debug("cross_section: cache hit (filters=%s)", filters)
            return cached.copy()

        where, params = self._build_filter(filters)
        cols = ", ".join(CURRENT_COLS)
        sql = (
            f"SELECT DISTINCT ON (symbol) {cols} "
            f"FROM {self._current} {where} "
            f"ORDER BY symbol, date DESC NULLS LAST"
        )
        rows, colnames = self._query(sql, params)
        df = pd.DataFrame(rows, columns=colnames)
        if not df.empty:
            df = df.set_index("symbol")
        else:
            df = df.reindex(columns=[c for c in colnames if c != "symbol"])
            df.index.name = "symbol"
        logger.debug("cross_section: %d symbols (filters=%s)", len(df), filters)
        self._xs_cache_put(key, df)
        return df.copy()

    # ---- cross_section cache (finding F1-3) --------------------------- #
    @staticmethod
    def _xs_cache_key(filters):
        if not filters:
            return ()
        return tuple(sorted((str(k), repr(v)) for k, v in filters.items()))

    def _xs_cache_get(self, key):
        import time
        entry = self._xs_cache.get(key)
        if entry is None:
            return None
        ts, df = entry
        if (time.monotonic() - ts) > self._xs_cache_ttl:
            self._xs_cache.pop(key, None)
            return None
        return df

    def _xs_cache_put(self, key, df) -> None:
        import time
        self._xs_cache[key] = (time.monotonic(), df.copy())

    def invalidate_cross_section_cache(self) -> None:
        """Drop the cross_section cache (a Writer upsert mutates the cross-section)."""
        self._xs_cache.clear()

    def cross_section_version(self) -> int:
        """Monotonic freshness token for the cross-section (Slice 1).

        Bumps on every :meth:`upsert` (the only mutation of the cross-section).
        Downstream result caches key on it so a fresh write invalidates them
        instantly — a cached pipeline/render is never staler than the data.
        """
        return self._xs_version

    def _build_filter(self, filters):
        if not filters:
            return "", []
        clauses, params = [], []
        for col, val in filters.items():
            if col not in VALUE_COLUMNS:
                raise ValueError(f"cross_section: unknown filter column {col!r}")
            clauses.append(f"{col} = %s")
            params.append(val)
        return "WHERE " + " AND ".join(clauses), params

    # ------------------------------------------------------------------ #
    # history (spec §5.3) — Monitor
    # ------------------------------------------------------------------ #
    def history(self, symbol: str, start=None, end=None, auto_fresh: bool = True) -> pd.DataFrame:
        """Classification history for one symbol as a ``symbol × date`` TimeSeries."""
        if auto_fresh:
            self._maybe_refresh([symbol])

        cols = ", ".join(HISTORY_COLS)
        clauses = ["symbol = %s"]
        params = [symbol]
        if start is not None:
            clauses.append("date >= %s")
            params.append(pd.Timestamp(start).date())
        if end is not None:
            clauses.append("date <= %s")
            params.append(pd.Timestamp(end).date())
        sql = (
            f"SELECT {cols} FROM {self._history} "
            f"WHERE {' AND '.join(clauses)} ORDER BY date"
        )
        rows, colnames = self._query(sql, params)
        df = pd.DataFrame(rows, columns=colnames)
        if df.empty:
            idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
            return df.drop(columns=["symbol", "date"]).set_axis(idx) if False else \
                pd.DataFrame(columns=[c for c in colnames if c not in ("symbol", "date")], index=idx)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index(["symbol", "date"]).sort_index()
        logger.debug("history: symbol=%s rows=%d", symbol, len(df))
        return df

    # ------------------------------------------------------------------ #
    # rs_rank_changes (Screener RS momentum) — original parity
    # ------------------------------------------------------------------ #
    def rs_rank_changes(self, asof=None) -> pd.DataFrame:
        """Per-symbol RS-rank momentum (``rs_chg1w/rs_chg1m/rs_chg3m``) from history.

        Reproduces the original screener's RS-momentum columns (app.py @9631169):
        the stored ``rs_rank`` is the 6-month-return cross-sectional percentile
        (Writer ``by="returns_6m"``), and ::

            RS_Chg{1W,1M,3M} = rs_rank[asof] − rs_rank[asof − {5,21,63} trading days]

        Lags are counted in **distinct ``date`` rows** of ``classification_history``
        (one per trading day), so they are market-calendar-correct without a holiday
        table. The anchor + three lagged dates are diffed **in SQL** so only one row
        per symbol crosses the wire.

        Returns a **symbol-indexed** frame with float columns
        ``rs_chg1w/rs_chg1m/rs_chg3m``; a window is ``NaN`` where history is too short
        to reach that lag (or the symbol lacks an ``rs_rank`` at either endpoint).

        ``asof`` (optional) anchors the "current" date to the latest trading day
        ``<= asof``; the default (``None``) uses the latest available date — matching
        :meth:`cross_section`, so the change base aligns with the displayed ``rs_rank``.
        """
        # row_number() is 1-based DESC, so the anchor is rn=1 and a lag of N is rn=N+1.
        windows = (("rs_chg1w", 5), ("rs_chg1m", 21), ("rs_chg3m", 63))
        rns = {col: lag + 1 for col, lag in windows}
        in_list = ",".join(str(r) for r in sorted(set(rns.values())))  # 6,22,64
        deltas = ",\n            ".join(
            f"max(rs_rank) FILTER (WHERE rn=1) - "
            f"max(rs_rank) FILTER (WHERE rn={rns[col]}) AS {col}"
            for col, _ in windows
        )
        asof_where, params = "", []
        if asof is not None:
            asof_where = "WHERE date <= %s"
            params.append(pd.Timestamp(asof).date())
        sql = f"""
        WITH d AS (
            SELECT date, row_number() OVER (ORDER BY date DESC) AS rn
            FROM (SELECT DISTINCT date FROM {self._history} {asof_where}) x
        ),
        picks AS (SELECT date, rn FROM d WHERE rn IN (1,{in_list})),
        h AS (
            SELECT ch.symbol, p.rn, ch.rs_rank
            FROM {self._history} ch JOIN picks p ON ch.date = p.date
        )
        SELECT symbol,
            {deltas}
        FROM h GROUP BY symbol
        """
        rows, cols = self._query(sql, params)
        df = pd.DataFrame(rows, columns=cols)
        out_cols = [c for c, _ in windows]
        if df.empty:
            return pd.DataFrame(columns=out_cols,
                                index=pd.Index([], name="symbol", dtype=object))
        df = df.set_index("symbol")
        for c in out_cols:
            # psycopg2 returns NUMERIC as Decimal; coerce to float (NaN where null).
            df[c] = pd.to_numeric(df[c], errors="coerce")
        logger.debug("rs_rank_changes: %d symbols (asof=%s)", len(df), asof)
        return df

    # ------------------------------------------------------------------ #
    # stage_transitions (Screener trans12 preset) — original parity
    # ------------------------------------------------------------------ #
    def stage_transitions(self, asof=None, lookback: int = 5) -> pd.Series:
        """Per-symbol stage transition label (``"prev->current"``) from history.

        Reproduces the original screener's ``Transition`` column
        (stage_classifier.py:243): ``current`` = the latest ``stage``; ``prev`` = the
        **mode** of the prior ``lookback`` bars' stage; the label is set only when
        ``prev != current`` and neither is 0 (unclassified). The ``trans12`` preset
        filters on ``"1->2"``.

        Reads ``stage`` for the latest ``lookback+1`` trading dates per symbol (one
        round-trip) and computes the mode in pandas. ``asof`` anchors "current" to the
        latest trading day ``<= asof`` (default: latest). Returns a **symbol-indexed**
        ``Series[str]``; symbols with too little history or no transition are omitted.
        """
        n = lookback + 1  # current bar (rn=1) + the `lookback` prior bars (rn=2..n)
        asof_where, params = "", []
        if asof is not None:
            asof_where = "WHERE date <= %s"
            params.append(pd.Timestamp(asof).date())
        sql = f"""
        WITH d AS (
            SELECT date, row_number() OVER (ORDER BY date DESC) AS rn
            FROM (SELECT DISTINCT date FROM {self._history} {asof_where}) x
        ),
        picks AS (SELECT date, rn FROM d WHERE rn <= %s)
        SELECT ch.symbol, p.rn, ch.stage
        FROM {self._history} ch JOIN picks p ON ch.date = p.date
        """
        rows, cols = self._query(sql, params + [n])
        df = pd.DataFrame(rows, columns=cols)
        if df.empty:
            return pd.Series(dtype=object, name="transition")
        df["stage"] = pd.to_numeric(df["stage"], errors="coerce")
        piv = df.pivot_table(index="symbol", columns="rn", values="stage",
                             aggfunc="first")
        prior_rns = [r for r in range(2, n + 1) if r in piv.columns]
        out: Dict[str, str] = {}
        for sym, srow in piv.iterrows():
            cur = srow.get(1)
            if pd.isna(cur) or not prior_rns:
                continue
            prior = srow[prior_rns].dropna()
            if prior.empty:
                continue
            mode = prior.mode()
            if mode.empty:
                continue
            cur, prev = int(cur), int(mode.iloc[0])
            if prev != cur and cur != 0 and prev != 0:
                out[sym] = f"{prev}->{cur}"
        logger.debug("stage_transitions: %d transitions (asof=%s)", len(out), asof)
        return pd.Series(out, name="transition", dtype=object)

    # ------------------------------------------------------------------ #
    # ensure_fresh (spec §5.3) — diff last-bar-date, recompute the stale
    # ------------------------------------------------------------------ #
    def last_bar_dates(self, ids=None) -> Dict[str, pd.Timestamp]:
        """Per-symbol ``MAX(date)`` from history — the freshness signal (spec §7)."""
        sql = f"SELECT symbol, MAX(date) FROM {self._history} GROUP BY symbol"
        params = None
        if ids is not None:
            ids = list(ids)
            if not ids:
                return {}
            sql = (
                f"SELECT symbol, MAX(date) FROM {self._history} "
                f"WHERE symbol = ANY(%s) GROUP BY symbol"
            )
            params = (ids,)
        rows, _ = self._query(sql, params)
        return {s: pd.Timestamp(d) for (s, d) in rows if d is not None}

    def ensure_fresh(self, ids) -> None:
        """Recompute any of ``ids`` that are missing OR stale (spec §7, finding F1-5).

        Freshness is self-described via ``MAX(date)``:

        - An id with **no** materialized history is stale (the cold-miss this layer
          must trigger — spec §5.3).
        - When a ``last_bar_provider`` is wired (the DataSource's ``last_bar_date``),
          an id whose stored ``MAX(date)`` **lags** the source last bar is *also*
          stale — so a symbol that has prior data but a newer price bar is refreshed,
          not treated as fresh forever (the original bug: ``ensure_fresh`` only caught
          zero-history symbols).

        Without a ``last_bar_provider`` the staleness diff is out of scope here and
        relies on external scheduling (the Writer's run); only missing ids refresh.
        """
        if self._refresher is None:
            return
        ids = list(ids)
        if not ids:
            return
        stored = self.last_bar_dates(ids)            # {sym: stored MAX(date)}
        source = self._source_last_bars(ids)         # {sym: source last bar} or {}
        stale = []
        for i in ids:
            have = stored.get(i)
            if have is None:
                stale.append(i)                      # no history → cold miss
                continue
            src = source.get(i)
            if src is not None and pd.Timestamp(src) > pd.Timestamp(have):
                stale.append(i)                      # stored lags source → stale
        if stale:
            logger.debug("ensure_fresh: %d stale → refresher", len(stale))
            self._refresher(stale)

    def _source_last_bars(self, ids) -> Dict:
        if self._last_bar_provider is None:
            return {}
        try:
            mapping = self._last_bar_provider(ids)
            return mapping or {}
        except Exception:  # pragma: no cover - defensive
            logger.debug("ensure_fresh: last_bar_provider failed", exc_info=True)
            return {}

    def _maybe_refresh(self, ids) -> None:
        if self._refresher is None:
            return
        if ids is not None:
            self.ensure_fresh(ids)

    # ------------------------------------------------------------------ #
    # upsert (spec §7) — history append + current upsert in ONE txn
    # ------------------------------------------------------------------ #
    def upsert(self, panel: pd.DataFrame, incremental: bool = True) -> Dict[str, int]:
        """Materialize a kernel+classifier ``symbol × date`` panel.

        Writes to ``classification_history`` and upserts the **latest** row per
        symbol to ``classification_current`` — both in ONE transaction (spec §7).
        Returns row counts written.

        ``classification_history`` is **append-only by date** (PK ``symbol,date``).
        When ``incremental`` (default), only rows **strictly newer** than each
        symbol's stored ``MAX(date)`` are written, so a re-run does not rewrite all
        ~6.5M rows via ``ON CONFLICT`` (review finding F1-2). ``classification_current``
        is *always* upserted (latest row per symbol) so the Screener cross-section
        stays current even when no new history bar exists. Pass ``incremental=False``
        to force a full history upsert (e.g. a backfill / repair).

        The panel index is ``symbol × date``; only :data:`VALUE_COLUMNS` present in
        the panel are written (absent ones stored NULL).
        """
        current_rows = self._latest_rows(panel)

        if incremental:
            symbols = self._panel_symbols(panel)
            since = self.last_bar_dates(symbols) if symbols else {}
            history_rows = self._panel_rows(panel, newer_than=since)
        else:
            history_rows = self._panel_rows(panel)

        conn = self._conn_factory()
        counts: Dict[str, int] = {}
        try:
            counts["classification_history"] = self._upsert(
                conn, self._history, HISTORY_COLS, ["symbol", "date"], history_rows)
            counts["classification_current"] = self._upsert(
                conn, self._current, CURRENT_COLS, ["symbol"], current_rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        # the cross-section changed — drop the read cache so it is not served stale
        # and bump the freshness token so downstream result caches invalidate.
        self.invalidate_cross_section_cache()
        self._xs_version += 1
        logger.debug("upsert: %s (incremental=%s, version=%d)",
                     counts, incremental, self._xs_version)
        return counts

    # ---- row shaping -------------------------------------------------- #
    @staticmethod
    def _panel_symbols(panel: pd.DataFrame) -> List[str]:
        if panel is None or len(panel) == 0:
            return []
        return list(dict.fromkeys(panel.index.get_level_values("symbol")))

    def _panel_rows(self, panel: pd.DataFrame, newer_than: Optional[Dict] = None) -> List[Dict]:
        """Shape panel rows for history via ``itertuples`` (fast — finding F1-2).

        When ``newer_than`` is given (``{symbol: stored_max_date}``), only rows with
        ``date > stored_max_date`` are emitted — history is append-only by date, so
        re-running over already-stored bars is skipped instead of re-upserted.
        """
        if panel is None or len(panel) == 0:
            return []
        cols = [c for c in VALUE_COLUMNS if c in panel.columns]
        col_pos = {c: i for i, c in enumerate(cols)}
        cutoffs = {}
        if newer_than:
            for s, d in newer_than.items():
                if d is not None:
                    cutoffs[s] = pd.Timestamp(d).date()
        sub = panel[cols] if cols else panel.iloc[:, :0]
        rows: List[Dict] = []
        # itertuples(index=True) → (Index(symbol,date), v0, v1, …); name=None keeps it light.
        for tup in sub.itertuples(index=True, name=None):
            sym, date = tup[0]
            d = pd.Timestamp(date).date()
            cutoff = cutoffs.get(sym)
            if cutoff is not None and d <= cutoff:
                continue
            rec = {"symbol": sym, "date": d}
            vals = tup[1:]
            for c in VALUE_COLUMNS:
                v = vals[col_pos[c]] if c in col_pos else None
                rec[c] = self._coerce(c, v)
            rows.append(rec)
        return rows

    def _latest_rows(self, panel: pd.DataFrame) -> List[Dict]:
        if panel is None or len(panel) == 0:
            return []
        last = panel.groupby(level="symbol", sort=False).tail(1)
        cols = [c for c in VALUE_COLUMNS if c in last.columns]
        col_pos = {c: i for i, c in enumerate(cols)}
        sub = last[cols] if cols else last.iloc[:, :0]
        rows: List[Dict] = []
        for tup in sub.itertuples(index=True, name=None):
            sym, date = tup[0]
            rec = {"symbol": sym, "date": pd.Timestamp(date).date()}
            vals = tup[1:]
            for c in VALUE_COLUMNS:
                v = vals[col_pos[c]] if c in col_pos else None
                rec[c] = self._coerce(c, v)
            rows.append(rec)
        return rows

    def _row_dict(self, sym, date, row) -> Dict:
        d = {"symbol": sym, "date": pd.Timestamp(date).date()}
        for c in VALUE_COLUMNS:
            v = row[c] if c in row.index else None
            d[c] = self._coerce(c, v)
        return d

    @staticmethod
    def _coerce(col, v):
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
        if col in _INT_COLUMNS:
            return int(v)
        return float(v)

    @staticmethod
    def _upsert(conn, table, cols, pk, rows) -> int:
        if not rows:
            return 0
        from psycopg2.extras import execute_values
        col_list = ", ".join(cols)
        update_cols = [c for c in cols if c not in pk]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        conflict = ", ".join(pk)
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES %s "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        )
        template = "(" + ", ".join(["%s"] * len(cols)) + ")"
        values = [tuple(r.get(c) for c in cols) for r in rows]
        with conn.cursor() as cur:
            execute_values(cur, sql, values, template=template, page_size=1000)
        return len(rows)
