"""
MKTT Screener Engine
Fetches and screens stocks using Yahoo Finance screener API
"""
import yfinance as yf
import pandas as pd
import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

CACHE_DIR = Path(__file__).parent / 'cache'
CACHE_DIR.mkdir(exist_ok=True)

EXCHANGES = {
    'US': {
        'NMS': 'NASDAQ GS',
        'NYQ': 'NYSE',
        'ASE': 'AMEX',
        'NCM': 'NASDAQ CM',
        'NGM': 'NASDAQ GM',
    },
    'Europe': {
        'GER': 'XETRA',
        'LSE': 'London',
        'PAR': 'Paris',
        'AMS': 'Amsterdam',
        'MIL': 'Milan',
        'MCE': 'Madrid',
        'STO': 'Stockholm',
        'HEL': 'Helsinki',
        'CPH': 'Copenhagen',
        'OSL': 'Oslo',
        'EBS': 'Swiss/SIX',
        'BRU': 'Brussels',
        'VIE': 'Vienna',
    },
    'Asia': {
        'JPX': 'Japan/Tokyo',
        'HKG': 'Hong Kong',
        'SHH': 'Shanghai',
        'SHZ': 'Shenzhen',
        'KSC': 'Korea',
        'TAI': 'Taiwan',
        'SES': 'Singapore',
        'BSE': 'India',
        'ASX': 'Australia',
    },
}

# Flat lookup
EXCHANGE_NAMES = {}
for region, exs in EXCHANGES.items():
    for code, name in exs.items():
        EXCHANGE_NAMES[code] = f'{name} ({code})'


def _cache_path(key):
    return CACHE_DIR / f'{key}.json'


def _load_cache(key, max_age_hours=1):
    path = _cache_path(key)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > max_age_hours * 3600:
        return None
    with open(path) as f:
        return json.load(f)


def _save_cache(key, data):
    with open(_cache_path(key), 'w') as f:
        json.dump(data, f)


def fetch_exchange_quotes(exchange_codes, min_avg_vol=500):
    """
    Fetch all quotes from given exchanges via yf.screen()
    Returns list of quote dicts
    """
    cache_key = f'quotes_{"_".join(sorted(exchange_codes))}_{min_avg_vol}'
    cached = _load_cache(cache_key)
    if cached:
        return cached

    q = yf.EquityQuery('and', [
        yf.EquityQuery('is-in', ['exchange'] + list(exchange_codes)),
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

    _save_cache(cache_key, all_quotes)
    return all_quotes


def screen_stocks(exchange_codes, min_turnover=500000, min_mcap=0, max_mcap=0,
                  sector=None, min_price=0, max_pe=0, sort_by='turnover',
                  sort_asc=False):
    """
    Screen stocks with given criteria.
    Returns pandas DataFrame sorted by criteria.
    """
    quotes = fetch_exchange_quotes(exchange_codes)

    if not quotes:
        return pd.DataFrame()

    df = pd.DataFrame(quotes)

    # Calculate turnover
    df['turnover'] = df['regularMarketPrice'].fillna(0) * df['averageDailyVolume3Month'].fillna(0)

    # Select and rename columns
    cols = {
        'symbol': 'Symbol',
        'longName': 'Name',
        'exchange': 'Exchange',
        'sector': 'Sector',
        'regularMarketPrice': 'Price',
        'regularMarketChange': 'Change',
        'regularMarketChangePercent': 'Change%',
        'marketCap': 'MktCap',
        'averageDailyVolume3Month': 'AvgVol3M',
        'turnover': 'Turnover',
        'fiftyTwoWeekHigh': '52wHigh',
        'fiftyTwoWeekLow': '52wLow',
        'fiftyTwoWeekChangePercent': '52wChg%',
        'epsTrailingTwelveMonths': 'EPS_TTM',
        'epsCurrentYear': 'EPS_Est',
        'epsForward': 'EPS_Fwd',
        'forwardPE': 'FwdPE',
        'trailingPE': 'PE',
        'dividendYield': 'DivYield',
        'averageAnalystRating': 'AnalystRating',
        'sharesOutstanding': 'SharesOut',
        'averageDailyVolume10Day': 'AvgVol10D',
        'fiftyDayAverage': 'MA50',
        'twoHundredDayAverage': 'MA200',
    }

    available = {k: v for k, v in cols.items() if k in df.columns}
    result = df[list(available.keys())].rename(columns=available)

    # Apply filters
    if min_turnover > 0:
        result = result[result['Turnover'] >= min_turnover]

    if min_mcap > 0:
        result = result[result['MktCap'] >= min_mcap]

    if max_mcap > 0:
        result = result[result['MktCap'] <= max_mcap]

    if sector and sector != 'All':
        result = result[result['Sector'] == sector]

    if min_price > 0:
        result = result[result['Price'] >= min_price]

    if max_pe > 0 and 'FwdPE' in result.columns:
        result = result[(result['FwdPE'] > 0) & (result['FwdPE'] <= max_pe)]

    # Sort
    sort_map = {
        'turnover': 'Turnover',
        'mcap': 'MktCap',
        'change': 'Change%',
        '52w': '52wChg%',
        'name': 'Name',
        'price': 'Price',
        'pe': 'FwdPE',
    }
    sort_col = sort_map.get(sort_by, 'Turnover')
    if sort_col in result.columns:
        result = result.sort_values(sort_col, ascending=sort_asc, na_position='last')

    return result.reset_index(drop=True)


def get_available_sectors(exchange_codes):
    """Get list of sectors available in the data"""
    quotes = fetch_exchange_quotes(exchange_codes)
    if not quotes:
        return []
    sectors = set()
    for q in quotes:
        s = q.get('sector')
        if s:
            sectors.add(s)
    return sorted(sectors)
