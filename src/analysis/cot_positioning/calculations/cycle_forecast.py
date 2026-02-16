"""
Cycle forecasting calculation module
Multi-granularity wavelet cycle extraction and pattern matching for futures contracts
"""
import pandas as pd
import numpy as np
import yfinance as yf
import pywt
from scipy.signal import find_peaks
from statsmodels.tsa.filters.hp_filter import hpfilter
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')


def fetch_price_data(ticker, start_date, end_date):
    """
    Fetch price data from yfinance

    Args:
        ticker: yfinance ticker symbol
        start_date: start date string 'YYYY-MM-DD'
        end_date: end date string 'YYYY-MM-DD'

    Returns:
        DataFrame with Close prices and Log_Price
    """
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    except Exception as e:
        raise ValueError(f"Failed to download data for {ticker}: {str(e)}")

    if df is None or df.empty:
        raise ValueError(f"No data fetched for {ticker}. Ticker may be invalid or data unavailable for date range {start_date} to {end_date}")

    # Handle MultiIndex columns (futures tickers return MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        # Flatten MultiIndex: (('Close', 'CL=F'), ...) -> ('Close', ...)
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # Also handle case where columns are tuples but not MultiIndex
    if len(df.columns) > 0 and isinstance(df.columns[0], tuple):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # Check if Close column exists
    if 'Close' not in df.columns:
        raise ValueError(f"No 'Close' price column found for {ticker}. Available columns: {list(df.columns)}")

    df = df[['Close']].copy()

    # Drop NaN values
    df = df.dropna()

    # Ensure we have numeric data
    df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
    df = df.dropna()

    if len(df) < 100:
        raise ValueError(f"Insufficient data for {ticker}: only {len(df)} days available. Need at least 100 days for analysis.")

    df['Log_Price'] = np.log(df['Close'])

    return df


def find_optimal_period(detrended, min_period, max_period, n_scales=100):
    """
    Scan period range to find optimal period with maximum power

    Args:
        detrended: detrended time series
        min_period: minimum period to search
        max_period: maximum period to search
        n_scales: number of scales to test

    Returns:
        tuple: (optimal_period, scales, coefficients, power, best_scale_idx)
    """
    omega0 = 6
    min_scale = min_period / (4 * np.pi / omega0)
    max_scale = max_period / (4 * np.pi / omega0)
    scales = np.linspace(min_scale, max_scale, n_scales)
    periods = scales * (4 * np.pi / omega0)

    coefficients, _ = pywt.cwt(detrended.values, scales, 'morl', 1.0)
    power = np.abs(coefficients) ** 2
    avg_power = np.mean(power, axis=1)
    best_scale_idx = np.argmax(avg_power)

    return periods[best_scale_idx], scales, coefficients, power, best_scale_idx


def extract_cycle_at_period(detrended, scales, coefficients, power, best_scale_idx):
    """
    Extract cycle at specific scale using Gaussian weighting

    Args:
        detrended: detrended time series
        scales: array of wavelet scales
        coefficients: CWT coefficients
        power: wavelet power
        best_scale_idx: index of best scale

    Returns:
        tuple: (cycle_series, amplitude)
    """
    reconstructed = np.zeros(len(detrended))
    weights = np.zeros(len(scales))

    # Gaussian weighting
    for i in range(len(scales)):
        distance = abs(i - best_scale_idx)
        sigma = len(scales) / 6
        weights[i] = np.exp(-(distance**2) / (2 * sigma**2))

    # Weighted reconstruction
    for i in range(len(scales)):
        reconstructed += np.real(coefficients[i, :]) * weights[i]

    # Normalize to wavelet power
    scale_power = np.mean(power[best_scale_idx, :])
    current_power = np.var(reconstructed)
    if current_power > 0 and scale_power > 0:
        reconstructed = reconstructed * np.sqrt(scale_power / current_power)

    amplitude = np.std(reconstructed)

    return pd.Series(reconstructed, index=detrended.index), amplitude


