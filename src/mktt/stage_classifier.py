"""
MKTT Stage Classifier
Weinstein 4-stage classification (O'Neil / Minervini / Zanger / Kullamägi synthesis)

Optimized: vectorized wide-DataFrame operations, in-memory caching.
"""
import pandas as pd
import numpy as np
import time
from pathlib import Path

CACHE_DIR = Path(__file__).parent / 'cache'
CACHE_DIR.mkdir(exist_ok=True)

STAGE_LABELS = {0: 'Unclassified', 1: 'Basing', 2: 'Uptrend', 3: 'Topping', 4: 'Declining'}
STAGE_ACTIONS = {0: 'No Trade', 1: 'Watch', 2: 'Long', 3: 'Reduce', 4: 'Short'}

# In-memory cache
_cache = {}
_cache_time = {}
CACHE_TTL = 300  # 5 minutes


def _get_cached(key):
    if key in _cache and (time.time() - _cache_time.get(key, 0)) < CACHE_TTL:
        return _cache[key]
    return None


def _set_cached(key, val):
    _cache[key] = val
    _cache_time[key] = time.time()


# =============================================================================
# Vectorized Computation (all tickers at once)
# =============================================================================

def compute_all_derived_vectorized(close_df, high_df, low_df, volume_df, spy_close):
    """
    Compute all derived fields for ALL tickers at once using wide DataFrames.
    Much faster than per-ticker loop — pandas vectorized rolling.

    Returns dict of wide DataFrames, each (dates × tickers).
    """
    # Filter to tickers with enough data (>200 rows non-null)
    valid_counts = close_df.notna().sum()
    valid_tickers = valid_counts[valid_counts > 200].index.tolist()

    close = close_df[valid_tickers].copy()
    high = high_df[[t for t in valid_tickers if t in high_df.columns]].copy()
    low = low_df[[t for t in valid_tickers if t in low_df.columns]].copy()
    volume = volume_df[[t for t in valid_tickers if t in volume_df.columns]].copy()

    # Common tickers across all fields
    common = list(set(close.columns) & set(high.columns) & set(low.columns) & set(volume.columns))
    close, high, low, volume = close[common], high[common], low[common], volume[common]

    d = {}

    # MAs (vectorized across all tickers)
    d['ma_50'] = close.rolling(50).mean()
    d['ma_150'] = close.rolling(150).mean()
    d['ma_200'] = close.rolling(200).mean()

    # MA slopes
    d['ma_150_slope_21d'] = d['ma_150'].diff(21)
    d['ma_150_slope_pct'] = d['ma_150'].pct_change(21) * 12  # Annualized

    # 52w high/low
    d['high_52w'] = close.rolling(252, min_periods=126).max()
    d['low_52w'] = close.rolling(252, min_periods=126).min()

    # Distance ratios
    d['dist_52w_high'] = close / d['high_52w']
    d['dist_52w_low'] = close / d['low_52w']

    # RS line vs SPY
    spy_aligned = spy_close.reindex(close.index).ffill()
    rs_line = close.div(spy_aligned, axis=0)
    d['rs_line'] = rs_line

    # Mansfield RS
    rs_sma = rs_line.rolling(252, min_periods=126).mean()
    d['mansfield_rs'] = (rs_line / rs_sma - 1) * 100

    # ADR
    daily_range = (high / low - 1) * 100
    d['adr_20'] = daily_range.rolling(20).mean()

    # Volume MA
    d['volume_ma_50'] = volume.rolling(50).mean()

    # Distribution days (last 25)
    down_day = close < close.shift(1)
    above_avg_vol = volume > d['volume_ma_50']
    dist_day = (down_day & above_avg_vol).astype(float)
    d['distribution_days_25'] = dist_day.rolling(25).sum()

    # RS rank (cross-sectional, 6-month returns)
    returns_6m = close.pct_change(126)
    d['rs_rank'] = returns_6m.rank(axis=1, pct=True) * 100

    d['close'] = close
    d['volume'] = volume

    return d, common


# =============================================================================
# Stage Classification (vectorized)
# =============================================================================

