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
    ) -> None:
        self._conn_factory = conn_factory or build_conn_factory()
        self.schema = schema
        self._refresher = refresher
        self._current = f'"{schema}".classification_current'
        self._history = f'"{schema}".classification_history'

    def set_refresher(self, refresher: Callable[[Sequence[str]], None]) -> None:
        """Wire the Writer's ``run`` as the auto-ensure-fresh hook (spec §5.3)."""
        self._refresher = refresher

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
        return df

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
        """Recompute any of ``ids`` that have no materialized history yet.

        Self-describes freshness via ``MAX(date)`` (spec §7): an id with no history
        row is stale and handed to the refresher (the Writer). A richer
        last-bar-date diff against the raw panel is the Writer's job; here a missing
        symbol is the cold-miss this layer must trigger (spec §5.3).
        """
        if self._refresher is None:
            return
        ids = list(ids)
        if not ids:
            return
        have = set(self.last_bar_dates(ids))
        stale = [i for i in ids if i not in have]
        if stale:
            logger.debug("ensure_fresh: %d stale → refresher", len(stale))
            self._refresher(stale)

    def _maybe_refresh(self, ids) -> None:
        if self._refresher is None:
            return
        if ids is not None:
            self.ensure_fresh(ids)

    # ------------------------------------------------------------------ #
    # upsert (spec §7) — history append + current upsert in ONE txn
    # ------------------------------------------------------------------ #
    def upsert(self, panel: pd.DataFrame) -> Dict[str, int]:
        """Materialize a kernel+classifier ``symbol × date`` panel.

        Writes every row to ``classification_history`` (append/upsert by PK) and
        the **latest** row per symbol to ``classification_current`` (upsert by
        symbol) — both in ONE transaction (spec §7). Returns row counts written.

        The panel index is ``symbol × date``; only :data:`VALUE_COLUMNS` present in
        the panel are written (absent ones stored NULL).
        """
        history_rows = self._panel_rows(panel)
        current_rows = self._latest_rows(panel)

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
        logger.debug("upsert: %s", counts)
        return counts

    # ---- row shaping -------------------------------------------------- #
    def _panel_rows(self, panel: pd.DataFrame) -> List[Dict]:
        if panel is None or len(panel) == 0:
            return []
        rows = []
        for (sym, date), row in panel.iterrows():
            rows.append(self._row_dict(sym, date, row))
        return rows

    def _latest_rows(self, panel: pd.DataFrame) -> List[Dict]:
        if panel is None or len(panel) == 0:
            return []
        last = panel.groupby(level="symbol", sort=False).tail(1)
        rows = []
        for (sym, date), row in last.iterrows():
            rows.append(self._row_dict(sym, date, row))
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
