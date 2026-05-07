r"""
Re-fetch Refinitiv data for 767 stocks that had broken RIC mapping.
NYSE tickers need .N suffix, not bare symbol.

Must be run from Windows (cmd.exe) where Refinitiv Workspace is running:
  cd C:\Users\krajcovic\Documents\GitHub\Trading963
  python sandbox\analysis\stage_pca\refetch_broken_rics.py
"""
import refinitiv.data as rd
import pandas as pd
import numpy as np
import pickle
import time
import os

pd.set_option('future.no_silent_downcasting', True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'mktt')
OUTPUT_FILE = os.path.join(DATA_DIR, 'refinitiv_fundamentals.pkl')

# Load existing results
with open(OUTPUT_FILE, 'rb') as f:
    results = pickle.load(f)
print(f"Loaded existing data: {list(results.keys())}")

# Find broken tickers (all-NA in snapshot)
snap = results['snapshot']
na_cols = ['Earnings Per Share - Actual', 'GICS Sector Name']
all_na = snap[na_cols].isna().all(axis=1) | (snap[na_cols] == '<NA>').all(axis=1)
broken_syms = snap[all_na]['Symbol'].tolist()
broken_instruments = snap[all_na]['Instrument'].tolist()
print(f"\nBroken tickers: {len(broken_syms)}")

# Load universe for exchange info
uni = pd.read_parquet(os.path.join(DATA_DIR, 'universe.parquet'))
exchange_map = dict(zip(uni['symbol'], uni['exchange']))

# Build correct RICs
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
        ric = sym + '.N'  # default to NYSE
    ric_to_sym[ric] = sym
    return ric

fixed_rics = [to_ric(s) for s in broken_syms]
print(f"Fixed RICs: {len(fixed_rics)}")
print(f"Sample: {list(zip(broken_syms[:5], fixed_rics[:5]))}")

# =========================================================================
# Field definitions (same as original)
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

BATCH_SIZE = 100
SLEEP_BETWEEN = 2