def find_pattern_matches(cycle_series, period, lookback_periods=2, n_matches=5, min_gap_periods=1):
    """
    Find historical patterns similar to recent cycle behavior

    Args:
        cycle_series: extracted cycle time series
        period: cycle period in days
        lookback_periods: number of periods to use for pattern matching
        n_matches: number of analogs to find
        min_gap_periods: minimum separation between matches (in periods)

    Returns:
        list of dicts with match info (start_idx, end_idx, correlation)
    """
    lookback = int(period * lookback_periods)

    # Ensure we have enough data
    if len(cycle_series) < lookback * 2:
        # Not enough data for pattern matching
        return []

    recent_pattern = cycle_series.iloc[-lookback:].values
    recent_norm = (recent_pattern - np.mean(recent_pattern)) / (np.std(recent_pattern) + 1e-10)

    correlations = []
    min_gap = int(period * min_gap_periods)
    search_end = len(cycle_series) - lookback - min_gap

    # Need at least some historical data to search
    if search_end <= lookback:
        return []

    for i in range(lookback, search_end):
        window = cycle_series.iloc[i-lookback:i].values

        if len(window) != len(recent_pattern):
            continue

        window_norm = (window - np.mean(window)) / (np.std(window) + 1e-10)
        corr = np.corrcoef(recent_norm, window_norm)[0, 1]

        correlations.append({
            'start_idx': i - lookback,
            'end_idx': i,
            'correlation': corr if not np.isnan(corr) else -1
        })

    # Sort by correlation
    correlations.sort(key=lambda x: x['correlation'], reverse=True)

    # Select non-overlapping matches
    selected_matches = []
    for match in correlations:
        overlap = False
        for selected in selected_matches:
            if abs(match['start_idx'] - selected['start_idx']) < min_gap:
                overlap = True
                break

        if not overlap:
            selected_matches.append(match)

        if len(selected_matches) >= n_matches:
            break

    return selected_matches


def project_from_matches(cycle_series, matches, forward_periods):
    """
    Project forward based on what happened after historical matches

    Args:
        cycle_series: extracted cycle time series
        matches: list of match dictionaries
        forward_periods: number of periods to project forward

    Returns:
        list of projection dicts with analog data
    """
    projections = []

    for match in matches:
        end_idx = match['end_idx']
        available = len(cycle_series) - end_idx

        if available > 0:
            actual_forward = min(forward_periods, available)
            analog = cycle_series.iloc[end_idx:end_idx + actual_forward].values

            projections.append({
                'correlation': match['correlation'],
                'analog': analog,
                'start_date': cycle_series.index[match['start_idx']],
                'end_date': cycle_series.index[match['end_idx']],
                'length': len(analog)
            })

    return projections


def compute_analog_bounds(projections, normalization_factor):
    """
    Compute mean and 2nd extreme bounds from analog projections

    Args:
        projections: list of projection dictionaries
        normalization_factor: factor to normalize amplitudes

    Returns:
        tuple: (mean_forecast, upper_bound, lower_bound, length)
    """
    if not projections:
        return None, None, None, 0

    min_len = min([p['length'] for p in projections])
    if min_len == 0:
        return None, None, None, 0

    analogs_array = np.array([p['analog'][:min_len] / normalization_factor for p in projections])
    mean_analog = np.mean(analogs_array, axis=0)

    upper_2nd = np.zeros(min_len)
    lower_2nd = np.zeros(min_len)

    for i in range(min_len):
        values = analogs_array[:, i]
        sorted_vals = np.sort(values)

        if len(sorted_vals) >= 2:
            lower_2nd[i] = sorted_vals[1]      # 2nd lowest
            upper_2nd[i] = sorted_vals[-2]     # 2nd highest
        else:
            lower_2nd[i] = sorted_vals[0]
            upper_2nd[i] = sorted_vals[-1]

    return mean_analog, upper_2nd, lower_2nd, min_len


