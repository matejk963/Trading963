"""MKFund loader — `refinitiv_fundamentals.pkl` → Postgres `MKFund` (spec §4.4, §6).

Collapses the 7 scattered pkl reads (snapshot, fy1/fy2, quarterly, the trend_* and
hist_est_* revision frames) into a single idempotent loader that upserts four tables:

    fundamentals_current   PK symbol                          ← snapshot
    estimates_forward      PK (symbol, fy_period)             ← fy1 / fy2
    quarterly              PK (symbol, report_date)           ← quarterly
    estimate_revisions     PK (symbol, fy_period, metric, asof) ← trend_*/hist_est_*

Design (spec §8):
- **Dependency injection**: `load(pkl_path, conn_factory, schema)` receives a zero-arg
  `conn_factory` (fresh psycopg2 connection) — tests inject a factory pointed at a
  disposable schema; the loader never opens a connection itself nor reads globals.
- **Schema-parameterized**: every statement is qualified with the supplied `schema`
  so the same code runs against real `MKFund` or a throwaway integration schema.
- **Pure mapping / impure write split**: the `map_*` functions are pure
  (DataFrame in → list[dict] rows out, Refinitiv object/string numerics coerced to
  float) and unit-tested on hand-built mini-frames; only `load` touches the DB.
- **Idempotent**: every write is `INSERT ... ON CONFLICT (<pk>) DO UPDATE`, so a
  re-run upserts and never duplicates / deletes.

Refinitiv quirks handled here:
- snapshot numeric columns arrive as object dtype (mixed float / `<NA>` / string) —
  coerced via `pandas.to_numeric(errors="coerce")` → Python float or None.
- the SmartEstimate column name carries a `®`; mapped to plain `_smart_estimate`.
"""
from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("mktt.datasource.loaders.mkfund")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

DEFAULT_SCHEMA = "MKFund"

ConnFactory = Callable[[], "object"]


# --------------------------------------------------------------------------- #
# coercion helpers (pure)
# --------------------------------------------------------------------------- #
def _num(value) -> Optional[float]:
    """Coerce a single Refinitiv object/string numeric to float (or None).

    Refinitiv dumps numerics as object dtype mixing real floats, pandas `<NA>`,
    empty strings and the odd string. `pd.to_numeric` with coercion gives NaN for
    anything unparseable; NaN/NA → None so the DB stores a real NULL.
    """
    s = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(s):
        return None
    return float(s)


