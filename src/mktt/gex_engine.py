"""
GEX engine — pure gamma-exposure computation.

This module is deliberately I/O-free and deterministic: it accepts plain Python
data (normalized option chains) and returns plain dicts. No network, no yfinance,
no datetime.now() — so it can be unit-tested with synthetic chains.

GEX convention (confirmed spec, issue #2):
    net_gex(strike) = Σ_contracts  Γ_bsm × OI × 100 × S² × 0.01 × multiplier
    multiplier = +1 for calls, −1 for puts          (naive dealer positioning)
Units: dollar notional gamma per +1% move in spot. Display divides by 1e9 → $Bn.

Black-Scholes gamma is computed from each contract's implied volatility.

Normalized chain input (what the data provider hands us):
    [
      {"expiration": "2026-06-01", "dte": 2,
       "calls": [{"strike": 590.0, "oi": 12000, "iv": 0.14}, ...],
       "puts":  [{"strike": 590.0, "oi":  9000, "iv": 0.16}, ...]},
      ...  # up to 4 expirations
    ]
"""
import logging
import math

logger = logging.getLogger(__name__)

# --- Modeling defaults (disclosed in the UI; never presented as exact fact) ---
R_DEFAULT = 0.045   # risk-free rate
Q_DEFAULT = 0.0     # dividend yield
CONTRACT_SIZE = 100
PCT_MOVE = 0.01     # per-1%-move scaling
IV_MIN = 0.001      # discard contracts with IV at/below this
IV_MAX = 5.0        # discard contracts with IV above this (garbage)
MIN_DTE = 1         # floor time-to-expiry at 1 day


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_d1(S, K, T, r, sigma, q=Q_DEFAULT):
    """d1 term of the Black-Scholes formula. Returns None for degenerate inputs."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_gamma(S, K, T, r, sigma, q=Q_DEFAULT):
    """
    Black-Scholes gamma: d(delta)/d(spot). Same for calls and puts.

        gamma = e^(-qT) · φ(d1) / (S · σ · √T)

    Returns 0.0 for degenerate / out-of-range inputs (never raises).
    """
    d1 = bs_d1(S, K, T, r, sigma, q)
    if d1 is None:
        return 0.0
    gamma = math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    return gamma


def contract_gex(gamma, oi, spot, is_call):
    """Signed dollar GEX for a single contract (per +1% move)."""
    mult = 1.0 if is_call else -1.0
    return gamma * oi * CONTRACT_SIZE * spot * spot * PCT_MOVE * mult


def _t_years(dte):
    return max(dte, MIN_DTE) / 365.0


def _valid_iv(iv):
    return iv is not None and IV_MIN < iv <= IV_MAX


def aggregate_by_strike(chains, spot, r=R_DEFAULT, q=Q_DEFAULT):
    """
    Aggregate call/put/net GEX per strike across all supplied expirations.

    Returns a dict: strike -> {"call_gex", "put_gex", "net_gex", "oi"}.
    Contracts with invalid IV or OI<=0 are skipped (no gamma signal).
    """
    by_strike = {}
    n_used = 0
    for exp in chains:
        T = _t_years(exp.get("dte", MIN_DTE))
        for side, is_call in (("calls", True), ("puts", False)):
            for c in exp.get(side, []):
                strike = c.get("strike")
                oi = c.get("oi") or 0
                iv = c.get("iv")
                if strike is None or oi <= 0 or not _valid_iv(iv):
                    continue
                gamma = bs_gamma(spot, strike, T, r, iv, q)
                gex = contract_gex(gamma, oi, spot, is_call)
                slot = by_strike.setdefault(
                    strike, {"call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0, "oi": 0}
                )
                if is_call:
                    slot["call_gex"] += gex
                else:
                    slot["put_gex"] += gex
                slot["net_gex"] += gex
                slot["oi"] += int(oi)
                n_used += 1
    logger.debug("aggregate_by_strike: %d strikes from %d contracts (spot=%s)",
                 len(by_strike), n_used, spot)
    return by_strike


def filter_band(strikes_sorted, spot, band_pct):
    """
    Keep strikes within ±band_pct (fraction, e.g. 0.15) of spot.
    band_pct=None or <=0 means no filtering ("all").
    Input/output: list of {"strike", ...} dicts sorted by strike ascending.
    """
    if not band_pct or band_pct <= 0:
        return list(strikes_sorted)
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    return [s for s in strikes_sorted if lo <= s["strike"] <= hi]


def compute_flip(strikes_sorted, spot):
    """
    Zero-gamma flip: the strike level where the net-GEX curve crosses zero,
    by linear interpolation between adjacent strikes whose net GEX changes sign.

    With multiple crossings, return the one nearest spot (most actionable).
    Returns None if the curve never changes sign.
    """
    crossings = []
    for i in range(1, len(strikes_sorted)):
        prev, curr = strikes_sorted[i - 1], strikes_sorted[i]
        y0, y1 = prev["net_gex"], curr["net_gex"]
        if y0 == 0:
            crossings.append(prev["strike"])
        if y0 * y1 < 0:  # strict sign change
            x0, x1 = prev["strike"], curr["strike"]
            x = x0 + (x1 - x0) * abs(y0) / (abs(y0) + abs(y1))
            crossings.append(round(x, 2))
    # last point exactly zero
    if strikes_sorted and strikes_sorted[-1]["net_gex"] == 0:
        crossings.append(strikes_sorted[-1]["strike"])
    if not crossings:
        return None
    flip = min(crossings, key=lambda x: abs(x - spot))
    logger.debug("compute_flip: crossings=%s -> nearest-spot flip=%s", crossings, flip)
    return flip


def find_walls(strikes_sorted):
    """Call wall = max positive net GEX strike; put wall = most negative net GEX strike."""
    if not strikes_sorted:
        return None, None
    call_wall = max(strikes_sorted, key=lambda s: s["net_gex"])
    put_wall = min(strikes_sorted, key=lambda s: s["net_gex"])
    cw = call_wall["strike"] if call_wall["net_gex"] > 0 else None
    pw = put_wall["strike"] if put_wall["net_gex"] < 0 else None
    return cw, pw


def compute_profile(chains, spot, band_pct=0.15, r=R_DEFAULT, q=Q_DEFAULT):
    """
    Full GEX profile for the supplied (already next-4) expirations.

    Returns:
        {
          "spot": float,
          "strikes": [{"strike","call_gex","put_gex","net_gex","oi"}, ...] (band-filtered, OI>0),
          "flip": float|None,
          "call_wall": float|None,
          "put_wall": float|None,
          "total_gex": float,
          "regime": "positive"|"negative",
          "assumptions": {...},
        }
    """
    if not spot or spot <= 0:
        raise ValueError("compute_profile requires a positive spot price")

    by_strike = aggregate_by_strike(chains, spot, r, q)
    strikes_sorted = [
        {"strike": k, **v} for k, v in sorted(by_strike.items())
    ]
    banded = filter_band(strikes_sorted, spot, band_pct)

    flip = compute_flip(banded, spot)
    call_wall, put_wall = find_walls(banded)
    total_gex = sum(s["net_gex"] for s in banded)
    regime = "positive" if total_gex >= 0 else "negative"

    # round for transport (keep full precision internally above)
    out_strikes = [
        {
            "strike": s["strike"],
            "call_gex": round(s["call_gex"]),
            "put_gex": round(s["put_gex"]),
            "net_gex": round(s["net_gex"]),
            "oi": s["oi"],
        }
        for s in banded
    ]
    logger.debug("compute_profile: %d strikes (band=%s), flip=%s, walls=(%s,%s), regime=%s",
                 len(out_strikes), band_pct, flip, call_wall, put_wall, regime)
    return {
        "spot": round(spot, 2),
        "strikes": out_strikes,
        "flip": flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "total_gex": round(total_gex),
        "regime": regime,
        "assumptions": {
            "risk_free": r,
            "dividend_yield": q,
            "dealer_positioning": "naive (dealers long calls, short puts)",
            "oi_basis": "prior-session end-of-day",
            "units": "$ notional gamma per +1% move",
        },
    }


def strike_breakdown(chains, spot, strike, r=R_DEFAULT, q=Q_DEFAULT):
    """
    Per-expiration, per-side contract detail behind a single strike (for drilldown).

    Returns list of {expiration, side, oi, iv, gamma, gex} ordered by expiration then side.
    Contributions sum to that strike's net GEX in compute_profile.
    """
    rows = []
    for exp in chains:
        T = _t_years(exp.get("dte", MIN_DTE))
        for side, is_call in (("call", True), ("put", False)):
            key = "calls" if is_call else "puts"
            for c in exp.get(key, []):
                if c.get("strike") != strike:
                    continue
                oi = c.get("oi") or 0
                iv = c.get("iv")
                if oi <= 0 or not _valid_iv(iv):
                    gamma = 0.0
                    gex = 0.0
                else:
                    gamma = bs_gamma(spot, strike, T, r, iv, q)
                    gex = contract_gex(gamma, oi, spot, is_call)
                rows.append({
                    "expiration": exp.get("expiration"),
                    "side": side,
                    "oi": int(oi),
                    "iv": round(iv, 4) if iv is not None else None,
                    "gamma": round(gamma, 6),
                    "gex": round(gex),
                })
    logger.debug("strike_breakdown: strike=%s -> %d contract rows", strike, len(rows))
    return rows
