"""
Daily classification update — recomputes all classification JSONs
from current price data. Run after prices are updated.

Usage:
    cd src/mktt
    python update_classifications.py

Generates:
    sandbox/analysis/stage_pca/output/data/pca20_5c_meta.json  (PCA 5-cluster regimes)
    sandbox/analysis/stage_pca/output/data/stages_meta.json     (Weinstein stages)
    sandbox/analysis/stage_pca/output/data/screener_meta.json   (MA position screener)
    sandbox/analysis/stage_pca/output/data/eps_growth_meta.json (EPS acceleration)
"""
import sys
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'mktt'))
sys.path.insert(0, str(PROJECT_ROOT / 'sandbox' / 'analysis' / 'stage_pca'))

from data_manager import load_prices, load_spy

DATA_DIR = PROJECT_ROOT / 'data' / 'mktt'
OUTPUT_DIR = PROJECT_ROOT / 'sandbox' / 'analysis' / 'stage_pca' / 'output' / 'data'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# Load price data
# =========================================================================
print("Loading price data...")
close = load_prices('close')
high = load_prices('high')
low = load_prices('low')
volume = load_prices('volume')
spy_df = load_spy()

if close is None or spy_df is None:
    print("ERROR: No data found.")
    sys.exit(1)

spyclose = spy_df['Close']
print(f"  {close.shape[1]} tickers, {close.shape[0]} days, last={close.index[-1].date()}")

# Find last dense row
min_stocks = len(close.columns) * 0.5
_idx = len(close) - 1
for _i in range(len(close) - 1, max(len(close) - 10, 0), -1):
    if close.iloc[_i].notna().sum() >= min_stocks:
        _idx = _i
        break
# Find last date with 20+ consecutive days of complete OHLCV (needed for rolling features)
min_stocks = len(close.columns) * 0.3
_idx = None
for _i in range(len(close) - 1, 20, -1):
    if min(close.iloc[_i].notna().sum(), high.iloc[_i].notna().sum(),
           low.iloc[_i].notna().sum(), volume.iloc[_i].notna().sum()) < min_stocks:
        continue
    # Check 20 prior days also have coverage
    ok = True
    for _j in range(1, 21):
        if min(high.iloc[_i - _j].notna().sum(), volume.iloc[_i - _j].notna().sum()) < min_stocks:
            ok = False
            break
    if ok:
        _idx = _i
        break

if _idx is None:
    print("ERROR: No date with 20 consecutive days of complete OHLCV found.")
    sys.exit(1)

n_ohlcv = min(close.iloc[_idx].notna().sum(), high.iloc[_idx].notna().sum())
print(f"  Using date: {close.index[_idx].date()} ({n_ohlcv} stocks with complete OHLCV)")

# Slice to dense date
close = close.iloc[:_idx + 1]
high = high.iloc[:_idx + 1]
low = low.iloc[:_idx + 1]
volume = volume.iloc[:_idx + 1]

# Common tickers with enough data (252 days)
valid = close.notna().sum() >= 252
tickers = sorted(valid[valid].index.tolist())
common = list(set(tickers) & set(high.columns) & set(low.columns) & set(volume.columns))
print(f"  {len(common)} tickers with >= 252 days of data")

# Technicals
last_prices = close[common].iloc[-1]
ma50 = close[common].rolling(50).mean().iloc[-1]
ma150 = close[common].rolling(150).mean().iloc[-1]
ma200 = close[common].rolling(200).mean().iloc[-1]
dist50 = ((last_prices - ma50) / ma50 * 100).round(2)
dist200 = ((last_prices - ma200) / ma200 * 100).round(2)

# RS rank
ret_6m = (close[common].iloc[-1] / close[common].iloc[-126] - 1)
rs_rank = (ret_6m.rank(pct=True) * 100).round(0)

# =========================================================================
# 1. Weinstein Stages
# =========================================================================
print("\n[1/4] Computing Weinstein Stages...")
from stage_classifier import compute_all_derived_vectorized, classify_all_stages

derived, _ = compute_all_derived_vectorized(close, high, low, volume, spyclose)
stage_df = classify_all_stages(derived)
latest_stages = stage_df.iloc[-1] if isinstance(stage_df, pd.DataFrame) else pd.Series()