def _str(value) -> Optional[str]:
    """Coerce to a stripped str, or None for NA/empty."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _date(value):
    """Coerce to a python ``date`` (or None) — for the DATE PK columns
    (`quarterly.report_date`, `estimate_revisions.asof`).

    The Refinitiv `Date` fields carry a time component (e.g. 16:08), but the DB
    PK columns are `date`; truncating here aligns the in-Python dedupe key with
    the DB's uniqueness, avoiding an `ON CONFLICT` cardinality violation when two
    same-day rows differ only in time.
    """
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


# --------------------------------------------------------------------------- #
# snapshot → fundamentals_current  (PK symbol)
# --------------------------------------------------------------------------- #
# Source column → (snake_case col, coercer). Order defines the table column order.
_SNAPSHOT_MAP = [
    ("Symbol", "symbol", _str),
    ("Instrument", "instrument", _str),
    ("Price Close", "price_close", _num),
    ("Earnings Per Share - Actual", "eps_actual", _num),
    ("Earnings Per Share - Mean", "eps_mean", _num),
    ("Earnings Per Share - SmartEstimate®", "eps_smart", _num),
    ("Revenue - Actual", "revenue_actual", _num),
    ("Revenue - Mean", "revenue_mean", _num),
    ("Operating Margin, Percent", "operating_margin", _num),
    ("Net Profit Margin, (%)", "net_margin", _num),
    ("Gross Profit", "gross_profit", _num),
    ("EBITDA", "ebitda", _num),
    ("Operating Income", "operating_income", _num),
    ("Net Income Incl Extra Before Distributions", "net_income", _num),
    ("Free Cash Flow", "free_cash_flow", _num),
    ("Total Debt", "total_debt", _num),
    ("Net Debt Incl. Pref.Stock & Min.Interest", "net_debt", _num),
    ("Cash and Short Term Investments", "cash_st_investments", _num),
    ("Total Assets", "total_assets", _num),
    ("Total Equity", "total_equity", _num),
    ("Net Debt To EBITDA (Daily Time Series Ratio)", "net_debt_to_ebitda", _num),
    ("Total Debt To EBITDA (Daily Time Series Ratio)", "total_debt_to_ebitda", _num),
    ("Current Ratio", "current_ratio", _num),
    ("Quick Ratio", "quick_ratio", _num),
    ("Working Capital", "working_capital", _num),
    ("Return on Capital, Total LT Capital, Percent", "roic", _num),
    ("Asset Turnover", "asset_turnover", _num),
    ("Enterprise Value To EBITDA (Daily Time Series Ratio)", "ev_to_ebitda", _num),
    ("Enterprise Value To Sales (Daily Time Series Ratio)", "ev_to_sales", _num),
    ("Enterprise Value (Daily Time Series)", "enterprise_value", _num),
    ("Dividend Per Share - Actual", "dps_actual", _num),
    ("Outstanding Shares", "shares_outstanding", _num),
    ("Price Target - Mean", "price_target_mean", _num),
    ("Number of Analysts", "num_analysts", _num),
    ("GICS Sector Name", "gics_sector", _str),
    ("GICS Industry Name", "gics_industry", _str),
]

FUNDAMENTALS_CURRENT_COLS = [snake for (_src, snake, _c) in _SNAPSHOT_MAP]


# fy1/fy2 → estimates_forward (PK symbol, fy_period)
_FORWARD_MAP = [
    ("Earnings Per Share - Mean", "eps_mean", _num),
    ("Earnings Per Share - High", "eps_high", _num),
    ("Earnings Per Share - Low", "eps_low", _num),
    ("Earnings Per Share - SmartEstimate®", "eps_smart", _num),
    ("EPS Number of Estimates", "eps_n_est", _num),
    ("Revenue - Mean", "revenue_mean", _num),
    ("Revenue - High", "revenue_high", _num),
    ("Revenue - Low", "revenue_low", _num),
    ("EBITDA - Mean", "ebitda_mean", _num),
    ("EBITDA - SmartEstimate®", "ebitda_smart", _num),
    ("Capital Expenditures - Mean", "capex_mean", _num),
    ("Cash Flow Per Share - Mean", "cfps_mean", _num),
    ("Dividend Per Share - Mean", "dps_mean", _num),
]

ESTIMATES_FORWARD_COLS = ["symbol", "fy_period"] + [snake for (_s, snake, _c) in _FORWARD_MAP]


# quarterly → quarterly (PK symbol, report_date)
_QUARTERLY_MAP = [
    ("Earnings Per Share - Actual", "eps_actual", _num),
    ("Earnings Per Share - Mean Estimate", "eps_mean_estimate", _num),
    ("Revenue - Actual", "revenue_actual", _num),
    ("Revenue - Mean Estimate", "revenue_mean_estimate", _num),
    ("Operating Margin, Percent", "operating_margin", _num),
    ("Net Profit Margin, (%)", "net_margin", _num),
    ("Free Cash Flow", "free_cash_flow", _num),
    ("Total Debt", "total_debt", _num),
    ("Net Debt Incl. Pref.Stock & Min.Interest", "net_debt", _num),
    ("Cash and Short Term Investments", "cash_st_investments", _num),
    ("Current Ratio", "current_ratio", _num),
]

QUARTERLY_COLS = ["symbol", "report_date"] + [snake for (_s, snake, _c) in _QUARTERLY_MAP]


ESTIMATE_REVISIONS_COLS = ["symbol", "fy_period", "metric", "asof", "mean_val", "high_val", "low_val", "n_est"]


# --------------------------------------------------------------------------- #
# pure mappers — DataFrame → list[dict]
# --------------------------------------------------------------------------- #
def map_snapshot(snapshot: pd.DataFrame) -> List[Dict]:
    """snapshot frame → fundamentals_current rows (one per symbol).

    Rows with a null/blank Symbol are dropped (no PK). On duplicate symbols the
    last wins (the upsert would do the same).
    """
    rows: List[Dict] = []
    seen = set()
    # iterate in reverse so "last wins", then restore order
    records = snapshot.to_dict("records")
    out: Dict[str, Dict] = {}
    for rec in records:
        sym = _str(rec.get("Symbol"))
        if not sym:
            continue
        row = {snake: coerce(rec.get(src)) for (src, snake, coerce) in _SNAPSHOT_MAP}
        row["symbol"] = sym
        out[sym] = row
    rows = list(out.values())
    logger.debug("map_snapshot: %d rows", len(rows))
    return rows


def _map_forward_frame(frame: pd.DataFrame, fy_period: int) -> List[Dict]:
    rows: List[Dict] = []
    for rec in frame.to_dict("records"):
        sym = _str(rec.get("Symbol"))
        if not sym:
            continue
        row = {"symbol": sym, "fy_period": fy_period}
        for (src, snake, coerce) in _FORWARD_MAP:
            row[snake] = coerce(rec.get(src))
        rows.append(row)
    return rows


def map_estimates_forward(fy1: Optional[pd.DataFrame], fy2: Optional[pd.DataFrame]) -> List[Dict]:
    """fy1/fy2 frames → estimates_forward rows (fy_period 1 / 2)."""
    rows: List[Dict] = []
    if fy1 is not None:
        rows.extend(_map_forward_frame(fy1, 1))
    if fy2 is not None:
        rows.extend(_map_forward_frame(fy2, 2))
    logger.debug("map_estimates_forward: %d rows", len(rows))
    return rows


def map_quarterly(quarterly: pd.DataFrame) -> List[Dict]:
    """quarterly frame → quarterly rows (PK symbol, report_date).

    Rows missing a symbol or date are dropped (no PK). On a duplicate
    (symbol, date) the last wins.
    """
    out: Dict[tuple, Dict] = {}
    for rec in quarterly.to_dict("records"):
        sym = _str(rec.get("Symbol"))
        rdate = _date(rec.get("Date"))
        if not sym or rdate is None:
            continue
        row = {"symbol": sym, "report_date": rdate}
        for (src, snake, coerce) in _QUARTERLY_MAP:
            row[snake] = coerce(rec.get(src))
        out[(sym, rdate)] = row
    rows = list(out.values())
    logger.debug("map_quarterly: %d rows", len(rows))
    return rows


def _map_revision_frame(
    frame: pd.DataFrame, metric: str, fy_period: int, has_bounds: bool
) -> List[Dict]:
    value_col = "Earnings Per Share - Mean" if metric == "eps" else "Revenue - Mean"
    rows: List[Dict] = []
    out: Dict[tuple, Dict] = {}
    for rec in frame.to_dict("records"):
        sym = _str(rec.get("Symbol"))
        asof = _date(rec.get("Date"))
        if not sym or asof is None:
            continue
        row = {
            "symbol": sym,
            "fy_period": fy_period,
            "metric": metric,
            "asof": asof,
            "mean_val": _num(rec.get(value_col)),
            "high_val": _num(rec.get("Earnings Per Share - High" if metric == "eps" else "Revenue - High")) if has_bounds else None,
            "low_val": _num(rec.get("Earnings Per Share - Low" if metric == "eps" else "Revenue - Low")) if has_bounds else None,
            "n_est": _num(rec.get("EPS Number of Estimates")) if (has_bounds and metric == "eps") else None,
        }
        out[(sym, fy_period, metric, asof)] = row
    rows = list(out.values())
    return rows


def map_estimate_revisions(frames: Dict[str, pd.DataFrame]) -> List[Dict]:
    """trend_*/hist_est_* frames → long-form estimate_revisions rows.

    `frames` is the pkl dict (or any subset). Recognized sources:
        trend_eps_fy1/fy2  → metric eps, with high/low/n_est bounds
        trend_rev_fy1/fy2  → metric rev, with high/low bounds
        hist_est_fy1/fy2   → metric eps, mean only (no bounds)
    PK is (symbol, fy_period, metric, asof); within one source the last wins, and
    across sources the upsert resolves collisions deterministically (bounds-bearing
    trend_* loaded after hist_est_* below so it wins on overlap).
    """
    specs = [
        # (key, metric, fy_period, has_bounds)
        ("hist_est_fy1", "eps", 1, False),
        ("hist_est_fy2", "eps", 2, False),
        ("trend_eps_fy1", "eps", 1, True),
        ("trend_eps_fy2", "eps", 2, True),
        ("trend_rev_fy1", "rev", 1, True),
        ("trend_rev_fy2", "rev", 2, True),
    ]
    # PK-dedupe across sources (last wins): trend_* specs come after hist_est_*,
    # so a bounds-bearing trend row overwrites a hist_est mean-only row on overlap.
    out: Dict[tuple, Dict] = {}
    for key, metric, fy, has_bounds in specs:
        frame = frames.get(key)
        if frame is None:
            continue
        for row in _map_revision_frame(frame, metric, fy, has_bounds):
            out[(row["symbol"], row["fy_period"], row["metric"], row["asof"])] = row
    rows = list(out.values())
    logger.debug("map_estimate_revisions: %d rows", len(rows))
    return rows


# --------------------------------------------------------------------------- #
# DDL (spec §6) — used by integration tests to build the disposable schema and
# available for first-run table creation against the real schema.
# --------------------------------------------------------------------------- #
def ddl(schema: str) -> str:
    fund_cols = ",\n    ".join(
        f"{c} double precision" if c not in ("symbol", "instrument", "gics_sector", "gics_industry")
        else f"{c} text"
        for c in FUNDAMENTALS_CURRENT_COLS
        if c != "symbol"
    )
    fwd_cols = ",\n    ".join(
        f"{c} double precision" for c in ESTIMATES_FORWARD_COLS if c not in ("symbol", "fy_period")
    )
    q_cols = ",\n    ".join(
        f"{c} double precision" for c in QUARTERLY_COLS if c not in ("symbol", "report_date")
    )
    return f"""
