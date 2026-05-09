"""
Compute classification time series: for each trading day over the last 12 months,
compute PCA regimes, Weinstein stages, and MA screener categories.
Shows how stock counts per sector × classification evolve over time.

Run from: cd src/mktt && python ../../sandbox/analysis/classification_evolution/compute_history.py
"""
import sys
import numpy as np
import pandas as pd
import pickle
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'mktt'))
sys.path.insert(0, str(PROJECT_ROOT / 'sandbox' / 'analysis' / 'stage_pca'))

from data_manager import load_prices, load_spy
from pca_stage_classifier import compute_features, FEATURE_NAMES
from stage_classifier import compute_all_derived_vectorized, classify_all_stages
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = PROJECT_ROOT / 'data' / 'mktt'

# =========================================================================
# Load data
# =========================================================================
print("Loading data...")
close = load_prices('close')
high = load_prices('high')
low = load_prices('low')
volume = load_prices('volume')
spy_df = load_spy()
spy_close = spy_df['Close']

# Load Refinitiv for sector mapping
rfv_path = DATA_DIR / 'refinitiv_fundamentals.pkl'
sector_map = {}
if rfv_path.exists():
    with open(rfv_path, 'rb') as f:
        rfv = pickle.load(f)
    snap = rfv.get('snapshot')
    if snap is not None:
        for _, row in snap.iterrows():
            sym = row.get('Symbol')
            sec = row.get('GICS Sector Name')
            if pd.notna(sym) and pd.notna(sec) and str(sec) != '<NA>':
                sector_map[str(sym)] = str(sec)

print(f"  {close.shape[1]} tickers, {close.shape[0]} days")
print(f"  Sector map: {len(sector_map)} stocks")

# =========================================================================
# Compute features once (full history)
# =========================================================================
print("\nComputing PCA features (full history)...")
features, common = compute_features(close, high, low, volume, spy_close)
print(f"  Features for {len(common)} tickers")

# Compute Weinstein stages (full history)
print("Computing Weinstein stages (full history)...")
derived, _ = compute_all_derived_vectorized(close, high, low, volume, spy_close)
stage_df = classify_all_stages(derived)
print(f"  Stages shape: {stage_df.shape}")

# =========================================================================
# EMA-smooth features for stability (halflife ~10 trading days)
# =========================================================================
print("\nSmoothing features with EMA (halflife=10d)...")
for fname in FEATURE_NAMES:
    features[fname] = features[fname].ewm(halflife=10).mean()
print("  Done")

# =========================================================================
# Sample dates
# =========================================================================
all_dates = close.index
start_idx = 252
sample_dates = all_dates[start_idx::10]
print(f"\nSampling {len(sample_dates)} dates from {sample_dates[0].date()} to {sample_dates[-1].date()}")

# =========================================================================
# For each sample date, compute classifications
# =========================================================================

# First fit PCA on latest date to get stable loadings
print("\nFitting PCA on latest cross-section...")
latest_cs = {}
for fname in FEATURE_NAMES:
    latest_cs[fname] = features[fname].iloc[-1]
latest_df = pd.DataFrame(latest_cs, index=common).dropna()
z_latest = (latest_df - latest_df.mean()) / latest_df.std().clip(lower=1e-8)
z_latest = z_latest.clip(-5, 5)

pca = PCA(n_components=min(5, len(FEATURE_NAMES), len(z_latest)))
pca.fit(z_latest.values)
idx_trend = FEATURE_NAMES.index('log_close_ma200')
if pca.components_[0, idx_trend] < 0:
    pca.components_[0] *= -1

# Fit KMeans on latest
scores_latest = z_latest.values @ pca.components_.T
km = KMeans(n_clusters=5, n_init=20, random_state=42)
labels_latest = km.fit_predict(scores_latest[:, :5])

# Sort clusters by mean PC1
cluster_means = {c: scores_latest[labels_latest == c, 0].mean() for c in range(5)}
sorted_clusters = sorted(cluster_means, key=cluster_means.get)
remap = {old: new for new, old in enumerate(sorted_clusters)}
cluster_names = {0: 'Declining', 1: 'Distributing', 2: 'Erupting', 3: 'Quiet Uptrend', 4: 'Strong Leader'}

