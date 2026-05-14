"""
Options data service — fetching, caching, Greeks computation, GEX analysis.
"""
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm
import time
import math

# =========================================================================
# TTL Cache
# =========================================================================
_cache = {}
_cache_time = {}
CACHE_TTL = 300  # 5 minutes


def _safe(v, default=0):
    """Convert NaN/None/inf to default."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _get_cached(key):
    if key in _cache and time.time() - _cache_time.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None


def _set_cached(key, value):
    _cache[key] = value
    _cache_time[key] = time.time()


# =========================================================================
# Data Fetching
# =========================================================================

def get_expirations(symbol):
    """Return list of available expiration dates for a symbol."""
    cached = _get_cached(f'exp_{symbol}')
    if cached is not None:
        return cached
    try:
        t = yf.Ticker(symbol)
        exps = list(t.options)
        _set_cached(f'exp_{symbol}', exps)
        return exps
    except Exception as e:
        return {'error': str(e)}


def get_chain(symbol, expiration):
    """Return calls and puts DataFrames for a specific expiration."""
    cached = _get_cached(f'chain_{symbol}_{expiration}')
    if cached is not None:
        return cached
    try:
        t = yf.Ticker(symbol)
        chain = t.option_chain(expiration)
        # Get spot price
        info = t.fast_info
        spot = float(info.get('lastPrice', 0) or info.get('previousClose', 0))
        if spot == 0:
            hist = t.history(period='1d')
            spot = float(hist['Close'].iloc[-1]) if not hist.empty else 0

        result = {
            'calls': chain.calls,
            'puts': chain.puts,
            'spot': spot,
            'expiration': expiration,
        }
        _set_cached(f'chain_{symbol}_{expiration}', result)
        return result
    except Exception as e:
        return {'error': str(e)}


def get_all_chains(symbol):
    """Fetch chains for all expirations (for IV surface). Cached."""
    cached = _get_cached(f'allchains_{symbol}')
    if cached is not None:
        return cached
    exps = get_expirations(symbol)
    if isinstance(exps, dict) and 'error' in exps:
        return exps
    chains = {}
    spot = None
    for exp in exps:
        c = get_chain(symbol, exp)
        if 'error' in c:
            continue
        chains[exp] = c
        if spot is None:
            spot = c['spot']
    result = {'chains': chains, 'spot': spot, 'expirations': exps}
    _set_cached(f'allchains_{symbol}', result)
    return result


# =========================================================================
# Black-Scholes Greeks
# =========================================================================

def bs_d1(S, K, T, r, sigma):
    """Compute d1 in BSM formula."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    return (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))


def bs_gamma(S, K, T, r, sigma):
    """BSM gamma: sensitivity of delta to price change."""
    d1 = bs_d1(S, K, T, r, sigma)
    if np.isnan(d1):
        return 0.0
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))


def bs_delta_call(S, K, T, r, sigma):
    d1 = bs_d1(S, K, T, r, sigma)
    return norm.cdf(d1) if not np.isnan(d1) else 0.0


def bs_delta_put(S, K, T, r, sigma):
    d1 = bs_d1(S, K, T, r, sigma)
    return norm.cdf(d1) - 1 if not np.isnan(d1) else 0.0


