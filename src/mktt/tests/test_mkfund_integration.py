"""Integration tests for Slice #4 — MKFund loader + DataSource.fundamentals.

Runs against the LIVE Postgres (DSN from MKTT_PG_DSN) but only ever touches a
DISPOSABLE schema `mktt_test` — created at setup, dropped at teardown. The real
MKFund schema is never touched. The whole module is skipped gracefully when the DB
is unreachable.

Path: load a small hand-built slice via `mkfund_loader.load(dict, conn_factory, schema)`,
then read it back through `DataSource.fundamentals(...)` and assert the round-trip.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from datasource import DataSource, Registry
from datasource.loaders import mkfund_loader as L
from datasource.submodules.fundamentals import FundamentalsSubmodule

psycopg2 = pytest.importorskip("psycopg2")

TEST_SCHEMA = "mktt_test"
DEFAULT_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"


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


def _factory():
    return psycopg2.connect(_dsn())


# --------------------------------------------------------------------------- #
# Disposable-schema fixture — NEVER touches the real MKFund schema.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def schema():
    conn = _factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE;')
            cur.execute(f'CREATE SCHEMA {TEST_SCHEMA};')
            cur.execute(L.ddl(TEST_SCHEMA))
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


def _mini_pkl():
    """A 2-symbol slice mirroring the real pkl's frame shapes."""
    snapshot = pd.DataFrame([
        {"Symbol": "AAA", "Instrument": "AAA.N", "Price Close": "100.5",
         "Earnings Per Share - Actual": 5.0, "Operating Margin, Percent": 21.0,
         "GICS Sector Name": "Health Care", "Number of Analysts": 20},
        {"Symbol": "BBB", "Instrument": "BBB.N", "Price Close": 50.0,
         "Earnings Per Share - Actual": 2.0, "GICS Sector Name": "Technology"},
    ])
    fy1 = pd.DataFrame([
        {"Symbol": "AAA", "Earnings Per Share - Mean": 5.5,
         "EPS Number of Estimates": 20, "Revenue - Mean": 7.0e9},
    ])
    fy2 = pd.DataFrame([
        {"Symbol": "AAA", "Earnings Per Share - Mean": 6.0, "Revenue - Mean": 7.5e9},
    ])
    quarterly = pd.DataFrame([
        {"Symbol": "AAA", "Date": pd.Timestamp("2020-05-21 16:08"),
         "Earnings Per Share - Actual": 0.71, "Current Ratio": 1.6},
    ])
    trend_eps_fy1 = pd.DataFrame([
        {"Symbol": "AAA", "Date": pd.Timestamp("2025-04-28"),
         "Earnings Per Share - Mean": 5.55, "Earnings Per Share - High": 5.6,
         "Earnings Per Share - Low": 5.5, "EPS Number of Estimates": 22},
    ])
    return {
        "snapshot": snapshot, "fy1": fy1, "fy2": fy2,
        "quarterly": quarterly, "trend_eps_fy1": trend_eps_fy1,
    }


# --------------------------------------------------------------------------- #
# load() row counts
# --------------------------------------------------------------------------- #
def test_load_returns_row_counts(schema):
    counts = L.load(_mini_pkl(), _factory, schema=schema)
    assert counts["fundamentals_current"] == 2
    assert counts["estimates_forward"] == 2   # fy1 + fy2 for AAA
    assert counts["quarterly"] == 1
    assert counts["estimate_revisions"] == 1


def test_load_is_idempotent(schema):
    L.load(_mini_pkl(), _factory, schema=schema)
    L.load(_mini_pkl(), _factory, schema=schema)  # re-run upserts, no dup/raise
    conn = _factory()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{schema}".fundamentals_current')
            assert cur.fetchone()[0] == 2
            cur.execute(f'SELECT count(*) FROM "{schema}".estimates_forward')
            assert cur.fetchone()[0] == 2
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# DataSource.fundamentals read-back
# --------------------------------------------------------------------------- #
def _datasource(schema):
    sub = FundamentalsSubmodule(conn_factory=_factory, schema=schema)
    registry = Registry(submodules={("fundamentals", "*"): sub})
    return DataSource(registry=registry)


def test_fundamentals_roundtrip_all_fields(schema):
    L.load(_mini_pkl(), _factory, schema=schema)
    data = _datasource(schema)
    f = data.fundamentals(["AAA", "BBB"])
    assert list(f.index) == ["AAA", "BBB"]
    assert f.loc["AAA", "price_close"] == 100.5     # coerced from string on load
    assert f.loc["AAA", "gics_sector"] == "Health Care"
    assert f.loc["BBB", "price_close"] == 50.0


def test_fundamentals_field_projection(schema):
    L.load(_mini_pkl(), _factory, schema=schema)
    data = _datasource(schema)
    f = data.fundamentals(["AAA"], fields=["price_close", "gics_sector"])
    assert set(f.columns) == {"price_close", "gics_sector"}
    assert f.loc["AAA", "gics_sector"] == "Health Care"


def test_fundamentals_missing_id_tolerated(schema):
    L.load(_mini_pkl(), _factory, schema=schema)
    data = _datasource(schema)
    f = data.fundamentals(["AAA", "ZZZ"])
    assert list(f.index) == ["AAA"]


def test_fundamentals_with_estimates(schema):
    L.load(_mini_pkl(), _factory, schema=schema)
    data = _datasource(schema)
    f = data.fundamentals(["AAA"], fields=["price_close"], estimates=True)
    assert "fy1_eps_mean" in f.columns
    assert "fy2_eps_mean" in f.columns
    assert f.loc["AAA", "fy1_eps_mean"] == 5.5
    assert f.loc["AAA", "fy2_eps_mean"] == 6.0


def test_fundamentals_empty_ids(schema):
    data = _datasource(schema)
    f = data.fundamentals([])
    assert len(f) == 0


def test_quarterly_roundtrip(schema):
    """F2: DataSource.quarterly reads the long MKFund.quarterly table (used by the
    screener to derive TTM/YoY EPS & Revenue growth)."""
    L.load(_mini_pkl(), _factory, schema=schema)
    data = _datasource(schema)
    q = data.quarterly(["AAA"])
    assert list(q.columns)[:2] == ["symbol", "report_date"]
    assert (q["symbol"] == "AAA").all()
    assert "eps_actual" in q.columns
    # the mini pkl has one AAA quarter with EPS 0.71.
    assert float(q.iloc[0]["eps_actual"]) == 0.71
