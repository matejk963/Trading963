"""Options DataSource submodule (spec §4.4, §5.3) — the `OptionChain` form.

Owns raw option-chain access behind the `option_chain` form interface: fetch the
next N expirations and their chains from yfinance, normalize them into the plain
structure the GEX engine consumes, cache with a TTL, back off on rate-limit, and
fall back to the last cached value on persistent failure (never hard-error if any
cache exists).

This is the relocation of the fetch/normalize/cache/backoff logic that lived in
``options_service.py`` (``_normalize_side`` :93-107, ``_fetch_with_backoff``,
``get_next_chains``, ``_assemble_from_cache``). **No GEX math lives here** — that
stays in the private ``gex_engine`` core; this submodule only produces the form.

Design (spec §8 — dependency injection):
- ``ticker_factory`` (``symbol -> ticker-like``) is injected; tests pass a fake
  ticker exposing ``.options`` / ``.fast_info`` / ``.history`` / ``.option_chain``.
  When omitted, ``yfinance.Ticker`` is imported **lazily** (the only place the
  dependency is needed) — so the submodule is unit-testable without network.
- ``clock`` (``() -> epoch seconds``) is injected for deterministic TTL tests.

The `(option_chain, *)` registry row routes every symbol here (asset-class blind —
every symbol's chain comes from the same source).

Debug logging is off by default (set ``MKTT_LOG_LEVEL=DEBUG``).
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger("mktt.datasource.options")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

CACHE_TTL = 300            # 5 minutes
DEFAULT_N_EXP = 4
MAX_RETRIES = 3
BACKOFF_BASE = 1.5         # seconds; exponential

TickerFactory = Callable[[str], "object"]
Clock = Callable[[], float]


# --------------------------------------------------------------------------- #
# Normalization (ported verbatim from options_service._normalize_side :93-107).
# --------------------------------------------------------------------------- #
def _normalize_side(df):
    """yfinance calls/puts DataFrame -> list of {strike, oi, iv}."""
    rows = []
    if df is None or getattr(df, "empty", True):
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


def _is_rate_limit(exc):
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "too many requests" in str(exc).lower()


class OptionsSubmodule:
    """Reads option chains from a (injected) ticker source into the `OptionChain` form.

    Parameters
    ----------
    ticker_factory:
        ``symbol -> ticker`` (DI seam). The ticker must expose ``.options`` (list of
        expiration strings), ``.fast_info`` / ``.history`` (for spot resolution), and
        ``.option_chain(exp)`` (object with ``.calls`` / ``.puts`` DataFrames). When
        ``None``, ``yfinance.Ticker`` is imported lazily.
    clock:
        ``() -> epoch seconds`` for TTL freshness (defaults to ``time.time``).
    """

    def __init__(
        self,
        ticker_factory: Optional[TickerFactory] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self._ticker_factory = ticker_factory
        self._clock = clock or time.time
        self._cache: dict = {}        # key -> payload/value
        self._cache_time: dict = {}   # key -> epoch seconds

    # ------------------------------------------------------------------ #
    # cache helpers
    # ------------------------------------------------------------------ #
    def _fresh(self, key):
        return key in self._cache and (self._clock() - self._cache_time.get(key, 0)) < CACHE_TTL

    def _set_cache(self, key, value):
        self._cache[key] = value
        self._cache_time[key] = self._clock()

    def _ticker(self, symbol):
        if self._ticker_factory is not None:
            return self._ticker_factory(symbol)
        import yfinance as yf  # lazy — only when actually fetching live
        return yf.Ticker(symbol)

    def _fetch_with_backoff(self, fn, what):
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

    # ------------------------------------------------------------------ #
    # low-level yfinance access (ported from options_service)
    # ------------------------------------------------------------------ #
    @staticmethod
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

    @staticmethod
    def _oi_as_of():
        """OI is prior-session EOD; report the previous business day as the basis."""
        today = pd.Timestamp.now().normalize()
        prev = today - pd.tseries.offsets.BDay(1)
        return prev.strftime("%Y-%m-%d") + " close"

    def _get_expirations(self, symbol, t, force_refresh=False):
        key = (symbol, "__exps__")
        if not force_refresh and self._fresh(key):
            return self._cache[key]
        exps = self._fetch_with_backoff(lambda: list(t.options), f"options({symbol})")
        if not exps:
            raise ValueError(f"No option expirations available for {symbol}")
        self._set_cache(key, exps)
        return exps

    def _get_spot(self, symbol, t, force_refresh=False):
        key = (symbol, "__spot__")
        if not force_refresh and self._fresh(key):
            return self._cache[key]
        spot = self._resolve_spot(t)
        if spot <= 0:
            raise ValueError(f"Could not resolve spot price for {symbol}")
        self._set_cache(key, spot)
        return spot

    def _get_one_chain(self, symbol, expiration, t, force_refresh=False):
        """Normalized single-expiration chain (cached per expiration)."""
        key = (symbol, expiration)
        if not force_refresh and self._fresh(key):
            return self._cache[key]
        chain = self._fetch_with_backoff(
            lambda: t.option_chain(expiration), f"chain({symbol},{expiration})")
        dte = max((pd.Timestamp(expiration) - pd.Timestamp.now()).days, 1)
        payload = {
            "expiration": expiration,
            "dte": dte,
            "calls": _normalize_side(chain.calls),
            "puts": _normalize_side(chain.puts),
        }
        self._set_cache(key, payload)
        return payload

    @staticmethod
    def _resolve_selection(available, expirations, n_exp):
        """Pick which expirations to use: explicit (valid subset) else first n_exp."""
        if expirations:
            selected = [e for e in expirations if e in available]
            if selected:
                return selected
        return available[:n_exp]

    # ------------------------------------------------------------------ #
    # the OptionChain form (spec §5.3) — option_chain(symbol, n_exp)
    # ------------------------------------------------------------------ #
    def option_chain(self, symbol, n_exp=DEFAULT_N_EXP, expirations=None,
                     force_refresh=False) -> "OptionChain":
        """symbol + params -> `OptionChain` (expiry × strike grids per side).

        ``expirations`` (optional list) overrides the default "first n_exp"; invalid
        entries are dropped and an empty result falls back to the first n_exp.
        Chains are cached per expiration, so adding one expiry never refetches the
        others. On fetch failure, assembles a STALE OptionChain from per-expiration
        cache if able; otherwise raises ``OptionChainError``.
        """
        from ..forms import OptionChain  # local import avoids a package import cycle

        symbol = symbol.upper().strip()
        try:
            t = self._ticker(symbol)
            available = self._get_expirations(symbol, t, force_refresh=force_refresh)
            selected = self._resolve_selection(available, expirations, n_exp)
            spot = self._get_spot(symbol, t, force_refresh=force_refresh)
            chains = [self._get_one_chain(symbol, e, t, force_refresh=force_refresh)
                      for e in selected]
            logger.debug("assembled %s: spot=%.2f, %d/%d expirations",
                         symbol, spot, len(chains), len(available))
            return OptionChain(
                symbol=symbol,
                spot=spot,
                chains=chains,
                expirations=selected,
                available_expirations=available,
                default_expirations=available[:n_exp],
                meta={
                    "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "oi_as_of": self._oi_as_of(),
                    "stale": False,
                    "warning": None,
                },
            )
        except Exception as e:  # noqa: BLE001 — provider boundary
            stale = self._assemble_from_cache(symbol, n_exp, expirations, e)
            if stale is not None:
                logger.debug("serving stale cache for %s due to: %s", symbol, e)
                return stale
            logger.debug("no cache fallback for %s: %s", symbol, e)
            raise OptionChainError(str(e)) from e

    def _assemble_from_cache(self, symbol, n_exp, expirations, exc):
        """Best-effort STALE OptionChain built from whatever per-key caches exist."""
        from ..forms import OptionChain

        av_key, sp_key = (symbol, "__exps__"), (symbol, "__spot__")
        if av_key not in self._cache or sp_key not in self._cache:
            return None
        available = self._cache[av_key]
        selected = self._resolve_selection(available, expirations, n_exp)
        cached = [e for e in selected if (symbol, e) in self._cache]
        if not cached:
            return None
        return OptionChain(
            symbol=symbol,
            spot=self._cache[sp_key],
            chains=[self._cache[(symbol, e)] for e in cached],
            expirations=cached,
            available_expirations=available,
            default_expirations=available[:n_exp],
            meta={
                "fetched_at": "(cached)",
                "oi_as_of": self._oi_as_of(),
                "stale": True,
                "warning": f"Live fetch failed ({exc}); showing last cached data.",
            },
        )


class OptionChainError(RuntimeError):
    """Raised when an option chain cannot be fetched and no stale cache exists."""