CREATE TABLE "{schema}".fundamentals_current (
    symbol text PRIMARY KEY,
    {fund_cols},
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "{schema}".estimates_forward (
    symbol text NOT NULL,
    fy_period integer NOT NULL,
    {fwd_cols},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, fy_period)
);
CREATE TABLE "{schema}".quarterly (
    symbol text NOT NULL,
    report_date date NOT NULL,
    {q_cols},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, report_date)
);
CREATE TABLE "{schema}".estimate_revisions (
    symbol text NOT NULL,
    fy_period integer NOT NULL,
    metric text NOT NULL,
    asof date NOT NULL,
    mean_val double precision,
    high_val double precision,
    low_val double precision,
    n_est double precision,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, fy_period, metric, asof)
);
"""


# --------------------------------------------------------------------------- #
# upsert helper (impure)
# --------------------------------------------------------------------------- #
def _upsert(conn, schema: str, table: str, cols: List[str], pk: List[str], rows: List[Dict]) -> int:
    """Batch upsert `rows` into `<schema>.<table>` on conflict of `pk`.

    Returns the number of rows submitted. Uses psycopg2.extras.execute_values for
    one round-trip; non-PK columns are refreshed on conflict (idempotent re-run).
    """
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    qualified = f'"{schema}".{table}'
    col_list = ", ".join(cols)
    update_cols = [c for c in cols if c not in pk]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    conflict = ", ".join(pk)
    sql = (
        f"INSERT INTO {qualified} ({col_list}) VALUES %s "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
    )
    template = "(" + ", ".join(["%s"] * len(cols)) + ")"
    values = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        execute_values(cur, sql, values, template=template, page_size=1000)
    logger.debug("upsert %s: %d rows", table, len(rows))
    return len(rows)


# --------------------------------------------------------------------------- #
# load — the one entry point
# --------------------------------------------------------------------------- #
def load(
    pkl_path,
    conn_factory: ConnFactory,
    schema: str = DEFAULT_SCHEMA,
) -> Dict[str, int]:
    """Load `refinitiv_fundamentals.pkl` into `<schema>` (idempotent upsert).

    Parameters
    ----------
    pkl_path:
        Path to `refinitiv_fundamentals.pkl` (or a pre-loaded dict of frames).
    conn_factory:
        Zero-arg callable returning a fresh psycopg2 connection (DI seam).
    schema:
        Target schema (default `MKFund`; tests pass a disposable schema).

    Returns
    -------
    dict: per-table row counts written
        {"fundamentals_current": n, "estimates_forward": n, "quarterly": n,
         "estimate_revisions": n}.
    """
    if isinstance(pkl_path, dict):
        data = pkl_path
    else:
        with open(Path(pkl_path), "rb") as f:
            data = pickle.load(f)

    snapshot_rows = map_snapshot(data["snapshot"]) if "snapshot" in data else []
    forward_rows = map_estimates_forward(data.get("fy1"), data.get("fy2"))
    quarterly_rows = map_quarterly(data["quarterly"]) if "quarterly" in data else []
    revision_rows = map_estimate_revisions(data)

    conn = conn_factory()
    counts: Dict[str, int] = {}
    try:
        counts["fundamentals_current"] = _upsert(
            conn, schema, "fundamentals_current",
            FUNDAMENTALS_CURRENT_COLS, ["symbol"], snapshot_rows,
        )
        counts["estimates_forward"] = _upsert(
            conn, schema, "estimates_forward",
            ESTIMATES_FORWARD_COLS, ["symbol", "fy_period"], forward_rows,
        )
        counts["quarterly"] = _upsert(
            conn, schema, "quarterly",
            QUARTERLY_COLS, ["symbol", "report_date"], quarterly_rows,
        )
        counts["estimate_revisions"] = _upsert(
            conn, schema, "estimate_revisions",
            ESTIMATE_REVISIONS_COLS, ["symbol", "fy_period", "metric", "asof"], revision_rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.debug("load complete: %s", counts)
    return counts
