"""
Liquidity Data Updater
Fetches latest data from FRED and updates local cache
"""
import os
import pandas as pd
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Get project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data', 'liquidity')


def update_liquidity_data(data_dir=None):
    """
    Update all liquidity indicator data from FRED

    Args:
        data_dir: Optional override for data directory

    Returns:
        dict with success status and message
    """
    if data_dir is None:
        data_dir = DATA_DIR

    cache_file = os.path.join(data_dir, 'us_liquidity_raw.csv')

    # Load existing data to check current state
    if os.path.exists(cache_file):
        existing_df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        current_latest = existing_df.index.max()
    else:
        existing_df = None
        current_latest = None

    try:
        # Check for FRED API key
        api_key_file = Path(PROJECT_ROOT) / 'data' / 'fred_api_key.txt'
        if not api_key_file.exists():
            return {
                'success': False,
                'message': f'FRED API key not found. Create {api_key_file} with your key from https://fred.stlouisfed.org/docs/api/api_key.html'
            }

        # Import fredapi
        try:
            from fredapi import Fred
        except ImportError:
            return {
                'success': False,
                'message': 'fredapi library not installed. Run: pip install fredapi'
            }

        # Read API key
        FRED_API_KEY = api_key_file.read_text().strip()
        fred = Fred(api_key=FRED_API_KEY)

        # Import series codes
        from config.indicators import FRED_SERIES

        # Fetch all series
        data = {}
        failed_series = []

        for series_id in FRED_SERIES:
            try:
                series = fred.get_series(series_id)
                if series is not None and not series.empty:
                    data[series_id] = series
                    logger.info(f"  Fetched {series_id}: {len(series)} observations")
                else:
                    failed_series.append(series_id)
                    logger.warning(f"  No data for {series_id}")
            except Exception as e:
                failed_series.append(series_id)
                logger.error(f"  Error fetching {series_id}: {e}")

        if not data:
            return {
                'success': False,
                'message': f'Failed to fetch any data. Check API key and network connection.'
            }

        # Combine into DataFrame
        df = pd.DataFrame(data)
        df.index.name = 'Date'

        new_latest = df.index.max()

        # Check if there's new data
        if current_latest and new_latest <= current_latest:
            return {
                'success': False,
                'message': f'Data is up to date (latest: {current_latest.strftime("%Y-%m-%d")})'
            }

        # Create backup of existing file
        if existing_df is not None:
            backup_file = cache_file.replace('.csv', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
            existing_df.to_csv(backup_file)
            logger.info(f"Created backup: {backup_file}")

        # Save new data
        os.makedirs(data_dir, exist_ok=True)
        df.to_csv(cache_file)

        # Calculate how many new records
        if current_latest:
            new_records = len(df[df.index > current_latest])
        else:
            new_records = len(df)

        result = {
            'success': True,
            'message': f'Updated to {new_latest.strftime("%Y-%m-%d")}',
            'new_records': new_records,
            'total_series': len(data),
            'failed_series': failed_series if failed_series else None,
            'latest_date': new_latest
        }

        if failed_series:
            result['message'] += f' (Warning: {len(failed_series)} series failed)'

        return result

    except Exception as e:
        logger.error(f"Error updating liquidity data: {e}")
        return {'success': False, 'message': f'Error: {str(e)}'}


def get_update_status(data_dir=None):
    """
    Get current status of liquidity data

    Returns:
        dict with data freshness information
    """
    if data_dir is None:
        data_dir = DATA_DIR

    cache_file = os.path.join(data_dir, 'us_liquidity_raw.csv')

    if not os.path.exists(cache_file):
        return {
            'has_data': False,
            'message': 'No data cached. Run update to fetch data.'
        }

    try:
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        latest_date = df.index.max()
        file_mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))

        # Check data staleness
        days_old = (datetime.now() - latest_date).days

        if days_old <= 1:
            freshness = 'Current'
        elif days_old <= 7:
            freshness = 'Recent'
        else:
            freshness = 'Stale'

        return {
            'has_data': True,
            'latest_date': latest_date,
            'file_updated': file_mtime,
            'series_count': len(df.columns),
            'record_count': len(df),
            'days_old': days_old,
            'freshness': freshness,
            'message': f'Data through {latest_date.strftime("%Y-%m-%d")} ({freshness})'
        }

    except Exception as e:
        return {
            'has_data': True,
            'error': str(e),
            'message': f'Error reading data: {e}'
        }


if __name__ == '__main__':
    # Test update
    logging.basicConfig(level=logging.INFO)

    print("Checking current status...")
    status = get_update_status()
    print(f"Status: {status}")

    print("\nUpdating data...")
    result = update_liquidity_data()
    print(f"Result: {result}")
