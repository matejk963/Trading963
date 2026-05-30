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


def get_expirations(symbol, force_refresh=False):
    """All available expiration dates for symbol (cached)."""
    symbol = symbol.upper().strip()
    key = (symbol, "__exps__")
    if not force_refresh and _fresh(key):
        return _cache[key]
    t = yf.Ticker(symbol)
    exps = _fetch_with_backoff(lambda: list(t.options), f"options({symbol})")
    if not exps:
        raise ValueError(f"No option expirations available for {symbol}")
    _set_cache(key, exps)
    return exps


def _get_spot(symbol, t=None, force_refresh=False):
    key = (symbol, "__spot__")
    if not force_refresh and _fresh(key):
        return _cache[key]
    spot = _resolve_spot(t or yf.Ticker(symbol))
    if spot <= 0:
        raise ValueError(f"Could not resolve spot price for {symbol}")
    _set_cache(key, spot)
    return spot


def _get_one_chain(symbol, expiration, t=None, force_refresh=False):
    """Normalized single-expiration chain (cached per expiration)."""
    key = (symbol, expiration)
    if not force_refresh and _fresh(key):
        return _cache[key]
    t = t or yf.Ticker(symbol)
    chain = _fetch_with_backoff(
        lambda: t.option_chain(expiration), f"chain({symbol},{expiration})")
    dte = max((pd.Timestamp(expiration) - pd.Timestamp.now()).days, 1)
    payload = {
        "expiration": expiration,
        "dte": dte,
        "calls": _normalize_side(chain.calls),
        "puts": _normalize_side(chain.puts),
    }
    _set_cache(key, payload)
    return payload


def _resolve_selection(available, expirations, n_exp):
    """Pick which expirations to use: explicit (valid subset) else first n_exp."""
    if expirations:
        selected = [e for e in expirations if e in available]
        if selected:
            return selected
    return available[:n_exp]


def get_next_chains(symbol, n_exp=DEFAULT_N_EXP, expirations=None, force_refresh=False):
    """
    Fetch + normalize the selected expirations for symbol.

    `expirations` (optional list) overrides the default "first n_exp"; invalid
    entries are dropped and an empty result falls back to the first n_exp.
    Chains are cached per expiration, so adding one expiry never refetches the
    others.

    Returns:
        {
          "symbol", "spot",
          "chains": [{expiration, dte, calls, puts}, ...],
          "expirations": [str, ...],            # what was actually used
          "available_expirations": [str, ...],  # full list for the picker
          "default_expirations": [str, ...],    # the first n_exp
          "meta": {"fetched_at", "oi_as_of", "stale", "warning"},
        }
    On fetch failure, assembles a stale payload from per-expiration cache if able.
    """
    symbol = symbol.upper().strip()
    try:
        available = get_expirations(symbol, force_refresh=force_refresh)
        selected = _resolve_selection(available, expirations, n_exp)
        t = yf.Ticker(symbol)
        spot = _get_spot(symbol, t, force_refresh=force_refresh)
        chains = [_get_one_chain(symbol, e, t, force_refresh=force_refresh)
                  for e in selected]
        payload = {
            "symbol": symbol,
            "spot": spot,
            "chains": chains,
            "expirations": selected,
            "available_expirations": available,
            "default_expirations": available[:n_exp],
            "meta": {
                "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "oi_as_of": _oi_as_of(),
                "stale": False,
                "warning": None,
            },
        }
        logger.debug("assembled %s: spot=%.2f, %d/%d expirations",
                     symbol, spot, len(chains), len(available))
        return payload

    except Exception as e:  # noqa: BLE001 — provider boundary
        stale = _assemble_from_cache(symbol, n_exp, expirations, e)
        if stale is not None:
            logger.debug("serving stale cache for %s due to: %s", symbol, e)
            return stale
        logger.debug("no cache fallback for %s: %s", symbol, e)
        return {"error": str(e)}


def _assemble_from_cache(symbol, n_exp, expirations, exc):
    """Best-effort stale payload built from whatever per-key caches exist."""
    av_key, sp_key = (symbol, "__exps__"), (symbol, "__spot__")
    if av_key not in _cache or sp_key not in _cache:
        return None
    available = _cache[av_key]
    selected = _resolve_selection(available, expirations, n_exp)
    cached = [e for e in selected if (symbol, e) in _cache]
    if not cached:
        return None
    return {
        "symbol": symbol,
        "spot": _cache[sp_key],
        "chains": [_cache[(symbol, e)] for e in cached],
        "expirations": cached,
        "available_expirations": available,
        "default_expirations": available[:n_exp],
        "meta": {
            "fetched_at": "(cached)",
            "oi_as_of": _oi_as_of(),
            "stale": True,
            "warning": f"Live fetch failed ({exc}); showing last cached data.",
        },
    }


# --------------------------------------------------------------------------- #
# High-level: provider + engine
# --------------------------------------------------------------------------- #
def gex_profile(symbol, band_pct=0.15, n_exp=DEFAULT_N_EXP, expirations=None,
                force_refresh=False):
    """Fetch chains and compute the full GEX profile. Returns engine output + meta."""
    data = get_next_chains(symbol, n_exp=n_exp, expirations=expirations,
                           force_refresh=force_refresh)
    if "error" in data:
        return data
    try:
        profile = gex_engine.compute_profile(
            data["chains"], data["spot"], band_pct=band_pct)
    except ValueError as e:
        return {"error": str(e)}
    profile["symbol"] = data["symbol"]
    profile["expirations"] = data["expirations"]
    profile["available_expirations"] = data.get("available_expirations", [])
    profile["default_expirations"] = data.get("default_expirations", [])
    profile["meta"] = data["meta"]
    return profile


def drilldown(symbol, strike, n_exp=DEFAULT_N_EXP, expirations=None):
    """Per-expiration / per-side contract breakdown behind a single strike."""
    data = get_next_chains(symbol, n_exp=n_exp, expirations=expirations)
    if "error" in data:
        return data
    rows = gex_engine.strike_breakdown(data["chains"], data["spot"], float(strike))
    return {
        "symbol": data["symbol"],
        "strike": float(strike),
        "spot": data["spot"],
        "contracts": rows,
        "expirations": data["expirations"],
        "meta": data["meta"],
    }
