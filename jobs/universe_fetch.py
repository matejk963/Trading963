#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""universe_fetch.py — standalone, schedulable US-equity universe fetch job.

PURPOSE
=======
A single self-contained job that, each run:

  1. Reads the SEC master ticker list (``data/sec/company_tickers.json``),
     downloading it from sec.gov with a descriptive User-Agent if absent /
     invalid (SEC rejects requests without one).
  2. ADV-scans every candidate via **yfinance** batch download (last ~1 month
     of daily bars) and keeps the **valid universe** = tickers whose
     ``ADV_Dollar = mean(Close x Volume)`` over the last ``ADV_WINDOW_TD``
     trading rows is >= ``ADV_THRESHOLD_USD``. Optionally drops non-common-stock
     (ETF/fund) instruments via yfinance ``quoteType`` (toggle
     ``EXCLUDE_NON_EQUITY``), checked on the *valid* set only.
  3. Maintains a **universe registry** (``"MKPrices".universe``) — upserting
     NEW / EXISTING / DROPPED state. DROPPED symbols (were active, now below
     threshold) are marked ``active=false`` and are NOT fetched.
  4. For each valid symbol:
       a. **Prices** -> ``"MKPrices".daily_bar`` (raw OHLC + adj_close + volume)
          from yfinance (``auto_adjust=False``); Refinitiv ``rd.get_history``
          fallback on yfinance failure/empty. NEW -> full history
          (``period="max"``); EXISTING -> incremental from day after last stored.
       b. **Fundamentals** -> the existing ``"MKFund"`` schema (4 frames:
          snapshot / fy1+fy2 forward / quarterly / estimate_revisions) via
          Refinitiv ``rd.get_data``; upserted with vendored copies of the app's
          ``mkfund_loader`` DDL / ``map_*`` / ``_upsert`` so the schema stays
          identical to the running app.
       c. **ticker -> RIC** resolution: Refinitiv symbology conversion, else a
          suffix heuristic (``.O`` NASDAQ / ``.N`` NYSE / ``.A`` AMEX).

This file is COPIED INTO A DIFFERENT SCHEDULER REPO, therefore it has **zero
imports from the Trading963 repo** — every needed piece of app logic is vendored
(copied) in below (see "VENDORED FROM src/mktt/datasource/loaders/mkfund_loader.py").

WINDOWS / REFINITIV REQUIREMENT
===============================
Refinitiv parts require **Windows** with **Refinitiv Workspace** running (the
Workspace data proxy listens on localhost:9000). ``rd.open_session()`` needs no
key/config when Workspace is up. yfinance + Postgres run anywhere. On a host
without Workspace, run ``--prices-only`` (yfinance) and the fundamentals stage
is skipped/falls back.

CONFIG CONSTANTS (all overridable; env wins where noted)
========================================================
  MKTT_PG_DSN          (env) Postgres DSN.
                       default postgresql://postgres:postgres@10.123.0.9:5432/etc_db
  ADV_THRESHOLD_USD    Min average daily dollar volume to be "valid". default 500_000
  ADV_WINDOW_TD        Trailing trading rows for the ADV mean.        default 21
  PRICES_SCHEMA        Schema for universe + daily_bar.               default "MKPrices"
  FUND_SCHEMA          Schema for the MKFund fundamentals tables.     default "MKFund"
  EXCLUDE_NON_EQUITY   Drop non-EQUITY quoteType from the valid set.  default True
  YF_BATCH_SIZE        Tickers per yfinance batch download.           default 200
  YF_SCAN_PERIOD       yfinance period for the ADV scan.              default "1mo"
  MAX_RETRIES          Backoff retries for yfinance/Refinitiv calls.  default 4
  BACKOFF_BASE_SEC     Exponential backoff base (sec).                default 2.0
  BACKOFF_CAP_SEC      Backoff ceiling (sec).                         default 60.0
  SEC_TICKERS_URL      SEC master list URL.
  SEC_USER_AGENT       Descriptive UA (SEC requirement).
  SEC_TICKERS_PATH     Local cache path for the SEC list.
  CHECKPOINT_PATH      Resumable per-symbol checkpoint JSON.
  QUARTERLY_LOOKBACK_Q ~quarters of quarterly actuals to fetch.       default 24

CLI FLAGS
=========
  --scan-only          Compute ADV + upsert the universe registry only; no fetch.
  --dry-run            No DB writes; log intended actions.
  --limit N            Cap candidates (testing).
  --prices-only        Fetch prices only (skip fundamentals).
  --fundamentals-only  Fetch fundamentals only (skip prices).
  --self-test          Run pure-function unit checks and exit (no network/DB).

DB TABLES CREATED (idempotent, created if absent)
=================================================
  "MKPrices".universe(symbol text PK, first_seen date, last_adv double precision,
                      last_scanned date, active boolean)
  "MKPrices".daily_bar(symbol text, date date, open, high, low, close,
                       adj_close, volume, PK(symbol,date))
  "MKFund".fundamentals_current   (PK symbol)                 [vendored DDL]
  "MKFund".estimates_forward      (PK symbol, fy_period)      [vendored DDL]
  "MKFund".quarterly              (PK symbol, report_date)    [vendored DDL]
  "MKFund".estimate_revisions     (PK symbol, fy_period, metric, asof) [vendored]

DEPENDENCIES
============
  Python 3.9+ (tested 3.11)
  psycopg2 (psycopg2-binary)   — Postgres
  pandas                       — frame mapping / ADV math
  requests                     — SEC master-list download
  yfinance                     — prices + ADV scan + quoteType
  refinitiv-data               — fundamentals + price fallback (Windows/Workspace)

LOGGING
=======
Python ``logging``. Debug logging is OFF by default; enable with
``LOG_LEVEL=DEBUG`` or ``DEBUG=1`` in the environment. Credentials / the DSN
secret are never logged.

USAGE
=====
  python jobs/universe_fetch.py --self-test          # pure checks, no net/DB
  python jobs/universe_fetch.py --scan-only          # registry only
  python jobs/universe_fetch.py --limit 50 --dry-run # rehearse on 50 tickers
  python jobs/universe_fetch.py                       # full run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

# pandas is required for the ADV math and the vendored frame mappers. Keep the
# import at module level (the pure helpers need it); yfinance / refinitiv /
# psycopg2 are imported lazily inside the impure functions so --self-test and
# py_compile work without them.
import pandas as pd

# --------------------------------------------------------------------------- #
# CONFIG (all overridable; env wins where noted)
# --------------------------------------------------------------------------- #
DEFAULT_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"
MKTT_PG_DSN = os.environ.get("MKTT_PG_DSN") or DEFAULT_DSN

ADV_THRESHOLD_USD = 500_000
ADV_WINDOW_TD = 21

PRICES_SCHEMA = os.environ.get("MKTT_PRICES_SCHEMA", "MKPrices")
FUND_SCHEMA = os.environ.get("MKTT_FUND_SCHEMA", "MKFund")

