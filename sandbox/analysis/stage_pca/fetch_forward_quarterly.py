r"""
Fetch forward quarterly EPS and Revenue estimates (next 4 quarters).
Used to compute true NTM (Next Twelve Months) EPS/Revenue.

Run from Windows: python sandbox\analysis\stage_pca\fetch_forward_quarterly.py
"""
import refinitiv.data as rd
import pandas as pd
import numpy as np
import pickle
import time
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'mktt')
OUTPUT_FILE = os.path.join(DATA_DIR, 'refinitiv_fundamentals.pkl')

# Load existing
with open(OUTPUT_FILE, 'rb') as f:
    results = pickle.load(f)
print(f"Loaded existing data: {list(results.keys())}")

# Build RIC mapping
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
print(f"Universe: {len(tickers)} tickers -> {len(all_rics)} RICs")

FIELDS = ['TR.EPSMean', 'TR.EPSMean.date', 'TR.RevenueMean']
PARAMS = {'SDate': '0', 'EDate': '4', 'Period': 'FQ1', 'Frq': 'FQ'}
BATCH_SIZE = 100
SLEEP = 2

rd.open_session()
print("Session opened\n")

all_dfs = []
n_batches = (len(all_rics) + BATCH_SIZE - 1) // BATCH_SIZE
for i in range(0, len(all_rics), BATCH_SIZE):
    batch = all_rics[i:i + BATCH_SIZE]
    bn = i // BATCH_SIZE + 1
    t0 = time.time()
    try:
        df = rd.get_data(batch, FIELDS, parameters=PARAMS)
        print(f"  Batch {bn}/{n_batches}: {len(df)} rows, {time.time()-t0:.1f}s")
        all_dfs.append(df)
    except Exception as e:
        print(f"  Batch {bn}/{n_batches} ERROR: {e}")
        for j in range(0, len(batch), 25):
            sub = batch[j:j+25]
            try:
                df = rd.get_data(sub, FIELDS, parameters=PARAMS)
                all_dfs.append(df)
            except:
                pass
            time.sleep(1)
    if i + BATCH_SIZE < len(all_rics):
        time.sleep(SLEEP)

rd.close_session()

if all_dfs:
    fwd_q = pd.concat(all_dfs, ignore_index=True)
    fwd_q['Symbol'] = fwd_q['Instrument'].map(lambda r: ric_to_sym.get(r, r.split('.')[0]))
    results['forward_quarterly'] = fwd_q
    print(f"\nForward quarterly: {len(fwd_q)} rows, {fwd_q['Symbol'].nunique()} stocks")

    # Backup and save
    import shutil
    backup = OUTPUT_FILE + '.bak'
    shutil.copy2(OUTPUT_FILE, backup)
    with open(OUTPUT_FILE, 'wb') as f:
        pickle.dump(results, f)
    fsize = os.path.getsize(OUTPUT_FILE) / 1e6
    print(f"Saved: {OUTPUT_FILE} ({fsize:.1f} MB)")
else:
    print("No data fetched")

print("Done!")
