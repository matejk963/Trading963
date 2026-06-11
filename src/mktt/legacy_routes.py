"""Legacy MKTT routes — endpoints NOT yet owned by a new section blueprint.

These are ported verbatim out of the pre-refactor ``app.py`` (slice 13). They keep
the EPS/revenue/sector-map/freshness surface alive with ZERO functionality loss
while the new kernel-centric sections own the rest of the URL space. The new
section blueprints own ``/ /screener /api/screener /options /api/options/*
/chart/<symbol> /api/chart /api/fundamentals/<symbol> /api/monitor /watchlist
/api/watchlist /macro /macro/api/* /rrg /api/rrg*`` — those duplicates are dropped
from here so there is no route-URL conflict.

Endpoints preserved here:
    GET /api/rolling_12m/<symbol>
    GET /api/sales_ttm_forward/<symbol>
    GET /api/eps_ttm_forward/<symbol>
    GET /api/revisions/<symbol>
    GET /api/sector_map
    GET /api/freshness

These read the cached Refinitiv fundamentals pkl + local price parquet directly
(the pre-refactor data path); they predate the DataSource/ComputedStore seams and
are kept faithful rather than re-plumbed (a working larger surface beats a broken
thin one — slice 13 priority order). ``fmt_number`` is also re-exported so the app
factory can register it as a jinja global, as the old monolith did.
"""
from __future__ import annotations

import pandas as pd
from flask import Blueprint, jsonify, request

legacy_bp = Blueprint("legacy", __name__)


# =========================================================================
# Shared shaping / lookup helpers (ported from app.py)
# =========================================================================
_classification_cache = {"data": None}


def load_classification_lookups():
    """Load pre-computed PCA, stage, and EPS accel/decel classifications."""
    if _classification_cache["data"] is not None:
        return _classification_cache["data"]

    import json
    from pathlib import Path
    data_dir = Path(__file__).parent.parent.parent / "sandbox" / "analysis" / "stage_pca" / "output" / "data"

    lookups = {}

    # PCA-20 regimes: symbol -> regime name
    try:
        with open(data_dir / "pca20_5c_meta.json") as f:
            d = json.load(f)
        pca = {}
        for k, v in d.items():
            for st in v["stocks"]:
                pca[st["s"]] = v["n"]
        lookups["pca20"] = pca
        lookups["pca20_labels"] = sorted(set(pca.values()))
    except Exception:
        lookups["pca20"] = {}
        lookups["pca20_labels"] = []

    # Weinstein stages: symbol -> stage label
    try:
        with open(data_dir / "stages_meta.json") as f:
            d = json.load(f)
        stages = {}
        for k, v in d.items():
            for st in v["stocks"]:
                stages[st["s"]] = v["n"]
        lookups["stages"] = stages
        lookups["stage_labels"] = sorted(set(stages.values()))
    except Exception:
        lookups["stages"] = {}
        lookups["stage_labels"] = []

    # EPS acceleration: symbol -> 'Accelerating' or 'Decelerating'
    try:
        with open(data_dir / "eps_growth_meta.json") as f:
            d = json.load(f)
        eps_acc = {}
        for k, v in d.get("accel", {}).items():
            for st in v["stocks"]:
                eps_acc[st["s"]] = {"label": "Accelerating" if k == "1" else "Decelerating",
                                    "acc": st.get("acc"), "g1": st.get("g1"), "g2": st.get("g2")}
        lookups["eps_accel"] = eps_acc
    except Exception:
        lookups["eps_accel"] = {}

    # MA Screener: symbol -> category
    try:
        with open(data_dir / "screener_meta.json") as f:
            d = json.load(f)
        ma_screen = {}
        for k, v in d.items():
            for st in v["stocks"]:
                ma_screen[st["s"]] = v["n"]
        lookups["ma_screen"] = ma_screen
        lookups["ma_screen_labels"] = sorted(set(ma_screen.values()))
    except Exception:
        lookups["ma_screen"] = {}
        lookups["ma_screen_labels"] = []

    _classification_cache["data"] = lookups
    return lookups


_refinitiv_cache = {"data": None, "mtime": 0}


