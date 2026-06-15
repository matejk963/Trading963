"""Fundamental-series blend — the pkl-backed EPS/Sales actual+forecast access.

FORK-2 (effort 2026-06-13-monitor-section): the rich ~8Q forward-quarterly fan
(mean/high/low) lives only in ``data/mktt/refinitiv_fundamentals.pkl``; the
``MKFund`` DB carries only FY1/FY2 annual forward + quarterly actuals. This module
ports the legacy blend out of ``legacy_routes.py`` (``_rolling_12m_impl`` /
``_eps_ttm_forward_impl`` / ``_sales_ttm_forward_impl``) into a reusable,
**Flask-free**, dependency-injected access the Monitor section reaches via
``DataSource.fundamental_series(symbol, asof=…)``.

DEBT (carried in the effort log): this reintroduces the ``.pkl`` dependency the
refactor was moving away from. A ``forward_quarterly`` DB-loader is the proper
future fix; until then this is the single, isolated place the pkl is read for the
forward fan.

Design (spec §8 — DI):
- ``build_fundamental_series(loader=…)`` takes a zero-arg ``loader`` returning the
  pkl dict (``{quarterly, forward_quarterly, fy1, fy2, …}``). The default loader
  reads + mtime-caches the on-disk pkl; tests inject a fake dict so the blend math
  is exercised without the 37 MB file.
- The returned callable is ``(symbol, asof=None) -> structured dict``:

    {
      "quarterly": {dates, eps, revenue},
      "ttm":       {dates, eps, revenue, fwd_dates, eps_mean/high/low, rev_mean/high/low},
      "annual":    {fy_dates, eps, rev, fwd_dates, eps_mean/high/low, rev_mean/high/low},
      "forward_q": {dates, eps_mean/high/low, rev_mean/high/low},
    }

  ``asof`` (default latest = ``None``) filters quarterly/TTM actuals to
  ``report_date <= asof`` (the forward fan is the as-of-now estimate snapshot).
  All values are JSON-safe (NaN/inf -> ``None``).
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger("mktt.datasource.fundamental_series")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

#: On-disk pkl (the legacy Refinitiv fundamentals snapshot — FORK-2 source).
_PKL_PATH = Path(__file__).resolve().parents[3] / "data" / "mktt" / "refinitiv_fundamentals.pkl"

#: mtime-keyed cache so the 37 MB pkl is read once per process (mirrors legacy).
_pkl_cache = {"data": None, "mtime": 0}


# --------------------------------------------------------------------------- #
# default loader (the pkl read — the one isolated place the pkl is touched)
# --------------------------------------------------------------------------- #
def _default_loader() -> dict:
    """Read + mtime-cache the Refinitiv fundamentals pkl. ``{}`` if absent."""
    if not _PKL_PATH.exists():
        logger.debug("fundamental_series: pkl missing at %s", _PKL_PATH)
        return {}
    mtime = os.path.getmtime(_PKL_PATH)
    if _pkl_cache["data"] is not None and _pkl_cache["mtime"] == mtime:
        return _pkl_cache["data"]
    import pickle
    with open(_PKL_PATH, "rb") as f:
        data = pickle.load(f)
    _pkl_cache["data"] = data
    _pkl_cache["mtime"] = mtime
    return data


# --------------------------------------------------------------------------- #
# JSON-safe scalar helpers
# --------------------------------------------------------------------------- #
def _n(v):
    """Float or None (empty / NaN / inf / non-numeric -> None)."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _clean(seq):
    return [_n(v) for v in seq]


# --------------------------------------------------------------------------- #
# the access factory
# --------------------------------------------------------------------------- #
def build_fundamental_series(loader: Optional[Callable[[], dict]] = None):
    """Return the ``(symbol, asof=None) -> structured dict`` access (DI seam).

    ``loader`` is a zero-arg callable returning the pkl dict; defaults to the
    on-disk mtime-cached reader. Inject a fake dict in tests to drive the blend.
    """
    load = loader or _default_loader

    def fundamental_series(symbol: str, asof=None) -> dict:
        logger.debug("fundamental_series symbol=%s asof=%s", symbol, asof)
        data = load() or {}
        q = _symbol_quarterly(data, symbol, asof)
        forward_q = _forward_quarterly(data, symbol)
        quarterly = _quarterly_block(q)
        ttm = _ttm_block(q, forward_q)
        annual = _annual_block(q, data, symbol)
        return {
            "quarterly": quarterly,
            "ttm": ttm,
            "annual": annual,
            "forward_q": forward_q,
        }

    return fundamental_series