def find_turning_points(mean_forecast, dates, min_distance=5):
    """
    Find peaks and troughs in the mean forecast

    Args:
        mean_forecast: array of forecast values
        dates: DatetimeIndex of forecast dates
        min_distance: minimum samples between peaks/troughs

    Returns:
        tuple: (peaks, troughs) as lists of (date, amplitude) tuples
    """
    if mean_forecast is None or len(mean_forecast) == 0:
        return [], []

    # Find peaks (local maxima)
    peak_indices, _ = find_peaks(mean_forecast, distance=min_distance)

    # Find troughs (local minima)
    trough_indices, _ = find_peaks(-mean_forecast, distance=min_distance)

    peaks = [(dates[i], mean_forecast[i]) for i in peak_indices]
    troughs = [(dates[i], mean_forecast[i]) for i in trough_indices]

    return peaks, troughs


def extract_multi_granularity_cycles(df_daily, lookback_days=252*20):
    """
    Extract short, medium, and long cycles at different granularities

    Args:
        df_daily: DataFrame with Close and Log_Price columns
        lookback_days: number of days to use for analysis (default: 20 years)

    Returns:
        dict with cycle information for short, medium, long cycles
    """
    # Use recent data for cycle extraction
    if len(df_daily) > lookback_days:
        df_recent = df_daily.iloc[-lookback_days:].copy()
    else:
        df_recent = df_daily.copy()

    if len(df_recent) < 252:
        raise ValueError(f"Insufficient data for cycle extraction: only {len(df_recent)} days available, need at least 252")

    results = {}

    # Short cycle: Daily data
    # Drop any NaN values before HP filter (HP filter can't handle NaN)
    log_price_clean = df_recent['Log_Price'].dropna()
    if len(log_price_clean) < 252:
        raise ValueError(f"Insufficient clean data after dropping NaN: only {len(log_price_clean)} days")

    cycle_daily, _ = hpfilter(log_price_clean, lamb=1600)
    short_period, short_scales, short_coeffs, short_power, short_best_idx = \
        find_optimal_period(cycle_daily, min_period=10, max_period=60, n_scales=100)
    short_cycle, short_amplitude = extract_cycle_at_period(
        cycle_daily, short_scales, short_coeffs, short_power, short_best_idx
    )

    results['short'] = {
        'period': short_period,
        'period_days': short_period,
        'cycle': short_cycle,
        'amplitude': short_amplitude,
        'granularity': 'daily'
    }

    # Medium cycle: Weekly data
    df_weekly = log_price_clean.resample('W-SUN').last().dropna()
    if len(df_weekly) < 52:
        raise ValueError(f"Insufficient weekly data: only {len(df_weekly)} weeks")
    cycle_weekly, _ = hpfilter(df_weekly, lamb=1600)
    medium_period_weeks, medium_scales, medium_coeffs, medium_power, medium_best_idx = \
        find_optimal_period(cycle_weekly, min_period=4, max_period=40, n_scales=100)
    medium_cycle_weekly, medium_amplitude = extract_cycle_at_period(
        cycle_weekly, medium_scales, medium_coeffs, medium_power, medium_best_idx
    )
    # Interpolate to daily (use clean index without NaN dates)
    medium_cycle_daily = medium_cycle_weekly.reindex(log_price_clean.index, method='ffill').interpolate(method='linear')
    medium_period_days = medium_period_weeks * 7

    results['medium'] = {
        'period': medium_period_weeks,
        'period_days': medium_period_days,
        'cycle': medium_cycle_daily,
        'amplitude': medium_amplitude,
        'granularity': 'weekly'
    }

    # Long cycle: Monthly data
    df_monthly = log_price_clean.resample('ME').last().dropna()
    if len(df_monthly) < 24:
        raise ValueError(f"Insufficient monthly data: only {len(df_monthly)} months")
    cycle_monthly, _ = hpfilter(df_monthly, lamb=1600)
    long_period_months, long_scales, long_coeffs, long_power, long_best_idx = \
        find_optimal_period(cycle_monthly, min_period=6, max_period=24, n_scales=100)
    long_cycle_monthly, long_amplitude = extract_cycle_at_period(
        cycle_monthly, long_scales, long_coeffs, long_power, long_best_idx
    )
    # Interpolate to daily (use clean index without NaN dates)
    long_cycle_daily = long_cycle_monthly.reindex(log_price_clean.index, method='ffill').interpolate(method='linear')
    long_period_days = long_period_months * 30

    results['long'] = {
        'period': long_period_months,
        'period_days': long_period_days,
        'cycle': long_cycle_daily,
        'amplitude': long_amplitude,
        'granularity': 'monthly'
    }

    return results