def load_refinitiv_snapshot():
    """Load Refinitiv snapshot as a symbol-keyed dict. Cached with mtime check."""
    import os
    import pickle
    from pathlib import Path
    pkl_path = Path(__file__).parent.parent.parent / "data" / "mktt" / "refinitiv_fundamentals.pkl"
    if not pkl_path.exists():
        return {}
    mtime = os.path.getmtime(pkl_path)
    if _refinitiv_cache["data"] is not None and _refinitiv_cache["mtime"] == mtime:
        return _refinitiv_cache["data"]
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)
    snap = data.get("snapshot")
    fy1 = data.get("fy1")
    fy2 = data.get("fy2")
    if snap is None:
        return {}
    lookup = {}
    for _, row in snap.iterrows():
        sym = row.get("Symbol")
        if pd.isna(sym):
            continue
        sym = str(sym)
        rec = {
            "sector": _safe_val(row.get("GICS Sector Name")),
            "industry": _safe_val(row.get("GICS Industry Name")),
            "eps_act": _safe_num(row.get("Earnings Per Share - Actual")),
            "eps_mean": _safe_num(row.get("Earnings Per Share - Mean")),
            "eps_smart": _safe_num(row.get("Earnings Per Share - SmartEstimate®")),
            "rev_act": _safe_num(row.get("Revenue - Actual")),
            "rev_mean": _safe_num(row.get("Revenue - Mean")),
            "op_margin": _safe_num(row.get("Operating Margin, Percent")),
            "net_margin": _safe_num(row.get("Net Profit Margin, (%)")),
            "ebitda": _safe_num(row.get("EBITDA")),
            "fcf": _safe_num(row.get("Free Cash Flow")),
            "total_debt": _safe_num(row.get("Total Debt")),
            "net_debt": _safe_num(row.get("Net Debt Incl. Pref.Stock & Min.Interest")),
            "cash": _safe_num(row.get("Cash and Short Term Investments")),
            "nd_ebitda": _safe_num(row.get("Net Debt To EBITDA (Daily Time Series Ratio)")),
            "current_ratio": _safe_num(row.get("Current Ratio")),
            "roic": _safe_num(row.get("Return on Capital, Total LT Capital, Percent")),
            "ev_ebitda": _safe_num(row.get("Enterprise Value To EBITDA (Daily Time Series Ratio)")),
            "target": _safe_num(row.get("Price Target - Mean")),
            "analysts": _safe_num(row.get("Number of Analysts")),
            "shares": _safe_num(row.get("Outstanding Shares")),
            "mktcap": None,  # compute from price * shares
        }
        # FY1/FY2 estimates
        if fy1 is not None:
            f1 = fy1[fy1["Symbol"] == sym]
            if len(f1) > 0:
                rec["fy1_eps"] = _safe_num(f1.iloc[0].get("Earnings Per Share - Mean"))
                rec["fy1_rev"] = _safe_num(f1.iloc[0].get("Revenue - Mean"))
                rec["fy2_eps"] = None
                rec["fy2_rev"] = None
        if fy2 is not None:
            f2 = fy2[fy2["Symbol"] == sym]
            if len(f2) > 0:
                rec["fy2_eps"] = _safe_num(f2.iloc[0].get("Earnings Per Share - Mean"))
                rec["fy2_rev"] = _safe_num(f2.iloc[0].get("Revenue - Mean"))
        lookup[sym] = rec
    _refinitiv_cache["data"] = lookup
    _refinitiv_cache["mtime"] = mtime
    return lookup


def _safe_num(v):
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v) if str(v) != "<NA>" else None


def fmt_number(val):
    """Format large numbers: 1.2B, 345M, 12.5K"""
    if val is None or val != val:
        return "—"
    val = float(val)
    if abs(val) >= 1e12:
        return f"{val/1e12:.1f}T"
    elif abs(val) >= 1e9:
        return f"{val/1e9:.1f}B"
    elif abs(val) >= 1e6:
        return f"{val/1e6:.1f}M"
    elif abs(val) >= 1e3:
        return f"{val/1e3:.0f}K"
    else:
        return f"{val:.0f}"