# --------------------------------------------------------------------------- #
# quarterly actuals (asof-filtered)
# --------------------------------------------------------------------------- #
def _symbol_quarterly(data, symbol, asof) -> pd.DataFrame:
    """The symbol's quarterly actuals (sorted, dated), filtered to report_date<=asof."""
    quarterly = data.get("quarterly")
    if quarterly is None:
        return pd.DataFrame(columns=["Date", "eps", "rev"])
    q = quarterly[quarterly["Symbol"] == symbol].copy()
    if q.empty:
        return pd.DataFrame(columns=["Date", "eps", "rev"])
    q["Date"] = pd.to_datetime(q["Date"], errors="coerce")
    q = q.dropna(subset=["Date"]).sort_values("Date")
    if asof is not None:
        cutoff = pd.to_datetime(asof, errors="coerce")
        if not pd.isna(cutoff):
            q = q[q["Date"] <= cutoff]
    q["eps"] = q["Earnings Per Share - Actual"].map(_n)
    q["rev"] = q["Revenue - Actual"].map(_n)
    return q


def _quarterly_block(q: pd.DataFrame) -> dict:
    """Raw quarterly actuals -> {dates, eps, revenue} (revenue in $m)."""
    if q.empty:
        return {"dates": [], "eps": [], "revenue": []}
    dates = [str(d)[:10] for d in q["Date"]]
    eps = list(q["eps"])
    rev = [(_n(v) / 1e6 if _n(v) is not None else None) for v in q["rev"]]
    return {"dates": dates, "eps": _clean(eps), "revenue": rev}


# --------------------------------------------------------------------------- #
# forward quarterly fan (mean/high/low) — the pkl-only payload
# --------------------------------------------------------------------------- #
def _forward_quarterly(data, symbol) -> dict:
    """Forward-quarterly EPS + Revenue fan {dates, eps_/rev_ mean/high/low}.

    Up to 8 forward quarters (legacy cap), dated by stepping +3 months from the
    last actual quarter. Revenue scaled to $m. Only as deep as the data holds (no
    fabrication)."""
    fwd_q = data.get("forward_quarterly")
    empty = {
        "dates": [], "eps_mean": [], "eps_high": [], "eps_low": [],
        "rev_mean": [], "rev_high": [], "rev_low": [],
    }
    if fwd_q is None:
        return empty
    fq = fwd_q[fwd_q["Symbol"] == symbol]
    if fq.empty:
        return empty

    def _col(name):
        return pd.to_numeric(fq.get(name, pd.Series()), errors="coerce").tolist()

    eps_mean = _col("Earnings Per Share - Mean")
    eps_high = _col("Earnings Per Share - High")
    eps_low = _col("Earnings Per Share - Low")
    rev_mean = _col("Revenue - Mean")
    rev_high = _col("Revenue - High")
    rev_low = _col("Revenue - Low")

    n_fwd = min(8, len(eps_mean))
    # date the steps off the last actual quarter (fall back to today if absent).
    q = data.get("quarterly")
    last_dt = None
    if q is not None:
        qs = q[q["Symbol"] == symbol]
        if not qs.empty:
            dts = pd.to_datetime(qs["Date"], errors="coerce").dropna()
            if len(dts) > 0:
                last_dt = dts.max()
    if last_dt is None:
        last_dt = pd.Timestamp.today().normalize()

    dates = []
    cursor = last_dt
    for _ in range(n_fwd):
        cursor = cursor + pd.DateOffset(months=3)
        dates.append(str(cursor)[:10])

    def _scaled(vals, div):
        return [(_n(v) / div if _n(v) is not None else None) for v in vals[:n_fwd]]

    return {
        "dates": dates,
        "eps_mean": _clean(eps_mean[:n_fwd]),
        "eps_high": _clean(eps_high[:n_fwd]),
        "eps_low": _clean(eps_low[:n_fwd]),
        "rev_mean": _scaled(rev_mean, 1e6),
        "rev_high": _scaled(rev_high, 1e6),
        "rev_low": _scaled(rev_low, 1e6),
    }