print(f"  PCA fitted on {len(z_latest)} stocks")
for c in range(5):
    n = (np.array([remap[l] for l in labels_latest]) == c).sum()
    print(f"    C{c} {cluster_names[c]}: {n}")

# =========================================================================
# Rolling computation
# =========================================================================
print("\nComputing rolling classifications...")

results = []
for di, date in enumerate(sample_dates):
    if di % 10 == 0:
        print(f"  {di+1}/{len(sample_dates)} — {date.date()}")

    date_idx = all_dates.get_loc(date)

    # PCA regime at this date
    cs_data = {}
    for fname in FEATURE_NAMES:
        s = features[fname]
        if date_idx < len(s):
            cs_data[fname] = s.iloc[date_idx]
    if not cs_data:
        continue

    cs_df = pd.DataFrame(cs_data, index=common).dropna()
    if len(cs_df) < len(common) * 0.5:
        # Too many NaN features at this date — skip (likely OHLCV gap)
        continue

    # Z-score cross-sectionally
    z = (cs_df - cs_df.mean()) / cs_df.std().clip(lower=1e-8)
    z = z.clip(-5, 5)

    # Project through FIXED PCA loadings (fitted on latest date for stability)
    z = z.fillna(0)
    scores = z.values @ pca.components_.T
    scores = np.nan_to_num(scores, nan=0.0, posinf=5.0, neginf=-5.0)

    # Classify using FIXED KMeans centroids (fitted on latest date)
    labels = km.predict(scores[:, :5])
    labels_remapped = np.array([remap[l] for l in labels])

    # Weinstein stages at this date
    stages_at = stage_df.iloc[date_idx] if date_idx < len(stage_df) else pd.Series()

    # MA screener at this date
    close_at = close.iloc[date_idx]
    ma50_at = close.iloc[max(0, date_idx-49):date_idx+1].mean()
    ma200_at = close.iloc[max(0, date_idx-199):date_idx+1].mean()

    # Build per-stock record
    for i, sym in enumerate(cs_df.index):
        sec = sector_map.get(sym, '')
        if not sec:
            continue

        pca_regime = cluster_names.get(labels_remapped[i], '?')

        stage = int(stages_at.get(sym, 0)) if sym in stages_at.index else 0
        stage_name = {0: 'Unclassified', 1: 'S1 Basing', 2: 'S2 Uptrend', 3: 'S3 Topping', 4: 'S4 Declining'}.get(stage, '?')

        p = close_at.get(sym)
        m50 = ma50_at.get(sym)
        m200 = ma200_at.get(sym)
        if pd.notna(p) and pd.notna(m50) and pd.notna(m200):
            if p > m50 and p > m200:
                ma_pos = 'Above Both'
            elif p > m200:
                ma_pos = 'Above 200 Below 50'
            elif p > m50:
                ma_pos = 'Below 200 Above 50'
            else:
                ma_pos = 'Below Both'
        else:
            ma_pos = '?'

        results.append({
            'date': date.date(),
            'symbol': sym,
            'sector': sec,
            'pca_regime': pca_regime,
            'stage': stage_name,
            'ma_position': ma_pos,
        })

print(f"\nTotal records: {len(results)}")
df = pd.DataFrame(results)

# =========================================================================
# Save raw data
# =========================================================================
df.to_parquet(OUTPUT_DIR / 'classification_history.parquet')
print(f"Saved: {OUTPUT_DIR / 'classification_history.parquet'}")

# =========================================================================
# Aggregate: count per date × sector × classification
# =========================================================================
for dim in ['pca_regime', 'stage', 'ma_position']:
    agg = df.groupby(['date', 'sector', dim]).size().reset_index(name='count')
    agg.to_csv(OUTPUT_DIR / f'history_{dim}.csv', index=False)
    print(f"Saved: history_{dim}.csv")

    # Also overall (no sector split)
    agg_all = df.groupby(['date', dim]).size().reset_index(name='count')
    agg_all.to_csv(OUTPUT_DIR / f'history_{dim}_overall.csv', index=False)

print("\nDone!")