stage_names = {1: 'Stage 1 Basing', 2: 'Stage 2 Uptrend', 3: 'Stage 3 Topping', 4: 'Stage 4 Declining'}
stages_meta = {}
for stage_id, stage_name in stage_names.items():
    mask = latest_stages == stage_id
    syms = [t for t in mask.index if mask[t] and t in common]
    stocks = []
    for s in syms:
        stocks.append({
            's': s,
            'p': round(float(last_prices.get(s, 0)), 2),
            'd50': round(float(dist50.get(s, 0)), 2),
            'd200': round(float(dist200.get(s, 0)), 2),
            'rs': int(rs_rank.get(s, 0)),
            'st': f'S{stage_id}',
        })
    stocks.sort(key=lambda x: x['rs'], reverse=True)
    stages_meta[str(stage_id)] = {'n': stage_name, 'stocks': stocks}

with open(OUTPUT_DIR / 'stages_meta.json', 'w') as f:
    json.dump(stages_meta, f)
total_staged = sum(len(v['stocks']) for v in stages_meta.values())
print(f"  Stages: {total_staged} stocks classified")
for k, v in stages_meta.items():
    print(f"    S{k} {v['n']}: {len(v['stocks'])}")

# =========================================================================
# 2. PCA 5-Cluster Regimes
# =========================================================================
print("\n[2/4] Computing PCA 5-Cluster Regimes...")
from pca_stage_classifier import compute_features, extract_latest_cross_section, FEATURE_NAMES

features, feat_common = compute_features(close, high, low, volume, spyclose)
cross_section = extract_latest_cross_section(features, feat_common)
print(f"  Cross-section: {len(cross_section)} stocks × {len(FEATURE_NAMES)} features")

# Z-score and PCA
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

z = (cross_section - cross_section.mean()) / cross_section.std().clip(lower=1e-8)
z = z.clip(-5, 5)

pca = PCA(n_components=min(20, len(FEATURE_NAMES), len(z)))
scores = pca.fit_transform(z.values)

# Enforce PC1 sign: positive = bullish
idx_trend = FEATURE_NAMES.index('log_close_ma200')
if pca.components_[0, idx_trend] < 0:
    pca.components_[0] *= -1
    scores[:, 0] *= -1

scores_df = pd.DataFrame(scores[:, :5], index=z.index, columns=[f'PC{i+1}' for i in range(min(5, scores.shape[1]))])

# KMeans 5 clusters on PC1-PC5
n_clusters = 5
km = KMeans(n_clusters=n_clusters, n_init=20, random_state=42)
labels = km.fit_predict(scores_df.values)

# Sort clusters by mean PC1
cluster_means = {c: scores_df.iloc[labels == c, 0].mean() for c in range(n_clusters)}
sorted_clusters = sorted(cluster_means, key=cluster_means.get)
remap = {old: new for new, old in enumerate(sorted_clusters)}
labels_sorted = np.array([remap[l] for l in labels])

# Name clusters by position
cluster_names = {0: 'Declining', 1: 'Distributing', 2: 'Erupting', 3: 'Quiet Uptrend', 4: 'Strong Leader'}

pca_meta = {}
for c in range(n_clusters):
    mask = labels_sorted == c
    syms = scores_df.index[mask].tolist()
    stocks = []
    for s in syms:
        stocks.append({
            's': s,
            'p': round(float(last_prices.get(s, 0)), 2),
            'p1': round(float(scores_df.loc[s, 'PC1']), 2),
            'p2': round(float(scores_df.loc[s, 'PC2']), 2),
            'rs': int(rs_rank.get(s, 0)),
            'st': f'S{int(latest_stages.get(s, 0))}' if s in latest_stages.index else 'S0',
        })
    stocks.sort(key=lambda x: x['rs'], reverse=True)
    pca_meta[str(c)] = {'n': cluster_names.get(c, f'Cluster {c}'), 'stocks': stocks}

with open(OUTPUT_DIR / 'pca20_5c_meta.json', 'w') as f:
    json.dump(pca_meta, f)
print(f"  PCA clusters: {sum(len(v['stocks']) for v in pca_meta.values())} stocks")
for k, v in pca_meta.items():
    print(f"    C{k} {v['n']}: {len(v['stocks'])}")

# =========================================================================
# 3. MA Position Screener
# =========================================================================
print("\n[3/4] Computing MA Position Screener...")
screener_cats = {
    'Above Both': lambda: (last_prices > ma50) & (last_prices > ma200),
    'Above 200 Below 50': lambda: (last_prices > ma200) & (last_prices <= ma50),
    'Below 200 Above 50': lambda: (last_prices <= ma200) & (last_prices > ma50),
    'Below Both': lambda: (last_prices <= ma50) & (last_prices <= ma200),
}

