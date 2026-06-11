"""Unit tests for Slice #4 — MKFund loader pure column mapping.

These are pure (no DB): hand-built mini-frames mirroring the
`refinitiv_fundamentals.pkl` shapes go in, list[dict] rows come out. They pin the
Refinitiv-name → snake_case mapping and the object/string → float coercion (spec §6).
"""
from __future__ import annotations

import pandas as pd

from datasource.loaders import mkfund_loader as L


# --------------------------------------------------------------------------- #
# snapshot → fundamentals_current
# --------------------------------------------------------------------------- #
def test_map_snapshot_basic_mapping_and_coercion():
    snap = pd.DataFrame([
        {
            "Instrument": "A.N",
            "Symbol": "A",
            "Price Close": "115.62",          # string numeric → float
            "Earnings Per Share - Actual": 5.59,
            "Earnings Per Share - Mean": 5.97,
            "Earnings Per Share - SmartEstimate®": 5.97172,
            "Operating Margin, Percent": 21.48,
            "Net Profit Margin, (%)": 18.75,
            "Return on Capital, Total LT Capital, Percent": 12.81,
            "Enterprise Value To EBITDA (Daily Time Series Ratio)": 17.95,
            "Number of Analysts": 20,
            "GICS Sector Name": "Health Care",
            "GICS Industry Name": "Life Sciences Tools & Services",
        }
    ])
    rows = L.map_snapshot(snap)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "A"
    assert row["instrument"] == "A.N"
    assert row["price_close"] == 115.62           # coerced from string
    assert isinstance(row["price_close"], float)
    assert row["eps_actual"] == 5.59
    assert row["eps_smart"] == 5.97172    # ® stripped from col name
    assert row["operating_margin"] == 21.48
    assert row["net_margin"] == 18.75
    assert row["roic"] == 12.81
    assert row["ev_to_ebitda"] == 17.95
    assert row["num_analysts"] == 20.0
    assert row["gics_sector"] == "Health Care"
    assert row["gics_industry"] == "Life Sciences Tools & Services"


def test_map_snapshot_drops_null_symbol():
    snap = pd.DataFrame([
        {"Symbol": "A", "Instrument": "A.N", "Price Close": 1.0},
        {"Symbol": None, "Instrument": "X.N", "Price Close": 2.0},
        {"Symbol": "", "Instrument": "Y.N", "Price Close": 3.0},
    ])
    rows = L.map_snapshot(snap)
    assert [r["symbol"] for r in rows] == ["A"]


def test_map_snapshot_unparseable_numeric_becomes_none():
    snap = pd.DataFrame([
        {"Symbol": "A", "Price Close": "n/a", "EBITDA": pd.NA},
    ])
    rows = L.map_snapshot(snap)
    assert rows[0]["price_close"] is None
    assert rows[0]["ebitda"] is None


def test_map_snapshot_duplicate_symbol_last_wins():
    snap = pd.DataFrame([
        {"Symbol": "A", "Price Close": 1.0},
        {"Symbol": "A", "Price Close": 2.0},
    ])
    rows = L.map_snapshot(snap)
    assert len(rows) == 1
    assert rows[0]["price_close"] == 2.0


def test_map_snapshot_row_has_all_columns():
    snap = pd.DataFrame([{"Symbol": "A"}])
    rows = L.map_snapshot(snap)
    assert set(rows[0].keys()) == set(L.FUNDAMENTALS_CURRENT_COLS)


# --------------------------------------------------------------------------- #
# fy1/fy2 → estimates_forward
# --------------------------------------------------------------------------- #
def test_map_estimates_forward_fy_periods():
    fy1 = pd.DataFrame([
        {"Symbol": "A", "Earnings Per Share - Mean": 5.97,
         "EPS Number of Estimates": 20, "Revenue - Mean": 7.3e9,
         "EBITDA - Mean": 2.1e9, "Capital Expenditures - Mean": 4.7e8,
         "Cash Flow Per Share - Mean": 6.1, "Dividend Per Share - Mean": 1.0},
    ])
    fy2 = pd.DataFrame([
        {"Symbol": "A", "Earnings Per Share - Mean": 6.40,
         "EPS Number of Estimates": 18, "Revenue - Mean": 7.9e9},
    ])
    rows = L.map_estimates_forward(fy1, fy2)
    by_fy = {r["fy_period"]: r for r in rows}
    assert set(by_fy) == {1, 2}
    assert by_fy[1]["eps_mean"] == 5.97
    assert by_fy[1]["eps_n_est"] == 20.0
    assert by_fy[1]["capex_mean"] == 4.7e8
    assert by_fy[1]["cfps_mean"] == 6.1
    assert by_fy[2]["eps_mean"] == 6.40
    assert by_fy[2]["revenue_mean"] == 7.9e9


