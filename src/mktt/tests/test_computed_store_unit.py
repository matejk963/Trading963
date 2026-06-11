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


def test_ddl_has_both_tables_and_pks():
    sql = ddl("mktt_test")
    assert "classification_current" in sql
    assert "classification_history" in sql
    assert "symbol text PRIMARY KEY" in sql
    assert "PRIMARY KEY (symbol, date)" in sql
    # all value columns present
    for c in VALUE_COLUMNS:
        assert c in sql
