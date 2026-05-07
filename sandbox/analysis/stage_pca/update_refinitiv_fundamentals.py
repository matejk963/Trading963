r"""
Incremental update of Refinitiv fundamentals data.
Fetches only new/changed data and merges with existing history.

Strategy (minimizes API calls):
  1. Snapshot + FY1 + FY2: REPLACE (always latest point-in-time)
  2. Trends (EPS/Rev FY1/FY2): EXTEND — fetch only from last known date forward
  3. Quarterly: EXTEND — fetch latest 4 quarters, merge with existing
  4. Hist estimates: EXTEND — fetch latest 4 quarters, merge with existing

Run from Windows (cmd.exe) where Refinitiv Workspace is running:
  cd C:\Users\krajcovic\Documents\GitHub\Trading963
  python sandbox\analysis\stage_pca\update_refinitiv_fundamentals.py
"""
import refinitiv.data as rd
import pandas as pd
import numpy as np
import pickle
import time
import os
import sys

pd.set_option('future.no_silent_downcasting', True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'mktt')
OUTPUT_FILE = os.path.join(DATA_DIR, 'refinitiv_fundamentals.pkl')

# =========================================================================
# Load existing data
# =========================================================================
if not os.path.exists(OUTPUT_FILE):
    print("ERROR: No existing data found. Run fetch_refinitiv_fundamentals.py first.")
    sys.exit(1)

with open(OUTPUT_FILE, 'rb') as f:
    results = pickle.load(f)
print(f"Loaded existing data: {list(results.keys())}")
for k, v in results.items():
    print(f"  {k}: {len(v)} rows")

# =========================================================================
# Build RIC mapping
# =========================================================================
uni = pd.read_parquet(os.path.join(DATA_DIR, 'universe.parquet'))
close = pd.read_parquet(os.path.join(DATA_DIR, 'close.parquet'))
tickers = sorted(close.columns.tolist())

exchange_map = dict(zip(uni['symbol'], uni['exchange']))
ric_to_sym = {}

def to_ric(sym):
    ex = exchange_map.get(sym, 'NYQ')
    if ex in ('NMS', 'NCM', 'NGM'):
        ric = sym + '.O'
    elif ex in ('NYQ', 'NYSE'):
        ric = sym + '.N'
    elif ex == 'ASE':
        ric = sym + '.A'
    else:
        ric = sym + '.N'
    ric_to_sym[ric] = sym
    return ric

all_rics = [to_ric(t) for t in tickers]
print(f"\nUniverse: {len(tickers)} tickers -> {len(all_rics)} RICs")

# =========================================================================
# Field definitions
# =========================================================================
SNAPSHOT_FIELDS = [
    'TR.PriceClose',
    'TR.EPSActValue', 'TR.EPSMean', 'TR.EPSSmartEst',
    'TR.RevenueActValue', 'TR.RevenueMean',
    'TR.OperatingMargin', 'TR.NetProfitMargin', 'TR.GrossProfit',
    'TR.EBITDA', 'TR.OperatingIncome', 'TR.NetIncome',
    'TR.FreeCashFlow', 'TR.CashFromOperations', 'TR.CapitalExpenditure',
    'TR.TotalDebt', 'TR.NetDebt', 'TR.CashAndSTInvestments',
    'TR.TotalAssets', 'TR.TotalEquity',
    'TR.DebtToEquity', 'TR.NetDebtToEBITDA', 'TR.TotalDebtToEBITDA',
    'TR.CurrentRatio', 'TR.QuickRatio', 'TR.WorkingCapital',
    'TR.ReturnOnCapitalPercent', 'TR.AssetTurnover',
    'TR.EVToEBITDA', 'TR.EVToSales', 'TR.EV', 'TR.MktCap',
    'TR.DPSActValue', 'TR.SharesOutstanding',
    'TR.PriceTargetMean', 'TR.NumberOfAnalysts',
    'TR.GICSSector', 'TR.GICSIndustry',
]

FORWARD_FIELDS = [
    'TR.EPSMean', 'TR.EPSHigh', 'TR.EPSLow', 'TR.EPSSmartEst', 'TR.EPSNumOfEst',
    'TR.RevenueMean', 'TR.RevenueHigh', 'TR.RevenueLow',
    'TR.EBITDAMean', 'TR.EBITDASmartEst',
    'TR.CapExMean', 'TR.CFPSMean', 'TR.DPSMean',
]

