"""
Data loading functions for liquidity indicators from FRED
"""
import os
import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Get project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data', 'liquidity')


def get_fred_api_key():
    """Load FRED API key from file"""
    api_key_file = Path(PROJECT_ROOT) / 'data' / 'fred_api_key.txt'
    if not api_key_file.exists():
        raise FileNotFoundError(
            f'FRED API key not found. Create {api_key_file} with your key from '
            'https://fred.stlouisfed.org/docs/api/api_key.html'
        )
    return api_key_file.read_text().strip()


def get_fred_client():
    """Get initialized FRED API client"""
    try:
        from fredapi import Fred
    except ImportError:
        raise ImportError('fredapi library not installed. Run: pip install fredapi')

    api_key = get_fred_api_key()
    return Fred(api_key=api_key)


@st.cache_data(ttl=3600)
def fetch_fred_series(series_id: str, start_date: str = None) -> pd.Series:
    """
    Fetch a single FRED series

    Args:
        series_id: FRED series code (e.g., 'WALCL')
        start_date: Start date (defaults to 10 years ago)

    Returns:
        pandas Series with datetime index
    """
    try:
        fred = get_fred_client()

        if start_date is None:
            start_date = '2000-01-01'  # Fetch max available history

        logger.info(f"Fetching FRED series: {series_id}")
        series = fred.get_series(series_id, observation_start=start_date)

        if series is None or series.empty:
            logger.warning(f"No data returned for {series_id}")
            return None

        logger.info(f"  Fetched {len(series)} observations for {series_id}")
        logger.info(f"  Date range: {series.index.min()} to {series.index.max()}")

        return series

    except Exception as e:
        logger.error(f"Error fetching {series_id}: {e}")
        return None


@st.cache_data(ttl=3600)
def fetch_all_fred_series(series_codes: list, start_date: str = None) -> pd.DataFrame:
    """
    Fetch multiple FRED series and combine into DataFrame

    Args:
        series_codes: List of FRED series codes
        start_date: Start date for all series

    Returns:
        DataFrame with datetime index and one column per series
    """
    data = {}

    for code in series_codes:
        series = fetch_fred_series(code, start_date)
        if series is not None:
            data[code] = series
        else:
            logger.warning(f"Skipping {code} - no data")

    if not data:
        return None

    # Combine into DataFrame
    df = pd.DataFrame(data)
    df.index.name = 'Date'

    logger.info(f"Combined {len(data)} series into DataFrame")
    logger.info(f"  Shape: {df.shape}")
    logger.info(f"  Date range: {df.index.min()} to {df.index.max()}")

    return df


def load_cached_data(filename: str) -> pd.DataFrame:
    """Load cached liquidity data from CSV"""
    filepath = os.path.join(DATA_DIR, filename)

    if not os.path.exists(filepath):
        logger.info(f"No cached file found: {filepath}")
        return None

    try:
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        logger.info(f"Loaded cached data from {filepath}")
        logger.info(f"  Shape: {df.shape}")
        logger.info(f"  Date range: {df.index.min()} to {df.index.max()}")
        return df
    except Exception as e:
        logger.error(f"Error loading cached data: {e}")
        return None


def save_cached_data(df: pd.DataFrame, filename: str) -> bool:
    """Save liquidity data to CSV cache"""
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, filename)

    try:
        df.to_csv(filepath)
        logger.info(f"Saved data to {filepath}")
        return True
    except Exception as e:
        logger.error(f"Error saving data: {e}")
        return False


def get_data_freshness(filename: str) -> dict:
    """Get information about cached data freshness"""
    filepath = os.path.join(DATA_DIR, filename)

    if not os.path.exists(filepath):
        return {
            'exists': False,
            'message': 'No cached data'
        }

    try:
        # Get file modification time
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))

        # Load to get latest data point
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        latest_date = df.index.max()

        return {
            'exists': True,
            'file_updated': mtime,
            'latest_data': latest_date,
            'records': len(df),
            'columns': len(df.columns),
            'message': f'Data through {latest_date.strftime("%Y-%m-%d")}, file updated {mtime.strftime("%Y-%m-%d %H:%M")}'
        }
    except Exception as e:
        return {
            'exists': True,
            'error': str(e),
            'message': f'Error reading file: {e}'
        }


@st.cache_data(ttl=3600)
def load_liquidity_data(force_refresh: bool = False) -> dict:
    """
    Load all liquidity indicator data

    Returns dict with:
        - raw_data: DataFrame of raw FRED series
        - last_updated: timestamp of last data point
        - status: dict with per-series status
    """
    from config.indicators import FRED_SERIES

    cache_file = 'us_liquidity_raw.csv'

    # Try to load cached data first
    if not force_refresh:
        cached = load_cached_data(cache_file)
        if cached is not None:
            # Check if data is recent enough (within 1 day)
            latest = cached.index.max()
            if (datetime.now() - latest).days <= 1:
                return {
                    'raw_data': cached,
                    'last_updated': latest,
                    'status': {'cached': True, 'series_count': len(cached.columns)}
                }

    # Fetch fresh data
    logger.info("Fetching fresh data from FRED...")
    df = fetch_all_fred_series(FRED_SERIES)

    if df is not None:
        save_cached_data(df, cache_file)
        return {
            'raw_data': df,
            'last_updated': df.index.max(),
            'status': {'cached': False, 'series_count': len(df.columns)}
        }

    # Fallback to cached if fetch failed
    cached = load_cached_data(cache_file)
    if cached is not None:
        return {
            'raw_data': cached,
            'last_updated': cached.index.max(),
            'status': {'cached': True, 'fetch_failed': True, 'series_count': len(cached.columns)}
        }

    return {
        'raw_data': None,
        'last_updated': None,
        'status': {'error': 'No data available'}
    }


def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample all series to weekly frequency (Friday close)
    Handles mixed frequencies (daily, weekly, monthly)
    """
    # Forward fill to handle different frequencies
    df_filled = df.ffill()

    # Resample to weekly (Friday)
    df_weekly = df_filled.resample('W-FRI').last()

    return df_weekly


def align_series(series_dict: dict) -> pd.DataFrame:
    """
    Align multiple series with different frequencies to common timeline
    Uses forward-fill for lower frequency series
    """
    df = pd.DataFrame(series_dict)

    # Forward fill to propagate monthly/quarterly values
    df = df.ffill()

    return df
