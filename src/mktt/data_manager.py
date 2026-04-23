"""
MKTT Data Manager
Builds and maintains a local Parquet database of liquid stock prices.

Storage layout (data/mktt/):
    universe.parquet   — ticker metadata (symbol, name, exchange, sector, mcap, etc.)
    close.parquet      — daily adjusted close prices (wide: dates × tickers)
    high.parquet       — daily highs
    low.parquet        — daily lows
    volume.parquet     — daily volume
    spy.parquet        — SPY benchmark OHLCV

Parquet chosen for:
    - 5-10x smaller than CSV
    - Columnar: read only the tickers you need
    - Native pandas support, zero-config
    - Fast: reads 5000-column file in <1 second
"""
import yfinance as yf
import pandas as pd
import numpy as np
import time
import sys
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent.parent / 'data' / 'mktt'
DATA_DIR.mkdir(parents=True, exist_ok=True)

US_EXCHANGES = ['NMS', 'NYQ', 'ASE', 'NCM', 'NGM']
EU_EXCHANGES = ['GER', 'LSE', 'PAR', 'AMS', 'MIL', 'MCE', 'STO', 'HEL', 'CPH', 'OSL', 'EBS', 'BRU', 'VIE']
ASIA_EXCHANGES = ['JPX', 'HKG', 'ASX', 'KSC', 'TAI', 'SES']


# =============================================================================
# Universe Fetching
# =============================================================================

def fetch_liquid_universe(exchanges=None, min_avg_vol=1000):
    """
    Fetch all liquid tickers from given exchanges via yf.screen().
    Returns DataFrame with quote-level metadata.
    """
    if exchanges is None:
        exchanges = US_EXCHANGES

    q = yf.EquityQuery('and', [
        yf.EquityQuery('is-in', ['exchange'] + list(exchanges)),
        yf.EquityQuery('gt', ['avgdailyvol3m', min_avg_vol])
    ])

    all_quotes = []
    offset = 0
    while True:
        result = yf.screen(q, sortField='intradaymarketcap', sortAsc=False, size=250, offset=offset)
        quotes = result.get('quotes', [])
        if not quotes:
            break
        all_quotes.extend(quotes)
        offset += 250

    if not all_quotes:
        return pd.DataFrame()

    df = pd.DataFrame(all_quotes)

    # Compute turnover
    df['turnover'] = df['regularMarketPrice'].fillna(0) * df['averageDailyVolume3Month'].fillna(0)

    # Keep useful columns
    keep = ['symbol', 'longName', 'exchange', 'sector', 'marketCap', 'regularMarketPrice',
            'averageDailyVolume3Month', 'turnover', 'fiftyTwoWeekHigh', 'fiftyTwoWeekLow',
            'epsTrailingTwelveMonths', 'epsCurrentYear', 'epsForward', 'forwardPE',
            'trailingPE', 'dividendYield', 'averageAnalystRating', 'currency']
    available = [c for c in keep if c in df.columns]
    return df[available]


# =============================================================================
# Price Fetching
# =============================================================================

def fetch_prices_batch(tickers, period='2y', batch_size=200):
    """
    Fetch daily OHLCV for tickers in batches.
    Returns dict of DataFrames: {'close': wide_df, 'high': ..., 'low': ..., 'volume': ...}
    """
    all_close, all_high, all_low, all_volume = {}, {}, {}, {}
    total = len(tickers)
    failed = []

    for i in range(0, total, batch_size):
        batch = tickers[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"  Batch {batch_num}/{total_batches}: {len(batch)} tickers...", end=' ', flush=True)

        try:
            raw = yf.download(batch, period=period, progress=False,
                              auto_adjust=True, threads=True)

            if raw.empty:
                print("empty")
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                for field, store in [('Close', all_close), ('High', all_high),
                                     ('Low', all_low), ('Volume', all_volume)]:
                    if field in raw.columns.get_level_values(0):
                        field_df = raw[field]
                        for col in field_df.columns:
                            series = field_df[col].dropna()
                            if len(series) > 50:
                                store[col] = series
            else:
                # Single ticker
                ticker = batch[0]
                for field, store in [('Close', all_close), ('High', all_high),
                                     ('Low', all_low), ('Volume', all_volume)]:
                    if field in raw.columns:
                        store[ticker] = raw[field].dropna()

            ok = len(all_close) - sum(1 for t in batch if t in all_close)
            print(f"OK ({len(all_close)} total)")

        except Exception as e:
            print(f"ERROR: {e}")
            failed.extend(batch)

        # Rate limit pause
        if i + batch_size < total:
            time.sleep(1)

    print(f"  Done: {len(all_close)} tickers fetched, {len(failed)} failed")

    return {
        'close': pd.DataFrame(all_close),
        'high': pd.DataFrame(all_high),
        'low': pd.DataFrame(all_low),
        'volume': pd.DataFrame(all_volume),
    }


