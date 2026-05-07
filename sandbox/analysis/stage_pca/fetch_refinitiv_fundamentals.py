"""
Fetch comprehensive fundamentals from Refinitiv for the full MKTT universe.
Must be run from Windows (cmd.exe) where Refinitiv Workspace is running.

Fetches:
  1. Snapshot: 38 fundamental fields for all stocks
  2. Forward estimates: FY1 + FY2 (EPS, Revenue, EBITDA, CapEx, CFPS, DPS)
  3. Quarterly history: 12 quarters of EPS, Revenue, Margins, FCF, Debt, Liquidity

Output: data/mktt/refinitiv_fundamentals.pkl
"""
import refinitiv.data as rd
import pandas as pd
import numpy as np
import pickle
import time
import sys
import os

pd.set_option('future.no_silent_downcasting', True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'mktt')
OUTPUT_FILE = os.path.join(DATA_DIR, 'refinitiv_fundamentals.pkl')

# Load universe
uni = pd.read_parquet(os.path.join(DATA_DIR, 'universe.parquet'))
close = pd.read_parquet(os.path.join(DATA_DIR, 'close.parquet'))
tickers = sorted(close.columns.tolist())

# RIC mapping
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
        ric = sym + '.N'  # default to NYSE
    ric_to_sym[ric] = sym
    return ric

all_rics = [to_ric(t) for t in tickers]
print(f"Universe: {len(tickers)} tickers -> {len(all_rics)} RICs")

# =========================================================================
# Field definitions
# =========================================================================
SNAPSHOT_FIELDS = [
    # Price
    'TR.PriceClose',
    # EPS
    'TR.EPSActValue', 'TR.EPSMean', 'TR.EPSSmartEst',
    # Revenue
    'TR.RevenueActValue', 'TR.RevenueMean',
    # Margins
    'TR.OperatingMargin', 'TR.NetProfitMargin', 'TR.GrossProfit',
    'TR.EBITDA', 'TR.OperatingIncome', 'TR.NetIncome',
    # FCF
    'TR.FreeCashFlow', 'TR.CashFromOperations', 'TR.CapitalExpenditure',
    # Balance sheet
    'TR.TotalDebt', 'TR.NetDebt', 'TR.CashAndSTInvestments',
    'TR.TotalAssets', 'TR.TotalEquity',
    # Leverage
    'TR.DebtToEquity', 'TR.NetDebtToEBITDA', 'TR.TotalDebtToEBITDA',
    # Liquidity
    'TR.CurrentRatio', 'TR.QuickRatio', 'TR.WorkingCapital',
    # Quality
    'TR.ReturnOnCapitalPercent', 'TR.AssetTurnover',
    # Valuation
    'TR.EVToEBITDA', 'TR.EVToSales', 'TR.EV', 'TR.MktCap',
    # Dividends & shares
    'TR.DPSActValue', 'TR.SharesOutstanding',
    # Analyst
    'TR.PriceTargetMean', 'TR.NumberOfAnalysts',
    # Sector
    'TR.GICSSector', 'TR.GICSIndustry',
]

FORWARD_FIELDS = [
    'TR.EPSMean', 'TR.EPSHigh', 'TR.EPSLow', 'TR.EPSSmartEst', 'TR.EPSNumOfEst',
    'TR.RevenueMean', 'TR.RevenueHigh', 'TR.RevenueLow',
    'TR.EBITDAMean', 'TR.EBITDASmartEst',
    'TR.CapExMean',
    'TR.CFPSMean',
    'TR.DPSMean',
]

QUARTERLY_FIELDS = [
    'TR.EPSActValue', 'TR.EPSActValue.date', 'TR.EPSMeanEstimate',
    'TR.RevenueActValue', 'TR.RevenueMeanEstimate',
    'TR.OperatingMargin', 'TR.NetProfitMargin',
    'TR.FreeCashFlow',
    'TR.TotalDebt', 'TR.NetDebt',
    'TR.CashAndSTInvestments',
    'TR.CurrentRatio',
]

QUARTERLY_PARAMS = {'SDate': '0', 'EDate': '-11', 'Period': 'FQ0', 'Frq': 'FQ'}

BATCH_SIZE = 200
SLEEP_BETWEEN = 2  # seconds between batches