def bs_theta_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * np.sqrt(T)
    if np.isnan(d1):
        return 0.0
    return (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
            - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365


def bs_vega(S, K, T, r, sigma):
    d1 = bs_d1(S, K, T, r, sigma)
    if np.isnan(d1):
        return 0.0
    return S * norm.pdf(d1) * np.sqrt(T) / 100  # per 1% vol change


# =========================================================================
# Chain Processing
# =========================================================================

def process_chain(symbol, expiration, risk_free=0.045):
    """Process a chain: add Greeks, format for display."""
    data = get_chain(symbol, expiration)
    if 'error' in data:
        return data

    spot = data['spot']
    calls = data['calls'].copy()
    puts = data['puts'].copy()

    # Days to expiration
    exp_date = pd.Timestamp(expiration)
    now = pd.Timestamp.now()
    dte = max((exp_date - now).days, 1)
    T = dte / 365

    def _add_greeks(df, is_call=True):
        rows = []
        for _, row in df.iterrows():
            iv = _safe(row.get('impliedVolatility', 0))
            strike = _safe(row['strike'])
            oi = int(_safe(row.get('openInterest', 0)))
            vol = int(_safe(row.get('volume', 0)))

            # Skip invalid IV
            if iv <= 0.001 or iv > 5:
                gamma = delta = theta = vega = 0
            else:
                gamma = bs_gamma(spot, strike, T, risk_free, iv)
                delta = bs_delta_call(spot, strike, T, risk_free, iv) if is_call else bs_delta_put(spot, strike, T, risk_free, iv)
                theta = bs_theta_call(spot, strike, T, risk_free, iv)
                vega = bs_vega(spot, strike, T, risk_free, iv)

            rows.append({
                'strike': strike,
                'bid': round(_safe(row.get('bid', 0)), 2),
                'ask': round(_safe(row.get('ask', 0)), 2),
                'last': round(_safe(row.get('lastPrice', 0)), 2),
                'volume': int(vol),
                'oi': int(oi),
                'iv': round(iv * 100, 1) if iv > 0.001 else None,  # as percentage
                'itm': bool(row.get('inTheMoney', False)),
                'delta': round(delta, 3),
                'gamma': round(gamma, 4),
                'theta': round(theta, 3),
                'vega': round(vega, 3),
            })
        return rows

    return {
        'spot': round(spot, 2),
        'expiration': expiration,
        'dte': dte,
        'calls': _add_greeks(calls, is_call=True),
        'puts': _add_greeks(puts, is_call=False),
    }


# =========================================================================
# IV Surface
# =========================================================================

def compute_iv_surface(symbol):
    """Build IV surface data across all expirations."""
    all_data = get_all_chains(symbol)
    if 'error' in all_data:
        return all_data

    spot = all_data['spot']
    now = pd.Timestamp.now()
    surface = []

    for exp, chain_data in all_data['chains'].items():
        exp_date = pd.Timestamp(exp)
        dte = max((exp_date - now).days, 1)

        for _, row in chain_data['calls'].iterrows():
            iv = _safe(row.get('impliedVolatility', 0))
            if iv > 0.001 and iv < 5:
                moneyness = round((_safe(row['strike']) / spot - 1) * 100, 1)
                surface.append({
                    'strike': _safe(row['strike']),
                    'moneyness': moneyness,
                    'dte': dte,
                    'expiration': exp,
                    'iv': round(iv * 100, 1),
                    'type': 'call',
                    'oi': int(_safe(row.get('openInterest', 0))),
                })

        for _, row in chain_data['puts'].iterrows():
            iv = _safe(row.get('impliedVolatility', 0))
            if iv > 0.001 and iv < 5:
                moneyness = round((_safe(row['strike']) / spot - 1) * 100, 1)
                surface.append({
                    'strike': _safe(row['strike']),
                    'moneyness': moneyness,
                    'dte': dte,
                    'expiration': exp,
                    'iv': round(iv * 100, 1),
                    'type': 'put',
                    'oi': int(_safe(row.get('openInterest', 0))),
                })

    return {
        'spot': round(spot, 2),
        'surface': surface,
        'expirations': all_data['expirations'],
    }


# =========================================================================
# P/C Ratios, Max Pain, OI Summary
# =========================================================================

def compute_summary(symbol):
    """Compute P/C ratios, max pain, OI summary across all expirations."""
    all_data = get_all_chains(symbol)
    if 'error' in all_data:
        return all_data

    spot = all_data['spot']
    per_exp = []

    for exp, chain_data in all_data['chains'].items():
        calls = chain_data['calls']
        puts = chain_data['puts']

        call_oi = _safe(calls['openInterest'].fillna(0).sum())
        put_oi = _safe(puts['openInterest'].fillna(0).sum())
        call_vol = _safe(calls['volume'].fillna(0).sum())
        put_vol = _safe(puts['volume'].fillna(0).sum())
        pc_oi = put_oi / call_oi if call_oi > 0 else 0
        pc_vol = put_vol / call_vol if call_vol > 0 else 0

        # Max pain: strike where total value of options is minimized
        all_strikes = sorted(set(calls['strike'].tolist() + puts['strike'].tolist()))
        min_pain = float('inf')
        max_pain_strike = spot

        for strike in all_strikes:
            pain = 0
            for _, r in calls.iterrows():
                if strike > r['strike']:
                    pain += (strike - r['strike']) * (r.get('openInterest', 0) or 0)
            for _, r in puts.iterrows():
                if strike < r['strike']:
                    pain += (r['strike'] - strike) * (r.get('openInterest', 0) or 0)
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = strike

        dte = max((pd.Timestamp(exp) - pd.Timestamp.now()).days, 0)
        per_exp.append({
            'expiration': exp,
            'dte': dte,
            'call_oi': int(call_oi),
            'put_oi': int(put_oi),
            'call_vol': int(call_vol),
            'put_vol': int(put_vol),
            'pc_oi': round(pc_oi, 2),
            'pc_vol': round(pc_vol, 2),
            'max_pain': max_pain_strike,
        })

    total_call_oi = sum(e['call_oi'] for e in per_exp)
    total_put_oi = sum(e['put_oi'] for e in per_exp)

    return {
        'spot': round(spot, 2),
        'total_call_oi': total_call_oi,
        'total_put_oi': total_put_oi,
        'total_pc_oi': round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0,
        'per_expiration': per_exp,
    }


# =========================================================================
# GEX (Gamma Exposure)
# =========================================================================

def compute_gex(symbol, expiration=None, risk_free=0.045, max_dte=45):
    """
    Compute Gamma Exposure (GEX) per strike.
    - Call OI: dealers assumed long → positive gamma
    - Put OI: dealers assumed short → negative gamma
    - Net GEX = call_gex - put_gex per strike
    """
    if expiration:
        exps = [expiration]
        data = get_chain(symbol, expiration)
        if 'error' in data:
            return data
        spot = data['spot']
        chains = {expiration: data}
    else:
        all_data = get_all_chains(symbol)
        if 'error' in all_data:
            return all_data
        spot = all_data['spot']
        chains = all_data['chains']
        exps = all_data['expirations']

    now = pd.Timestamp.now()
    gex_by_strike = {}

    for exp, chain_data in chains.items():
        exp_date = pd.Timestamp(exp)
        dte = max((exp_date - now).days, 1)
        # Filter: skip expirations beyond max_dte (unless specific exp requested)
        if expiration is None and max_dte and dte > max_dte:
            continue
        T = dte / 365

        for _, row in chain_data['calls'].iterrows():
            strike = _safe(row['strike'])
            iv = _safe(row.get('impliedVolatility', 0))
            oi = _safe(row.get('openInterest', 0))
            if iv <= 0.001 or iv > 5 or oi <= 0:
                continue
            gamma = bs_gamma(spot, strike, T, risk_free, iv)
            gex = gamma * oi * 100 * spot * spot  # S^2 = dollar GEX per 1% move
            gex_by_strike.setdefault(strike, {'call_gex': 0, 'put_gex': 0})
            gex_by_strike[strike]['call_gex'] += gex

        for _, row in chain_data['puts'].iterrows():
            strike = _safe(row['strike'])
            iv = _safe(row.get('impliedVolatility', 0))
            oi = _safe(row.get('openInterest', 0))
            if iv <= 0.001 or iv > 5 or oi <= 0:
                continue
            gamma = bs_gamma(spot, strike, T, risk_free, iv)
            gex = gamma * oi * 100 * spot * spot
            gex_by_strike.setdefault(strike, {'call_gex': 0, 'put_gex': 0})
            gex_by_strike[strike]['put_gex'] -= gex

    # Build result sorted by strike
    strikes = sorted(gex_by_strike.keys())
    result_strikes = []
    for s in strikes:
        g = gex_by_strike[s]
        net = g['call_gex'] + g['put_gex']
        result_strikes.append({
            'strike': s,
            'call_gex': round(g['call_gex']),
            'put_gex': round(g['put_gex']),
            'net_gex': round(net),
        })

    # Find GEX flip point (where net GEX crosses zero)
    flip_strike = None
    for i in range(1, len(result_strikes)):
        prev = result_strikes[i-1]['net_gex']
        curr = result_strikes[i]['net_gex']
        if prev * curr < 0:  # sign change
            # Linear interpolation
            s1, s2 = result_strikes[i-1]['strike'], result_strikes[i]['strike']
            flip_strike = round(s1 + (s2 - s1) * abs(prev) / (abs(prev) + abs(curr)), 1)
            break

    # Key levels
    max_pos = max(result_strikes, key=lambda x: x['net_gex']) if result_strikes else None
    max_neg = min(result_strikes, key=lambda x: x['net_gex']) if result_strikes else None

    return {
        'spot': round(spot, 2),
        'strikes': result_strikes,
        'flip_strike': flip_strike,
        'max_positive_strike': max_pos['strike'] if max_pos else None,
        'max_negative_strike': max_neg['strike'] if max_neg else None,
        'total_gex': sum(s['net_gex'] for s in result_strikes),
    }
