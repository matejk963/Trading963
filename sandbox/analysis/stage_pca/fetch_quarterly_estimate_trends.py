r"""
Fetch monthly trends of per-quarter EPS/Revenue estimates (FQ1-FQ4).
Provides proper revision history at the quarterly level.

Run from Windows: python sandbox\analysis\stage_pca\fetch_quarterly_estimate_trends.py
"""
import refinitiv.data as rd
import pandas as pd
import pickle
import time
import os
import shutil

pd.set_option('future.no_silent_downcasting', True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'mktt')
OUTPUT_FILE = os.path.join(DATA_DIR, 'refinitiv_fundamentals.pkl')

with open(OUTPUT_FILE, 'rb') as f:
    results = pickle.load(f)

uni = pd.read_parquet(os.path.join(DATA_DIR, 'universe.parquet'))
close = pd.read_parquet(os.path.join(DATA_DIR, 'close.parquet'))
tickers = sorted(close.columns.tolist())

exchange_map = dict(zip(uni['symbol'], uni['exchange']))
ric_to_sym = {}
def to_ric(sym):
    ex = exchange_map.get(sym, 'NYQ')
    if ex in ('NMS', 'NCM', 'NGM'): ric = sym + '.O'
    elif ex in ('NYQ', 'NYSE'): ric = sym + '.N'
    elif ex == 'ASE': ric = sym + '.A'
    else: ric = sym + '.N'
    ric_to_sym[ric] = sym
    return ric

all_rics = [to_ric(t) for t in tickers]
print(f"Universe: {len(all_rics)} RICs")

EPS_FIELDS = ['TR.EPSMean', 'TR.EPSMean.date']
REV_FIELDS = ['TR.RevenueMean', 'TR.RevenueMean.date']
BATCH = 100
SLEEP = 2

rd.open_session()
print("Session opened\n")

# Fetch EPS trends for FQ1-FQ4 (next 4 unreported quarters)
for fq_period in ['FQ1', 'FQ2', 'FQ3', 'FQ4']:
    for metric, fields, key_prefix in [('eps', EPS_FIELDS, 'trend_eps'), ('rev', REV_FIELDS, 'trend_rev')]:
        key = f'{key_prefix}_{fq_period.lower()}'
        print(f"{'='*60}")
        print(f"Fetching {key} (12M monthly)")
        print(f"{'='*60}")

        all_dfs = []
        n_batches = (len(all_rics) + BATCH - 1) // BATCH
        for i in range(0, len(all_rics), BATCH):
            batch = all_rics[i:i + BATCH]
            bn = i // BATCH + 1
            t0 = time.time()
            try:
                df = rd.get_data(batch, fields,
                    parameters={'SDate': '-12M', 'EDate': '0', 'Period': fq_period, 'Frq': 'CM'})
                print(f"  [{key}] Batch {bn}/{n_batches}: {len(df)} rows, {time.time()-t0:.1f}s")
                all_dfs.append(df)
            except Exception as e:
                print(f"  [{key}] Batch {bn}/{n_batches} ERROR: {e}")
            if i + BATCH < len(all_rics):
                time.sleep(SLEEP)

        if all_dfs:
            trend_df = pd.concat(all_dfs, ignore_index=True)
            trend_df['Symbol'] = trend_df['Instrument'].map(lambda r: ric_to_sym.get(r, r.split('.')[0]))
            trend_df['FQ'] = fq_period
            results[key] = trend_df
            print(f"  Total: {len(trend_df)} rows, {trend_df['Symbol'].nunique()} stocks")

rd.close_session()

# Save
shutil.copy2(OUTPUT_FILE, OUTPUT_FILE + '.bak')
with open(OUTPUT_FILE, 'wb') as f:
    pickle.dump(results, f)

fsize = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\nSaved: {OUTPUT_FILE} ({fsize:.1f} MB)")
print(f"Keys: {list(results.keys())}")
print("Done!")
