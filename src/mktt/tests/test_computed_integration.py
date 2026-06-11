"""Integration tests — ComputedStore vs a DISPOSABLE Postgres schema (spec §8).

Runs against the live Postgres (DSN from MKTT_PG_DSN) but ONLY ever touches a
disposable schema ``mktt_test`` (created at setup, dropped at teardown). The real
MKCompStore schema is never touched. Skipped gracefully when the DB is unreachable.

Path: upsert a 5-symbol kernel+classifier panel, read it back through
``cross_section`` (assert fixed-size, one row per symbol, DISTINCT ON latest) and
``history`` (assert the full per-date series), and check the current/history split.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from computed.store import VALUE_COLUMNS, ComputedStore, ddl

psycopg2 = pytest.importorskip("psycopg2")

TEST_SCHEMA = "mktt_test"
DEFAULT_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"


def _dsn():
    return os.environ.get("MKTT_PG_DSN", DEFAULT_DSN)


def _can_connect():
    try:
        c = psycopg2.connect(_dsn(), connect_timeout=8)
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(), reason="live Postgres (MKTT_PG_DSN) not reachable"
)


def _factory():
    return psycopg2.connect(_dsn())


@pytest.fixture()
def schema():
    conn = _factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE;')
            cur.execute(f'CREATE SCHEMA {TEST_SCHEMA};')
            cur.execute(ddl(TEST_SCHEMA))
        conn.commit()
    finally:
        conn.close()
    yield TEST_SCHEMA
    conn = _factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE;')
        conn.commit()
    finally:
        conn.close()


def _panel(symbols=("AAA", "BBB", "CCC", "DDD", "EEE"), n=4):
    dates = pd.date_range("2024-01-01", periods=n)
    idx = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "date"])
    df = pd.DataFrame(index=idx)
    for i, c in enumerate(VALUE_COLUMNS):
        df[c] = float(i + 1)
    # vary stage by date so "latest" is distinguishable from earlier history
    for j, d in enumerate(dates):
        df.loc[(slice(None), d), "stage"] = float(j + 1)
    return df, dates


def _store(schema):
    return ComputedStore(conn_factory=_factory, schema=schema)


def test_upsert_then_cross_section_is_fixed_size(schema):
    panel, dates = _panel()
    store = _store(schema)
    counts = store.upsert(panel)
    assert counts["classification_history"] == 20   # 5 symbols × 4 dates
    assert counts["classification_current"] == 5     # one per symbol

    cs = store.cross_section()
    assert len(cs) == 5                               # fixed-size
    assert list(cs.index) == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    # DISTINCT ON latest → stage from the last date (n=4 → stage 4)
    assert (cs["stage"] == 4).all()


def test_history_split(schema):
    panel, dates = _panel()
    store = _store(schema)
    store.upsert(panel)

    h = store.history("AAA")
    assert len(h) == 4                                # full per-date history
    assert list(h.index.get_level_values("date").date) == [d.date() for d in dates]
    # stage evolves 1→4 across the history
    assert h["stage"].tolist() == [1, 2, 3, 4]


def test_cross_section_filter(schema):
    panel, dates = _panel()
    store = _store(schema)
    store.upsert(panel)
    # current stage is 4 for every symbol; filter on it returns all, on 1 returns none
    assert len(store.cross_section(filters={"stage": 4})) == 5
    assert len(store.cross_section(filters={"stage": 1})) == 0


def test_upsert_idempotent(schema):
    panel, _ = _panel()
    store = _store(schema)
    store.upsert(panel)
    store.upsert(panel)  # re-run upserts, no dup
    cs = store.cross_section()
    assert len(cs) == 5
    h = store.history("AAA")
    assert len(h) == 4


def test_ensure_fresh_triggers_refresher_for_missing(schema):
    store = _store(schema)
    seen = []
    store.set_refresher(lambda ids: seen.append(list(ids)))
    # nothing materialized → all stale
    store.ensure_fresh(["AAA", "BBB"])
    assert seen == [["AAA", "BBB"]]

    # materialize AAA, then only BBB is stale
    panel, _ = _panel(symbols=("AAA",))
    store.upsert(panel)
    seen.clear()
    store.ensure_fresh(["AAA", "BBB"])
    assert seen == [["BBB"]]


def test_last_bar_dates(schema):
    panel, dates = _panel(symbols=("AAA",))
    store = _store(schema)
    store.upsert(panel)
    lbd = store.last_bar_dates(["AAA", "ZZZ"])
    assert lbd["AAA"] == pd.Timestamp(dates[-1].date())
    assert "ZZZ" not in lbd