# =========================================================================
# Routes
# =========================================================================
@legacy_bp.route("/api/rolling_12m/<symbol>")
def rolling_12m_api(symbol):
    """Return rolling 12-month EPS and Revenue with estimate bounds."""
    try:
        return _rolling_12m_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _rolling_12m_impl(symbol):
    import pickle
    from pathlib import Path

    pkl_path = Path(__file__).parent.parent.parent / "data" / "mktt" / "refinitiv_fundamentals.pkl"
    if not pkl_path.exists():
        return jsonify({"error": "No data"}), 404
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    quarterly = data.get("quarterly")
    if quarterly is None:
        return jsonify({"error": "No quarterly data"}), 404

    q = quarterly[quarterly["Symbol"] == symbol].copy()
    if q.empty:
        return jsonify({"error": f"No data for {symbol}"}), 404

    q["Date"] = pd.to_datetime(q["Date"], errors="coerce")
    q = q.sort_values("Date").dropna(subset=["Date"])

    def _n(v):
        if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except Exception:
            return None

    q["eps"] = q["Earnings Per Share - Actual"].map(_n)
    q["eps_est"] = q["Earnings Per Share - Mean Estimate"].map(_n)
    q["rev"] = q["Revenue - Actual"].map(_n)

    # Rolling 12M (4 quarter sum) for actuals
    dates = []
    eps_ttm = []
    rev_ttm = []
    eps_est_ttm = []

    for i in range(3, len(q)):
        window = q.iloc[i-3:i+1]
        dt = q.iloc[i]["Date"]

        eps_vals = [window.iloc[j]["eps"] for j in range(4)]
        rev_vals = [window.iloc[j]["rev"] for j in range(4)]
        est_vals = [window.iloc[j]["eps_est"] for j in range(4)]

        if all(v is not None for v in eps_vals):
            eps_ttm.append(round(sum(eps_vals), 2))
        else:
            eps_ttm.append(None)

        if all(v is not None for v in rev_vals):
            rev_ttm.append(round(sum(rev_vals) / 1e6, 1))
        else:
            rev_ttm.append(None)

        if all(v is not None for v in est_vals):
            eps_est_ttm.append(round(sum(est_vals), 2))
        else:
            eps_est_ttm.append(None)

        dates.append(str(dt)[:10])

    # Forward: add NTM from forward quarterly estimates
    fwd_q = data.get("forward_quarterly")
    fwd_dates = []
    fwd_eps_mean = []
    fwd_eps_high = []
    fwd_eps_low = []
    fwd_rev_mean = []
    fwd_rev_high = []
    fwd_rev_low = []

    if fwd_q is not None:
        fq = fwd_q[fwd_q["Symbol"] == symbol]
        if len(fq) >= 4:
            eps_fwd_mean = pd.to_numeric(fq.get("Earnings Per Share - Mean", pd.Series()), errors="coerce").values
            eps_fwd_high = pd.to_numeric(fq.get("Earnings Per Share - High", pd.Series()), errors="coerce").values
            eps_fwd_low = pd.to_numeric(fq.get("Earnings Per Share - Low", pd.Series()), errors="coerce").values
            rev_fwd_mean_v = pd.to_numeric(fq.get("Revenue - Mean", pd.Series()), errors="coerce").values
            rev_fwd_high_v = pd.to_numeric(fq.get("Revenue - High", pd.Series()), errors="coerce").values
            rev_fwd_low_v = pd.to_numeric(fq.get("Revenue - Low", pd.Series()), errors="coerce").values

            last_actuals_eps = [q.iloc[-(4-j)]["eps"] for j in range(4) if len(q) > (4-j-1)]
            last_actuals_rev = [q.iloc[-(4-j)]["rev"] for j in range(4) if len(q) > (4-j-1)]

            def _blend(actuals, fwd_vals, step, div=1):
                """Rolling 12M at step N: take last (4-step) actuals + first (step) forward estimates.
                For step > 4, all 4 come from forward: fwd[step-4:step]."""
                if step <= len(actuals):
                    actual_part = actuals[step:]
                    fwd_part = fwd_vals[:step].tolist()
                else:
                    actual_part = []
                    fwd_part = fwd_vals[step-4:step].tolist() if step <= len(fwd_vals) else []
                a = [v for v in actual_part if v is not None]
                f = [v for v in fwd_part if not pd.isna(v)]
                if len(a) + len(f) == 4:
                    return round((sum(a) + sum(f)) / div, 2 if div == 1 else 1)
                return None

            n_fwd_steps = min(8, len(eps_fwd_mean))
            for step in range(1, n_fwd_steps + 1):
                if step > len(eps_fwd_mean):
                    break
                fwd_eps_mean.append(_blend(last_actuals_eps, eps_fwd_mean, step))
                fwd_eps_high.append(_blend(last_actuals_eps, eps_fwd_high, step))
                fwd_eps_low.append(_blend(last_actuals_eps, eps_fwd_low, step))
                fwd_rev_mean.append(_blend(last_actuals_rev, rev_fwd_mean_v, step, 1e6))
                fwd_rev_high.append(_blend(last_actuals_rev, rev_fwd_high_v, step, 1e6))
                fwd_rev_low.append(_blend(last_actuals_rev, rev_fwd_low_v, step, 1e6))

                last_dt = pd.to_datetime(dates[-1]) if dates else q["Date"].iloc[-1]
                fwd_dates.append(str(last_dt + pd.DateOffset(months=3 * step))[:10])

    # Sanitize: replace NaN/inf with None for JSON
    import math

    def _clean(lst):
        return [v if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else None for v in lst]

    result = {
        "dates": dates,
        "eps_ttm": _clean(eps_ttm),
        "eps_est_ttm": _clean(eps_est_ttm),
        "rev_ttm": _clean(rev_ttm),
        "fwd_dates": fwd_dates,
        "fwd_eps_mean": _clean(fwd_eps_mean),
        "fwd_eps_high": _clean(fwd_eps_high),
        "fwd_eps_low": _clean(fwd_eps_low),
        "fwd_rev_mean": _clean(fwd_rev_mean),
        "fwd_rev_high": _clean(fwd_rev_high),
        "fwd_rev_low": _clean(fwd_rev_low),
    }
    return jsonify(result)


