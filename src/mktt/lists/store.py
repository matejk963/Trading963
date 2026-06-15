"""ListStore — shared lists access layer over `MKLists.list_member` (spec §4.6, §6).

The store owns the **only** access path to the shared lists table. Sections receive
it (DI) and call `add/remove/members/lists/lists_for`; the Screener-writes /
Monitor-reads contract is honored without either section importing the other.

Design (spec §8):
- **Dependency injection**: the store takes a `conn_factory` (a zero-arg callable
  returning a fresh psycopg2 connection). Tests inject a factory pointed at a
  disposable schema; production defaults to one built from `MKTT_PG_DSN`.
- **Schema-parameterized**: every statement is qualified with `self.schema`
  (default `"MKLists"`), so the same code runs against the real schema or a
  throwaway integration schema.
- No module-level globals, no implicit connection — purely injected.

Table (spec §6):
    MKLists.list_member(list_name text, symbol text, added_at timestamptz,
                        note text, PRIMARY KEY (list_name, symbol), index on symbol)
"""
from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional

logger = logging.getLogger("mktt.lists.store")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

# Live DSN (spec FLAG-7). Code reads MKTT_PG_DSN; this is the documented default.
DEFAULT_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"

DEFAULT_SCHEMA = "MKLists"

ConnFactory = Callable[[], "object"]


def build_conn_factory(dsn: Optional[str] = None) -> ConnFactory:
    """Build a zero-arg psycopg2 connection factory from a DSN.

    DSN resolution: explicit arg → `MKTT_PG_DSN` env → `DEFAULT_DSN`. Each call to
    the returned factory opens a **fresh** connection (the store opens/closes per
    operation, so connections never leak across calls)."""
    resolved = dsn or os.environ.get("MKTT_PG_DSN") or DEFAULT_DSN

    def _factory():
        import psycopg2  # local import: keep the module importable without psycopg2
        return psycopg2.connect(resolved)

    return _factory


class ListStore:
    """Shared named-list store backed by `<schema>.list_member`.

    Parameters
    ----------
    conn_factory:
        Zero-arg callable returning a fresh DB connection (the DI seam). Defaults
        to one built from `MKTT_PG_DSN` / `DEFAULT_DSN`.
    schema:
        Schema holding `list_member`. Defaults to `"MKLists"`; tests pass a
        disposable schema.
    """

    def __init__(
        self,
        conn_factory: Optional[ConnFactory] = None,
        schema: str = DEFAULT_SCHEMA,
    ) -> None:
        self._conn_factory = conn_factory or build_conn_factory()
        self.schema = schema
        # Pre-format the qualified table once. The schema is operator-supplied
        # config (not user input), so identifier interpolation here is safe.
        self._table = f'"{schema}".list_member'

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _execute(self, sql: str, params=None, fetch: bool = False):
        """Open a fresh connection, run one statement, commit, close.

        Returns the fetched rows when `fetch=True`, else None. Per-operation
        connections keep the store stateless and connection-leak-free.
        """
        logger.debug("ListStore execute schema=%s sql=%s params=%s", self.schema, sql, params)
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                rows = cur.fetchall() if fetch else None
            conn.commit()
            return rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # writes (Screener)
    # ------------------------------------------------------------------ #
    def add(self, list_name: str, symbol: str, note: Optional[str] = None) -> None:
        """Add `symbol` to `list_name` (idempotent via the PK).

        On a PK collision the row is upserted (note refreshed, added_at left as
        the original) — so re-adding never raises and never duplicates."""
        self._execute(
            f"""
            INSERT INTO {self._table} (list_name, symbol, note)
            VALUES (%s, %s, %s)
            ON CONFLICT (list_name, symbol)
            DO UPDATE SET note = EXCLUDED.note
            """,
            (list_name, symbol, note),
        )

    def remove(self, list_name: str, symbol: str) -> None:
        """Remove `symbol` from `list_name`. A no-op if the pair is absent."""
        self._execute(
            f"DELETE FROM {self._table} WHERE list_name = %s AND symbol = %s",
            (list_name, symbol),
        )

    # ------------------------------------------------------------------ #
    # reads (Monitor)
    # ------------------------------------------------------------------ #
    def members(self, list_name: str) -> List[str]:
        """Symbols in `list_name`, ordered by symbol (deterministic)."""
        rows = self._execute(
            f"SELECT symbol FROM {self._table} WHERE list_name = %s ORDER BY symbol",
            (list_name,),
            fetch=True,
        )
        return [r[0] for r in rows]

    def members_with_notes(self, list_name: str) -> List[tuple]:
        """`(symbol, note)` pairs in `list_name`, ordered by symbol.

        The note carries the watchlist `side` (long/short) so the Monitor /
        watchlist page can split the list without a second lookup."""
        rows = self._execute(
            f"SELECT symbol, note FROM {self._table} WHERE list_name = %s ORDER BY symbol",
            (list_name,),
            fetch=True,
        )
        return [(r[0], r[1]) for r in rows]

    def members_detailed(self, list_name: str) -> List[tuple]:
        """`(symbol, note, added_at)` triples in `list_name`, ordered by symbol.

        Adds `added_at` (the Monitor rail's `recently-added` sort key) on top of
        `members_with_notes`. Ordering is by symbol for a deterministic read; the
        caller re-orders by `added_at` when it wants recency."""
        rows = self._execute(
            f"SELECT symbol, note, added_at FROM {self._table} "
            "WHERE list_name = %s ORDER BY symbol",
            (list_name,),
            fetch=True,
        )
        return [(r[0], r[1], r[2]) for r in rows]

    def lists(self) -> List[str]:
        """All distinct list names, ordered by name."""
        rows = self._execute(
            f"SELECT DISTINCT list_name FROM {self._table} ORDER BY list_name",
            fetch=True,
        )
        return [r[0] for r in rows]

    def lists_for(self, symbol: str) -> List[str]:
        """Reverse lookup — every list `symbol` belongs to, ordered by name.

        Backed by the `symbol` index on `list_member`."""
        rows = self._execute(
            f"SELECT list_name FROM {self._table} WHERE symbol = %s ORDER BY list_name",
            (symbol,),
            fetch=True,
        )
        return [r[0] for r in rows]