# =============================================================================
# Storage
# =============================================================================

def save_universe(df):
    """Save universe metadata to parquet"""
    path = DATA_DIR / 'universe.parquet'
    df.to_parquet(path, engine='pyarrow', compression='snappy')
    print(f"  Saved universe: {len(df)} tickers → {path} ({path.stat().st_size / 1024:.0f} KB)")


def save_prices(prices_dict):
    """Save price DataFrames to parquet files"""
    for field, df in prices_dict.items():
        if df.empty:
            continue
        path = DATA_DIR / f'{field}.parquet'
        df.to_parquet(path, engine='pyarrow', compression='snappy')
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  Saved {field}: {df.shape[1]} tickers × {df.shape[0]} days → {size_mb:.1f} MB")


def save_spy():
    """Fetch and save SPY benchmark"""
    spy = yf.download('SPY', period='2y', progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    path = DATA_DIR / 'spy.parquet'
    spy.to_parquet(path, engine='pyarrow', compression='snappy')
    print(f"  Saved SPY: {len(spy)} days → {path}")


# =============================================================================
# Loading
# =============================================================================

def build_sector_map(exchanges=None):
    """
    Build ticker→sector mapping using Yahoo screener sector filter.
    Fetches each sector separately and maps tickers.
    """
    if exchanges is None:
        exchanges = US_EXCHANGES

    SECTORS = [
        'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
        'Industrials', 'Communication Services', 'Consumer Defensive',
        'Energy', 'Basic Materials', 'Real Estate', 'Utilities'
    ]

    path = DATA_DIR / 'sectors.parquet'

    # Check cache (24 hour TTL)
    if path.exists():
        age_hrs = (time.time() - path.stat().st_mtime) / 3600
        if age_hrs < 24:
            return pd.read_parquet(path)

    print("Building sector map...")
    all_rows = []
    for sector in SECTORS:
        try:
            q = yf.EquityQuery('and', [
                yf.EquityQuery('is-in', ['exchange'] + list(exchanges)),
                yf.EquityQuery('eq', ['sector', sector]),
                yf.EquityQuery('gt', ['avgdailyvol3m', 500])
            ])
            offset = 0
            while True:
                result = yf.screen(q, sortField='intradaymarketcap', sortAsc=False, size=250, offset=offset)
                quotes = result.get('quotes', [])
                if not quotes:
                    break
                for qt in quotes:
                    all_rows.append({'symbol': qt['symbol'], 'sector': sector})
                offset += 250
            print(f"  {sector}: {sum(1 for r in all_rows if r['sector'] == sector)}")
        except Exception as e:
            print(f"  {sector}: ERROR {e}")

    if all_rows:
        df = pd.DataFrame(all_rows).drop_duplicates(subset='symbol')
        df.to_parquet(path, engine='pyarrow', compression='snappy')
        print(f"  Saved sector map: {len(df)} tickers")
        return df

    return pd.DataFrame()


# In-memory cache for loaded parquet files
_mem_cache = {}

def _load_parquet_cached(path_str):
    """Load parquet with in-memory caching — only re-reads if file changed."""
    path = Path(path_str)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cache_key = str(path)
    if cache_key in _mem_cache and _mem_cache[cache_key][0] == mtime:
        return _mem_cache[cache_key][1]
    df = pd.read_parquet(path)
    _mem_cache[cache_key] = (mtime, df)
    return df


def load_sector_map():
    """Load cached sector mapping"""
    return _load_parquet_cached(str(DATA_DIR / 'sectors.parquet'))


def load_universe():
    """Load universe metadata"""
    return _load_parquet_cached(str(DATA_DIR / 'universe.parquet'))


def load_prices(field='close', tickers=None):
    """
    Load price data. Optionally filter to specific tickers.
    field: 'close', 'high', 'low', 'volume'
    """
    df = _load_parquet_cached(str(DATA_DIR / f'{field}.parquet'))
    if df is None:
        return None
    if tickers:
        available = [t for t in tickers if t in df.columns]
        return df[available] if available else None
    return df


def load_spy():
    """Load SPY benchmark data"""
    return _load_parquet_cached(str(DATA_DIR / 'spy.parquet'))


def get_db_status():
    """Get status of the local database"""
    status = {}
    for name in ['universe', 'close', 'high', 'low', 'volume', 'spy']:
        path = DATA_DIR / f'{name}.parquet'
        if path.exists():
            age_hrs = (time.time() - path.stat().st_mtime) / 3600
            size_mb = path.stat().st_size / (1024 * 1024)
            if name == 'universe':
                df = pd.read_parquet(path)
                status[name] = {'exists': True, 'rows': len(df), 'size_mb': size_mb,
                                'age_hrs': age_hrs}
            else:
                df = pd.read_parquet(path)
                status[name] = {'exists': True, 'tickers': df.shape[1], 'days': df.shape[0],
                                'size_mb': size_mb, 'age_hrs': age_hrs,
                                'last_date': str(df.index.max().date()) if not df.empty else '?'}
        else:
            status[name] = {'exists': False}
    return status


# =============================================================================
# Full Build
# =============================================================================

def build_database(exchanges=None, min_turnover=500000, period='2y'):
    """
    Full database build: fetch universe, download all prices, save to parquet.
    """
    if exchanges is None:
        exchanges = US_EXCHANGES

    print("="*60)
    print("MKTT Database Build")
    print("="*60)
    start = time.time()

    # Step 1: Fetch universe
    print(f"\n[1/4] Fetching liquid universe from {len(exchanges)} exchanges...")
    universe = fetch_liquid_universe(exchanges)
    if universe.empty:
        print("  ERROR: No tickers found")
        return

    # Filter by turnover
    universe = universe[universe['turnover'] >= min_turnover]
    universe = universe.sort_values('turnover', ascending=False)
    tickers = universe['symbol'].tolist()
    print(f"  Found {len(tickers)} tickers with turnover >= {min_turnover:,.0f}")

    # Step 2: Save universe
    print(f"\n[2/4] Saving universe metadata...")
    save_universe(universe)

    # Step 3: Fetch all prices
    print(f"\n[3/4] Fetching {period} daily OHLCV for {len(tickers)} tickers...")
    prices = fetch_prices_batch(tickers, period=period)

    # Step 4: Save prices
    print(f"\n[4/4] Saving to parquet...")
    save_prices(prices)
    save_spy()

    elapsed = time.time() - start
    total_size = sum(
        (DATA_DIR / f).stat().st_size
        for f in DATA_DIR.iterdir()
        if f.suffix == '.parquet'
    ) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"Database build complete!")
    print(f"  Tickers: {prices['close'].shape[1]}")
    print(f"  Days: {prices['close'].shape[0]}")
    print(f"  Total size: {total_size:.1f} MB")
    print(f"  Time: {elapsed/60:.1f} min")
    print(f"  Location: {DATA_DIR}")
    print(f"{'='*60}")