@legacy_bp.route("/api/sales_ttm_forward/<symbol>")
def sales_ttm_forward_api(symbol):
    """Return forward TTM Revenue curves with revisions."""
    try:
        return _sales_ttm_forward_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _sales_ttm_forward_impl(symbol):
    import pickle
    import math
    from pathlib import Path

    pkl_path = Path(__file__).parent.parent.parent / "data" / "mktt" / "refinitiv_fundamentals.pkl"
    if not pkl_path.exists():
        return jsonify({"error": "No data"}), 404
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    quarterly = data.get("quarterly")
    fwd_q = data.get("forward_quarterly")
    if quarterly is None or fwd_q is None:
        return jsonify({"error": "Missing data"}), 404

    # Quarterly actuals
    q = quarterly[quarterly["Symbol"] == symbol].copy()
    if q.empty:
        return jsonify({"error": f"No quarterly data for {symbol}"}), 404
    q["Date"] = pd.to_datetime(q["Date"])
    q = q.sort_values("Date")
    q["Rev"] = pd.to_numeric(q["Revenue - Actual"], errors="coerce")
    q = q.dropna(subset=["Rev"])
    if len(q) < 4:
        return jsonify({"error": f"Not enough quarterly revenue data for {symbol}"}), 404

    # Forward quarterly revenue
    fq = fwd_q[fwd_q["Symbol"] == symbol]
    fq_rev = pd.to_numeric(fq.get("Revenue - Mean", pd.Series()), errors="coerce").values
    fq_rev = [v if not (math.isnan(v) if isinstance(v, float) else False) else None for v in fq_rev]

    n_fwd = min(8, len(fq_rev))
    if n_fwd < 4:
        return jsonify({"error": f"Not enough forward quarterly revenue estimates for {symbol}"}), 404

    # Trailing actuals (last 4)
    trailing = q["Rev"].tail(4).tolist()

    # Build forward TTM from per-quarter estimates
    all_rev = trailing + fq_rev[:n_fwd]
    quarter_dates = []
    last_dt = q["Date"].iloc[-1]
    for i in range(n_fwd):
        last_dt = last_dt + pd.DateOffset(months=3)
        quarter_dates.append(last_dt)

    forward_mean = []
    for i in range(n_fwd):
        window = all_rev[i+1: i+5]
        if all(v is not None for v in window):
            forward_mean.append(round(sum(window) / 1e6, 1))
        else:
            forward_mean.append(None)

    # Revision curves: use per-quarter revenue estimate trends (FQ1-FQ4)
    curves_list = []
    n_available = 0
    fq_rev_trends = {}
    for fq_key in ["trend_rev_fq1", "trend_rev_fq2", "trend_rev_fq3", "trend_rev_fq4"]:
        t = data.get(fq_key)
        if t is not None:
            ts = t[t["Symbol"] == symbol].copy()
            if not ts.empty:
                ts["Date"] = pd.to_datetime(ts["Date"])
                ts["Mean"] = pd.to_numeric(ts.get("Revenue - Mean", pd.Series()), errors="coerce")
                ts = ts.dropna(subset=["Mean"]).sort_values("Date")
                fq_rev_trends[fq_key] = ts

    if fq_rev_trends:
        all_trend_dates = sorted(set(
            d for t in fq_rev_trends.values() for d in t["Date"].tolist()
        ), reverse=True)
        n_available = len(all_trend_dates)

        n_rev = int(request.args.get("n", 3))
        n_rev = max(1, min(n_rev, n_available))
        snap_dates = all_trend_dates[:n_rev]

        for si, snap_date in enumerate(snap_dates):
            fwd_est = []
            for fq_key in ["trend_rev_fq1", "trend_rev_fq2", "trend_rev_fq3", "trend_rev_fq4"]:
                ts = fq_rev_trends.get(fq_key)
                if ts is not None:
                    at = ts[ts["Date"] <= snap_date]
                    fwd_est.append(float(at["Mean"].iloc[-1]) if not at.empty else None)
                else:
                    fwd_est.append(None)

            fwd_est = fwd_est + fwd_est  # extend to 8Q
            rev_all = trailing + fwd_est[:n_fwd]
            rev_ttm = []
            for i in range(n_fwd):
                window = rev_all[i+1: i+5]
                if len(window) == 4 and all(v is not None for v in window):
                    rev_ttm.append(round(sum(window) / 1e6, 1))
                else:
                    rev_ttm.append(None)

            label = "Current (" + snap_date.strftime("%m/%d") + ")" if si == 0 else snap_date.strftime("%Y-%m-%d")
            curves_list.append({"label": label, "values": rev_ttm})

    result = {
        "quarter_labels": [f"{d.year}-Q{(d.month - 1)//3 + 1}" for d in quarter_dates],
        "quarter_dates": [d.strftime("%Y-%m-%d") for d in quarter_dates],
        "curves": curves_list,
        "current_ttm": round(float(q["Rev"].tail(4).sum() / 1e6), 1),
        "forward_mean": forward_mean,
        "n_available": n_available,
    }
    return jsonify(result)


