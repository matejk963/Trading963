"""
Liquidity Indicator Calculations
Core calculation functions for rate of change, Z-scores, scoring, and aggregation
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# RATE OF CHANGE CALCULATIONS
# =============================================================================

def calculate_roc(series: pd.Series, periods: int = 252) -> pd.Series:
    """
    Calculate rate of change over N periods

    Args:
        series: Price/value series
        periods: Number of periods (252 trading days ~ 12 months)

    Returns:
        Rate of change as percentage (e.g., 0.05 = 5%)
    """
    return series.pct_change(periods=periods)


def calculate_roc_12m(series: pd.Series) -> pd.Series:
    """Calculate 12-month (252 trading day) rate of change"""
    return calculate_roc(series, periods=252)


def calculate_roc_29m(series: pd.Series) -> pd.Series:
    """Calculate 29-month rate of change (per Howell spec for unemployment)"""
    return calculate_roc(series, periods=29 * 21)  # ~21 trading days per month


def calculate_yoy(series: pd.Series) -> pd.Series:
    """
    Calculate year-over-year change for monthly data
    Uses 12-period shift for monthly frequency
    """
    return series.pct_change(periods=12)


# =============================================================================
# Z-SCORE CALCULATIONS
# =============================================================================

def calculate_rolling_zscore(series: pd.Series, window: int = 1260) -> pd.Series:
    """
    Calculate Z-score with rolling window

    Args:
        series: Input series
        window: Rolling window size (1260 trading days ~ 5 years)

    Returns:
        Z-score series: (value - rolling_mean) / rolling_std
    """
    rolling_mean = series.rolling(window=window, min_periods=window//2).mean()
    rolling_std = series.rolling(window=window, min_periods=window//2).std()

    # Avoid division by zero
    rolling_std = rolling_std.replace(0, np.nan)

    return (series - rolling_mean) / rolling_std


def calculate_zscore_5y(series: pd.Series) -> pd.Series:
    """Calculate Z-score with 5-year rolling window"""
    return calculate_rolling_zscore(series, window=1260)


# =============================================================================
# CPI MOMENTUM CALCULATION
# =============================================================================

def calculate_cpi_momentum(cpi_series: pd.Series) -> pd.Series:
    """
    Calculate CPI momentum: 3-month annualized vs 12-month

    Positive momentum = inflation accelerating = bearish
    Negative momentum = inflation decelerating = bullish

    Args:
        cpi_series: CPI index values (not % change)

    Returns:
        Momentum series (3m ann. - 12m)
    """
    # 3-month change, annualized
    change_3m = cpi_series.pct_change(periods=3)
    annualized_3m = (1 + change_3m) ** 4 - 1  # Compound to annual

    # 12-month change
    change_12m = cpi_series.pct_change(periods=12)

    # Momentum = difference (negative = deceleration = bullish)
    momentum = annualized_3m - change_12m

    return momentum


# =============================================================================
# DERIVED SERIES CALCULATIONS
# =============================================================================

def calculate_net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    """
    Calculate Fed Net Liquidity = WALCL - TGA - RRP

    This represents actual liquidity available in the system
    """
    # Align series (forward fill for different frequencies)
    df = pd.DataFrame({'WALCL': walcl, 'TGA': tga, 'RRP': rrp})
    df = df.ffill()

    return df['WALCL'] - df['TGA'] - df['RRP']


def calculate_real_rate(fed_funds: pd.Series, cpi_yoy: pd.Series) -> pd.Series:
    """
    Calculate Real Policy Rate = Fed Funds - CPI YoY

    Negative real rate = stimulative = bullish
    Positive real rate = restrictive = bearish
    """
    df = pd.DataFrame({'FF': fed_funds, 'CPI': cpi_yoy})
    df = df.ffill()

    return df['FF'] - df['CPI']


def calculate_yield_curve(dgs10: pd.Series, dgs2: pd.Series) -> pd.Series:
    """
    Calculate Yield Curve = 10Y - 2Y spread

    Positive (steep) = bullish
    Negative (inverted) = bearish
    """
    df = pd.DataFrame({'DGS10': dgs10, 'DGS2': dgs2})
    df = df.ffill()

    return df['DGS10'] - df['DGS2']


def calculate_sofr_effr_spread(sofr: pd.Series, effr: pd.Series) -> pd.Series:
    """
    Calculate SOFR - EFFR spread in basis points

    Tight spread (<5bp) = normal = bullish
    Wide spread (>15bp) = repo stress = bearish
    """
    df = pd.DataFrame({'SOFR': sofr, 'EFFR': effr})
    df = df.ffill()

    return (df['SOFR'] - df['EFFR']) * 100  # Convert to basis points


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================

def score_indicator_roc(value: float, bullish_threshold: float, bearish_threshold: float,
                        invert: bool = False) -> int:
    """
    Score rate-of-change indicator

    Args:
        value: ROC value
        bullish_threshold: Value above which is bullish
        bearish_threshold: Value below which is bearish
        invert: If True, invert the scoring (for drains like TGA, RRP)

    Returns:
        +1 (bullish), 0 (neutral), or -1 (bearish)
    """
    if pd.isna(value):
        return 0

    if value > bullish_threshold:
        score = 1
    elif value < bearish_threshold:
        score = -1
    else:
        score = 0

    return -score if invert else score


def score_indicator_level(value: float, bullish_threshold: float, bearish_threshold: float,
                          neutral_low: float = None, neutral_high: float = None,
                          invert: bool = False) -> int:
    """
    Score level-based indicator

    Args:
        value: Current level
        bullish_threshold: Below this is bullish (or above if not inverted)
        bearish_threshold: Above this is bearish (or below if not inverted)
        neutral_low: Lower bound of neutral zone
        neutral_high: Upper bound of neutral zone
        invert: If True, lower values are bullish

    Returns:
        +1 (bullish), 0 (neutral), or -1 (bearish)
    """
    if pd.isna(value):
        return 0

    if invert:
        # Lower is better (e.g., VIX, credit spreads)
        if value < bullish_threshold:
            score = 1
        elif value > bearish_threshold:
            score = -1
        else:
            score = 0
    else:
        # Higher is better (e.g., yield curve steepness)
        if value > bullish_threshold:
            score = 1
        elif value < bearish_threshold:
            score = -1
        else:
            score = 0

    return score


def score_indicator(value: float, config: dict) -> int:
    """
    Score an indicator based on its configuration

    Args:
        value: Current indicator value
        config: Indicator configuration dict

    Returns:
        +1, 0, or -1
    """
    signal_type = config.get('signal_type', 'level')
    invert = config.get('invert', False)

    if signal_type in ['roc_12m', 'roc_29m', 'yoy']:
        return score_indicator_roc(
            value,
            config.get('bullish_threshold', 0),
            config.get('bearish_threshold', 0),
            invert
        )
    elif signal_type == 'level':
        return score_indicator_level(
            value,
            config.get('bullish_threshold', 0),
            config.get('bearish_threshold', 0),
            config.get('neutral_low'),
            config.get('neutral_high'),
            invert
        )
    elif signal_type == 'momentum':
        # Negative momentum (deceleration) = bullish
        if pd.isna(value):
            return 0
        if value < 0:  # Decelerating
            return 1
        elif value > 0:  # Accelerating
            return -1
        return 0
    else:
        # Component series - not scored directly
        return 0


# =============================================================================
# LAYER AGGREGATION
# =============================================================================

def calculate_layer_scores(raw_data: pd.DataFrame, layer_config: dict) -> pd.DataFrame:
    """
    Calculate scores for all indicators in a layer

    Args:
        raw_data: DataFrame with raw FRED series
        layer_config: Layer indicator configuration dict

    Returns:
        DataFrame with columns: indicator_name, raw_value, transformed_value, score
    """
    results = {}

    for indicator_id, config in layer_config.items():
        fred_code = config.get('fred_code')
        signal_type = config.get('signal_type', 'level')

        # Skip derived indicators (handled separately)
        if config.get('derived', False):
            continue

        # Skip component indicators (used in derived calculations)
        if signal_type == 'component':
            continue

        if fred_code not in raw_data.columns:
            logger.warning(f"Missing data for {indicator_id} ({fred_code})")
            continue

        series = raw_data[fred_code].dropna()
        if series.empty:
            continue

        # Transform based on signal type
        if signal_type == 'roc_12m':
            transformed = calculate_roc_12m(series)
        elif signal_type == 'roc_29m':
            transformed = calculate_roc_29m(series)
        elif signal_type == 'yoy':
            transformed = calculate_yoy(series)
        elif signal_type == 'momentum':
            transformed = calculate_cpi_momentum(series)
        else:
            transformed = series

        # Get latest value and score
        latest_raw = series.iloc[-1]
        latest_transformed = transformed.dropna().iloc[-1] if not transformed.dropna().empty else np.nan
        latest_score = score_indicator(latest_transformed, config)

        results[indicator_id] = {
            'name': config['name'],
            'raw_value': latest_raw,
            'transformed_value': latest_transformed,
            'score': latest_score,
            'signal_type': signal_type,
            'invert': config.get('invert', False),
            'counterintuitive': config.get('counterintuitive', False)
        }

    return pd.DataFrame(results).T


def aggregate_layer_score(layer_results: pd.DataFrame) -> int:
    """
    Aggregate individual indicator scores into layer score

    Args:
        layer_results: DataFrame from calculate_layer_scores

    Returns:
        Sum of all indicator scores
    """
    return int(layer_results['score'].sum())


def get_layer_direction(layer_score: float, threshold: float = 0.5) -> int:
    """
    Convert layer score to direction for regime classification

    Args:
        layer_score: Aggregate layer score
        threshold: Threshold for positive/negative classification

    Returns:
        +1 (positive), 0 (neutral), or -1 (negative)
    """
    if layer_score > threshold:
        return 1
    elif layer_score < -threshold:
        return -1
    return 0


# =============================================================================
# COMPOSITE SCORE
# =============================================================================

def calculate_composite_score(l1_score: float, l2a_score: float, l2b_score: float,
                              weights: dict = None) -> float:
    """
    Calculate weighted composite liquidity score

    Args:
        l1_score: Layer 1 (CB) score
        l2a_score: Layer 2a (Wholesale) score
        l2b_score: Layer 2b (Economic) score
        weights: Optional weight override (default 40/35/25)

    Returns:
        Weighted composite score
    """
    if weights is None:
        weights = {'L1': 0.40, 'L2a': 0.35, 'L2b': 0.25}

    return (l1_score * weights['L1'] +
            l2a_score * weights['L2a'] +
            l2b_score * weights['L2b'])


def normalize_layer_score(score: float, score_range: Tuple[int, int]) -> float:
    """
    Normalize layer score to -1 to +1 range

    Args:
        score: Raw layer score
        score_range: (min, max) possible score

    Returns:
        Normalized score between -1 and +1
    """
    min_score, max_score = score_range

    if score >= 0:
        return score / max_score if max_score != 0 else 0
    else:
        return score / abs(min_score) if min_score != 0 else 0


# =============================================================================
# HISTORICAL CALCULATIONS
# =============================================================================

def calculate_historical_scores(raw_data: pd.DataFrame, layer_config: dict) -> pd.DataFrame:
    """
    Calculate historical score time series for a layer

    Args:
        raw_data: DataFrame with raw FRED series (DatetimeIndex)
        layer_config: Layer indicator configuration

    Returns:
        DataFrame with historical scores (columns = indicators, index = dates)
    """
    score_series = {}

    for indicator_id, config in layer_config.items():
        fred_code = config.get('fred_code')
        signal_type = config.get('signal_type', 'level')

        if config.get('derived', False) or signal_type == 'component':
            continue

        if fred_code not in raw_data.columns:
            continue

        series = raw_data[fred_code].dropna()

        # Transform
        if signal_type == 'roc_12m':
            transformed = calculate_roc_12m(series)
        elif signal_type == 'roc_29m':
            transformed = calculate_roc_29m(series)
        elif signal_type == 'yoy':
            transformed = calculate_yoy(series)
        elif signal_type == 'momentum':
            transformed = calculate_cpi_momentum(series)
        else:
            transformed = series

        # Score each value
        scores = transformed.apply(lambda x: score_indicator(x, config))
        score_series[indicator_id] = scores

    return pd.DataFrame(score_series)


def calculate_historical_layer_totals(raw_data: pd.DataFrame,
                                       l1_config: dict,
                                       l2a_config: dict,
                                       l2b_config: dict) -> pd.DataFrame:
    """
    Calculate historical layer totals over time

    Returns:
        DataFrame with columns: L1, L2a, L2b, Composite
    """
    l1_scores = calculate_historical_scores(raw_data, l1_config)
    l2a_scores = calculate_historical_scores(raw_data, l2a_config)
    l2b_scores = calculate_historical_scores(raw_data, l2b_config)

    # Sum across indicators for each date (min_count=1 means return NaN only if ALL are NaN)
    result = pd.DataFrame({
        'L1': l1_scores.sum(axis=1, skipna=True, min_count=1),
        'L2a': l2a_scores.sum(axis=1, skipna=True, min_count=1),
        'L2b': l2b_scores.sum(axis=1, skipna=True, min_count=1)
    })

    # Fill any remaining NaN with 0 (neutral) to allow composite calculation
    result = result.fillna(0)

    # Calculate composite
    result['Composite'] = result.apply(
        lambda row: calculate_composite_score(row['L1'], row['L2a'], row['L2b']),
        axis=1
    )

    # Only drop rows where we have no data at all (before 2000)
    return result.loc[result.index >= '2003-01-01']  # Start when Fed balance sheet data begins