def create_cycle_forecast(ticker, forecast_days=180, lookback_years=20):
    """
    Create complete cycle forecast for a given ticker

    Args:
        ticker: yfinance ticker symbol
        forecast_days: number of days to forecast forward
        lookback_years: years of historical data to use

    Returns:
        dict with complete forecast information
    """
    # Fetch data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*lookback_years)

    # Try to fetch data, if fails with long lookback, try shorter periods
    df_daily = None
    for years in [lookback_years, 15, 10, 5]:
        try:
            start_date = end_date - timedelta(days=365*years)
            df_daily = fetch_price_data(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            if len(df_daily) >= 252 * 3:  # At least 3 years of data
                break
        except Exception as e:
            if years == 5:  # Last attempt failed
                raise ValueError(f"Unable to fetch sufficient data for {ticker} even with {years} years lookback: {str(e)}")
            continue

    if df_daily is None or len(df_daily) < 252 * 3:
        raise ValueError(f"Insufficient data for {ticker}: only {len(df_daily) if df_daily is not None else 0} days available")

    # Extract cycles
    cycles = extract_multi_granularity_cycles(df_daily)

    # Find pattern matches and create projections
    forecast_start = df_daily.index[-1] + timedelta(days=1)
    forecast_dates = pd.date_range(forecast_start, periods=forecast_days, freq='D')

    forecasts = {}

    for cycle_type in ['short', 'medium', 'long']:
        cycle_data = cycles[cycle_type]

        # Find matches
        lookback_periods = 2 if cycle_type != 'long' else 1.5
        matches = find_pattern_matches(
            cycle_data['cycle'],
            cycle_data['period_days'],
            lookback_periods=lookback_periods,
            n_matches=5
        )

        # Debug: log match results
        if len(matches) == 0:
            import warnings
            warnings.warn(f"No pattern matches found for {cycle_type} cycle (period={cycle_data['period_days']:.1f}d, data_len={len(cycle_data['cycle'])})")

        # Project from matches
        projections = project_from_matches(cycle_data['cycle'], matches, forecast_days)

        # Compute bounds
        lookback_days = 252  # 1 year for display
        hist_start_idx = len(df_daily) - lookback_days
        hist_cycle = cycle_data['cycle'].iloc[hist_start_idx:]
        norm_factor = np.max(np.abs(hist_cycle))

        mean_forecast, upper_bound, lower_bound, forecast_len = compute_analog_bounds(
            projections, norm_factor
        )

        # Find turning points
        if mean_forecast is not None and forecast_len > 0:
            min_dist = 5 if cycle_type == 'short' else (10 if cycle_type == 'medium' else 20)
            peaks, troughs = find_turning_points(
                mean_forecast,
                forecast_dates[:forecast_len],
                min_distance=min_dist
            )
        else:
            peaks, troughs = [], []

        forecasts[cycle_type] = {
            'matches': matches,
            'projections': projections,
            'mean_forecast': mean_forecast,
            'upper_bound': upper_bound,
            'lower_bound': lower_bound,
            'forecast_len': forecast_len,
            'forecast_dates': forecast_dates[:forecast_len] if forecast_len > 0 else [],
            'peaks': peaks,
            'troughs': troughs,
            'hist_cycle': hist_cycle,
            'norm_factor': norm_factor
        }

    return {
        'ticker': ticker,
        'last_date': df_daily.index[-1],
        'last_price': df_daily['Close'].iloc[-1],
        'df_daily': df_daily.iloc[-252:],  # Last year for display
        'cycles': cycles,
        'forecasts': forecasts,
        'forecast_days': forecast_days,
        'forecast_dates': forecast_dates
    }
