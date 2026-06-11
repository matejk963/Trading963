"""MKTT shared lists access layer (spec §4.6, §6).

Server-side list store backed by Postgres `MKLists.list_member`. The contract is
**Screener writes, Monitor reads** — neither section imports the other; the shared
meaning lives here, one layer down.

Public surface:
    ListStore           — the store (DI: conn_factory, schema-parameterized).
    build_conn_factory  — builds a psycopg2 connection factory from a DSN.
    DEFAULT_DSN         — fallback DSN when MKTT_PG_DSN is unset.
"""
from __future__ import annotations

from .store import ListStore, build_conn_factory, DEFAULT_DSN

__all__ = ["ListStore", "build_conn_factory", "DEFAULT_DSN"]
