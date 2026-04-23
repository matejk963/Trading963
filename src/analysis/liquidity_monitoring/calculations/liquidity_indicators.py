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
    """Calculate 12-month rate of change (auto-detects frequency)"""
    # Detect frequency from data
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:  # Monthly
            periods = 12
        elif avg_gap > 4:  # Weekly
            periods = 52
        else:  # Daily
            periods = 252
    else:
        periods = 12  # Default to monthly for short series
    return calculate_roc(series, periods=periods)


def calculate_roc_29m(series: pd.Series) -> pd.Series:
    """Calculate 29-month rate of change (per Howell spec for unemployment)"""
    # Detect frequency from data
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:  # Monthly
            periods = 29
        elif avg_gap > 4:  # Weekly
            periods = 29 * 4  # ~4 weeks per month
        else:  # Daily
            periods = 29 * 21  # ~21 trading days per month
    else:
        periods = 29  # Default to monthly
    return calculate_roc(series, periods=periods)


def calculate_roc_4w(series: pd.Series) -> pd.Series:
    """Calculate 4-week rate of change (auto-detects frequency)"""
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:  # Monthly
            periods = 1  # ~1 month
        elif avg_gap > 4:  # Weekly
            periods = 4
        else:  # Daily
            periods = 20
    else:
        periods = 4
    return calculate_roc(series, periods=periods)


def calculate_roc_18m(series: pd.Series) -> pd.Series:
    """Calculate 18-month rate of change (Boucher spec for ISM Prices)"""
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:  # Monthly
            periods = 18
        elif avg_gap > 4:  # Weekly
            periods = 78  # ~18 months
        else:  # Daily
            periods = 378
    else:
        periods = 18
    return calculate_roc(series, periods=periods)


def calculate_yoy(series: pd.Series) -> pd.Series:
    """
    Calculate year-over-year change for monthly data
    Uses 12-period shift for monthly frequency
    """
    return series.pct_change(periods=12)


# =============================================================================
# Z-SCORE CALCULATIONS
# =============================================================================