def fetch_batched(rics, fields, parameters=None, desc=""):
    all_dfs = []
    n_batches = (len(rics) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(rics), BATCH_SIZE):
        batch = rics[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
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
                    df = rd.get_data(sub, fields, parameters=(parameters or {})) if parameters else rd.get_data(sub, fields)
                    all_dfs.append(df)
                except:
                    pass
                time.sleep(1)
        if i + BATCH_SIZE < len(rics):
            time.sleep(SLEEP_BETWEEN)
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


# =========================================================================
# Re-fetch
# =========================================================================
rd.open_session()
print("Session opened\n")

def add_symbol_col(df):
    df['Symbol'] = df['Instrument'].map(lambda r: ric_to_sym.get(r, r.split('.')[0]))
    return df

# 1. Snapshot
print("=" * 60)
print("1. RE-FETCH SNAPSHOT")
print("=" * 60)
new_snap = fetch_batched(fixed_rics, SNAPSHOT_FIELDS, desc="Snapshot")
if len(new_snap) > 0:
    new_snap = add_symbol_col(new_snap)
    # Replace broken rows in existing snapshot
    keep = snap[~snap['Symbol'].isin(new_snap['Symbol'])]
    results['snapshot'] = pd.concat([keep, new_snap], ignore_index=True)
    valid = new_snap.iloc[:, 1:-1].notna().any(axis=1).sum()
    print(f"  Got data for {valid}/{len(new_snap)} stocks")

# 2. FY1
print("\n" + "=" * 60)
print("2. RE-FETCH FY1")
print("=" * 60)
new_fy1 = fetch_batched(fixed_rics, FORWARD_FIELDS, parameters={'Period': 'FY1'}, desc="FY1")
if len(new_fy1) > 0:
    new_fy1 = add_symbol_col(new_fy1)
    keep = results['fy1'][~results['fy1']['Symbol'].isin(new_fy1['Symbol'])]
    results['fy1'] = pd.concat([keep, new_fy1], ignore_index=True)
    print(f"  Got {len(new_fy1)} rows")

# 3. FY2
print("\n" + "=" * 60)
print("3. RE-FETCH FY2")
print("=" * 60)
new_fy2 = fetch_batched(fixed_rics, FORWARD_FIELDS, parameters={'Period': 'FY2'}, desc="FY2")
if len(new_fy2) > 0:
    new_fy2 = add_symbol_col(new_fy2)
    keep = results['fy2'][~results['fy2']['Symbol'].isin(new_fy2['Symbol'])]
    results['fy2'] = pd.concat([keep, new_fy2], ignore_index=True)
    print(f"  Got {len(new_fy2)} rows")

# 4. Quarterly (24Q)
print("\n" + "=" * 60)
print("4. RE-FETCH QUARTERLY (24Q)")
print("=" * 60)
BATCH_Q = 50
all_q = []
n_batches = (len(fixed_rics) + BATCH_Q - 1) // BATCH_Q
for i in range(0, len(fixed_rics), BATCH_Q):
    batch = fixed_rics[i:i + BATCH_Q]
    batch_num = i // BATCH_Q + 1
    t0 = time.time()
    try:
        df = rd.get_data(batch, QUARTERLY_FIELDS,
                         parameters={'SDate': '0', 'EDate': '-23', 'Period': 'FQ0', 'Frq': 'FQ'})
        print(f"  [Quarterly] Batch {batch_num}/{n_batches}: {len(df)} rows, {time.time()-t0:.1f}s")
        all_q.append(df)
    except Exception as e:
        print(f"  [Quarterly] Batch {batch_num}/{n_batches} ERROR: {e}")
    time.sleep(SLEEP_BETWEEN)
if all_q:
    new_q = pd.concat(all_q, ignore_index=True)
    new_q = add_symbol_col(new_q)
    keep = results['quarterly'][~results['quarterly']['Symbol'].isin(new_q['Symbol'])]
    results['quarterly'] = pd.concat([keep, new_q], ignore_index=True)
    print(f"  Total new quarterly: {len(new_q)} rows")

# 5. Estimate trends (EPS & Revenue, FY1 & FY2)
for period_label, period_code in [('FY1', 'FY1'), ('FY2', 'FY2')]:
    for metric, fields in [('eps', TREND_FIELDS_EPS), ('rev', TREND_FIELDS_REV)]:
        key = f'trend_{metric}_{period_label.lower()}'
        print(f"\n{'='*60}")
        print(f"5. RE-FETCH {key.upper()}")
        print(f"{'='*60}")
        new_trend = fetch_batched(fixed_rics, fields,
            parameters={'SDate': '-12M', 'EDate': '0', 'Period': period_code, 'Frq': 'CM'},
            desc=key)
        if len(new_trend) > 0:
            new_trend = add_symbol_col(new_trend)
            keep = results[key][~results[key]['Symbol'].isin(new_trend['Symbol'])]
            results[key] = pd.concat([keep, new_trend], ignore_index=True)
            print(f"  Got {len(new_trend)} rows")

# 6. Historical estimates
for fy_label, params in [('hist_est_fy1', {'SDate':'0','EDate':'-23','Period':'FY1','Frq':'FQ'}),
                          ('hist_est_fy2', {'SDate':'0','EDate':'-23','Period':'FY2','Frq':'FQ'})]:
    print(f"\n{'='*60}")
    print(f"6. RE-FETCH {fy_label.upper()}")
    print(f"{'='*60}")
    new_he = fetch_batched(fixed_rics, HIST_EST_FIELDS, parameters=params, desc=fy_label)
    if len(new_he) > 0:
        new_he = add_symbol_col(new_he)
        keep = results[fy_label][~results[fy_label]['Symbol'].isin(new_he['Symbol'])]
        results[fy_label] = pd.concat([keep, new_he], ignore_index=True)
        print(f"  Got {len(new_he)} rows")

rd.close_session()

# Save
with open(OUTPUT_FILE, 'wb') as f:
    pickle.dump(results, f)

fsize = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\n{'='*60}")
print(f"SAVED: {OUTPUT_FILE} ({fsize:.1f} MB)")
for k, v in results.items():
    print(f"  {k}: {len(v)} rows")
print("DONE")