# =========================================================================
# Fetch functions
# =========================================================================
def fetch_batched(rics, fields, parameters=None, desc=""):
    """Fetch data in batches, return combined DataFrame."""
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
            # Try smaller sub-batches
            for j in range(0, len(batch), 50):
                sub = batch[j:j+50]
                try:
                    if parameters:
                        df = rd.get_data(sub, fields, parameters=parameters)
                    else:
                        df = rd.get_data(sub, fields)
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
# Main
# =========================================================================
# Load existing results if available (for incremental fetch)
if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, 'rb') as f:
        results = pickle.load(f)
    print(f"Loaded existing data: {list(results.keys())}")
else:
    results = {}

rd.open_session()
print("Session opened\n")

# 1. Snapshot
if 'snapshot' in results:
    print("1. SNAPSHOT — already fetched, skipping")
else:
    print("=" * 60)
    print("1. SNAPSHOT FUNDAMENTALS")
    print("=" * 60)
    t0 = time.time()
    snapshot = fetch_batched(all_rics, SNAPSHOT_FIELDS, desc="Snapshot")
    if len(snapshot) > 0:
        snapshot['Symbol'] = snapshot['Instrument'].map(lambda r: ric_to_sym.get(r, r))
        results['snapshot'] = snapshot
        print(f"  Total: {len(snapshot)} rows, {time.time()-t0:.0f}s")
        nn = snapshot.iloc[:, 1:].notna().sum()
        print(f"  Non-null coverage:")
        for col, cnt in nn.items():
            print(f"    {col}: {cnt}/{len(snapshot)} ({cnt/len(snapshot)*100:.0f}%)")

# 2. Forward estimates FY1
if 'fy1' in results:
    print("2. FY1 — already fetched, skipping")
else:
    print("\n" + "=" * 60)
    print("2. FORWARD ESTIMATES FY1")
    print("=" * 60)
    t0 = time.time()
    fy1 = fetch_batched(all_rics, FORWARD_FIELDS, parameters={'Period': 'FY1'}, desc="FY1")
    if len(fy1) > 0:
        fy1['Symbol'] = fy1['Instrument'].map(lambda r: ric_to_sym.get(r, r))
        results['fy1'] = fy1
        print(f"  Total: {len(fy1)} rows, {time.time()-t0:.0f}s")

# 3. Forward estimates FY2
if 'fy2' in results:
    print("3. FY2 — already fetched, skipping")
else:
    print("\n" + "=" * 60)
    print("3. FORWARD ESTIMATES FY2")
    print("=" * 60)
    t0 = time.time()
    fy2 = fetch_batched(all_rics, FORWARD_FIELDS, parameters={'Period': 'FY2'}, desc="FY2")
    if len(fy2) > 0:
        fy2['Symbol'] = fy2['Instrument'].map(lambda r: ric_to_sym.get(r, r))
        results['fy2'] = fy2
        print(f"  Total: {len(fy2)} rows, {time.time()-t0:.0f}s")

# 4. Quarterly history
if 'quarterly' in results:
    print("4. QUARTERLY — already fetched, skipping")
else:
    print("\n" + "=" * 60)
    print("4. QUARTERLY HISTORY (12 quarters)")
    print("=" * 60)
    t0 = time.time()
    BATCH_SIZE_Q = 50
    all_q = []
    n_batches = (len(all_rics) + BATCH_SIZE_Q - 1) // BATCH_SIZE_Q
    for i in range(0, len(all_rics), BATCH_SIZE_Q):
        batch = all_rics[i:i + BATCH_SIZE_Q]
        batch_num = i // BATCH_SIZE_Q + 1
        t1 = time.time()
        try:
            df = rd.get_data(batch, QUARTERLY_FIELDS, parameters=QUARTERLY_PARAMS)
            elapsed = time.time() - t1
            print(f"  [Quarterly] Batch {batch_num}/{n_batches}: {len(df)} rows, {elapsed:.1f}s")
            all_q.append(df)
        except Exception as e:
            print(f"  [Quarterly] Batch {batch_num}/{n_batches} ERROR: {e}")
            for ric in batch:
                try:
                    df = rd.get_data(ric, QUARTERLY_FIELDS, parameters=QUARTERLY_PARAMS)
                    all_q.append(df)
                except:
                    pass
        time.sleep(SLEEP_BETWEEN)
    if all_q:
        quarterly = pd.concat(all_q, ignore_index=True)
        quarterly['Symbol'] = quarterly['Instrument'].map(lambda r: ric_to_sym.get(r, r))
        results['quarterly'] = quarterly
        print(f"  Total: {len(quarterly)} rows, {time.time()-t0:.0f}s")
        n_stocks = quarterly['Instrument'].nunique()
        print(f"  Unique stocks: {n_stocks}")
        avg_q = len(quarterly) / n_stocks if n_stocks > 0 else 0
        print(f"  Avg quarters per stock: {avg_q:.1f}")

