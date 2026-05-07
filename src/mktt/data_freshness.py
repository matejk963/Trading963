"""
Data freshness checker for MKTT.
Reports staleness of all data sources and returns actionable status.

Usage:
    python data_freshness.py           # print report
    python data_freshness.py --json    # JSON output for automation
"""
import pandas as pd
import pickle
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent.parent / 'data' / 'mktt'


def check_prices():
    """Check price parquet freshness."""
    close_path = DATA_DIR / 'close.parquet'
    if not close_path.exists():
        return {'status': 'MISSING', 'detail': 'close.parquet not found'}

    close = pd.read_parquet(close_path)
    file_mtime = datetime.fromtimestamp(os.path.getmtime(close_path))

    # Find last row with substantial data
    min_stocks = len(close.columns) * 0.5
    last_good_idx = len(close) - 1
    for i in range(len(close) - 1, max(len(close) - 10, 0), -1):
        if close.iloc[i].notna().sum() >= min_stocks:
            last_good_idx = i
            break

    last_date = close.index[last_good_idx]
    n_stocks = int(close.iloc[last_good_idx].notna().sum())
    total_stocks = len(close.columns)
    days_old = (pd.Timestamp.now() - last_date).days

    # Check for sparse trailing rows
    sparse_rows = 0
    for i in range(len(close) - 1, last_good_idx, -1):
        sparse_rows += 1

    return {
        'source': 'Prices',
        'file': 'close.parquet',
        'file_modified': file_mtime.strftime('%Y-%m-%d %H:%M'),
        'last_date': str(last_date.date()),
        'stocks': n_stocks,
        'total_stocks': total_stocks,
        'days_old': days_old,
        'sparse_trailing_rows': sparse_rows,
        'status': 'OK' if days_old <= 1 else 'STALE' if days_old <= 5 else 'OLD',
        'date_range': f"{close.index[0].date()} to {close.index[-1].date()}",
        'trading_days': len(close),
    }


def check_refinitiv():
    """Check Refinitiv fundamentals pickle freshness."""
    pkl_path = DATA_DIR / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return [{'status': 'MISSING', 'detail': 'refinitiv_fundamentals.pkl not found'}]

    file_mtime = datetime.fromtimestamp(os.path.getmtime(pkl_path))
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)

    results = []

    # Snapshot
    snap = data.get('snapshot')
    if snap is not None:
        na_cols = ['Earnings Per Share - Actual', 'GICS Sector Name']
        all_na = snap[na_cols].isna().all(axis=1) | (snap[na_cols] == '<NA>').all(axis=1)
        n_with_data = int((~all_na).sum())
        results.append({
            'source': 'Refinitiv Snapshot',
            'file': 'refinitiv_fundamentals.pkl',
            'file_modified': file_mtime.strftime('%Y-%m-%d %H:%M'),
            'stocks': n_with_data,
            'total_stocks': len(snap),
            'coverage': f"{n_with_data/len(snap)*100:.0f}%",
            'missing': int(all_na.sum()),
            'status': 'OK' if n_with_data > len(snap) * 0.9 else 'PARTIAL',
            'note': 'Point-in-time snapshot, no date series',
        })

    # Quarterly
    q = data.get('quarterly')
    if q is not None:
        dates = pd.to_datetime(q['Date'], errors='coerce').dropna()
        latest = dates.max()
        n_stocks = q['Symbol'].nunique()
        valid = q[q['Earnings Per Share - Actual'] != '']
        n_with_eps = valid['Symbol'].nunique()
        results.append({
            'source': 'Quarterly Actuals',
            'latest_date': str(latest.date()),
            'stocks_with_eps': n_with_eps,
            'total_stocks': n_stocks,
            'total_rows': len(q),
            'avg_quarters': f"{len(valid) / n_with_eps:.1f}" if n_with_eps > 0 else '0',
            'status': 'OK',
        })

    # Trend data
    for key, label in [('trend_eps_fy1', 'EPS Trend FY1'), ('trend_eps_fy2', 'EPS Trend FY2'),
                        ('trend_rev_fy1', 'Rev Trend FY1'), ('trend_rev_fy2', 'Rev Trend FY2')]:
        df = data.get(key)
        if df is None:
            results.append({'source': label, 'status': 'MISSING'})
            continue
        dates = pd.to_datetime(df['Date'], errors='coerce').dropna()
        latest = dates.max()
        days_old = (pd.Timestamp.now() - latest).days
        n_stocks = df['Symbol'].nunique()
        results.append({
            'source': label,
            'latest_date': str(latest.date()),
            'days_old': days_old,
            'stocks': n_stocks,
            'total_rows': len(df),
            'status': 'OK' if days_old <= 7 else 'STALE' if days_old <= 14 else 'OLD',
        })

    # Historical estimates
    for key, label in [('hist_est_fy1', 'Hist Est FY1'), ('hist_est_fy2', 'Hist Est FY2')]:
        df = data.get(key)
        if df is None:
            results.append({'source': label, 'status': 'MISSING'})
            continue
        dates = pd.to_datetime(df['Date'], errors='coerce').dropna()
        latest = dates.max()
        n_stocks = df['Symbol'].nunique()
        results.append({
            'source': label,
            'latest_date': str(latest.date()),
            'stocks': n_stocks,
            'total_rows': len(df),
            'status': 'OK',
        })

    # FY1/FY2 estimates
    for key, label in [('fy1', 'Forward FY1'), ('fy2', 'Forward FY2')]:
        df = data.get(key)
        if df is None:
            results.append({'source': label, 'status': 'MISSING'})
            continue
        n_stocks = df['Symbol'].nunique()
        eps_col = 'Earnings Per Share - Mean'
        n_with = int((df[eps_col] != '').sum()) if eps_col in df.columns else 0
        results.append({
            'source': label,
            'stocks': n_stocks,
            'with_estimates': n_with,
            'status': 'OK' if n_with > n_stocks * 0.5 else 'PARTIAL',
        })

    return results


