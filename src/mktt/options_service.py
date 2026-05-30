"""
Options data provider — yfinance fetch, normalization, caching, resilience.

Responsibilities (issue #2 / #7):
  - fetch the next N expirations and their chains from yfinance
  - normalize them into the plain structure the GEX engine consumes
  - 5-minute TTL cache keyed by (symbol, n_exp)
  - exponential backoff on rate-limit; on persistent failure, fall back to the
    last cached value and flag it stale (never hard-error if we have anything)
  - carry "fetched_at" / "oi_as_of" metadata for honest UI disclosure

No GEX math lives here — that's gex_engine. This module is the only place that
touches yfinance.
"""
import logging
import time
import math

import pandas as pd
import yfinance as yf

import gex_engine

logger = logging.getLogger(__name__)

CACHE_TTL = 300            # 5 minutes
DEFAULT_N_EXP = 4
MAX_RETRIES = 3
BACKOFF_BASE = 1.5         # seconds; exponential

_cache = {}        # key -> normalized payload
_cache_time = {}   # key -> epoch seconds


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #
def _fresh(key):
    return key in _cache and (time.time() - _cache_time.get(key, 0)) < CACHE_TTL


def _set_cache(key, value):
    _cache[key] = value
    _cache_time[key] = time.time()


def _is_rate_limit(exc):
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "too many requests" in str(exc).lower()


def _fetch_with_backoff(fn, what):
    """Call fn() with exponential backoff on rate-limit. Raises on final failure."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — provider boundary
            last = e
            if _is_rate_limit(e) and attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.debug("rate-limited on %s (attempt %d) — backing off %.1fs",
                             what, attempt + 1, wait)
                time.sleep(wait)
                continue
            logger.debug("fetch failed on %s: %s", what, e)
            raise
    raise last


# --------------------------------------------------------------------------- #
# Low-level yfinance access
# --------------------------------------------------------------------------- #
def _resolve_spot(t):
    """Spot from fast_info.lastPrice -> previousClose -> 1d history."""
    try:
        fi = t.fast_info
        spot = fi.get("lastPrice") or fi.get("last_price") \
            or fi.get("previousClose") or fi.get("previous_close")
        if spot:
            return float(spot)
    except Exception as e:  # noqa: BLE001
        logger.debug("fast_info spot failed: %s", e)
    try:
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:  # noqa: BLE001
        logger.debug("history spot failed: %s", e)
    return 0.0


def _normalize_side(df):
    """yfinance calls/puts DataFrame -> list of {strike, oi, iv}."""
    rows = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        strike = r.get("strike")
        if strike is None or (isinstance(strike, float) and math.isnan(strike)):
            continue
        oi = r.get("openInterest")
        iv = r.get("impliedVolatility")
        oi = 0 if oi is None or (isinstance(oi, float) and math.isnan(oi)) else int(oi)
        iv = None if iv is None or (isinstance(iv, float) and math.isnan(iv)) else float(iv)
        rows.append({"strike": float(strike), "oi": oi, "iv": iv})
    return rows


def _oi_as_of():
    """OI is prior-session EOD; report the previous business day as the basis."""
    today = pd.Timestamp.now().normalize()
    prev = today - pd.tseries.offsets.BDay(1)
    return prev.strftime("%Y-%m-%d") + " close"


def get_next_chains(symbol, n_exp=DEFAULT_N_EXP, force_refresh=False):
    """
    Fetch + normalize the next n_exp expirations for symbol.

    Returns:
        {
          "symbol": str, "spot": float,
          "chains": [{expiration, dte, calls:[...], puts:[...]}, ...],
          "expirations": [str, ...],
          "meta": {"fetched_at": iso, "oi_as_of": str, "stale": bool, "warning": str|None},
        }
    On rate-limit with a prior cache entry, returns that entry marked stale.
    """
    symbol = symbol.upper().strip()
    key = (symbol, n_exp)
    if not force_refresh and _fresh(key):
        logger.debug("cache hit %s", key)
        return _cache[key]

    try:
        t = yf.Ticker(symbol)
        exps = _fetch_with_backoff(lambda: list(t.options), f"options({symbol})")
        if not exps:
            raise ValueError(f"No option expirations available for {symbol}")
        chosen = exps[:n_exp]
        spot = _resolve_spot(t)
        if spot <= 0:
            raise ValueError(f"Could not resolve spot price for {symbol}")

        now = pd.Timestamp.now()
        chains = []
        for exp in chosen:
            chain = _fetch_with_backoff(
                lambda e=exp: t.option_chain(e), f"chain({symbol},{exp})")
            dte = max((pd.Timestamp(exp) - now).days, 1)
            chains.append({
                "expiration": exp,
                "dte": dte,
                "calls": _normalize_side(chain.calls),
                "puts": _normalize_side(chain.puts),
            })

        payload = {
            "symbol": symbol,
            "spot": spot,
            "chains": chains,
            "expirations": chosen,
            "meta": {
                "fetched_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "oi_as_of": _oi_as_of(),
                "stale": False,
                "warning": None,
            },
        }
        _set_cache(key, payload)
        logger.debug("fetched %s: spot=%.2f, %d expirations", symbol, spot, len(chains))
        return payload

    except Exception as e:  # noqa: BLE001
        # Fall back to last cached value if we have one
        if key in _cache:
            stale = dict(_cache[key])
            meta = dict(stale["meta"])
            meta["stale"] = True
            meta["warning"] = f"Live fetch failed ({e}); showing last cached data."
            stale["meta"] = meta
            logger.debug("serving stale cache for %s due to: %s", symbol, e)
            return stale
        logger.debug("no cache fallback for %s: %s", symbol, e)
        return {"error": str(e)}


# --------------------------------------------------------------------------- #
# High-level: provider + engine
# --------------------------------------------------------------------------- #
def gex_profile(symbol, band_pct=0.15, n_exp=DEFAULT_N_EXP, force_refresh=False):
    """Fetch chains and compute the full GEX profile. Returns engine output + meta."""
    data = get_next_chains(symbol, n_exp=n_exp, force_refresh=force_refresh)
    if "error" in data:
        return data
    try:
        profile = gex_engine.compute_profile(
            data["chains"], data["spot"], band_pct=band_pct)
    except ValueError as e:
        return {"error": str(e)}
    profile["symbol"] = data["symbol"]
    profile["expirations"] = data["expirations"]
    profile["meta"] = data["meta"]
    return profile


def drilldown(symbol, strike, n_exp=DEFAULT_N_EXP):
    """Per-expiration / per-side contract breakdown behind a single strike."""
    data = get_next_chains(symbol, n_exp=n_exp)
    if "error" in data:
        return data
    rows = gex_engine.strike_breakdown(data["chains"], data["spot"], float(strike))
    return {
        "symbol": data["symbol"],
        "strike": float(strike),
        "spot": data["spot"],
        "contracts": rows,
        "meta": data["meta"],
    }