# =============================================================================
# Incremental Update
# =============================================================================

def update_prices(batch_size=200):
    """
    Incremental update: fetch only missing days since last build.
    Much faster than full rebuild (~30s vs ~3min).
    Returns True if data was updated, False if already fresh.
    """
    close_path = DATA_DIR / 'close.parquet'
    if not close_path.exists():
        print("  No existing database — run full build first.")
        return False

    # Check how stale the data is
    close_df = load_prices('close')
    if close_df is None or close_df.empty:
        return False

    last_date = close_df.index.max()
    # Strip timezone if present
    if hasattr(last_date, 'tz') and last_date.tz is not None:
        last_date = last_date.tz_localize(None)

    today = pd.Timestamp.now().normalize()

    # Skip weekends for staleness check
    bdays_behind = len(pd.bdate_range(last_date, today)) - 1
    if bdays_behind <= 0:
        print(f"  Data is current (last: {last_date.date()})")
        return False

    print(f"  Data is {bdays_behind} business days behind (last: {last_date.date()})")

    # Fetch recent data for all tickers in existing DB
    tickers = close_df.columns.tolist()
    start_date = (last_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"  Fetching {len(tickers)} tickers from {start_date}...")

    new_close, new_high, new_low, new_volume = {}, {}, {}, {}

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(tickers) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches}...", end=' ', flush=True)

        try:
            raw = yf.download(batch, start=start_date, progress=False,
                              auto_adjust=True, threads=True)

            if raw.empty:
                print("no new data")
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                for field, store in [('Close', new_close), ('High', new_high),
                                     ('Low', new_low), ('Volume', new_volume)]:
                    if field in raw.columns.get_level_values(0):
                        field_df = raw[field]
                        for col in field_df.columns:
                            series = field_df[col].dropna()
                            if not series.empty:
                                store[col] = series
            else:
                ticker = batch[0]
                for field, store in [('Close', new_close), ('High', new_high),
                                     ('Low', new_low), ('Volume', new_volume)]:
                    if field in raw.columns:
                        store[ticker] = raw[field].dropna()

            print(f"OK")
        except Exception as e:
            print(f"error: {e}")

        if i + batch_size < len(tickers):
            time.sleep(0.5)

    if not new_close:
        print("  No new data available.")
        return False

    # Append new rows to existing DataFrames
    high_df = load_prices('high')
    low_df = load_prices('low')
    volume_df = load_prices('volume')

    new_days = len(pd.DataFrame(new_close))

    for field, existing, new_data in [
        ('close', close_df, new_close),
        ('high', high_df, new_high),
        ('low', low_df, new_low),
        ('volume', volume_df, new_volume),
    ]:
        if not new_data:
            continue
        new_df = pd.DataFrame(new_data)
        # Strip timezone from new data index to match existing
        if hasattr(new_df.index, 'tz') and new_df.index.tz is not None:
            new_df.index = new_df.index.tz_localize(None)
        # Only keep rows after existing data
        new_df = new_df[new_df.index > existing.index.max()]
        if new_df.empty:
            continue
        # Concat and save
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep='last')]
        combined = combined.sort_index()
        path = DATA_DIR / f'{field}.parquet'
        combined.to_parquet(path, engine='pyarrow', compression='snappy')

    # Update SPY too
    try:
        spy_existing = load_spy()
        spy_new = yf.download('SPY', start=start_date, progress=False, auto_adjust=True)
        if isinstance(spy_new.columns, pd.MultiIndex):
            spy_new.columns = spy_new.columns.get_level_values(0)
        if not spy_new.empty:
            if hasattr(spy_new.index, 'tz') and spy_new.index.tz is not None:
                spy_new.index = spy_new.index.tz_localize(None)
            if spy_existing is not None:
                combined_spy = pd.concat([spy_existing, spy_new])
                combined_spy = combined_spy[~combined_spy.index.duplicated(keep='last')]
                combined_spy = combined_spy.sort_index()
            else:
                combined_spy = spy_new
            path = DATA_DIR / 'spy.parquet'
            combined_spy.to_parquet(path, engine='pyarrow', compression='snappy')
    except Exception:
        pass

    # Clear in-memory caches so next load picks up new data
    _mem_cache.clear()

    print(f"  Updated: {new_days} new days appended for {len(new_close)} tickers")
    return True