QUARTERLY_FIELDS = [
    'TR.EPSActValue', 'TR.EPSActValue.date', 'TR.EPSMeanEstimate',
    'TR.RevenueActValue', 'TR.RevenueMeanEstimate',
    'TR.OperatingMargin', 'TR.NetProfitMargin',
    'TR.FreeCashFlow',
    'TR.TotalDebt', 'TR.NetDebt',
    'TR.CashAndSTInvestments', 'TR.CurrentRatio',
]

TREND_FIELDS_EPS = [
    'TR.EPSMean', 'TR.EPSMean.date',
    'TR.EPSHigh', 'TR.EPSLow', 'TR.EPSNumOfEst',
]
TREND_FIELDS_REV = [
    'TR.RevenueMean', 'TR.RevenueMean.date',
    'TR.RevenueHigh', 'TR.RevenueLow',
]

HIST_EST_FIELDS = ['TR.EPSMean', 'TR.EPSMean.date']

BATCH_SIZE = 200
SLEEP_BETWEEN = 2

# =========================================================================
# Helpers
# =========================================================================
def fetch_batched(rics, fields, parameters=None, desc="", batch_size=None):
    bs = batch_size or BATCH_SIZE
    all_dfs = []
    n_batches = (len(rics) + bs - 1) // bs
    for i in range(0, len(rics), bs):
        batch = rics[i:i + bs]
        batch_num = i // bs + 1
        t0 = time.time()
        try:
            if parameters:
                df = rd.get_data(batch, fields, parameters=parameters)
            else:
                df = rd.get_data(batch, fields)
            elapsed = time.time() - t0
            print(f"  [{desc}] Batch {batch_num}/{n_batches}: {len(df)} rows, {elapsed:.1f}s")
            all_dfs.append(df)
        except Exception as e:
            print(f"  [{desc}] Batch {batch_num}/{n_batches} ERROR: {e}")
            for j in range(0, len(batch), 25):
                sub = batch[j:j+25]
                try:
                    if parameters:
                        df = rd.get_data(sub, fields, parameters=parameters)
                    else:
                        df = rd.get_data(sub, fields)
                    all_dfs.append(df)
                except:
                    pass
                time.sleep(1)
        if i + bs < len(rics):
            time.sleep(SLEEP_BETWEEN)
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def add_symbol(df):
    df['Symbol'] = df['Instrument'].map(lambda r: ric_to_sym.get(r, r.split('.')[0]))
    return df


def merge_by_symbol_date(existing, new_data, date_col='Date'):
    """Merge new data with existing, keeping newest version for duplicates."""
    combined = pd.concat([existing, new_data], ignore_index=True)
    combined[date_col] = pd.to_datetime(combined[date_col], errors='coerce')
    # Dedup: same Symbol + Date -> keep last (new data)
    dedup_key = combined['Symbol'].astype(str) + '_' + combined[date_col].astype(str)
    combined = combined[~dedup_key.duplicated(keep='last')]
    combined = combined.sort_values(['Symbol', date_col]).reset_index(drop=True)
    return combined


def get_latest_trend_date(key):
    """Get the latest date in existing trend data."""
    df = results.get(key)
    if df is None or df.empty:
        return None
    dates = pd.to_datetime(df['Date'], errors='coerce').dropna()
    return dates.max() if len(dates) > 0 else None


# =========================================================================
# Main update
# =========================================================================
rd.open_session()
print("\nSession opened")
print(f"Update started: {pd.Timestamp.now()}\n")

# --- 1. SNAPSHOT: full replace ---
print("=" * 60)
print("1. SNAPSHOT (full replace)")
print("=" * 60)
t0 = time.time()
new_snap = fetch_batched(all_rics, SNAPSHOT_FIELDS, desc="Snapshot")
if len(new_snap) > 0:
    new_snap = add_symbol(new_snap)
    results['snapshot'] = new_snap
    na_check = new_snap.iloc[:, 1:-1].notna().any(axis=1).sum()
    print(f"  {na_check}/{len(new_snap)} stocks with data, {time.time()-t0:.0f}s")

# --- 2. FY1 + FY2: full replace ---
for period in ['FY1', 'FY2']:
    key = period.lower()
    print(f"\n{'='*60}")
    print(f"2. {period} ESTIMATES (full replace)")
    print(f"{'='*60}")
    t0 = time.time()
    new_fy = fetch_batched(all_rics, FORWARD_FIELDS, parameters={'Period': period}, desc=period)
    if len(new_fy) > 0:
        new_fy = add_symbol(new_fy)
        results[key] = new_fy
        print(f"  {len(new_fy)} rows, {time.time()-t0:.0f}s")