def calculate_rolling_zscore(series: pd.Series, window: int = 1260,
                             min_periods: int = None) -> pd.Series:
    """
    Calculate Z-score with rolling window

    Args:
        series: Input series
        window: Rolling window size (1260 trading days ~ 5 years)
        min_periods: Minimum periods required (default: window//4 for earlier data)

    Returns:
        Z-score series: (value - rolling_mean) / rolling_std
    """
    if min_periods is None:
        min_periods = max(window // 4, 60)  # At least 1.25 years or 60 periods

    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()

    # Avoid division by zero
    rolling_std = rolling_std.replace(0, np.nan)

    zscore = (series - rolling_mean) / rolling_std

    # Clip extreme values to avoid inf/-inf
    zscore = zscore.clip(-10, 10)

    return zscore


def calculate_zscore_5y(series: pd.Series) -> pd.Series:
    """Calculate Z-score with 5-year rolling window"""
    return calculate_rolling_zscore(series, window=1260)


# =============================================================================
# CONTINUOUS Z-SCORE CALCULATIONS
# =============================================================================

def calculate_yoy_zscore(series: pd.Series, yoy_periods: int = 252,
                         zscore_window: int = 1260) -> pd.Series:
    """
    Calculate YoY change then normalize with rolling Z-score.

    Args:
        series: Input price/value series
        yoy_periods: Periods for YoY calculation (252 for daily, 12 for monthly)
        zscore_window: Rolling window for Z-score (1260 ~ 5 years daily)

    Returns:
        Continuous Z-score normalized YoY in typical -3 to +3 range
    """
    yoy = series.pct_change(periods=yoy_periods)
    return calculate_rolling_zscore(yoy, window=zscore_window)


def calculate_continuous_indicator_score(series: pd.Series, config: dict) -> pd.Series:
    """
    Calculate continuous Z-scored measure for any indicator.
    Handles inversion and different signal types.

    Args:
        series: Raw indicator series
        config: Indicator configuration dict

    Returns:
        Continuous Z-score series (typically -3 to +3)
    """
    signal_type = config.get('signal_type', 'level')
    invert = config.get('invert', False)

    # Detect frequency from series (daily, weekly, or monthly)
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:  # Monthly
            yoy_periods = 12
            zscore_window = 60  # 5 years monthly
        elif avg_gap > 4:  # Weekly
            yoy_periods = 52
            zscore_window = 260  # 5 years weekly
        else:  # Daily
            yoy_periods = 252
            zscore_window = 1260  # 5 years daily
    else:
        # Default to monthly for short series
        yoy_periods = 12
        zscore_window = 60

    if signal_type in ['roc_12m', 'roc_29m', 'roc_4w', 'roc_18m', 'yoy']:
        # Already a change measure, just Z-score it
        if signal_type == 'roc_29m':
            change = calculate_roc_29m(series)
        elif signal_type == 'roc_4w':
            change = calculate_roc_4w(series)
        elif signal_type == 'roc_18m':
            change = calculate_roc_18m(series)
        else:
            change = series.pct_change(periods=yoy_periods)
        zscore = calculate_rolling_zscore(change, window=zscore_window)

    elif signal_type == 'momentum':
        # CPI momentum - Z-score the momentum directly
        momentum = calculate_cpi_momentum(series)
        zscore = calculate_rolling_zscore(momentum, window=zscore_window)

    elif signal_type == 'level':
        # Level-based - Z-score the raw level directly
        # This answers "is current level high or low relative to history"
        # Better for indicators with regime changes (like RRP going 0 -> trillions)
        zscore = calculate_rolling_zscore(series, window=zscore_window)

    elif signal_type == 'level_change':
        # Level change - take YoY change then Z-score
        # For spreads/rates, use level change rather than % change
        if config.get('units') in ['percent', 'basis_points', 'index']:
            change = series.diff(periods=yoy_periods)
        else:
            change = series.pct_change(periods=yoy_periods)
        zscore = calculate_rolling_zscore(change, window=zscore_window)

    else:
        # Component - calculate YoY Z-score as default
        zscore = calculate_yoy_zscore(series, yoy_periods, zscore_window)

    # Apply inversion (positive Z-score becomes negative for drains)
    if invert:
        zscore = -zscore

    return zscore


def calculate_continuous_layer_scores(raw_data: pd.DataFrame,
                                       layer_config: dict) -> pd.DataFrame:
    """
    Calculate continuous Z-score normalized scores for all indicators in a layer.

    Args:
        raw_data: DataFrame with raw FRED series
        layer_config: Layer indicator configuration dict

    Returns:
        DataFrame with indicator columns, continuous Z-score values
    """
    score_series = {}

    for indicator_id, config in layer_config.items():
        fred_code = config.get('fred_code')
        signal_type = config.get('signal_type', 'level')

        # Handle derived indicators
        if config.get('derived', False):
            if indicator_id == 'net_liquidity':
                if all(c in raw_data.columns for c in ['WALCL', 'WTREGEN', 'RRPONTSYD']):
                    net_liq = calculate_net_liquidity(
                        raw_data['WALCL'],
                        raw_data['WTREGEN'],
                        raw_data['RRPONTSYD'],
                        smooth=True,
                        ema_span=10
                    )
                    if len(net_liq.dropna()) >= 50:
                        zscore = calculate_continuous_indicator_score(net_liq.dropna(), config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'real_policy_rate':
                if all(c in raw_data.columns for c in ['DFF', 'PCEPILFE']):
                    real_rate, zlb_flag = calculate_real_policy_rate(
                        raw_data['DFF'], raw_data['PCEPILFE']
                    )
                    real_rate_clean = real_rate.dropna()
                    if len(real_rate_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(real_rate_clean, config)
                        # Apply ZLB down-weighting if currently at ZLB
                        zlb_weight = config.get('zlb_weight', 0.5)
                        if not zlb_flag.empty and zlb_flag.iloc[-1]:
                            zscore = zscore * zlb_weight
                        score_series[indicator_id] = zscore

            elif indicator_id == 'mmf_deployed':
                if all(c in raw_data.columns for c in ['WRMFSL', 'RRPONTSYD']):
                    deployed = calculate_mmf_deployed(
                        raw_data['WRMFSL'], raw_data['RRPONTSYD']
                    )
                    deployed_clean = deployed.dropna()
                    if len(deployed_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(deployed_clean, config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'sofr_effr_spread':
                if all(c in raw_data.columns for c in ['SOFR', 'EFFR']):
                    spread = calculate_sofr_effr_spread(raw_data['SOFR'], raw_data['EFFR'])
                    spread_clean = spread.dropna()
                    if len(spread_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(spread_clean, config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'cpi_momentum':
                if 'CPIAUCSL' in raw_data.columns:
                    momentum = calculate_cpi_momentum(raw_data['CPIAUCSL'])
                    momentum_clean = momentum.dropna()
                    if len(momentum_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(momentum_clean, config)
                        score_series[indicator_id] = zscore

            continue

        # Skip component indicators (used in derived calculations)
        if signal_type == 'component':
            continue

        if fred_code not in raw_data.columns:
            logger.warning(f"Missing data for {indicator_id} ({fred_code})")
            continue

        series = raw_data[fred_code].dropna()
        if len(series) < 50:  # Need minimum data for Z-score
            continue

        # Calculate continuous Z-score
        zscore = calculate_continuous_indicator_score(series, config)
        score_series[indicator_id] = zscore

    # Combine all scores and forward-fill to align different frequencies
    if score_series:
        result = pd.DataFrame(score_series)
        # Forward-fill to propagate weekly/monthly values to daily index
        result = result.ffill()
        return result
    return pd.DataFrame()


def calculate_historical_continuous_totals(raw_data: pd.DataFrame,
                                            l1_config: dict,
                                            l2a_config: dict,
                                            l2b_config: dict) -> pd.DataFrame:
    """
    Calculate historical continuous layer scores.
    Layer total = mean of Z-scores (not sum of discrete).

    Args:
        raw_data: DataFrame with raw FRED series
        l1_config, l2a_config, l2b_config: Layer configurations

    Returns:
        DataFrame with L1, L2a, L2b, Composite as continuous values (-3 to +3 range)
    """
    l1_scores = calculate_continuous_layer_scores(raw_data, l1_config)
    l2a_scores = calculate_continuous_layer_scores(raw_data, l2a_config)
    l2b_scores = calculate_continuous_layer_scores(raw_data, l2b_config)

    # Mean across indicators (keeps on comparable scale)
    empty_dt_series = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    l1_mean = l1_scores.mean(axis=1, skipna=True) if not l1_scores.empty else empty_dt_series
    l2a_mean = l2a_scores.mean(axis=1, skipna=True) if not l2a_scores.empty else empty_dt_series
    l2b_mean = l2b_scores.mean(axis=1, skipna=True) if not l2b_scores.empty else empty_dt_series

    # Combine into DataFrame - this creates union of all indices
    result = pd.DataFrame({
        'L1': l1_mean,
        'L2a': l2a_mean,
        'L2b': l2b_mean
    })

    # Forward-fill to align different frequencies (monthly -> daily)
    result = result.ffill()

    # Fill remaining NaN with 0 (neutral) for composite calculation
    result_filled = result.fillna(0)

    # Calculate composite with same weights
    result['Composite'] = (
        result_filled['L1'] * 0.40 +
        result_filled['L2a'] * 0.35 +
        result_filled['L2b'] * 0.25
    )

    # Ensure index is DatetimeIndex (safe in case of empty layer)
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, errors='coerce')
        result = result[result.index.notna()]

    # Start from 2005 to have sufficient Z-score history
    cutoff = pd.Timestamp('2005-01-01')
    return result.loc[result.index >= cutoff]


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

def calculate_net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series,
                            smooth: bool = True, ema_span: int = 5) -> pd.Series:
    """
    Calculate Fed Net Liquidity = WALCL - TGA - RRP

    This represents actual liquidity available in the system

    Args:
        walcl: Fed Balance Sheet series
        tga: Treasury General Account series
        rrp: Reverse Repo series
        smooth: If True, apply EMA to raw data before combining
        ema_span: EMA span for smoothing (default 5)

    Returns:
        Net Liquidity series
    """
    # Align series (forward fill for different frequencies)
    df = pd.DataFrame({'WALCL': walcl, 'TGA': tga, 'RRP': rrp})
    df = df.ffill()

    if smooth:
        # Apply 5-period EMA to each raw series first
        df['WALCL'] = df['WALCL'].ewm(span=ema_span, adjust=False).mean()
        df['TGA'] = df['TGA'].ewm(span=ema_span, adjust=False).mean()
        df['RRP'] = df['RRP'].ewm(span=ema_span, adjust=False).mean()

    # Pre-2010: RRP was not a significant policy tool (sparse data, tiny values)
    # Use WALCL - TGA only for pre-2010, full formula post-2010
    cutoff = pd.Timestamp('2010-01-01')
    result = pd.Series(index=df.index, dtype=float)
    result[df.index < cutoff] = df.loc[df.index < cutoff, 'WALCL'] - df.loc[df.index < cutoff, 'TGA']
    result[df.index >= cutoff] = df.loc[df.index >= cutoff, 'WALCL'] - df.loc[df.index >= cutoff, 'TGA'] - df.loc[df.index >= cutoff, 'RRP']

    return result


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


def calculate_real_policy_rate(dff: pd.Series, core_pce: pd.Series,
                                zlb_threshold: float = 0.25) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate Real Policy Rate = DFF - Core PCE YoY

    Args:
        dff: Fed Funds Rate series
        core_pce: Core PCE Price Index (level, not YoY)
        zlb_threshold: Rate below which ZLB flag is set

    Returns:
        Tuple of (real_rate_series, zlb_flag_series)
    """
    # Calculate Core PCE YoY (12-month change)
    pce_yoy = core_pce.pct_change(periods=12) * 100  # As percentage

    df = pd.DataFrame({'FF': dff, 'PCE_YoY': pce_yoy})
    df = df.ffill()

    real_rate = df['FF'] - df['PCE_YoY']
    zlb_flag = df['FF'] <= zlb_threshold

    return real_rate, zlb_flag


def calculate_mmf_deployed(wrmfsl: pd.Series, rrpontsyd: pd.Series) -> pd.Series:
    """
    Calculate MMF Deployed Cash = WRMFSL - RRPONTSYD

    Rising deployed cash = liquidity entering private wholesale system.
    Rising total MMF with rising RRP = abundance but not transmitting.
    """
    df = pd.DataFrame({'MMF': wrmfsl, 'RRP': rrpontsyd})
    df = df.ffill()
    return df['MMF'] - df['RRP']


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

    if signal_type in ['roc_12m', 'roc_29m', 'roc_4w', 'roc_18m', 'yoy']:
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

        # Handle derived indicators
        if config.get('derived', False):
            series = None
            transformed = None

            if indicator_id == 'net_liquidity':
                if all(c in raw_data.columns for c in ['WALCL', 'WTREGEN', 'RRPONTSYD']):
                    series = calculate_net_liquidity(
                        raw_data['WALCL'], raw_data['WTREGEN'], raw_data['RRPONTSYD'],
                        smooth=True, ema_span=10
                    )
                    transformed = calculate_roc_12m(series)

            elif indicator_id == 'real_policy_rate':
                if all(c in raw_data.columns for c in ['DFF', 'PCEPILFE']):
                    series, _ = calculate_real_policy_rate(raw_data['DFF'], raw_data['PCEPILFE'])
                    transformed = series
                elif all(c in raw_data.columns for c in ['DFF', 'CPIAUCSL']):
                    # Fallback to CPI if Core PCE not available
                    cpi_yoy = calculate_yoy(raw_data['CPIAUCSL']) * 100
                    series = calculate_real_rate(raw_data['DFF'], cpi_yoy)
                    transformed = series

            elif indicator_id == 'sofr_effr_spread':
                if all(c in raw_data.columns for c in ['SOFR', 'EFFR']):
                    series = calculate_sofr_effr_spread(raw_data['SOFR'], raw_data['EFFR'])
                    transformed = series

            elif indicator_id == 'mmf_deployed':
                if all(c in raw_data.columns for c in ['WRMFSL', 'RRPONTSYD']):
                    series = calculate_mmf_deployed(raw_data['WRMFSL'], raw_data['RRPONTSYD'])
                    transformed = calculate_roc_12m(series)

            elif indicator_id == 'cpi_momentum':
                if 'CPIAUCSL' in raw_data.columns:
                    series = raw_data['CPIAUCSL']
                    transformed = calculate_cpi_momentum(series)

            if series is not None and transformed is not None:
                series_clean = series.dropna()
                transformed_clean = transformed.dropna()
                if not series_clean.empty and not transformed_clean.empty:
                    latest_raw = series_clean.iloc[-1]
                    latest_transformed = transformed_clean.iloc[-1]
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
        elif signal_type == 'roc_4w':
            transformed = calculate_roc_4w(series)
        elif signal_type == 'roc_18m':
            transformed = calculate_roc_18m(series)
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