def auto_update_if_stale(max_age_hours=16):
    """
    Check if data is stale and auto-update if needed.
    Called on app startup. Only updates if >16 hours old (overnight).
    """
    close_path = DATA_DIR / 'close.parquet'
    if not close_path.exists():
        return False

    age_hrs = (time.time() - close_path.stat().st_mtime) / 3600
    if age_hrs < max_age_hours:
        return False

    print(f"  Database is {age_hrs:.0f}h old — running incremental update...")
    return update_prices()


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MKTT Database Manager')
    parser.add_argument('command', choices=['build', 'status', 'build-all', 'update'],
                        help='build=US only, build-all=US+EU+Asia, update=incremental, status=show db info')
    parser.add_argument('--min-turnover', type=float, default=500000,
                        help='Minimum average daily turnover (default: 500000)')
    parser.add_argument('--period', default='2y', help='History period (default: 2y)')
    args = parser.parse_args()

    if args.command == 'status':
        status = get_db_status()
        print("\nMKTT Database Status")
        print("=" * 50)
        for name, info in status.items():
            if info['exists']:
                details = ', '.join(f'{k}={v}' for k, v in info.items() if k != 'exists')
                print(f"  {name:10s}: {details}")
            else:
                print(f"  {name:10s}: NOT BUILT")

    elif args.command == 'build':
        build_database(US_EXCHANGES, min_turnover=args.min_turnover, period=args.period)

    elif args.command == 'update':
        update_prices()

    elif args.command == 'build-all':
        all_exchanges = US_EXCHANGES + EU_EXCHANGES + ASIA_EXCHANGES
        build_database(all_exchanges, min_turnover=args.min_turnover, period=args.period)