def test_map_estimates_forward_handles_missing_frame():
    fy1 = pd.DataFrame([{"Symbol": "A", "Earnings Per Share - Mean": 5.0}])
    rows = L.map_estimates_forward(fy1, None)
    assert {r["fy_period"] for r in rows} == {1}


# --------------------------------------------------------------------------- #
# quarterly → quarterly
# --------------------------------------------------------------------------- #
def test_map_quarterly_pk_and_coercion():
    q = pd.DataFrame([
        {"Symbol": "A", "Date": pd.Timestamp("2020-05-21 16:08"),
         "Earnings Per Share - Actual": 0.71,
         "Earnings Per Share - Mean Estimate": "0.606",
         "Revenue - Actual": 1.238e9, "Operating Margin, Percent": 8.23,
         "Current Ratio": 1.63},
    ])
    rows = L.map_quarterly(q)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "A"
    assert r["report_date"].year == 2020 and r["report_date"].month == 5
    assert r["eps_actual"] == 0.71
    assert r["eps_mean_estimate"] == 0.606    # coerced from string
    assert r["operating_margin"] == 8.23
    assert r["current_ratio"] == 1.63


def test_map_quarterly_drops_rows_without_pk():
    q = pd.DataFrame([
        {"Symbol": "A", "Date": pd.Timestamp("2020-05-21")},
        {"Symbol": None, "Date": pd.Timestamp("2020-05-21")},
        {"Symbol": "A", "Date": pd.NaT},
    ])
    rows = L.map_quarterly(q)
    assert len(rows) == 1


def test_map_quarterly_dedup_pk_last_wins():
    d = pd.Timestamp("2020-05-21")
    q = pd.DataFrame([
        {"Symbol": "A", "Date": d, "Earnings Per Share - Actual": 0.71},
        {"Symbol": "A", "Date": d, "Earnings Per Share - Actual": 0.99},
    ])
    rows = L.map_quarterly(q)
    assert len(rows) == 1
    assert rows[0]["eps_actual"] == 0.99


# --------------------------------------------------------------------------- #
# trend_*/hist_est_* → estimate_revisions
# --------------------------------------------------------------------------- #
def test_map_estimate_revisions_long_form():
    frames = {
        "trend_eps_fy1": pd.DataFrame([
            {"Symbol": "A", "Date": pd.Timestamp("2025-04-28"),
             "Earnings Per Share - Mean": 5.55, "Earnings Per Share - High": 5.63,
             "Earnings Per Share - Low": 5.47, "EPS Number of Estimates": 22},
        ]),
        "trend_rev_fy1": pd.DataFrame([
            {"Symbol": "A", "Date": pd.Timestamp("2025-04-17"),
             "Revenue - Mean": 6.7e9, "Revenue - High": 6.85e9, "Revenue - Low": 6.68e9},
        ]),
        "hist_est_fy2": pd.DataFrame([
            {"Symbol": "A", "Date": pd.Timestamp("2020-05-21"),
             "Earnings Per Share - Mean": 3.10},
        ]),
    }
    rows = L.map_estimate_revisions(frames)
    eps_fy1 = [r for r in rows if r["metric"] == "eps" and r["fy_period"] == 1]
    rev_fy1 = [r for r in rows if r["metric"] == "rev" and r["fy_period"] == 1]
    eps_fy2 = [r for r in rows if r["metric"] == "eps" and r["fy_period"] == 2]
    assert len(eps_fy1) == 1 and eps_fy1[0]["mean_val"] == 5.55 and eps_fy1[0]["high_val"] == 5.63
    assert eps_fy1[0]["n_est"] == 22.0
    assert len(rev_fy1) == 1 and rev_fy1[0]["mean_val"] == 6.7e9 and rev_fy1[0]["low_val"] == 6.68e9
    assert rev_fy1[0]["n_est"] is None        # rev has no n_est
    assert len(eps_fy2) == 1 and eps_fy2[0]["mean_val"] == 3.10
    assert eps_fy2[0]["high_val"] is None          # hist_est has no bounds


def test_map_estimate_revisions_pk_shape():
    frames = {
        "trend_eps_fy1": pd.DataFrame([
            {"Symbol": "A", "Date": pd.Timestamp("2025-04-28"),
             "Earnings Per Share - Mean": 5.55},
        ]),
    }
    rows = L.map_estimate_revisions(frames)
    assert set(rows[0].keys()) == set(L.ESTIMATE_REVISIONS_COLS)