def check_universe():
    """Check universe parquet."""
    uni_path = DATA_DIR / 'universe.parquet'
    if not uni_path.exists():
        return {'status': 'MISSING', 'detail': 'universe.parquet not found'}

    uni = pd.read_parquet(uni_path)
    file_mtime = datetime.fromtimestamp(os.path.getmtime(uni_path))
    return {
        'source': 'Universe',
        'file': 'universe.parquet',
        'file_modified': file_mtime.strftime('%Y-%m-%d %H:%M'),
        'stocks': len(uni),
        'exchanges': dict(uni['exchange'].value_counts()),
        'status': 'OK',
    }


def full_report():
    """Run all checks, return structured report."""
    report = {
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'prices': check_prices(),
        'universe': check_universe(),
        'refinitiv': check_refinitiv(),
    }

    # Compute overall status
    all_statuses = []
    all_statuses.append(report['prices'].get('status', 'MISSING'))
    all_statuses.append(report['universe'].get('status', 'MISSING'))
    for r in report['refinitiv']:
        all_statuses.append(r.get('status', 'MISSING'))

    if 'MISSING' in all_statuses:
        report['overall'] = 'INCOMPLETE'
    elif 'OLD' in all_statuses:
        report['overall'] = 'OLD'
    elif 'STALE' in all_statuses:
        report['overall'] = 'STALE'
    else:
        report['overall'] = 'OK'

    return report


def print_report(report):
    """Pretty-print the freshness report."""
    STATUS_COLORS = {'OK': '\033[92m', 'STALE': '\033[93m', 'OLD': '\033[91m',
                     'MISSING': '\033[91m', 'PARTIAL': '\033[93m', 'INCOMPLETE': '\033[91m'}
    RESET = '\033[0m'

    def color(status):
        return f"{STATUS_COLORS.get(status, '')}{status}{RESET}"

    print(f"\n{'='*60}")
    print(f"  MKTT Data Freshness Report — {report['checked_at']}")
    print(f"  Overall: {color(report['overall'])}")
    print(f"{'='*60}\n")

    # Prices
    p = report['prices']
    print(f"  PRICES  {color(p['status'])}")
    print(f"    Last trading date: {p.get('last_date', '?')} ({p.get('days_old', '?')}d ago)")
    print(f"    Stocks: {p.get('stocks', '?')}/{p.get('total_stocks', '?')}")
    print(f"    Range: {p.get('date_range', '?')} ({p.get('trading_days', '?')} days)")
    if p.get('sparse_trailing_rows', 0) > 0:
        print(f"    Warning: {p['sparse_trailing_rows']} sparse trailing row(s)")
    print()

    # Universe
    u = report['universe']
    print(f"  UNIVERSE  {color(u['status'])}")
    print(f"    Stocks: {u.get('stocks', '?')}")
    print(f"    Modified: {u.get('file_modified', '?')}")
    print()

    # Refinitiv
    print(f"  REFINITIV FUNDAMENTALS")
    for r in report['refinitiv']:
        src = r.get('source', '?')
        st = color(r.get('status', '?'))
        detail_parts = []
        if 'latest_date' in r:
            detail_parts.append(f"latest={r['latest_date']}")
        if 'days_old' in r:
            detail_parts.append(f"{r['days_old']}d ago")
        if 'stocks' in r:
            detail_parts.append(f"{r['stocks']} stocks")
        if 'coverage' in r:
            detail_parts.append(f"coverage={r['coverage']}")
        if 'missing' in r and r['missing'] > 0:
            detail_parts.append(f"{r['missing']} missing")
        detail = ', '.join(detail_parts) if detail_parts else ''
        print(f"    {src:25s} {st:20s} {detail}")
    print()

    # Actions needed
    actions = []
    if p.get('days_old', 0) > 1:
        actions.append(f"Prices {p['days_old']}d old — run auto_update or manual price fetch")
    if p.get('sparse_trailing_rows', 0) > 0:
        actions.append(f"Clean {p['sparse_trailing_rows']} sparse trailing row(s) from price DB")
    for r in report['refinitiv']:
        if r.get('status') in ('STALE', 'OLD'):
            actions.append(f"{r['source']} is {r.get('days_old', '?')}d old — re-fetch from Refinitiv")
        if r.get('status') == 'MISSING':
            actions.append(f"{r['source']} is MISSING — run fetch_refinitiv_fundamentals.py")
        if r.get('missing', 0) > 100:
            actions.append(f"{r['source']}: {r['missing']} stocks missing data — check RIC mapping")

    if actions:
        print(f"  ACTIONS NEEDED:")
        for a in actions:
            print(f"    - {a}")
    else:
        print(f"  All data sources are current.")
    print()


if __name__ == '__main__':
    report = full_report()
    if '--json' in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