EXCLUDE_NON_EQUITY = True

YF_BATCH_SIZE = 200
YF_SCAN_PERIOD = "1mo"

MAX_RETRIES = 4
BACKOFF_BASE_SEC = 2.0
BACKOFF_CAP_SEC = 60.0

QUARTERLY_LOOKBACK_Q = 24

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "Trading963 universe_fetch job (admin@energytrading.sk)",
)
SEC_TICKERS_PATH = os.environ.get(
    "SEC_TICKERS_PATH", str(Path("data") / "sec" / "company_tickers.json")
)
CHECKPOINT_PATH = os.environ.get("CHECKPOINT_PATH", "universe_fetch_checkpoint.json")

# --------------------------------------------------------------------------- #
# logging — off by default; LOG_LEVEL=DEBUG / DEBUG=1 turns it on. The DSN
# secret is never logged.
# --------------------------------------------------------------------------- #
logger = logging.getLogger("universe_fetch")


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "").upper()
    debug = level_name == "DEBUG" or os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    level = logging.DEBUG if debug else logging.INFO
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    logger.setLevel(level)


def _safe_dsn(dsn: str) -> str:
    """Redact the password component of a DSN for logging."""
    try:
        if "://" in dsn and "@" in dsn:
            scheme, rest = dsn.split("://", 1)
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
    except Exception:  # pragma: no cover - defensive
        pass
    return "***"


# =========================================================================== #
# VENDORED FROM src/mktt/datasource/loaders/mkfund_loader.py
# Copied faithfully so the MKFund schema stays identical to the running app.
# (coercers, the four _MAP tables, the *_COLS lists, the pure map_* functions,
#  ddl(), and _upsert().)
# =========================================================================== #
def _num(value) -> Optional[float]:
    """Coerce a single Refinitiv object/string numeric to float (or None)."""
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
    """Coerce to a python ``date`` (or None) for the DATE PK columns."""
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


# snapshot -> fundamentals_current (PK symbol). Order defines table column order.
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


# fy1/fy2 -> estimates_forward (PK symbol, fy_period)
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


# quarterly -> quarterly (PK symbol, report_date)
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


ESTIMATE_REVISIONS_COLS = [
    "symbol", "fy_period", "metric", "asof", "mean_val", "high_val", "low_val", "n_est"
]


def map_snapshot(snapshot: pd.DataFrame) -> List[Dict]:
    """snapshot frame -> fundamentals_current rows (one per symbol; last wins)."""
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
    """fy1/fy2 frames -> estimates_forward rows (fy_period 1 / 2)."""
    rows: List[Dict] = []
    if fy1 is not None:
        rows.extend(_map_forward_frame(fy1, 1))
    if fy2 is not None:
        rows.extend(_map_forward_frame(fy2, 2))
    logger.debug("map_estimates_forward: %d rows", len(rows))
    return rows


def map_quarterly(quarterly: pd.DataFrame) -> List[Dict]:
    """quarterly frame -> quarterly rows (PK symbol, report_date; last wins)."""
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
    return list(out.values())


def map_estimate_revisions(frames: Dict[str, pd.DataFrame]) -> List[Dict]:
    """trend_*/hist_est_* frames -> long-form estimate_revisions rows."""
    specs = [
        ("hist_est_fy1", "eps", 1, False),
        ("hist_est_fy2", "eps", 2, False),
        ("trend_eps_fy1", "eps", 1, True),
        ("trend_eps_fy2", "eps", 2, True),
        ("trend_rev_fy1", "rev", 1, True),
        ("trend_rev_fy2", "rev", 2, True),
    ]
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