# 4b. Extended quarterly history (quarters -12 to -23, the 12 before existing)
QUARTERLY_PARAMS_EXT = {'SDate': '-12', 'EDate': '-23', 'Period': 'FQ0', 'Frq': 'FQ'}

if 'quarterly_ext' in results:
    print("4b. QUARTERLY EXT — already fetched, skipping")
else:
    print("\n" + "=" * 60)
    print("4b. QUARTERLY HISTORY EXTENDED (quarters -12 to -23)")
    print("=" * 60)
    t0 = time.time()
    BATCH_SIZE_Q = 50
    all_qx = []
    n_batches = (len(all_rics) + BATCH_SIZE_Q - 1) // BATCH_SIZE_Q
    for i in range(0, len(all_rics), BATCH_SIZE_Q):
        batch = all_rics[i:i + BATCH_SIZE_Q]
        batch_num = i // BATCH_SIZE_Q + 1
        t1 = time.time()
        try:
            df = rd.get_data(batch, QUARTERLY_FIELDS, parameters=QUARTERLY_PARAMS_EXT)
            elapsed = time.time() - t1
            print(f"  [QuarterlyExt] Batch {batch_num}/{n_batches}: {len(df)} rows, {elapsed:.1f}s")
            all_qx.append(df)
        except Exception as e:
            print(f"  [QuarterlyExt] Batch {batch_num}/{n_batches} ERROR: {e}")
            for ric in batch:
                try:
                    df = rd.get_data(ric, QUARTERLY_FIELDS, parameters=QUARTERLY_PARAMS_EXT)
                    all_qx.append(df)
                except:
                    pass
        time.sleep(SLEEP_BETWEEN)
    if all_qx:
        qx_df = pd.concat(all_qx, ignore_index=True)
        qx_df['Symbol'] = qx_df['Instrument'].map(lambda r: ric_to_sym.get(r, r))
        results['quarterly_ext'] = qx_df
        print(f"  Total: {len(qx_df)} rows, {time.time()-t0:.0f}s")
        n_stocks = qx_df['Instrument'].nunique()
        print(f"  Unique stocks: {n_stocks}")

    # Merge with existing quarterly
    if 'quarterly' in results and 'quarterly_ext' in results:
        merged_q = pd.concat([results['quarterly_ext'], results['quarterly']], ignore_index=True)
        # Remove duplicates (same instrument + date)
        merged_q['_dedup'] = merged_q['Instrument'].astype(str) + '_' + merged_q['Date'].astype(str)
        merged_q = merged_q.drop_duplicates(subset='_dedup', keep='last').drop(columns='_dedup')
        merged_q = merged_q.sort_values(['Instrument', 'Date'])
        results['quarterly'] = merged_q
        del results['quarterly_ext']  # no need to keep separate
        print(f"  Merged quarterly: {len(merged_q)} rows")
        n_stocks = merged_q['Symbol'].nunique()
        avg_q = len(merged_q) / n_stocks if n_stocks > 0 else 0
        print(f"  Avg quarters per stock: {avg_q:.1f}")

# 4c. Historical FY1/FY2 estimates at each quarterly earnings date (24Q)
HIST_EST_FIELDS = ['TR.EPSMean', 'TR.EPSMean.date']
HIST_EST_PARAMS_FY1 = {'SDate':'0','EDate':'-23','Period':'FY1','Frq':'FQ'}
HIST_EST_PARAMS_FY2 = {'SDate':'0','EDate':'-23','Period':'FY2','Frq':'FQ'}

