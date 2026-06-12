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


# --------------------------------------------------------------------------- #
# incremental history upsert (finding F1-2)
# --------------------------------------------------------------------------- #
def test_upsert_incremental_writes_only_newer_history(schema):
    store = _store(schema)
    panel, dates = _panel(symbols=("AAA",), n=4)   # dates 01-01 .. 01-04
    c1 = store.upsert(panel)
    assert c1["classification_history"] == 4

    # re-running the SAME panel writes ZERO history rows (all dates already stored)
    # but still upserts current (latest row per symbol).
    c2 = store.upsert(panel)
    assert c2["classification_history"] == 0
    assert c2["classification_current"] == 1

    # extending with two newer dates writes only the 2 new bars.
    dates2 = pd.date_range("2024-01-01", periods=6)
    idx = pd.MultiIndex.from_product([["AAA"], dates2], names=["symbol", "date"])
    grown = pd.DataFrame(index=idx)
    for i, col in enumerate(VALUE_COLUMNS):
        grown[col] = float(i + 1)
    c3 = store.upsert(grown)
    assert c3["classification_history"] == 2
    # full history is intact (6 rows total — no loss, no dup).
    assert len(store.history("AAA")) == 6


def test_upsert_full_mode_writes_all_history(schema):
    store = _store(schema)
    panel, _ = _panel(symbols=("AAA",), n=4)
    store.upsert(panel)
    # incremental=False forces a full re-upsert (backfill/repair path).
    c = store.upsert(panel, incremental=False)
    assert c["classification_history"] == 4


# --------------------------------------------------------------------------- #
# cross_section cache (finding F1-3)
# --------------------------------------------------------------------------- #
def test_cross_section_cache_hit_and_invalidate(schema):
    store = _store(schema)
    panel, _ = _panel()
    store.upsert(panel)

    first = store.cross_section()
    assert len(first) == 5
    # second call within TTL is served from cache (consistent rows, same content).
    second = store.cross_section()
    pd.testing.assert_frame_equal(first, second)
    # returned frames are copies — mutating one must not poison the cache.
    second.loc[second.index[0], "stage"] = -999
    third = store.cross_section()
    assert (third["stage"] == 4).all()

    # a Writer upsert invalidates the cache so a fresh write is never served stale.
    grown, _ = _panel(symbols=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"), n=4)
    store.upsert(grown)
    after = store.cross_section()
    assert len(after) == 6


# --------------------------------------------------------------------------- #
# stale (not just empty) freshness diff (finding F1-5)
# --------------------------------------------------------------------------- #
def test_ensure_fresh_diffs_stored_max_against_source_last_bar(schema):
    store = _store(schema)
    panel, dates = _panel(symbols=("AAA",), n=4)    # stored MAX(date) = 2024-01-04
    store.upsert(panel)

    seen = []
    store.set_refresher(lambda ids: seen.append(sorted(ids)))

    # source says AAA has a NEWER bar than stored → AAA is stale despite having history.
    store.set_last_bar_provider(lambda ids: {"AAA": pd.Timestamp("2024-01-10")})
    store.ensure_fresh(["AAA"])
    assert seen == [["AAA"]]

    # source bar == stored bar → fresh, no refresh.
    seen.clear()
    store.set_last_bar_provider(lambda ids: {"AAA": pd.Timestamp(dates[-1].date())})
    store.ensure_fresh(["AAA"])
    assert seen == []


# --------------------------------------------------------------------------- #
# rs_rank_changes — RS momentum (RS_Chg1W/1M/3M) from history, original parity
# --------------------------------------------------------------------------- #
def _rs_panel(n, symbols=("AAA", "BBB")):
    """Panel where ``rs_rank`` == the date ordinal (0..n-1), identical across symbols,
    so ``rs_rank_changes`` deltas equal the trading-day lags exactly (anchor − lag)."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    idx = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "date"])
    df = pd.DataFrame(index=idx)
    for c in VALUE_COLUMNS:
        df[c] = 1.0
    ordinal = {d: float(j) for j, d in enumerate(dates)}
    df["rs_rank"] = [ordinal[d] for (_, d) in df.index]
    return df, dates


def test_rs_rank_changes_deltas(schema):
    """rs_rank == date ordinal → deltas are exactly the 5/21/63 trading-day lags."""
    store = _store(schema)
    panel, _ = _rs_panel(n=64)
    store.upsert(panel)
    chg = store.rs_rank_changes()
    assert list(chg.columns) == ["rs_chg1w", "rs_chg1m", "rs_chg3m"]
    assert list(chg.index) == ["AAA", "BBB"]
    for sym in ("AAA", "BBB"):
        assert chg.loc[sym, "rs_chg1w"] == 5    # rank[63] − rank[58]
        assert chg.loc[sym, "rs_chg1m"] == 21   # rank[63] − rank[42]
        assert chg.loc[sym, "rs_chg3m"] == 63   # rank[63] − rank[0]


def test_rs_rank_changes_short_history_is_nan(schema):
    """Lags beyond the available history yield NaN (the original left them None)."""
    store = _store(schema)
    panel, _ = _rs_panel(n=10)   # only 10 trading days of history
    store.upsert(panel)
    chg = store.rs_rank_changes()
    assert chg.loc["AAA", "rs_chg1w"] == 5      # 1W lag (5) reachable: rank[9] − rank[4]
    assert pd.isna(chg.loc["AAA", "rs_chg1m"])  # 1M lag (21) unreachable
    assert pd.isna(chg.loc["AAA", "rs_chg3m"])  # 3M lag (63) unreachable


def test_rs_rank_changes_asof_anchors_to_past_date(schema):
    """``asof`` anchors the 'current' date to the latest trading day ≤ asof."""
    store = _store(schema)
    panel, dates = _rs_panel(n=65)
    store.upsert(panel)
    # anchor one trading day earlier (ordinal 63) → all three lags still reachable,
    # deltas unchanged because rs_rank == ordinal (constant slope).
    chg = store.rs_rank_changes(asof=dates[-2])
    assert chg.loc["AAA", "rs_chg1w"] == 5      # rank[63] − rank[58]
    assert chg.loc["AAA", "rs_chg1m"] == 21     # rank[63] − rank[42]
    assert chg.loc["AAA", "rs_chg3m"] == 63     # rank[63] − rank[0]