def mkfund_ddl(schema: str) -> str:
    """Vendored copy of mkfund_loader.ddl — keeps MKFund schema-identical."""
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
CREATE TABLE IF NOT EXISTS "{schema}".fundamentals_current (
    symbol text PRIMARY KEY,
    {fund_cols},
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS "{schema}".estimates_forward (
    symbol text NOT NULL,
    fy_period integer NOT NULL,
    {fwd_cols},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, fy_period)
);
CREATE TABLE IF NOT EXISTS "{schema}".quarterly (
    symbol text NOT NULL,
    report_date date NOT NULL,
    {q_cols},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, report_date)
);
CREATE TABLE IF NOT EXISTS "{schema}".estimate_revisions (
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


def _upsert(conn, schema: str, table: str, cols: List[str], pk: List[str], rows: List[Dict]) -> int:
    """Vendored copy of mkfund_loader._upsert — batch ON CONFLICT upsert."""
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


# =========================================================================== #
# END VENDORED mkfund_loader section
# =========================================================================== #


# --------------------------------------------------------------------------- #
# PURE HELPERS (unit-tested by --self-test; no network / DB)
# --------------------------------------------------------------------------- #
def compute_adv_dollar(df: pd.DataFrame, window: int = ADV_WINDOW_TD) -> Optional[float]:
    """Average daily *dollar* volume over the last ``window`` trading rows.

    ``df`` is a per-ticker OHLCV frame with ``Close`` and ``Volume`` columns
    (yfinance shape). Returns ``mean(Close * Volume)`` over the trailing
    ``window`` rows with both values present, or ``None`` if there is no usable
    row. Rows with a NaN Close or Volume are dropped before the window is taken.
    """
    if df is None or df.empty:
        return None
    if "Close" not in df.columns or "Volume" not in df.columns:
        return None
    sub = df[["Close", "Volume"]].dropna()
    if sub.empty:
        return None
    dollar = (sub["Close"] * sub["Volume"]).tail(window)
    if dollar.empty:
        return None
    val = float(dollar.mean())
    if pd.isna(val):
        return None
    return val


def classify_universe_delta(prev_active: Set[str], valid_now: Set[str]) -> Dict[str, Set[str]]:
    """Partition symbols into NEW / EXISTING / DROPPED.

    NEW      = valid now and NOT previously active.
    EXISTING = valid now and previously active.
    DROPPED  = previously active but NOT valid now.
    """
    prev_active = set(prev_active)
    valid_now = set(valid_now)
    new = valid_now - prev_active
    existing = valid_now & prev_active
    dropped = prev_active - valid_now
    return {"new": new, "existing": existing, "dropped": dropped}


def ticker_to_ric(ticker: str, exchange: Optional[str] = None) -> Optional[str]:
    """Resolve a plain ticker to a Refinitiv RIC via a suffix heuristic.

    ``exchange`` (when known) selects the suffix; otherwise NASDAQ ``.O`` is the
    pragmatic default for US common stock. Class-share dots (``BRK.B``) are
    normalized to the RIC convention (``BRK.B`` -> ``BRKb`` + suffix). Returns
    ``None`` for an empty/invalid ticker.

    NB: this is the *fallback*. The live job tries the Refinitiv symbology
    conversion first (see ``resolve_ric``) and only falls back to this heuristic.
    """
    if not ticker or not isinstance(ticker, str):
        return None
    t = ticker.strip().upper()
    if not t:
        return None
    # Already a RIC (carries a known suffix)?
    for suf in (".O", ".N", ".A", ".OQ", ".K"):
        if t.endswith(suf):
            return t

    exch = (exchange or "").strip().upper()
    suffix_by_exchange = {
        "NASDAQ": ".O", "NMS": ".O", "NCM": ".O", "NGM": ".O", "NASDAQGS": ".O",
        "NYSE": ".N", "NYQ": ".N", "NYE": ".N",
        "AMEX": ".A", "ASE": ".A", "AMX": ".A", "NYSEAMERICAN": ".A",
    }
    suffix = suffix_by_exchange.get(exch, ".O")

    # Class shares: "BRK.B" -> RIC root "BRKb" (lower-case class letter, no dot).
    if "." in t:
        root, cls = t.rsplit(".", 1)
        if len(cls) == 1 and cls.isalpha():
            return f"{root}{cls.lower()}{suffix}"
    return f"{t}{suffix}"


def parse_sec_tickers(data: dict) -> List[str]:
    """Extract the ticker list from the SEC company_tickers.json structure.

    Shape: ``{ "0": {"cik_str":.., "ticker":"AAPL", "title":..}, ... }``.
    De-duplicates preserving first-seen order; skips blank/missing tickers.
    """
    out: List[str] = []
    seen: Set[str] = set()
    if not isinstance(data, dict):
        return out
    for _key, rec in data.items():
        if not isinstance(rec, dict):
            continue
        tic = rec.get("ticker")
        if not tic or not isinstance(tic, str):
            continue
        sym = tic.strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def incremental_start(last_stored: Optional[date]) -> Optional[str]:
    """yfinance ``start`` for an incremental fetch = day after ``last_stored``.

    Returns an ISO ``YYYY-MM-DD`` string, or ``None`` when there is no stored
    bar (-> caller fetches full history with ``period="max"``).
    """
    if last_stored is None:
        return None
    from datetime import timedelta

    return (last_stored + timedelta(days=1)).isoformat()


def map_price_frame(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """yfinance OHLCV frame (``auto_adjust=False``) -> daily_bar rows.

    Expects TitleCase columns ``Open/High/Low/Close/Adj Close/Volume`` indexed by
    date. Drops rows with no usable close. ``adj_close`` falls back to ``close``
    when ``Adj Close`` is absent.
    """
    if df is None or df.empty:
        return []
    cols = {c.lower(): c for c in df.columns}
    rows: List[Dict] = []
    out: Dict[date, Dict] = {}
    for idx, rec in df.iterrows():
        d = _date(idx)
        if d is None:
            continue
        close = _num(rec.get(cols.get("close")))
        if close is None:
            continue
        adj = _num(rec.get(cols.get("adj close"))) if "adj close" in cols else None
        out[d] = {
            "symbol": symbol,
            "date": d,
            "open": _num(rec.get(cols.get("open"))),
            "high": _num(rec.get(cols.get("high"))),
            "low": _num(rec.get(cols.get("low"))),
            "close": close,
            "adj_close": adj if adj is not None else close,
            "volume": _num(rec.get(cols.get("volume"))),
        }
    rows = list(out.values())
    logger.debug("map_price_frame %s: %d rows", symbol, len(rows))
    return rows


DAILY_BAR_COLS = ["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]
UNIVERSE_COLS = ["symbol", "first_seen", "last_adv", "last_scanned", "active"]


def prices_ddl(schema: str) -> str:
    """DDL for the MKPrices universe + daily_bar tables (created if absent)."""
    return f"""
CREATE SCHEMA IF NOT EXISTS "{schema}";
CREATE TABLE IF NOT EXISTS "{schema}".universe (
    symbol text PRIMARY KEY,
    first_seen date,
    last_adv double precision,
    last_scanned date,
    active boolean
);
CREATE TABLE IF NOT EXISTS "{schema}".daily_bar (
    symbol text NOT NULL,
    date date NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    adj_close double precision,
    volume double precision,
    PRIMARY KEY (symbol, date)
);
"""


# --------------------------------------------------------------------------- #
# CHECKPOINT (resumable per-symbol status) — small JSON file.
# --------------------------------------------------------------------------- #
def _today_key() -> str:
    return date.today().isoformat()


def load_checkpoint(path: str = CHECKPOINT_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {"run_day": _today_key(), "symbols": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.warning("checkpoint unreadable, starting fresh: %s", path)
        return {"run_day": _today_key(), "symbols": {}}
    # New day -> fresh checkpoint (don't skip yesterday's symbols today).
    if data.get("run_day") != _today_key():
        return {"run_day": _today_key(), "symbols": {}}
    data.setdefault("symbols", {})
    return data


def save_checkpoint(ckpt: dict, path: str = CHECKPOINT_PATH) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ckpt, f, indent=2, sort_keys=True)
    tmp.replace(path)


def checkpoint_done(ckpt: dict, symbol: str, stage: str) -> bool:
    return bool(ckpt.get("symbols", {}).get(symbol, {}).get(stage))


def checkpoint_mark(ckpt: dict, symbol: str, stage: str, status: str = "done") -> None:
    ckpt.setdefault("symbols", {}).setdefault(symbol, {})[stage] = status


# --------------------------------------------------------------------------- #
# BACKOFF — exponential with jitter, used by the impure yfinance/Refinitiv calls.
# --------------------------------------------------------------------------- #
def with_backoff(fn: Callable, *args, what: str = "call", retries: int = MAX_RETRIES, **kwargs):
    """Call ``fn`` with exponential backoff on exception. Re-raises last error."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — best-effort retry boundary
            last_exc = exc
            delay = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** attempt))
            delay += random.uniform(0, delay * 0.25)
            logger.warning("%s failed (attempt %d/%d): %s; backoff %.1fs",
                           what, attempt + 1, retries, exc, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


# --------------------------------------------------------------------------- #
# IMPURE: SEC master list
# --------------------------------------------------------------------------- #
def _looks_like_ticker_json(text: str) -> bool:
    """Cheap guard: is this real SEC JSON (object with a ticker), not an error page?"""
    t = text.lstrip()
    if not t.startswith("{"):
        return False
    try:
        data = json.loads(text)
    except Exception:
        return False
    return len(parse_sec_tickers(data)) > 0


def load_or_download_sec_tickers(path: str = SEC_TICKERS_PATH,
                                 url: str = SEC_TICKERS_URL,
                                 user_agent: str = SEC_USER_AGENT) -> List[str]:
    """Read the SEC master list, (re)downloading with a UA when absent/invalid."""
    p = Path(path)
    if p.exists():
        try:
            text = p.read_text(encoding="utf-8")
            if _looks_like_ticker_json(text):
                tickers = parse_sec_tickers(json.loads(text))
                logger.info("SEC tickers loaded from cache: %d", len(tickers))
                return tickers
            logger.warning("SEC cache present but not valid ticker JSON; re-downloading")
        except Exception as exc:
            logger.warning("SEC cache unreadable (%s); re-downloading", exc)

    import requests  # lazy

    logger.info("downloading SEC tickers from %s", url)
    resp = with_backoff(
        requests.get, url, headers={"User-Agent": user_agent}, timeout=30,
        what="sec-download",
    )
    resp.raise_for_status()
    text = resp.text
    if not _looks_like_ticker_json(text):
        raise RuntimeError("SEC download did not return valid ticker JSON")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    tickers = parse_sec_tickers(json.loads(text))
    logger.info("SEC tickers downloaded: %d", len(tickers))
    return tickers


# --------------------------------------------------------------------------- #
# IMPURE: yfinance ADV scan + prices + quoteType
# --------------------------------------------------------------------------- #
def _yf():
    import yfinance as yf  # lazy
    return yf


def _per_ticker_frame(batch_df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Slice one ticker's OHLCV frame out of a yfinance batch-download frame.

    yfinance multi-ticker frames are column-MultiIndex; the field/ticker level
    order varies by version, so handle both.
    """
    if batch_df is None or batch_df.empty:
        return None
    if not isinstance(batch_df.columns, pd.MultiIndex):
        # single ticker download already returns flat columns
        return batch_df
    lvl0 = batch_df.columns.get_level_values(0)
    lvl1 = batch_df.columns.get_level_values(1)
    if ticker in set(lvl0):
        sub = batch_df.xs(ticker, axis=1, level=0)
    elif ticker in set(lvl1):
        sub = batch_df.xs(ticker, axis=1, level=1)
    else:
        return None
    return sub.dropna(how="all")


def adv_scan(candidates: Sequence[str],
             batch_size: int = YF_BATCH_SIZE,
             period: str = YF_SCAN_PERIOD,
             window: int = ADV_WINDOW_TD,
             threshold: float = ADV_THRESHOLD_USD) -> Dict[str, float]:
    """Batch-download ~1mo of bars and return {ticker: ADV_Dollar} for valid ones.

    Only tickers with ADV_Dollar >= ``threshold`` are returned. yfinance is
    imported lazily; each batch is retried with backoff.
    """
    yf = _yf()
    valid: Dict[str, float] = {}
    cand = list(candidates)
    for i in range(0, len(cand), batch_size):
        batch = cand[i:i + batch_size]
        logger.debug("adv_scan batch %d..%d (%d)", i, i + len(batch), len(batch))
        df = with_backoff(
            yf.download, batch, period=period, interval="1d",
            group_by="ticker", auto_adjust=False, threads=True, progress=False,
            what="yf.download(scan)",
        )
        for t in batch:
            sub = _per_ticker_frame(df, t)
            adv = compute_adv_dollar(sub, window=window) if sub is not None else None
            if adv is not None and adv >= threshold:
                valid[t] = adv
    logger.info("adv_scan: %d/%d candidates valid (>= $%s)", len(valid), len(cand), threshold)
    return valid


def filter_non_equity(symbols: Sequence[str]) -> Set[str]:
    """Return the subset of ``symbols`` whose yfinance quoteType == 'EQUITY'.

    Checked on the (small) valid set only. A lookup failure keeps the symbol
    (best-effort: never silently drop on a transient error).
    """
    yf = _yf()
    keep: Set[str] = set()
    for sym in symbols:
        try:
            info = yf.Ticker(sym).get_info()
            qt = (info or {}).get("quoteType", "")
            if str(qt).upper() == "EQUITY":
                keep.add(sym)
            else:
                logger.debug("excluding non-equity %s (quoteType=%s)", sym, qt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("quoteType lookup failed for %s (%s); keeping", sym, exc)
            keep.add(sym)
    return keep


def fetch_prices_yf(symbol: str, start: Optional[str]) -> List[Dict]:
    """yfinance raw OHLC + adj_close for one symbol -> daily_bar rows.

    ``start=None`` -> full history (``period="max"``); else incremental from
    ``start``. Returns [] on empty (caller then tries the Refinitiv fallback).
    """
    yf = _yf()
    if start is None:
        df = with_backoff(yf.download, symbol, period="max", interval="1d",
                          auto_adjust=False, progress=False, what=f"yf.download(max,{symbol})")
    else:
        df = with_backoff(yf.download, symbol, start=start, interval="1d",
                          auto_adjust=False, progress=False, what=f"yf.download({start},{symbol})")
    if isinstance(df.columns, pd.MultiIndex):
        df = _per_ticker_frame(df, symbol)
    return map_price_frame(df, symbol)


# --------------------------------------------------------------------------- #
# IMPURE: Refinitiv (Windows / Workspace) — prices fallback + fundamentals
# --------------------------------------------------------------------------- #
def _rd():
    import refinitiv.data as rd  # lazy — Windows/Workspace only
    return rd


def resolve_ric(rd, ticker: str, exchange: Optional[str] = None) -> Optional[str]:
    """ticker -> RIC: try Refinitiv symbology conversion, else suffix heuristic."""
    try:
        from refinitiv.data import symbology
        res = symbology.convert(symbols=[ticker], from_symbol_type="ticker", to_symbol_type="RIC")
        if res is not None and not res.empty:
            ric = res.iloc[0].get("RIC")
            if isinstance(ric, str) and ric.strip():
                return ric.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("symbology.convert failed for %s (%s); heuristic", ticker, exc)
    ric = ticker_to_ric(ticker, exchange)
    if ric is None:
        logger.warning("unresolved ticker->RIC: %s", ticker)
    return ric


_RD_PRICE_FIELD_MAP = {
    "OPEN_PRC": "open", "HIGH_1": "high", "LOW_1": "low",
    "TRDPRC_1": "close", "ACVOL_UNS": "volume",
}


def fetch_prices_refinitiv(rd, ric: str, symbol: str, start: Optional[str]) -> List[Dict]:
    """Refinitiv ``rd.get_history`` fallback -> daily_bar rows.

    Refinitiv returns raw OHLC (no adjusted close field here), so ``adj_close``
    mirrors ``close``. ``start=None`` -> a long lookback for full history.
    """
    kwargs = dict(universe=ric, interval="daily")
    kwargs["start"] = start if start else "1990-01-01"
    df = with_backoff(rd.get_history, what=f"rd.get_history({ric})", **kwargs)
    if df is None or df.empty:
        return []
    df = df.rename(columns=_RD_PRICE_FIELD_MAP)
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    df = df[keep].copy()
    if "close" in df.columns:
        df["Adj Close"] = df["close"]
    df.columns = [c.title() if c != "Adj Close" else c for c in df.columns]
    return map_price_frame(df, symbol)


# Refinitiv field -> snapshot source column (the names mkfund_loader maps).
_RD_SNAPSHOT_FIELDS = [
    ("TR.EPSActValue", "Earnings Per Share - Actual"),
    ("TR.EPSMean", "Earnings Per Share - Mean"),
    ("TR.EPSSmartEst", "Earnings Per Share - SmartEstimate®"),
    ("TR.RevenueActValue", "Revenue - Actual"),
    ("TR.RevenueMean", "Revenue - Mean"),
    ("TR.OperatingMargin", "Operating Margin, Percent"),
    ("TR.NetProfitMargin", "Net Profit Margin, (%)"),
    ("TR.GrossProfit", "Gross Profit"),
    ("TR.EBITDA", "EBITDA"),
    ("TR.OperatingIncome", "Operating Income"),
    ("TR.NetIncome", "Net Income Incl Extra Before Distributions"),
    ("TR.FreeCashFlow", "Free Cash Flow"),
    ("TR.TotalDebt", "Total Debt"),
    ("TR.NetDebt", "Net Debt Incl. Pref.Stock & Min.Interest"),
    ("TR.CashAndSTInvestments", "Cash and Short Term Investments"),
    ("TR.TotalAssets", "Total Assets"),
    ("TR.TotalEquity", "Total Equity"),
    ("TR.CurrentRatio", "Current Ratio"),
    ("TR.QuickRatio", "Quick Ratio"),
    ("TR.ReturnOnCapitalPercent", "Return on Capital, Total LT Capital, Percent"),
    ("TR.EVToEBITDA", "Enterprise Value To EBITDA (Daily Time Series Ratio)"),
    ("TR.EVToSales", "Enterprise Value To Sales (Daily Time Series Ratio)"),
    ("TR.EV", "Enterprise Value (Daily Time Series)"),
    ("TR.DPSActValue", "Dividend Per Share - Actual"),
    ("TR.SharesOutstanding", "Outstanding Shares"),
    ("TR.PriceTargetMean", "Price Target - Mean"),
    ("TR.NumberOfAnalysts", "Number of Analysts"),
    ("TR.GICSSector", "GICS Sector Name"),
    ("TR.GICSIndustry", "GICS Industry Name"),
]


def fetch_fundamentals_refinitiv(rd, ric: str, symbol: str,
                                 lookback_q: int = QUARTERLY_LOOKBACK_Q) -> Dict[str, pd.DataFrame]:
    """Build the four-frame dict ``mkfund_loader.load`` consumes, for one RIC.

    Returns a dict with keys: ``snapshot``, ``fy1``, ``fy2``, ``quarterly``,
    and the ``trend_*`` / ``hist_est_*`` revision frames. Each frame carries a
    ``Symbol`` column set to the plain ``symbol`` (not the RIC) so the vendored
    mappers key the MKFund tables on the app's symbol convention.
    """
    frames: Dict[str, pd.DataFrame] = {}

    def _tag(df: pd.DataFrame) -> pd.DataFrame:
        if df is None:
            return pd.DataFrame()
        df = df.copy()
        df["Symbol"] = symbol
        return df

    # snapshot
    snap_fields = [f for (f, _label) in _RD_SNAPSHOT_FIELDS]
    snap = with_backoff(rd.get_data, ric, snap_fields, what=f"rd.get_data(snapshot,{ric})")
    if snap is not None and not snap.empty:
        rename = {}
        # rd returns human-readable labels already matching the source names; if it
        # returns the TR.* codes, map them to the loader's expected labels.
        for fld, label in _RD_SNAPSHOT_FIELDS:
            if fld in snap.columns:
                rename[fld] = label
        snap = snap.rename(columns=rename)
    frames["snapshot"] = _tag(snap)

    # fy1 / fy2 forward estimates
    fwd_fields = [
        "TR.EPSMean", "TR.EPSHigh", "TR.EPSLow", "TR.EPSSmartEst", "TR.EPSNumOfEst",
        "TR.RevenueMean", "TR.RevenueHigh", "TR.RevenueLow",
        "TR.EBITDAMean", "TR.EBITDASmartEst", "TR.CapitalExpenditureMean",
        "TR.CashFlowPerShareMean", "TR.DPSMean",
    ]
    fwd_labels = {
        "TR.EPSMean": "Earnings Per Share - Mean", "TR.EPSHigh": "Earnings Per Share - High",
        "TR.EPSLow": "Earnings Per Share - Low",
        "TR.EPSSmartEst": "Earnings Per Share - SmartEstimate®",
        "TR.EPSNumOfEst": "EPS Number of Estimates",
        "TR.RevenueMean": "Revenue - Mean", "TR.RevenueHigh": "Revenue - High",
        "TR.RevenueLow": "Revenue - Low", "TR.EBITDAMean": "EBITDA - Mean",
        "TR.EBITDASmartEst": "EBITDA - SmartEstimate®",
        "TR.CapitalExpenditureMean": "Capital Expenditures - Mean",
        "TR.CashFlowPerShareMean": "Cash Flow Per Share - Mean",
        "TR.DPSMean": "Dividend Per Share - Mean",
    }
    for fy, period in (("fy1", "FY1"), ("fy2", "FY2")):
        df = with_backoff(rd.get_data, ric, fwd_fields, parameters={"Period": period},
                          what=f"rd.get_data({period},{ric})")
        if df is not None and not df.empty:
            df = df.rename(columns={k: v for k, v in fwd_labels.items() if k in df.columns})
        frames[fy] = _tag(df)

    # quarterly actuals (~lookback_q quarters back)
    q_fields = [
        "TR.EPSActValue", "TR.EPSMeanEstimate", "TR.RevenueActValue", "TR.RevenueMeanEstimate",
        "TR.OperatingMargin", "TR.NetProfitMargin", "TR.FreeCashFlow", "TR.TotalDebt",
        "TR.NetDebt", "TR.CashAndSTInvestments", "TR.CurrentRatio", "TR.EPSActValue.date",
    ]
    q_labels = {
        "TR.EPSActValue": "Earnings Per Share - Actual",
        "TR.EPSMeanEstimate": "Earnings Per Share - Mean Estimate",
        "TR.RevenueActValue": "Revenue - Actual",
        "TR.RevenueMeanEstimate": "Revenue - Mean Estimate",
        "TR.OperatingMargin": "Operating Margin, Percent",
        "TR.NetProfitMargin": "Net Profit Margin, (%)",
        "TR.FreeCashFlow": "Free Cash Flow", "TR.TotalDebt": "Total Debt",
        "TR.NetDebt": "Net Debt Incl. Pref.Stock & Min.Interest",
        "TR.CashAndSTInvestments": "Cash and Short Term Investments",
        "TR.CurrentRatio": "Current Ratio", "Date": "Date",
    }
    qdf = with_backoff(
        rd.get_data, ric, q_fields,
        parameters={"SDate": "0", "EDate": f"-{lookback_q - 1}", "Period": "FQ0", "Frq": "FQ"},
        what=f"rd.get_data(quarterly,{ric})",
    )
    if qdf is not None and not qdf.empty:
        qdf = qdf.rename(columns={k: v for k, v in q_labels.items() if k in qdf.columns})
    frames["quarterly"] = _tag(qdf)

    # estimate revision trends (FY1/FY2 EPS & Rev mean over time, with date)
    for key, fields, period in (
        ("trend_eps_fy1", ["TR.EPSMean", "TR.EPSHigh", "TR.EPSLow", "TR.EPSNumOfEst", "TR.EPSMean.date"], "FY1"),
        ("trend_eps_fy2", ["TR.EPSMean", "TR.EPSHigh", "TR.EPSLow", "TR.EPSNumOfEst", "TR.EPSMean.date"], "FY2"),
        ("trend_rev_fy1", ["TR.RevenueMean", "TR.RevenueHigh", "TR.RevenueLow", "TR.RevenueMean.date"], "FY1"),
        ("trend_rev_fy2", ["TR.RevenueMean", "TR.RevenueHigh", "TR.RevenueLow", "TR.RevenueMean.date"], "FY2"),
    ):
        df = with_backoff(
            rd.get_data, ric, fields,
            parameters={"SDate": "0", "EDate": "-23", "Period": period, "Frq": "FQ"},
            what=f"rd.get_data({key},{ric})",
        )
        if df is not None and not df.empty:
            ren = {
                "TR.EPSMean": "Earnings Per Share - Mean", "TR.EPSHigh": "Earnings Per Share - High",
                "TR.EPSLow": "Earnings Per Share - Low", "TR.EPSNumOfEst": "EPS Number of Estimates",
                "TR.RevenueMean": "Revenue - Mean", "TR.RevenueHigh": "Revenue - High",
                "TR.RevenueLow": "Revenue - Low",
            }
            df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
        frames[key] = _tag(df)

    return frames


# --------------------------------------------------------------------------- #
# IMPURE: Postgres registry I/O
# --------------------------------------------------------------------------- #
def _connect():
    import psycopg2  # lazy
    return psycopg2.connect(MKTT_PG_DSN)


def ensure_schemas(conn) -> None:
    """Create MKPrices + MKFund schemas/tables if absent (idempotent DDL)."""
    with conn.cursor() as cur:
        cur.execute(prices_ddl(PRICES_SCHEMA))
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{FUND_SCHEMA}";')
        cur.execute(mkfund_ddl(FUND_SCHEMA))
    conn.commit()


def read_active_symbols(conn) -> Set[str]:
    with conn.cursor() as cur:
        cur.execute(f'SELECT symbol FROM "{PRICES_SCHEMA}".universe WHERE active = true')
        return {r[0] for r in cur.fetchall()}


def read_last_bar_dates(conn, symbols: Sequence[str]) -> Dict[str, date]:
    if not symbols:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT symbol, max(date) FROM "{PRICES_SCHEMA}".daily_bar '
            f'WHERE symbol = ANY(%s) GROUP BY symbol',
            (list(symbols),),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def upsert_universe(conn, rows: List[Dict]) -> int:
    return _upsert(conn, PRICES_SCHEMA, "universe", UNIVERSE_COLS, ["symbol"], rows)


def upsert_daily_bars(conn, rows: List[Dict]) -> int:
    return _upsert(conn, PRICES_SCHEMA, "daily_bar", DAILY_BAR_COLS, ["symbol", "date"], rows)


def upsert_fundamentals(conn, frames: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    snap_rows = map_snapshot(frames["snapshot"]) if "snapshot" in frames else []
    fwd_rows = map_estimates_forward(frames.get("fy1"), frames.get("fy2"))
    q_rows = map_quarterly(frames["quarterly"]) if "quarterly" in frames else []
    rev_rows = map_estimate_revisions(frames)
    counts["fundamentals_current"] = _upsert(conn, FUND_SCHEMA, "fundamentals_current",
                                             FUNDAMENTALS_CURRENT_COLS, ["symbol"], snap_rows)
    counts["estimates_forward"] = _upsert(conn, FUND_SCHEMA, "estimates_forward",
                                          ESTIMATES_FORWARD_COLS, ["symbol", "fy_period"], fwd_rows)
    counts["quarterly"] = _upsert(conn, FUND_SCHEMA, "quarterly",
                                  QUARTERLY_COLS, ["symbol", "report_date"], q_rows)
    counts["estimate_revisions"] = _upsert(conn, FUND_SCHEMA, "estimate_revisions",
                                           ESTIMATE_REVISIONS_COLS,
                                           ["symbol", "fy_period", "metric", "asof"], rev_rows)
    return counts


def build_universe_rows(delta: Dict[str, Set[str]],
                        adv: Dict[str, float],
                        prev_active: Set[str],
                        scanned_on: date) -> List[Dict]:
    """Universe registry rows for NEW/EXISTING (active) + DROPPED (inactive).

    NEW rows get ``first_seen = scanned_on``; the upsert leaves ``first_seen`` of
    EXISTING/DROPPED rows untouched because ``first_seen`` is omitted from those
    rows (it is not in the update set when we don't supply it... — see note).
    Here we always supply ``first_seen`` only for NEW; for EXISTING/DROPPED we
    leave it None so the column is refreshed to NULL — to avoid clobbering it we
    instead rely on a COALESCE-style merge handled in ``upsert_universe_merge``.
    """
    rows: List[Dict] = []
    for sym in sorted(delta["new"]):
        rows.append({"symbol": sym, "first_seen": scanned_on,
                     "last_adv": adv.get(sym), "last_scanned": scanned_on, "active": True})
    for sym in sorted(delta["existing"]):
        rows.append({"symbol": sym, "first_seen": None,
                     "last_adv": adv.get(sym), "last_scanned": scanned_on, "active": True})
    for sym in sorted(delta["dropped"]):
        rows.append({"symbol": sym, "first_seen": None,
                     "last_adv": None, "last_scanned": scanned_on, "active": False})
    return rows


def upsert_universe_merge(conn, rows: List[Dict]) -> int:
    """Upsert universe rows, preserving existing first_seen when not supplied.

    ``first_seen`` is only set on NEW rows; for EXISTING/DROPPED it is NULL in the
    payload and we COALESCE so the original first_seen is preserved.
    """
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    sql = (
        f'INSERT INTO "{PRICES_SCHEMA}".universe '
        f'(symbol, first_seen, last_adv, last_scanned, active) VALUES %s '
        f'ON CONFLICT (symbol) DO UPDATE SET '
        f'first_seen = COALESCE("{PRICES_SCHEMA}".universe.first_seen, EXCLUDED.first_seen), '
        f'last_adv = EXCLUDED.last_adv, '
        f'last_scanned = EXCLUDED.last_scanned, '
        f'active = EXCLUDED.active'
    )
    values = [(r["symbol"], r["first_seen"], r["last_adv"], r["last_scanned"], r["active"]) for r in rows]
    with conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=1000)
    return len(rows)


# --------------------------------------------------------------------------- #
# ORCHESTRATION
# --------------------------------------------------------------------------- #
def run(args) -> int:
    _configure_logging()
    logger.info("universe_fetch start dsn=%s schemas=%s/%s dry_run=%s scan_only=%s",
                _safe_dsn(MKTT_PG_DSN), PRICES_SCHEMA, FUND_SCHEMA, args.dry_run, args.scan_only)

    # 1. master list
    candidates = load_or_download_sec_tickers()
    if args.limit:
        candidates = candidates[: args.limit]
        logger.info("limited to %d candidates", len(candidates))

    # 2. ADV scan
    adv = adv_scan(candidates)
    valid_now = set(adv)

    # 2b. optional non-equity exclusion (valid set only)
    if EXCLUDE_NON_EQUITY and valid_now:
        equities = filter_non_equity(sorted(valid_now))
        dropped_ne = valid_now - equities
        if dropped_ne:
            logger.info("excluded %d non-equity instruments", len(dropped_ne))
        valid_now = equities
        adv = {k: v for k, v in adv.items() if k in valid_now}

    # 3. registry delta (needs DB read for prev_active)
    if args.dry_run:
        prev_active: Set[str] = set()
        conn = None
    else:
        conn = _connect()
        ensure_schemas(conn)
        prev_active = read_active_symbols(conn)

    delta = classify_universe_delta(prev_active, valid_now)
    logger.info("delta: new=%d existing=%d dropped=%d",
                len(delta["new"]), len(delta["existing"]), len(delta["dropped"]))

    scanned_on = date.today()
    universe_rows = build_universe_rows(delta, adv, prev_active, scanned_on)
    if args.dry_run:
        logger.info("[dry-run] would upsert %d universe rows", len(universe_rows))
    else:
        upsert_universe_merge(conn, universe_rows)
        conn.commit()

    if args.scan_only:
        logger.info("scan-only: registry updated, skipping fetch")
        if conn:
            conn.close()
        return 0

    # 4. per-symbol fetch (NEW + EXISTING)
    to_fetch = sorted(delta["new"] | delta["existing"])
    ckpt = load_checkpoint()
    last_bar = {} if (args.dry_run or conn is None) else read_last_bar_dates(conn, to_fetch)

    rd_session = None
    do_prices = not args.fundamentals_only
    do_fund = not args.prices_only

    for sym in to_fetch:
        is_new = sym in delta["new"]
        # ----- prices -----
        if do_prices and not checkpoint_done(ckpt, sym, "prices"):
            try:
                start = None if is_new else incremental_start(last_bar.get(sym))
                rows = []
                try:
                    rows = fetch_prices_yf(sym, start)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("yfinance prices failed for %s (%s); Refinitiv fallback", sym, exc)
                if not rows:  # yfinance empty/rate-limited -> Refinitiv fallback (any mode)
                    rd_session = rd_session or _open_rd()
                    if rd_session is not None:
                        ric = resolve_ric(rd_session, sym)
                        if ric:
                            rows = fetch_prices_refinitiv(rd_session, ric, sym, start)
                if args.dry_run:
                    logger.info("[dry-run] %s prices: %d rows", sym, len(rows))
                else:
                    upsert_daily_bars(conn, rows)
                    conn.commit()
                    checkpoint_mark(ckpt, sym, "prices")
                    save_checkpoint(ckpt)
            except Exception as exc:  # noqa: BLE001
                logger.error("prices stage failed for %s: %s", sym, exc)

        # ----- fundamentals -----
        if do_fund and not checkpoint_done(ckpt, sym, "fundamentals"):
            try:
                rd_session = rd_session or _open_rd()
                if rd_session is None:
                    logger.debug("no Refinitiv session; skipping fundamentals for %s", sym)
                else:
                    ric = resolve_ric(rd_session, sym)
                    if not ric:
                        logger.warning("no RIC for %s; skipping fundamentals", sym)
                    else:
                        frames = fetch_fundamentals_refinitiv(rd_session, ric, sym)
                        if args.dry_run:
                            logger.info("[dry-run] %s fundamentals frames: %s",
                                        sym, {k: (0 if v is None else len(v)) for k, v in frames.items()})
                        else:
                            upsert_fundamentals(conn, frames)
                            conn.commit()
                            checkpoint_mark(ckpt, sym, "fundamentals")
                            save_checkpoint(ckpt)
            except Exception as exc:  # noqa: BLE001
                logger.error("fundamentals stage failed for %s: %s", sym, exc)

    if rd_session is not None:
        try:
            rd_session.close_session()
        except Exception:  # noqa: BLE001
            pass
    if conn:
        conn.close()
    logger.info("universe_fetch done: %d symbols processed", len(to_fetch))
    return 0


def _open_rd():
    """Open a Refinitiv session (Windows/Workspace). None if unavailable."""
    try:
        rd = _rd()
        rd.open_session()
        return rd
    except Exception as exc:  # noqa: BLE001
        logger.warning("Refinitiv session unavailable (%s); Refinitiv stages skipped", exc)
        return None


# --------------------------------------------------------------------------- #
# SELF-TEST (pure functions only; no network / DB)
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    _configure_logging()
    failures: List[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    print("compute_adv_dollar")
    df = pd.DataFrame({"Close": [10.0, 11.0, 12.0], "Volume": [100, 100, 100]})
    # mean of [1000, 1100, 1200] = 1100
    check("mean of close*volume", compute_adv_dollar(df, window=3) == 1100.0,
          f"got {compute_adv_dollar(df, window=3)}")
    # window truncation: last 2 rows -> mean([1100,1200]) = 1150
    check("window truncation", compute_adv_dollar(df, window=2) == 1150.0,
          f"got {compute_adv_dollar(df, window=2)}")
    check("empty -> None", compute_adv_dollar(pd.DataFrame()) is None)
    check("missing cols -> None", compute_adv_dollar(pd.DataFrame({"X": [1]})) is None)
    df_na = pd.DataFrame({"Close": [10.0, float("nan"), 12.0], "Volume": [100, 100, 100]})
    # dropna -> rows 0 and 2 -> mean([1000, 1200]) = 1100
    check("NaN rows dropped", compute_adv_dollar(df_na, window=3) == 1100.0,
          f"got {compute_adv_dollar(df_na, window=3)}")

    print("classify_universe_delta")
    d = classify_universe_delta({"A", "B", "C"}, {"B", "C", "D"})
    check("new", d["new"] == {"D"}, f"got {d['new']}")
    check("existing", d["existing"] == {"B", "C"}, f"got {d['existing']}")
    check("dropped", d["dropped"] == {"A"}, f"got {d['dropped']}")
    d2 = classify_universe_delta(set(), {"X"})
    check("all-new when no prev", d2["new"] == {"X"} and not d2["dropped"])
    d3 = classify_universe_delta({"Y"}, set())
    check("all-dropped when none valid", d3["dropped"] == {"Y"} and not d3["new"])

    print("ticker_to_ric")
    check("nasdaq default", ticker_to_ric("AAPL") == "AAPL.O", ticker_to_ric("AAPL"))
    check("nyse exchange", ticker_to_ric("JPM", "NYSE") == "JPM.N", ticker_to_ric("JPM", "NYSE"))
    check("amex exchange", ticker_to_ric("UAMY", "AMEX") == "UAMY.A", ticker_to_ric("UAMY", "AMEX"))
    check("yfinance exch code NMS", ticker_to_ric("MSFT", "NMS") == "MSFT.O")
    check("class share", ticker_to_ric("BRK.B", "NYSE") == "BRKb.N", ticker_to_ric("BRK.B", "NYSE"))
    check("already a ric passthrough", ticker_to_ric("EOG.N") == "EOG.N")
    check("empty -> None", ticker_to_ric("") is None)
    check("none -> None", ticker_to_ric(None) is None)

    print("parse_sec_tickers")
    sec = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
        "2": {"cik_str": 1, "ticker": "aapl", "title": "dup lowercase"},
        "3": {"cik_str": 2, "ticker": "", "title": "blank"},
    }
    parsed = parse_sec_tickers(sec)
    check("extracts + dedupes + uppercases", parsed == ["AAPL", "MSFT"], f"got {parsed}")
    check("not-a-dict -> []", parse_sec_tickers([]) == [])

    print("incremental_start")
    check("day after last", incremental_start(date(2024, 1, 10)) == "2024-01-11",
          incremental_start(date(2024, 1, 10)))
    check("none -> none (full history)", incremental_start(None) is None)

    print("map_price_frame")
    pf = pd.DataFrame(
        {"Open": [9.0], "High": [12.0], "Low": [8.5], "Close": [11.0],
         "Adj Close": [10.8], "Volume": [1000]},
        index=[pd.Timestamp("2024-03-01")],
    )
    prows = map_price_frame(pf, "AAPL")
    check("one row", len(prows) == 1, f"got {len(prows)}")
    r0 = prows[0] if prows else {}
    check("symbol set", r0.get("symbol") == "AAPL")
    check("date coerced", r0.get("date") == date(2024, 3, 1), r0.get("date"))
    check("ohlc + adj", (r0.get("open"), r0.get("close"), r0.get("adj_close")) == (9.0, 11.0, 10.8))
    # adj_close falls back to close when Adj Close absent
    pf2 = pf.drop(columns=["Adj Close"])
    pr2 = map_price_frame(pf2, "X")
    check("adj_close fallback to close", pr2 and pr2[0]["adj_close"] == 11.0,
          pr2[0].get("adj_close") if pr2 else None)
    check("empty -> []", map_price_frame(pd.DataFrame(), "X") == [])

    print("map_snapshot (vendored fundamentals mapping, one synthetic row)")
    snap = pd.DataFrame([{
        "Symbol": "AAPL",
        "Instrument": "AAPL.O",
        "Price Close": "195.5",          # object/string numeric -> float
        "Earnings Per Share - Actual": 6.13,
        "Earnings Per Share - SmartEstimate®": "6.20",  # the ® column
        "Revenue - Mean": "<NA>",        # unparseable -> None
        "GICS Sector Name": " Information Technology ",  # str trim
        "Number of Analysts": 30,
    }])
    rows = map_snapshot(snap)
    check("one snapshot row", len(rows) == 1, f"got {len(rows)}")
    s0 = rows[0] if rows else {}
    check("symbol", s0.get("symbol") == "AAPL")
    check("string numeric coerced", s0.get("price_close") == 195.5, s0.get("price_close"))
    check("smartestimate ® column mapped", s0.get("eps_smart") == 6.20, s0.get("eps_smart"))
    check("unparseable -> None", s0.get("revenue_mean") is None, s0.get("revenue_mean"))
    check("str trimmed", s0.get("gics_sector") == "Information Technology", repr(s0.get("gics_sector")))
    check("col coverage == FUNDAMENTALS_CURRENT_COLS",
          set(s0.keys()) == set(FUNDAMENTALS_CURRENT_COLS),
          f"missing {set(FUNDAMENTALS_CURRENT_COLS) - set(s0.keys())}")

    print("map_quarterly / map_estimates_forward / map_estimate_revisions")
    q = pd.DataFrame([{"Symbol": "AAPL", "Date": pd.Timestamp("2024-03-31 16:00"),
                       "Earnings Per Share - Actual": "1.50"}])
    qr = map_quarterly(q)
    check("quarterly date truncated to date", qr and qr[0]["report_date"] == date(2024, 3, 31))
    check("quarterly eps coerced", qr and qr[0]["eps_actual"] == 1.50)
    fy1 = pd.DataFrame([{"Symbol": "AAPL", "Earnings Per Share - Mean": "7.0"}])
    fr = map_estimates_forward(fy1, None)
    check("forward fy_period=1", fr and fr[0]["fy_period"] == 1 and fr[0]["eps_mean"] == 7.0)
    rev_frames = {"trend_eps_fy1": pd.DataFrame([
        {"Symbol": "AAPL", "Date": pd.Timestamp("2024-02-01"),
         "Earnings Per Share - Mean": "6.9", "Earnings Per Share - High": "7.1",
         "Earnings Per Share - Low": "6.7", "EPS Number of Estimates": "25"}])}
    rr = map_estimate_revisions(rev_frames)
    check("revision row metric/fy/asof", rr and rr[0]["metric"] == "eps"
          and rr[0]["fy_period"] == 1 and rr[0]["asof"] == date(2024, 2, 1))
    check("revision bounds + n_est", rr and rr[0]["high_val"] == 7.1 and rr[0]["n_est"] == 25.0)

    print("DDL sanity")
    pddl = prices_ddl("MKPrices")
    check("prices_ddl has universe pk", "universe" in pddl and "PRIMARY KEY (symbol, date)" in pddl)
    fddl = mkfund_ddl("MKFund")
    check("mkfund_ddl has all four tables",
          all(t in fddl for t in ("fundamentals_current", "estimates_forward",
                                  "quarterly", "estimate_revisions")))
    check("mkfund_ddl IF NOT EXISTS (re-runnable)", "IF NOT EXISTS" in fddl)

    print("checkpoint")
    ck = {"run_day": _today_key(), "symbols": {}}
    checkpoint_mark(ck, "AAPL", "prices")
    check("mark + done", checkpoint_done(ck, "AAPL", "prices"))
    check("other stage not done", not checkpoint_done(ck, "AAPL", "fundamentals"))

    print()
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)} check(s) failed: {failures}")
        return 1
    print("SELF-TEST PASSED: all pure-function checks green")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone US-equity universe fetch job.")
    p.add_argument("--scan-only", action="store_true",
                   help="compute ADV + upsert the universe registry only; no heavy fetch")
    p.add_argument("--dry-run", action="store_true", help="no DB writes; log intended actions")
    p.add_argument("--limit", type=int, default=None, help="cap candidates (testing)")
    p.add_argument("--prices-only", action="store_true", help="fetch prices only")
    p.add_argument("--fundamentals-only", action="store_true", help="fetch fundamentals only")
    p.add_argument("--self-test", action="store_true",
                   help="run pure-function unit checks and exit (no network/DB)")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        return _self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