screener_meta = {}
for i, (name, condition_fn) in enumerate(screener_cats.items()):
    mask = condition_fn()
    syms = [s for s in mask.index if mask[s]]
    stocks = []
    for s in syms:
        stocks.append({
            's': s,
            'p': round(float(last_prices.get(s, 0)), 2),
            'd50': round(float(dist50.get(s, 0)), 2),
            'd200': round(float(dist200.get(s, 0)), 2),
            'rs': int(rs_rank.get(s, 0)),
            'st': f'S{int(latest_stages.get(s, 0))}' if s in latest_stages.index else 'S0',
        })
    stocks.sort(key=lambda x: x['rs'], reverse=True)
    screener_meta[str(i)] = {'n': name, 'stocks': stocks}

with open(OUTPUT_DIR / 'screener_meta.json', 'w') as f:
    json.dump(screener_meta, f)
print(f"  Screener: {sum(len(v['stocks']) for v in screener_meta.values())} stocks")
for k, v in screener_meta.items():
    print(f"    {v['n']}: {len(v['stocks'])}")

# =========================================================================
# 4. EPS Growth Acceleration
# =========================================================================
print("\n[4/4] Computing EPS Acceleration...")
rfv_path = DATA_DIR / 'refinitiv_fundamentals.pkl'
eps_meta = {'accel': {'n': 'Accelerating vs Decelerating', 'stocks': []}}

if rfv_path.exists():
    with open(rfv_path, 'rb') as f:
        rfv_data = pickle.load(f)
    snap = rfv_data.get('snapshot')
    fy1 = rfv_data.get('fy1')
    fy2 = rfv_data.get('fy2')

    if snap is not None and fy1 is not None and fy2 is not None:
        accel_stocks = {'1': [], '0': []}  # 1=accelerating, 0=decelerating
        for _, row in snap.iterrows():
            sym = row.get('Symbol')
            if pd.isna(sym) or sym not in common:
                continue
            eps_act = pd.to_numeric(row.get('Earnings Per Share - Actual'), errors='coerce')
            f1 = fy1[fy1['Symbol'] == sym]
            f2 = fy2[fy2['Symbol'] == sym]
            eps_fy1 = pd.to_numeric(f1.iloc[0].get('Earnings Per Share - Mean'), errors='coerce') if len(f1) > 0 else np.nan
            eps_fy2 = pd.to_numeric(f2.iloc[0].get('Earnings Per Share - Mean'), errors='coerce') if len(f2) > 0 else np.nan

            if pd.isna(eps_act) or pd.isna(eps_fy1) or pd.isna(eps_fy2):
                continue

            g1 = eps_fy1 - eps_act  # CY growth
            g2 = eps_fy2 - eps_fy1  # NY growth
            acc = g2 - g1  # acceleration

            _rs = rs_rank.get(sym)
            rec = {
                's': sym,
                'p': round(float(last_prices.get(sym, 0)), 2),
                'acc': round(float(acc), 3),
                'g1': round(float(g1), 3),
                'g2': round(float(g2), 3),
                'rs': int(_rs) if pd.notna(_rs) else 0,
            }
            if acc > 0:
                accel_stocks['1'].append(rec)
            else:
                accel_stocks['0'].append(rec)

        accel_stocks['1'].sort(key=lambda x: x['rs'], reverse=True)
        accel_stocks['0'].sort(key=lambda x: x['rs'], reverse=True)
        eps_meta = accel_stocks

with open(OUTPUT_DIR / 'eps_growth_meta.json', 'w') as f:
    json.dump({'accel': eps_meta}, f)
n_acc = len(eps_meta.get('1', []))
n_dec = len(eps_meta.get('0', []))
print(f"  EPS: {n_acc} accelerating, {n_dec} decelerating")

# =========================================================================
# Summary
# =========================================================================
print(f"\n{'='*60}")
print(f"Classification update complete — {close.index[-1].date()}")
print(f"  Output: {OUTPUT_DIR}")
print(f"  PCA regimes: {sum(len(v['stocks']) for v in pca_meta.values())} stocks")
print(f"  Stages: {total_staged} stocks")
print(f"  MA Screener: {sum(len(v['stocks']) for v in screener_meta.values())} stocks")
print(f"  EPS Accel: {n_acc + n_dec} stocks")
print(f"{'='*60}")