def classify_all_stages(d):
    """
    Classify all tickers at once. Each condition is a wide boolean DataFrame.
    Returns wide DataFrame of stage labels (0-4).
    """
    close = d['close']

    stage2 = (
        (close > d['ma_150']) &
        (close > d['ma_50']) &
        (d['ma_50'] > d['ma_150']) &
        (d['ma_150'] > d['ma_200']) &
        (d['ma_150_slope_21d'] > 0) &
        (d['dist_52w_high'] >= 0.75) &
        (d['dist_52w_low'] >= 1.25) &
        (d['rs_rank'] >= 70) &
        (d['distribution_days_25'] < 5)
    )

    stage4 = (
        (close < d['ma_150']) &
        (close < d['ma_50']) &
        (d['ma_50'] < d['ma_150']) &
        (d['ma_150'] < d['ma_200']) &
        (d['ma_150_slope_21d'] < 0) &
        (d['dist_52w_low'] <= 1.25) &
        (d['dist_52w_high'] < 0.75) &
        (d['rs_rank'] < 30)
    )

    ma150_decel = d['ma_150_slope_21d'] < d['ma_150_slope_21d'].shift(21)
    rs_rollover = d['rs_line'] < d['rs_line'].rolling(50).max().shift(10)
    adr_expanding = d['adr_20'] > d['adr_20'].rolling(60).mean()

    stage3 = (
        ma150_decel &
        (d['dist_52w_high'] >= 0.75) &
        rs_rollover &
        (d['distribution_days_25'] >= 5) &
        adr_expanding
    )

    adr_contracting = d['adr_20'] < d['adr_20'].rolling(40).mean()
    stage1 = (
        (d['ma_150_slope_pct'].abs() < 0.05) &
        (close >= 0.90 * d['ma_150']) &
        (close <= 1.10 * d['ma_150']) &
        (d['dist_52w_low'] >= 1.30) &
        (d['dist_52w_high'] <= 0.70) &
        adr_contracting &
        (d['rs_rank'] >= 40) & (d['rs_rank'] <= 70)
    )

    # Priority: S2 > S4 > S3 > S1 > 0
    stages = pd.DataFrame(0, index=close.index, columns=close.columns)
    stages[stage1] = 1
    stages[stage3] = 3
    stages[stage4] = 4
    stages[stage2] = 2

    return stages


# =============================================================================
# Result Builder
# =============================================================================

def build_results(d, stages, min_price=5):
    """
    Extract latest row per ticker from the vectorized results.
    Returns a DataFrame ready for display.
    """
    close = d['close']
    tickers = close.columns.tolist()

    # Get latest valid row index per ticker
    last_idx = close.apply(lambda s: s.last_valid_index())

    results = []
    for ticker in tickers:
        li = last_idx[ticker]
        if li is None:
            continue

        price = close.at[li, ticker]
        if pd.isna(price) or price < min_price:
            continue

        ma150 = d['ma_150'].at[li, ticker]
        ma200 = d['ma_200'].at[li, ticker]
        rs_rank = d['rs_rank'].at[li, ticker]

        if pd.isna(ma150) or pd.isna(ma200) or pd.isna(rs_rank):
            continue

        stage = int(stages.at[li, ticker])

        # Days in stage
        ticker_stages = stages[ticker].dropna()
        if len(ticker_stages) > 1:
            changes = ticker_stages != ticker_stages.shift(1)
            change_dates = changes[changes].index
            if len(change_dates) > 0:
                days_in_stage = (li - change_dates[-1]).days
            else:
                days_in_stage = (li - ticker_stages.index[0]).days
        else:
            days_in_stage = 0

        # Transition (compare last 5 bars)
        transition = None
        if len(ticker_stages) > 5:
            current = ticker_stages.iloc[-1]
            prev_mode = ticker_stages.iloc[-6:-1].mode()
            if not prev_mode.empty:
                prev = prev_mode.iloc[0]
                if prev != current and current != 0 and prev != 0:
                    transition = f"{int(prev)}->{int(current)}"

        # Previous close for change%
        prev_idx = close.index.get_loc(li)
        change_pct = 0
        if prev_idx > 0:
            prev_close = close.iloc[prev_idx - 1][ticker]
            if pd.notna(prev_close) and prev_close > 0:
                change_pct = (price / prev_close - 1) * 100

        vol_ma = d['volume_ma_50'].at[li, ticker]
        adv_dollar = price * vol_ma if pd.notna(vol_ma) else 0

        results.append({
            'Symbol': ticker,
            'Stage': stage,
            'StageLabel': STAGE_LABELS.get(stage, '?'),
            'Action': STAGE_ACTIONS.get(stage, '?'),
            'DaysInStage': days_in_stage,
            'Price': price,
            'Change%': change_pct,
            'MA50': d['ma_50'].at[li, ticker],
            'MA150': ma150,
            'MA200': ma200,
            'MA150_Slope': d['ma_150_slope_21d'].at[li, ticker],
            'RS_Rank': rs_rank,
            'Mansfield_RS': d['mansfield_rs'].at[li, ticker],
            'DistDays25': d['distribution_days_25'].at[li, ticker],
            'ADR20': d['adr_20'].at[li, ticker],
            'Dist52wHigh%': (1 - d['dist_52w_high'].at[li, ticker]) * 100,
            'Dist52wLow%': (d['dist_52w_low'].at[li, ticker] - 1) * 100,
            'ADV_Dollar': adv_dollar,
            'Transition': transition,
        })

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values('RS_Rank', ascending=False)
    return result_df