# --------------------------------------------------------------------------- #
# rolling TTM (4Q sum) actuals + forward-TTM blend
# --------------------------------------------------------------------------- #
def _ttm_block(q: pd.DataFrame, forward_q: dict) -> dict:
    """Rolling 12-month (4Q sum) EPS + Revenue actuals, plus the forward-TTM blend.

    Ported from ``_rolling_12m_impl`` / ``_eps_ttm_forward_impl``: each TTM point is
    the 4-quarter trailing sum (only when all 4 are present); the forward-TTM
    progressively replaces trailing actuals with the forward-quarterly mean/high/low
    estimates (the band carried through)."""
    out = {
        "dates": [], "eps": [], "revenue": [],
        "fwd_dates": [], "eps_mean": [], "eps_high": [], "eps_low": [],
        "rev_mean": [], "rev_high": [], "rev_low": [],
    }
    if q.empty or len(q) < 4:
        return out

    eps = list(q["eps"])
    rev = list(q["rev"])
    dates = [str(d)[:10] for d in q["Date"]]

    for i in range(3, len(q)):
        eps_w = eps[i - 3:i + 1]
        rev_w = rev[i - 3:i + 1]
        out["dates"].append(dates[i])
        out["eps"].append(round(sum(eps_w), 2) if all(v is not None for v in eps_w) else None)
        out["revenue"].append(
            round(sum(rev_w) / 1e6, 1) if all(v is not None for v in rev_w) else None
        )

    # forward-TTM: trailing 4 actuals + forward-quarterly estimates, rolled 4Q.
    trailing_eps = [v for v in eps[-4:]]
    trailing_rev = [v for v in rev[-4:]]
    fq_dates = forward_q.get("dates", [])
    n_fwd = len(fq_dates)
    if n_fwd >= 1:
        out["fwd_dates"] = list(fq_dates)
        # forward_q revenue is already $m; trailing rev is raw -> convert to $m too.
        trailing_rev_m = [(v / 1e6 if v is not None else None) for v in trailing_rev]
        out["eps_mean"] = _rolling_forward(trailing_eps, forward_q.get("eps_mean", []), n_fwd, 2)
        out["eps_high"] = _rolling_forward(trailing_eps, forward_q.get("eps_high", []), n_fwd, 2)
        out["eps_low"] = _rolling_forward(trailing_eps, forward_q.get("eps_low", []), n_fwd, 2)
        out["rev_mean"] = _rolling_forward(trailing_rev_m, forward_q.get("rev_mean", []), n_fwd, 1)
        out["rev_high"] = _rolling_forward(trailing_rev_m, forward_q.get("rev_high", []), n_fwd, 1)
        out["rev_low"] = _rolling_forward(trailing_rev_m, forward_q.get("rev_low", []), n_fwd, 1)
    return out


def _rolling_forward(trailing, fwd_vals, n_fwd, ndigits):
    """Forward-TTM curve: at step i (1..n_fwd) the trailing window slides one quarter
    forward, replacing the oldest actual with the next forward estimate.

    Window at step i = last (4-i) trailing actuals + first i forward estimates
    (for i>4, all 4 come from the forward stream). Returns a value only when the
    full 4-quarter window is present (no fabrication)."""
    all_q = list(trailing) + list(fwd_vals[:n_fwd])
    out = []
    for i in range(n_fwd):
        window = all_q[i + 1: i + 5]
        if len(window) == 4 and all(v is not None for v in window):
            out.append(round(sum(window), ndigits))
        else:
            out.append(None)
    return out


# --------------------------------------------------------------------------- #
# annual FY actuals + FY1/FY2 forward
# --------------------------------------------------------------------------- #
def _annual_block(q: pd.DataFrame, data, symbol) -> dict:
    """Annual FY actuals (calendar-year sum of the quarterly actuals) + FY1/FY2
    forward (mean/high/low) from the pkl's ``fy1``/``fy2`` frames.

    Annual actuals: group the quarterly actuals by calendar year, summing only
    complete (4-quarter) years (no fabrication). Revenue in $m."""
    out = {
        "fy_dates": [], "eps": [], "rev": [],
        "fwd_dates": [], "eps_mean": [], "eps_high": [], "eps_low": [],
        "rev_mean": [], "rev_high": [], "rev_low": [],
    }
    if not q.empty:
        qy = q.copy()
        qy["year"] = qy["Date"].dt.year
        for year, grp in qy.groupby("year"):
            eps_vals = list(grp["eps"])
            rev_vals = list(grp["rev"])
            if len(grp) >= 4 and all(v is not None for v in eps_vals):
                out["fy_dates"].append(f"{int(year)}-12-31")
                out["eps"].append(round(sum(eps_vals), 2))
                out["rev"].append(
                    round(sum(rev_vals) / 1e6, 1) if all(v is not None for v in rev_vals) else None
                )

    # FY1/FY2 forward (mean/high/low). Date them as the next two calendar years
    # after the last actual FY (fall back to the next two years from today).
    base_year = None
    if out["fy_dates"]:
        base_year = int(out["fy_dates"][-1][:4])
    else:
        base_year = pd.Timestamp.today().year - 1

    for n, key in ((1, "fy1"), (2, "fy2")):
        fy = data.get(key)
        if fy is None:
            continue
        row = fy[fy["Symbol"] == symbol]
        if row.empty:
            continue
        r = row.iloc[0]
        out["fwd_dates"].append(f"{base_year + n}-12-31")
        out["eps_mean"].append(_n(r.get("Earnings Per Share - Mean")))
        out["eps_high"].append(_n(r.get("Earnings Per Share - High")))
        out["eps_low"].append(_n(r.get("Earnings Per Share - Low")))
        rm, rh, rl = (
            _n(r.get("Revenue - Mean")), _n(r.get("Revenue - High")), _n(r.get("Revenue - Low")),
        )
        out["rev_mean"].append(round(rm / 1e6, 1) if rm is not None else None)
        out["rev_high"].append(round(rh / 1e6, 1) if rh is not None else None)
        out["rev_low"].append(round(rl / 1e6, 1) if rl is not None else None)
    return out
