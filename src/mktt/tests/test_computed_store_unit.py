"""Unit tests — ComputedStore row-shaping + DDL (no DB).

The DB-touching current/history split + DISTINCT ON is covered by the integration
test against the disposable schema; here we test the pure shaping seams.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from computed.store import VALUE_COLUMNS, ComputedStore, ddl


def _store():
    # conn_factory never called by the shaping helpers under test.
    return ComputedStore(conn_factory=lambda: None, schema="mktt_test")


def _enriched_panel():
    dates = pd.date_range("2024-01-01", periods=3)
    idx = pd.MultiIndex.from_product([["AAA", "BBB"], dates], names=["symbol", "date"])
    df = pd.DataFrame(index=idx)
    for c in VALUE_COLUMNS:
        df[c] = 1.0
    # make the latest row distinguishable per symbol
    df.loc[("AAA", dates[-1]), "stage"] = 2.0
    df.loc[("BBB", dates[-1]), "stage"] = 4.0
    return df, dates


def test_latest_rows_one_per_symbol():
    store = _store()
    panel, dates = _enriched_panel()
    rows = store._latest_rows(panel)
    assert len(rows) == 2  # fixed-size: one per symbol
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["AAA"]["date"] == dates[-1].date()
    assert by_sym["AAA"]["stage"] == 2  # int-coerced
    assert by_sym["BBB"]["stage"] == 4


def test_panel_rows_full_history():
    store = _store()
    panel, _ = _enriched_panel()
    rows = store._panel_rows(panel)
    assert len(rows) == 6  # all symbol×date rows


def test_int_columns_coerced():
    store = _store()
    row = pd.Series({c: 1.0 for c in VALUE_COLUMNS})
    d = store._row_dict("AAA", pd.Timestamp("2024-01-01"), row)
    assert isinstance(d["stage"], int)
    assert isinstance(d["regime"], int)
    assert isinstance(d["ma_screen"], int)
    assert isinstance(d["rs_rank"], float)


def test_nan_becomes_none():
    store = _store()
    row = pd.Series({c: np.nan for c in VALUE_COLUMNS})
    d = store._row_dict("AAA", pd.Timestamp("2024-01-01"), row)
    assert all(d[c] is None for c in VALUE_COLUMNS)


def test_panel_rows_skips_already_stored_dates():
    """Incremental shaping (finding F1-2): rows at/under a stored MAX(date) are
    skipped; only strictly-newer dates are emitted."""
    store = _store()
    panel, dates = _enriched_panel()  # AAA/BBB × 2024-01-01..03
    # pretend AAA is stored through 01-02, BBB has no history.
    newer = {"AAA": pd.Timestamp("2024-01-02"), "BBB": None}
    rows = store._panel_rows(panel, newer_than=newer)
    by_sym = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r["date"])
    # AAA: only 01-03 survives; BBB: all three (no cutoff).
    assert by_sym["AAA"] == [dates[-1].date()]
    assert len(by_sym["BBB"]) == 3


def test_panel_rows_full_when_no_cutoff():
    store = _store()
    panel, _ = _enriched_panel()
    assert len(store._panel_rows(panel)) == 6  # itertuples path, all rows


def test_cross_section_cache_get_respects_ttl():
    """Cache helper honours TTL and returns None when expired (finding F1-3)."""
    import time
    store = _store()
    store._xs_cache_ttl = 1000
    key = store._xs_cache_key({"stage": 4})
    df = pd.DataFrame({"stage": [4]})
    store._xs_cache_put(key, df)
    assert store._xs_cache_get(key) is not None
    # expire by forcing the stored timestamp into the past.
    ts, cached = store._xs_cache[key]
    store._xs_cache[key] = (ts - 10_000, cached)
    assert store._xs_cache_get(key) is None
    # invalidate clears all entries.
    store._xs_cache_put(key, df)
    store.invalidate_cross_section_cache()
    assert store._xs_cache_get(key) is None


class _FakeConn:
    """Minimal conn for an empty-panel upsert (no rows -> no execute_values)."""

    def cursor(self):
        class _Cur:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, *a, **k):
                pass

            def fetchall(self_inner):
                return []

            description = []

        return _Cur()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_cross_section_version_starts_truthy_and_bumps_on_upsert():
    """Slice 1: the cross-section freshness token is monotonic and bumps on upsert.

    Downstream result caches key on it so a Writer upsert invalidates them instantly
    (a cached view is never staler than the data)."""
    store = ComputedStore(conn_factory=lambda: _FakeConn(), schema="mktt_test")
    v0 = store.cross_section_version()
    assert v0  # truthy from the start

    store.upsert(pd.DataFrame())     # an (empty) upsert still bumps the token
    v1 = store.cross_section_version()
    assert v1 > v0

    store.upsert(pd.DataFrame())
    assert store.cross_section_version() > v1


def test_ensure_fresh_noop_without_refresher():
    store = _store()
    # no refresher wired → ensure_fresh is a no-op even with a stale provider.
    store.set_last_bar_provider(lambda ids: {"AAA": pd.Timestamp("2099-01-01")})
    store.ensure_fresh(["AAA"])  # must not raise / not call anything


def test_ddl_has_both_tables_and_pks():
    sql = ddl("mktt_test")
    assert "classification_current" in sql
    assert "classification_history" in sql
    assert "symbol text PRIMARY KEY" in sql
    assert "PRIMARY KEY (symbol, date)" in sql
    # all value columns present
    for c in VALUE_COLUMNS:
        assert c in sql