# =============================================================================
# Main Entry Point
# =============================================================================

def run_stage_from_local_db(min_turnover=500000, min_price=5):
    """
    Run stage classification from local Parquet DB.
    Cached in memory for 5 minutes.
    """
    cache_key = f'stages_{min_turnover}_{min_price}'
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    from data_manager import load_universe, load_prices, load_spy

    t0 = time.time()

    universe = load_universe()
    if universe is None:
        return pd.DataFrame()

    if 'turnover' in universe.columns:
        universe = universe[universe['turnover'] >= min_turnover]

    tickers = universe['symbol'].tolist()
    if not tickers:
        return pd.DataFrame()

    # Load all price data (parquet columnar read — fast)
    close_df = load_prices('close')
    high_df = load_prices('high')
    low_df = load_prices('low')
    volume_df = load_prices('volume')
    spy_df = load_spy()

    if close_df is None or spy_df is None:
        return pd.DataFrame()

    spy_close = spy_df['Close']

    # Filter to requested tickers
    available = [t for t in tickers if t in close_df.columns]
    close_df = close_df[available]
    high_df = high_df[[t for t in available if t in high_df.columns]]
    low_df = low_df[[t for t in available if t in low_df.columns]]
    volume_df = volume_df[[t for t in available if t in volume_df.columns]]

    t1 = time.time()

    # Vectorized computation
    d, common_tickers = compute_all_derived_vectorized(close_df, high_df, low_df, volume_df, spy_close)

    t2 = time.time()

    # Vectorized classification
    stages = classify_all_stages(d)

    t3 = time.time()

    # Build result rows
    result = build_results(d, stages, min_price=min_price)

    t4 = time.time()
    print(f"  Stage classifier: load={t1-t0:.1f}s compute={t2-t1:.1f}s classify={t3-t2:.1f}s build={t4-t3:.1f}s total={t4-t0:.1f}s ({len(result)} stocks)")

    _set_cached(cache_key, result)
    return result


def clear_cache():
    """Clear all in-memory caches (called after data update)"""
    _cache.clear()
    _cache_time.clear()


def run_stage_classification(tickers, min_adv_dollar=500000, min_price=5):
    """Legacy wrapper — use run_stage_from_local_db instead."""
    return run_stage_from_local_db(min_turnover=min_adv_dollar, min_price=min_price)


def get_stage_distribution(classified_df):
    """Get stage distribution summary"""
    if classified_df.empty:
        return {}
    counts = classified_df['Stage'].value_counts().to_dict()
    total = len(classified_df)
    dist = {}
    for stage in [0, 1, 2, 3, 4]:
        count = counts.get(stage, 0)
        dist[stage] = {
            'count': count,
            'pct': count / total * 100 if total > 0 else 0,
            'label': STAGE_LABELS.get(stage, '?'),
            'action': STAGE_ACTIONS.get(stage, '?'),
        }
    return dist
