r"""
Re-fetch forward quarterly estimates with High/Low bounds.
Overwrites forward_quarterly in the pickle.

Run from Windows: python sandbox\analysis\stage_pca\refetch_forward_quarterly_hilo.py
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

FIELDS = ['TR.EPSMean', 'TR.EPSHigh', 'TR.EPSLow', 'TR.EPSMean.date',
          'TR.RevenueMean', 'TR.RevenueHigh', 'TR.RevenueLow']
PARAMS = {'SDate': '0', 'EDate': '8', 'Period': 'FQ1', 'Frq': 'FQ'}
BATCH = 100

rd.open_session()
print("Session opened\n")

all_dfs = []
n_batches = (len(all_rics) + BATCH - 1) // BATCH
for i in range(0, len(all_rics), BATCH):
    batch = all_rics[i:i + BATCH]
    bn = i // BATCH + 1
    t0 = time.time()
    try:
        df = rd.get_data(batch, FIELDS, parameters=PARAMS)
        print(f"  Batch {bn}/{n_batches}: {len(df)} rows, {time.time()-t0:.1f}s")
        all_dfs.append(df)
    except Exception as e:
        print(f"  Batch {bn}/{n_batches} ERROR: {e}")
    if i + BATCH < len(all_rics):
        time.sleep(2)

rd.close_session()

if all_dfs:
    fwd_q = pd.concat(all_dfs, ignore_index=True)
    fwd_q['Symbol'] = fwd_q['Instrument'].map(lambda r: ric_to_sym.get(r, r.split('.')[0]))
    results['forward_quarterly'] = fwd_q
    print(f"\nForward quarterly: {len(fwd_q)} rows, {fwd_q['Symbol'].nunique()} stocks")
    print(f"Columns: {list(fwd_q.columns)}")

    shutil.copy2(OUTPUT_FILE, OUTPUT_FILE + '.bak')
    with open(OUTPUT_FILE, 'wb') as f:
        pickle.dump(results, f)
    print(f"Saved: {os.path.getsize(OUTPUT_FILE)/1e6:.1f} MB")

print("Done!")