for fy_label, params in [('hist_est_fy1', HIST_EST_PARAMS_FY1), ('hist_est_fy2', HIST_EST_PARAMS_FY2)]:
    if fy_label in results:
        print(f"4c. {fy_label} — already fetched, skipping")
    else:
        print(f"\n{'='*60}")
        print(f"4c. HISTORICAL ESTIMATES: {fy_label.upper()} (24 quarterly snapshots)")
        print(f"{'='*60}")
        t0 = time.time()
        BATCH_SIZE_Q = 50
        all_he = []
        n_batches = (len(all_rics) + BATCH_SIZE_Q - 1) // BATCH_SIZE_Q
        for i in range(0, len(all_rics), BATCH_SIZE_Q):
            batch = all_rics[i:i + BATCH_SIZE_Q]
            batch_num = i // BATCH_SIZE_Q + 1
            t1 = time.time()
            try:
                df = rd.get_data(batch, HIST_EST_FIELDS, parameters=params)
                elapsed = time.time() - t1
                print(f"  [{fy_label}] Batch {batch_num}/{n_batches}: {len(df)} rows, {elapsed:.1f}s")
                all_he.append(df)
            except Exception as e:
                print(f"  [{fy_label}] Batch {batch_num}/{n_batches} ERROR: {e}")
                for ric in batch:
                    try:
                        df = rd.get_data(ric, HIST_EST_FIELDS, parameters=params)
                        all_he.append(df)
                    except:
                        pass
            time.sleep(SLEEP_BETWEEN)
        if all_he:
            he_df = pd.concat(all_he, ignore_index=True)
            he_df['Symbol'] = he_df['Instrument'].map(lambda r: ric_to_sym.get(r, r))
            results[fy_label] = he_df
            n_stocks = he_df['Instrument'].nunique()
            print(f"  Total: {len(he_df)} rows, {n_stocks} stocks, {time.time()-t0:.0f}s")

# 5. Estimate trends — monthly EPS & Revenue consensus evolution (12M)
TREND_FIELDS_EPS = [
    'TR.EPSMean', 'TR.EPSMean.date',
    'TR.EPSHigh', 'TR.EPSLow', 'TR.EPSNumOfEst',
]
TREND_FIELDS_REV = [
    'TR.RevenueMean', 'TR.RevenueMean.date',
    'TR.RevenueHigh', 'TR.RevenueLow',
]
TREND_BATCH = 100  # smaller batches since each returns ~13 rows per stock

for period_label, period_code in [('FY1', 'FY1'), ('FY2', 'FY2')]:
    for metric, fields in [('eps', TREND_FIELDS_EPS), ('rev', TREND_FIELDS_REV)]:
        key = f'trend_{metric}_{period_label.lower()}'
        if key in results:
            print(f"5. {key} — already fetched, skipping")
            continue
        print(f"\n{'='*60}")
        print(f"5. ESTIMATE TREND: {metric.upper()} {period_label} (12M monthly)")
        print(f"{'='*60}")
        t0 = time.time()
        all_trend = []
        n_batches_t = (len(all_rics) + TREND_BATCH - 1) // TREND_BATCH

        for i in range(0, len(all_rics), TREND_BATCH):
            batch = all_rics[i:i + TREND_BATCH]
            batch_num = i // TREND_BATCH + 1
            t1 = time.time()
            try:
                df = rd.get_data(batch, fields,
                    parameters={'SDate': '-12M', 'EDate': '0', 'Period': period_code, 'Frq': 'CM'})
                elapsed = time.time() - t1
                print(f"  [{key}] Batch {batch_num}/{n_batches_t}: {len(df)} rows, {elapsed:.1f}s")
                all_trend.append(df)
            except Exception as e:
                print(f"  [{key}] Batch {batch_num}/{n_batches_t} ERROR: {e}")
                # Retry with smaller sub-batches
                for j in range(0, len(batch), 25):
                    sub = batch[j:j+25]
                    try:
                        df = rd.get_data(sub, fields,
                            parameters={'SDate': '-12M', 'EDate': '0', 'Period': period_code, 'Frq': 'CM'})
                        all_trend.append(df)
                    except:
                        pass
                    time.sleep(1)
            time.sleep(SLEEP_BETWEEN)

        if all_trend:
            trend_df = pd.concat(all_trend, ignore_index=True)
            trend_df['Symbol'] = trend_df['Instrument'].map(lambda r: ric_to_sym.get(r, r))
            results[key] = trend_df
            n_stocks = trend_df['Instrument'].nunique()
            print(f"  Total: {len(trend_df)} rows, {n_stocks} stocks, {time.time()-t0:.0f}s")
            avg_pts = len(trend_df) / n_stocks if n_stocks > 0 else 0
            print(f"  Avg points per stock: {avg_pts:.1f}")

rd.close_session()

# Save
with open(OUTPUT_FILE, 'wb') as f:
    pickle.dump(results, f)

fsize = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\n{'='*60}")
print(f"SAVED: {OUTPUT_FILE} ({fsize:.1f} MB)")
print(f"Keys: {list(results.keys())}")
for k, v in results.items():
    print(f"  {k}: {len(v)} rows x {len(v.columns)} cols")
print("DONE")