@legacy_bp.route("/api/eps_ttm_forward/<symbol>")
def eps_ttm_forward_api(symbol):
    """Return forward TTM EPS curve at current, -10d, -30d, -60d snapshots."""
    try:
        return _eps_ttm_forward_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _eps_ttm_forward_impl(symbol):
    """
    Build forward TTM EPS curves using per-quarter forward estimates.
    Shows how rolling 12M EPS evolves as each future quarter replaces a trailing one.
    Multiple revision snapshots show how estimates changed over time.
    """
    import pickle
    import math
    from pathlib import Path

    pkl_path = Path(__file__).parent.parent.parent / "data" / "mktt" / "refinitiv_fundamentals.pkl"
    if not pkl_path.exists():
        return jsonify({"error": "No data"}), 404
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    quarterly = data.get("quarterly")
    fwd_q = data.get("forward_quarterly")
    trend_fy1 = data.get("trend_eps_fy1")
    if quarterly is None or fwd_q is None:
        return jsonify({"error": "Missing data"}), 404

    # Get quarterly actuals
    q = quarterly[quarterly["Symbol"] == symbol].copy()
    if q.empty:
        return jsonify({"error": f"No quarterly data for {symbol}"}), 404
    q["Date"] = pd.to_datetime(q["Date"])
    q = q.sort_values("Date")
    q["EPS"] = pd.to_numeric(q["Earnings Per Share - Actual"], errors="coerce")
    q = q.dropna(subset=["EPS"])
    if len(q) < 4:
        return jsonify({"error": f"Not enough quarterly EPS data for {symbol}"}), 404

    # Get forward quarterly estimates
    fq = fwd_q[fwd_q["Symbol"] == symbol]
    fq_eps = pd.to_numeric(fq.get("Earnings Per Share - Mean", pd.Series()), errors="coerce").values
    fq_eps = [v if not (math.isnan(v) if isinstance(v, float) else False) else None for v in fq_eps]

    n_fwd = min(8, len(fq_eps))
    if n_fwd < 4:
        return jsonify({"error": f"Not enough forward quarterly estimates for {symbol}"}), 404

    # Trailing actuals (last 4)
    trailing = q["EPS"].tail(4).tolist()

    # Build forward TTM: progressively replace actuals with estimates
    all_eps = trailing + fq_eps[:n_fwd]
    quarter_dates = []
    last_dt = q["Date"].iloc[-1]
    for i in range(n_fwd):
        last_dt = last_dt + pd.DateOffset(months=3)
        quarter_dates.append(last_dt)

    ttm_values = []
    for i in range(n_fwd):
        window = all_eps[i+1: i+5]
        if all(v is not None for v in window):
            ttm_values.append(round(sum(window), 2))
        else:
            ttm_values.append(None)

    # Revision curves: use per-quarter estimate trends (FQ1-FQ4)
    # Each has monthly snapshots of per-quarter estimates
    curves_list = []
    fq_trends = {}
    for fq_key in ["trend_eps_fq1", "trend_eps_fq2", "trend_eps_fq3", "trend_eps_fq4"]:
        t = data.get(fq_key)
        if t is not None:
            ts = t[t["Symbol"] == symbol].copy()
            if not ts.empty:
                ts["Date"] = pd.to_datetime(ts["Date"])
                ts["Mean"] = pd.to_numeric(ts["Earnings Per Share - Mean"], errors="coerce")
                ts = ts.dropna(subset=["Mean"]).sort_values("Date")
                fq_trends[fq_key] = ts

    n_available = 0
    all_trend_dates = []
    fy1 = pd.DataFrame()
    if fq_trends:
        # Collect all unique trend dates across quarters
        all_trend_dates = sorted(set(
            d for t in fq_trends.values() for d in t["Date"].tolist()
        ), reverse=True)
        n_available = len(all_trend_dates)

        n_rev = int(request.args.get("n", 3))
        n_rev = max(1, min(n_rev, n_available))
        snap_dates = all_trend_dates[:n_rev]

        for si, snap_date in enumerate(snap_dates):
            # Get per-quarter estimate at this snapshot date
            fwd_est = []
            for fq_key in ["trend_eps_fq1", "trend_eps_fq2", "trend_eps_fq3", "trend_eps_fq4"]:
                ts = fq_trends.get(fq_key)
                if ts is not None:
                    at = ts[ts["Date"] <= snap_date]
                    fwd_est.append(float(at["Mean"].iloc[-1]) if not at.empty else None)
                else:
                    fwd_est.append(None)

            # Extend to 8Q by repeating the pattern (FQ1-FQ4 twice)
            fwd_est = fwd_est + fwd_est
            rev_all = trailing + fwd_est[:n_fwd]
            rev_ttm = []
            for i in range(n_fwd):
                window = rev_all[i+1: i+5]
                if len(window) == 4 and all(v is not None for v in window):
                    rev_ttm.append(round(sum(window), 2))
                else:
                    rev_ttm.append(None)

            label = "Current (" + snap_date.strftime("%m/%d") + ")" if si == 0 else snap_date.strftime("%Y-%m-%d")
            curves_list.append({"label": label, "values": rev_ttm})
    else:
        # Fallback to FY1/FY2 if no per-quarter trends available
        trend_fy1 = data.get("trend_eps_fy1")
        if trend_fy1 is not None:
            n_available = 0

    result = {
        "quarter_labels": [f"{d.year}-Q{(d.month - 1)//3 + 1}" for d in quarter_dates],
        "quarter_dates": [d.strftime("%Y-%m-%d") for d in quarter_dates],
        "curves": curves_list,
        "current_ttm": round(float(q["EPS"].tail(4).sum()), 2),
        "forward_mean": ttm_values,
        "n_available": len(all_trend_dates) if trend_fy1 is not None and not fy1.empty else 0,
    }
    return jsonify(result)


