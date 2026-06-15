"""Integration tests for Slice #9 — MKLists access layer (ListStore).

Spec §4.6 / §6:
    Server-side shared list store backed by `MKLists.list_member`
    (PK (list_name, symbol); index on symbol; cols added_at, note).
    Screener writes, Monitor reads — neither imports the other.

ListStore surface (DI: conn_factory, schema-parameterized):
    add(list_name, symbol, note=None)
    remove(list_name, symbol)
    members(list_name) -> [symbol]
    lists() -> [name]
    lists_for(symbol) -> [name]

These run against the LIVE Postgres (DSN from MKTT_PG_DSN) but only ever touch a
DISPOSABLE schema `mktt_test` — created at setup, dropped at teardown. The real
MKLists/MKFund/MKCompStore schemas are never touched. The whole module is skipped
gracefully when the DB is unreachable (e.g. CI without the VPN).
"""
from __future__ import annotations

import os

import pytest

from lists.store import ListStore, build_conn_factory, DEFAULT_DSN

psycopg2 = pytest.importorskip("psycopg2")

TEST_SCHEMA = "mktt_test"


def _dsn() -> str:
    return os.environ.get("MKTT_PG_DSN", DEFAULT_DSN)


def _can_connect() -> bool:
    try:
        conn = psycopg2.connect(_dsn(), connect_timeout=8)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(), reason="live Postgres (MKTT_PG_DSN) not reachable"
)


# --------------------------------------------------------------------------- #
# Disposable-schema fixture — NEVER touches the real MKLists schema.
# --------------------------------------------------------------------------- #

# Mirrors the real MKLists.list_member DDL (spec §6) into the disposable schema.
_DDL = """
CREATE TABLE {schema}.list_member (
    list_name text NOT NULL,
    symbol    text NOT NULL,
    added_at  timestamptz NOT NULL DEFAULT now(),
    note      text,
    PRIMARY KEY (list_name, symbol)
);
CREATE INDEX ix_list_member_symbol ON {schema}.list_member USING btree (symbol);
"""


@pytest.fixture()
def store():
    factory = build_conn_factory(_dsn())
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE;')
            cur.execute(f'CREATE SCHEMA {TEST_SCHEMA};')
            cur.execute(_DDL.format(schema=TEST_SCHEMA))
        conn.commit()
    finally:
        conn.close()

    yield ListStore(conn_factory=factory, schema=TEST_SCHEMA)

    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE;')
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Round-trip add / members
# --------------------------------------------------------------------------- #

def test_add_then_members_roundtrip(store):
    store.add("watch", "AAPL")
    store.add("watch", "MSFT", note="strong RS")
    assert store.members("watch") == ["AAPL", "MSFT"]


def test_members_empty_list_is_empty(store):
    assert store.members("does-not-exist") == []


def test_note_is_persisted(store):
    store.add("watch", "AAPL", note="breakout")
    # members returns symbols only; the note round-trips at the row level.
    factory = build_conn_factory(_dsn())
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT note FROM {TEST_SCHEMA}.list_member "
                "WHERE list_name=%s AND symbol=%s",
                ("watch", "AAPL"),
            )
            assert cur.fetchone()[0] == "breakout"
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# members_detailed — (symbol, note, added_at) for the Monitor rail
# --------------------------------------------------------------------------- #

def test_members_detailed_returns_symbol_note_added_at(store):
    store.add("watch", "AAPL", note="long")
    store.add("watch", "MSFT", note="short")
    detailed = store.members_detailed("watch")
    by_sym = {row[0]: row for row in detailed}
    assert set(by_sym) == {"AAPL", "MSFT"}
    # note round-trips and added_at is populated (DB default now()).
    assert by_sym["AAPL"][1] == "long"
    assert by_sym["MSFT"][1] == "short"
    assert by_sym["AAPL"][2] is not None
    assert by_sym["MSFT"][2] is not None


def test_members_detailed_empty_list(store):
    assert store.members_detailed("does-not-exist") == []


# --------------------------------------------------------------------------- #
# remove
# --------------------------------------------------------------------------- #

def test_remove(store):
    store.add("watch", "AAPL")
    store.add("watch", "MSFT")
    store.remove("watch", "AAPL")
    assert store.members("watch") == ["MSFT"]


def test_remove_absent_is_noop(store):
    store.add("watch", "AAPL")
    store.remove("watch", "NOPE")  # must not raise
    assert store.members("watch") == ["AAPL"]


# --------------------------------------------------------------------------- #
# dedup — PK (list_name, symbol)
# --------------------------------------------------------------------------- #

def test_add_dedup_idempotent(store):
    store.add("watch", "AAPL")
    store.add("watch", "AAPL")  # PK collision must not raise nor duplicate
    assert store.members("watch") == ["AAPL"]


def test_add_dedup_updates_note(store):
    store.add("watch", "AAPL", note="first")
    store.add("watch", "AAPL", note="second")
    assert store.members("watch") == ["AAPL"]
    factory = build_conn_factory(_dsn())
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT note FROM {TEST_SCHEMA}.list_member "
                "WHERE list_name=%s AND symbol=%s",
                ("watch", "AAPL"),
            )
            assert cur.fetchone()[0] == "second"
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# lists() — distinct names
# --------------------------------------------------------------------------- #

def test_lists_distinct_names(store):
    store.add("watch", "AAPL")
    store.add("watch", "MSFT")
    store.add("longs", "NVDA")
    assert store.lists() == ["longs", "watch"]


def test_lists_empty(store):
    assert store.lists() == []


# --------------------------------------------------------------------------- #
# lists_for(symbol) — reverse lookup
# --------------------------------------------------------------------------- #

def test_lists_for_reverse_lookup(store):
    store.add("watch", "AAPL")
    store.add("longs", "AAPL")
    store.add("longs", "NVDA")
    assert store.lists_for("AAPL") == ["longs", "watch"]
    assert store.lists_for("NVDA") == ["longs"]
    assert store.lists_for("ZZZZ") == []


# --------------------------------------------------------------------------- #
# multiple named lists isolation
# --------------------------------------------------------------------------- #

def test_named_lists_isolation(store):
    store.add("watch", "AAPL")
    store.add("longs", "NVDA")
    assert store.members("watch") == ["AAPL"]
    assert store.members("longs") == ["NVDA"]
    store.remove("watch", "AAPL")
    assert store.members("watch") == []
    assert store.members("longs") == ["NVDA"]  # unaffected


# --------------------------------------------------------------------------- #
# DI — conn_factory is injected; default schema is MKLists.
# --------------------------------------------------------------------------- #

def test_default_schema_is_mklists():
    s = ListStore(conn_factory=lambda: None)
    assert s.schema == "MKLists"