# --- 3. TRENDS: extend from last date ---
for period_label, period_code in [('FY1', 'FY1'), ('FY2', 'FY2')]:
    for metric, fields in [('eps', TREND_FIELDS_EPS), ('rev', TREND_FIELDS_REV)]:
        key = f'trend_{metric}_{period_label.lower()}'
        latest = get_latest_trend_date(key)

        print(f"\n{'='*60}")
        print(f"3. {key.upper()} (extend)")
        print(f"{'='*60}")

        if latest is not None:
            days_since = (pd.Timestamp.now() - latest).days
            if days_since < 2:
                print(f"  Already current ({latest.date()}), skipping")
                continue
            # Fetch from 1 month before latest to now (overlap for dedup safety)
            sdate = '-2M'
            print(f"  Last data: {latest.date()} ({days_since}d ago), fetching from {sdate}")
        else:
            sdate = '-12M'
            print(f"  No existing data, fetching full 12M")

        t0 = time.time()
        new_trend = fetch_batched(all_rics, fields,
            parameters={'SDate': sdate, 'EDate': '0', 'Period': period_code, 'Frq': 'CM'},
            desc=key, batch_size=100)

        if len(new_trend) > 0:
            new_trend = add_symbol(new_trend)
            existing = results.get(key, pd.DataFrame())
            if not existing.empty:
                results[key] = merge_by_symbol_date(existing, new_trend)
                new_dates = set(pd.to_datetime(new_trend['Date'], errors='coerce').dt.date.dropna())
                old_dates = set(pd.to_datetime(existing['Date'], errors='coerce').dt.date.dropna())
                added = new_dates - old_dates
                print(f"  Merged: {len(results[key])} total rows (+{len(added)} new dates), {time.time()-t0:.0f}s")
            else:
                results[key] = new_trend
                print(f"  Fresh: {len(new_trend)} rows, {time.time()-t0:.0f}s")

# --- 4. QUARTERLY: extend with latest 4 quarters ---
print(f"\n{'='*60}")
print("4. QUARTERLY (extend with latest 4Q)")
print(f"{'='*60}")
t0 = time.time()
new_q = fetch_batched(all_rics, QUARTERLY_FIELDS,
    parameters={'SDate': '0', 'EDate': '-3', 'Period': 'FQ0', 'Frq': 'FQ'},
    desc="Quarterly", batch_size=50)
if len(new_q) > 0:
    new_q = add_symbol(new_q)
    existing_q = results.get('quarterly', pd.DataFrame())
    if not existing_q.empty:
        results['quarterly'] = merge_by_symbol_date(existing_q, new_q)
        print(f"  Merged: {len(results['quarterly'])} total rows, {time.time()-t0:.0f}s")
    else:
        results['quarterly'] = new_q
        print(f"  Fresh: {len(new_q)} rows, {time.time()-t0:.0f}s")

# --- 5. HIST ESTIMATES: extend with latest 4 quarters ---
for fy_label, params in [('hist_est_fy1', {'SDate':'0','EDate':'-3','Period':'FY1','Frq':'FQ'}),
                          ('hist_est_fy2', {'SDate':'0','EDate':'-3','Period':'FY2','Frq':'FQ'})]:
    print(f"\n{'='*60}")
    print(f"5. {fy_label.upper()} (extend with latest 4Q)")
    print(f"{'='*60}")
    t0 = time.time()
    new_he = fetch_batched(all_rics, HIST_EST_FIELDS, parameters=params,
                           desc=fy_label, batch_size=100)
    if len(new_he) > 0:
        new_he = add_symbol(new_he)
        existing_he = results.get(fy_label, pd.DataFrame())
        if not existing_he.empty:
            results[fy_label] = merge_by_symbol_date(existing_he, new_he)
            print(f"  Merged: {len(results[fy_label])} total rows, {time.time()-t0:.0f}s")
        else:
            results[fy_label] = new_he
            print(f"  Fresh: {len(new_he)} rows, {time.time()-t0:.0f}s")

rd.close_session()

# =========================================================================
# Save
# =========================================================================
# Backup existing
backup_path = OUTPUT_FILE + '.bak'
if os.path.exists(OUTPUT_FILE):
    import shutil
    shutil.copy2(OUTPUT_FILE, backup_path)
    print(f"\nBackup saved: {backup_path}")

with open(OUTPUT_FILE, 'wb') as f:
    pickle.dump(results, f)

fsize = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\n{'='*60}")
print(f"SAVED: {OUTPUT_FILE} ({fsize:.1f} MB)")
for k, v in results.items():
    print(f"  {k}: {len(v)} rows")
print(f"\nUpdate completed: {pd.Timestamp.now()}")
print("DONE")