@legacy_bp.route("/api/revisions/<symbol>")
def revisions_api(symbol):
    """Return EPS/Revenue estimate revision trends for a symbol."""
    try:
        return _revisions_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _revisions_impl(symbol):
    import pickle
    from pathlib import Path
    pkl_path = Path(__file__).parent.parent.parent / "data" / "mktt" / "refinitiv_fundamentals.pkl"
    if not pkl_path.exists():
        return jsonify({"error": "No data"}), 404
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    result = {}
    for key, label in [("trend_eps_fy1", "eps_fy1"), ("trend_eps_fy2", "eps_fy2"),
                       ("trend_rev_fy1", "rev_fy1"), ("trend_rev_fy2", "rev_fy2")]:
        df = data.get(key)
        if df is None:
            continue
        t = df[df["Symbol"] == symbol].copy()
        if t.empty:
            continue
        t["Date"] = pd.to_datetime(t["Date"])
        t = t.sort_values("Date")

        def _safe(v, div=1):
            if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
                return None
            try:
                return round(float(v) / div, 3)
            except (ValueError, TypeError):
                return None

        if "Earnings Per Share - Mean" in t.columns:
            result[label] = {
                "dates": [str(d)[:10] for d in t["Date"]],
                "mean": [_safe(v) for v in t["Earnings Per Share - Mean"]],
                "high": [_safe(v) for v in t.get("Earnings Per Share - High", [])],
                "low": [_safe(v) for v in t.get("Earnings Per Share - Low", [])],
            }
        elif "Revenue - Mean" in t.columns:
            result[label] = {
                "dates": [str(d)[:10] for d in t["Date"]],
                "mean": [_safe(v, 1e6) for v in t["Revenue - Mean"]],
            }

    if not result:
        return jsonify({"error": f"No revision data for {symbol}"}), 404
    return jsonify(result)


@legacy_bp.route("/api/sector_map")
def sector_map_api():
    """Return sector/industry breakdown by a given criteria dimension."""
    try:
        return _sector_map_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _sector_map_impl():
    from data_manager import load_prices, load_universe

    dimension = request.args.get("dim", "pca_regime")  # what to color/group by
    min_turnover = int(float(request.args.get("min_turnover", "500000")))

    close = load_prices("close")
    uni = load_universe()
    rfv = load_refinitiv_snapshot()
    cls = load_classification_lookups()

    if close is None or close.empty:
        return jsonify({"error": "No price data"}), 404

    # Find last dense row
    min_stocks = len(close.columns) * 0.5
    _idx = len(close) - 1
    for _i in range(len(close) - 1, max(len(close) - 10, 0), -1):
        if close.iloc[_i].notna().sum() >= min_stocks:
            _idx = _i
            break
    _close_slice = close.iloc[:_idx + 1]
    last_prices = _close_slice.iloc[-1]

    # RS ranks
    rs_ranks = {}
    rs_chg1m = {}
    if len(_close_slice) > 147:
        ret_6m = (_close_slice.iloc[-1] / _close_slice.iloc[-126] - 1)
        rs_pct = ret_6m.rank(pct=True) * 100
        rs_ranks = rs_pct.to_dict()
        s = _close_slice.iloc[:-21]
        r6_old = (s.iloc[-1] / s.iloc[-126] - 1)
        rs_old = (r6_old.rank(pct=True) * 100).to_dict()
        rs_chg1m = {sym: rs_ranks.get(sym, 0) - rs_old.get(sym, 0) for sym in rs_ranks}

    rows = []
    for sym in close.columns:
        price = last_prices.get(sym)
        if pd.isna(price) or price <= 0:
            continue
        uni_row = uni[uni["symbol"] == sym].iloc[0] if uni is not None and sym in uni["symbol"].values else None
        turnover = float(uni_row["turnover"]) if uni_row is not None and pd.notna(uni_row.get("turnover")) else 0
        if turnover < min_turnover:
            continue

        r = rfv.get(sym, {})
        sector = r.get("sector")
        if not sector:
            continue
        industry = r.get("industry") or "Unknown"
        eps_act = r.get("eps_act")
        fy1_eps = r.get("fy1_eps")

        # Compute PE
        pe = float(price) / float(eps_act) if eps_act and eps_act > 0 else None

        # Classification values
        pca = cls.get("pca20", {}).get(sym, "Unknown")
        stage = cls.get("stages", {}).get(sym, "Unknown")
        eps_acc_info = cls.get("eps_accel", {}).get(sym, {})
        eps_mom = eps_acc_info.get("label", "Unknown") if isinstance(eps_acc_info, dict) else "Unknown"

        # EPS growth direction
        eps_growth_dir = "Unknown"
        if eps_act and fy1_eps:
            eps_growth_dir = "Growing" if fy1_eps > eps_act else "Declining" if fy1_eps < eps_act else "Flat"

        # RS bucket
        rs_val = rs_ranks.get(sym)
        rs_bucket = "Unknown"
        if rs_val is not None:
            if rs_val >= 80:
                rs_bucket = "RS 80+"
            elif rs_val >= 60:
                rs_bucket = "RS 60-80"
            elif rs_val >= 40:
                rs_bucket = "RS 40-60"
            elif rs_val >= 20:
                rs_bucket = "RS 20-40"
            else:
                rs_bucket = "RS 0-20"

        # RS momentum bucket
        chg1m = rs_chg1m.get(sym, 0)
        rs_mom = "Unknown"
        if chg1m > 5:
            rs_mom = "Improving"
        elif chg1m > -5:
            rs_mom = "Stable"
        else:
            rs_mom = "Deteriorating"

        rows.append({
            "symbol": sym, "sector": sector, "industry": industry,
            "pe": pe, "turnover": turnover,
            "pca_regime": pca, "stage": stage, "eps_momentum": eps_mom,
            "eps_growth": eps_growth_dir, "rs_bucket": rs_bucket,
            "rs_momentum": rs_mom,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return jsonify({"error": "No data"}), 404

    # PE vs sector bucket
    if "pe" in df.columns:
        sector_med_pe = df[df["pe"].notna() & (df["pe"] > 0)].groupby("sector")["pe"].median()

        def _pe_bucket(row):
            if pd.isna(row.get("pe")) or row["pe"] is None:
                return "No PE"
            med = sector_med_pe.get(row["sector"])
            if med is None or med <= 0:
                return "No PE"
            ratio = row["pe"] / med
            if ratio < 0.7:
                return "Deep Discount"
            elif ratio < 0.9:
                return "Discount"
            elif ratio < 1.1:
                return "Fair"
            elif ratio < 1.3:
                return "Premium"
            else:
                return "High Premium"
        df["pe_vs_sector"] = df.apply(_pe_bucket, axis=1)

    # Available dimensions
    dim_map = {
        "pca_regime": "pca_regime", "stage": "stage", "eps_momentum": "eps_momentum",
        "eps_growth": "eps_growth", "rs_bucket": "rs_bucket", "rs_momentum": "rs_momentum",
        "pe_vs_sector": "pe_vs_sector",
    }
    col = dim_map.get(dimension, "pca_regime")

    # Build treemap data: sector -> industry -> count, colored by dimension
    treemap_data = []
    for sector, sec_group in df.groupby("sector"):
        for industry, ind_group in sec_group.groupby("industry"):
            for dim_val, dim_group in ind_group.groupby(col):
                treemap_data.append({
                    "sector": sector,
                    "industry": industry,
                    "dimension": str(dim_val),
                    "count": len(dim_group),
                    "symbols": dim_group["symbol"].tolist(),
                })

    # Summary: sector × dimension counts
    summary = df.groupby(["sector", col]).size().reset_index(name="count")
    summary.columns = ["sector", "dimension", "count"]
    summary_list = summary.to_dict("records")

    # Overall dimension distribution
    overall = df[col].value_counts().to_dict()

    return jsonify({
        "dimension": dimension,
        "dimensions_available": list(dim_map.keys()),
        "treemap": treemap_data,
        "summary": summary_list,
        "overall": {str(k): int(v) for k, v in overall.items()},
        "total_stocks": len(df),
    })


@legacy_bp.route("/api/freshness")
def freshness_api():
    """Return data freshness report as JSON."""
    try:
        from data_freshness import full_report
        return jsonify(full_report())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
