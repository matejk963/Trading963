"""
Analyze Weinstein stage transitions and feature distributions to derive
better classification criteria.

Run from: cd src/mktt && python ../../sandbox/analysis/classification_evolution/analyze_stages.py
"""
import sys
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'mktt'))

from data_manager import load_prices, load_spy
from stage_classifier import compute_all_derived_vectorized, classify_all_stages

OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# Load and compute stages for full history
# =========================================================================
print("Loading data...")
close = load_prices('close')
high = load_prices('high')
low = load_prices('low')
volume = load_prices('volume')
spy = load_spy()

print("Computing derived features...")
d, common = compute_all_derived_vectorized(close, high, low, volume, spy['Close'])

print("Classifying stages...")
stages = classify_all_stages(d)

print(f"  {len(common)} tickers, {len(stages)} days")

# =========================================================================
# 1. Transition matrix
# =========================================================================
print("\n[1] TRANSITION ANALYSIS")
print("=" * 60)

# For each ticker, find transitions (stage changes)
transitions = Counter()
total_days = 0
for ticker in common:
    s = stages[ticker].dropna()
    if len(s) < 2:
        continue
    for i in range(1, len(s)):
        prev = int(s.iloc[i-1])
        curr = int(s.iloc[i])
        if prev != curr:
            transitions[(prev, curr)] += 1
        total_days += 1

print(f"Total stock-days: {total_days:,}")
print(f"Total transitions: {sum(transitions.values()):,}")
print(f"Transition rate: {sum(transitions.values())/total_days*100:.2f}% per day")

# Transition matrix
stage_names = {0: 'S0 Unclass', 1: 'S1 Basing', 2: 'S2 Uptrend', 3: 'S3 Topping', 4: 'S4 Declining'}
print(f"\nTRANSITION MATRIX (from row → to column):")
print(f"{'':15s}", end='')
for to_s in [0, 1, 2, 3, 4]:
    print(f"  {stage_names[to_s]:>12s}", end='')
print()
for from_s in [0, 1, 2, 3, 4]:
    row_total = sum(transitions.get((from_s, to_s), 0) for to_s in [0, 1, 2, 3, 4])
    print(f"{stage_names[from_s]:15s}", end='')
    for to_s in [0, 1, 2, 3, 4]:
        n = transitions.get((from_s, to_s), 0)
        pct = n / row_total * 100 if row_total > 0 else 0
        print(f"  {n:>6d} ({pct:4.1f}%)", end='')
    print()

# Problematic transitions (should be rare)
print(f"\nPROBLEMATIC TRANSITIONS:")
for pair, label in [((1, 3), 'S1→S3'), ((3, 1), 'S3→S1'), ((2, 4), 'S2→S4'), ((4, 2), 'S4→S2')]:
    n = transitions.get(pair, 0)
    print(f"  {label}: {n} ({n/sum(transitions.values())*100:.2f}%)")

# =========================================================================
# 2. Feature distributions per stage
# =========================================================================
print("\n[2] FEATURE DISTRIBUTIONS AT EACH STAGE")
print("=" * 60)

# Sample every 20 days to keep it manageable
sample_dates = stages.index[252::20]
feature_keys = [
    'ma_150_slope_pct', 'ma_150_slope_21d', 'dist_52w_high', 'dist_52w_low',
    'adr_20', 'rs_rank', 'distribution_days_25',
]

# Also compute additional features
records = []
for di, date in enumerate(sample_dates):
    if di % 10 == 0:
        print(f"  {di+1}/{len(sample_dates)}...")
    idx = stages.index.get_loc(date)

    for ticker in common[:500]:  # sample 500 tickers for speed
        stage = stages.iloc[idx].get(ticker)
        if pd.isna(stage):
            continue
        stage = int(stage)

        rec = {'date': date, 'ticker': ticker, 'stage': stage}
        for feat in feature_keys:
            val = d[feat].iloc[idx].get(ticker)
            rec[feat] = val if pd.notna(val) else np.nan

        # Additional: price vs MAs
        p = d['close'].iloc[idx].get(ticker)
        m50 = d['ma_50'].iloc[idx].get(ticker)
        m150 = d['ma_150'].iloc[idx].get(ticker)
        m200 = d['ma_200'].iloc[idx].get(ticker)

        if pd.notna(p) and pd.notna(m50) and m50 > 0:
            rec['pct_vs_ma50'] = (p / m50 - 1) * 100
        if pd.notna(p) and pd.notna(m150) and m150 > 0:
            rec['pct_vs_ma150'] = (p / m150 - 1) * 100
        if pd.notna(p) and pd.notna(m200) and m200 > 0:
            rec['pct_vs_ma200'] = (p / m200 - 1) * 100
        if pd.notna(m50) and pd.notna(m150) and m150 > 0:
            rec['ma50_vs_ma150'] = (m50 / m150 - 1) * 100
        if pd.notna(m150) and pd.notna(m200) and m200 > 0:
            rec['ma150_vs_ma200'] = (m150 / m200 - 1) * 100

        records.append(rec)

feat_df = pd.DataFrame(records)
print(f"\n  {len(feat_df)} records")

# Print percentiles per stage
all_features = feature_keys + ['pct_vs_ma50', 'pct_vs_ma150', 'pct_vs_ma200', 'ma50_vs_ma150', 'ma150_vs_ma200']

print(f"\nFEATURE PERCENTILES BY STAGE (P25 / P50 / P75):")
print("-" * 100)
print(f"{'Feature':25s}", end='')
for s in [2, 1, 3, 4, 0]:
    print(f"  {'S'+str(s):>8s}", end='')
print()
print("-" * 100)

for feat in all_features:
    print(f"{feat:25s}", end='')
    for s in [2, 1, 3, 4, 0]:
        vals = feat_df[feat_df['stage'] == s][feat].dropna()
        if len(vals) > 10:
            med = vals.median()
            print(f"  {med:>8.2f}", end='')
        else:
            print(f"  {'N/A':>8s}", end='')
    print()

# =========================================================================
# 3. Feature separation analysis — what best distinguishes stages?
# =========================================================================
print(f"\nFEATURE SEPARATION (median difference between stages):")
print("-" * 70)

for feat in all_features:
    s2_med = feat_df[feat_df['stage'] == 2][feat].dropna().median()
    s4_med = feat_df[feat_df['stage'] == 4][feat].dropna().median()
    s1_med = feat_df[feat_df['stage'] == 1][feat].dropna().median()
    s3_med = feat_df[feat_df['stage'] == 3][feat].dropna().median()

    if pd.notna(s2_med) and pd.notna(s4_med):
        sep = abs(s2_med - s4_med)
        print(f"  {feat:25s}: S2={s2_med:>7.2f}  S4={s4_med:>7.2f}  |gap|={sep:.2f}  "
              f"S1={s1_med:>7.2f} if notna else 'N/A'  S3={s3_med:>7.2f}")

# =========================================================================
# 4. Plot feature distributions
# =========================================================================
print("\n[3] Generating distribution plots...")

stage_colors = {0: '#666', 1: '#f59e0b', 2: '#10b981', 3: '#ef4444', 4: '#6b7280'}

fig = make_subplots(rows=4, cols=3, subplot_titles=[f for f in all_features[:12]],
                    vertical_spacing=0.08, horizontal_spacing=0.06)

for i, feat in enumerate(all_features[:12]):
    row = i // 3 + 1
    col = i % 3 + 1
    for s in [2, 1, 3, 4]:
        vals = feat_df[feat_df['stage'] == s][feat].dropna()
        if len(vals) < 20:
            continue
        fig.add_trace(go.Violin(
            y=vals, name=f'S{s}', legendgroup=f'S{s}',
            marker_color=stage_colors[s], showlegend=(i == 0),
            box_visible=True, meanline_visible=True,
            scalegroup=feat, side='both',
        ), row=row, col=col)

fig.update_layout(template='plotly_dark', height=1200,
                  title='Feature Distributions by Weinstein Stage',
                  legend=dict(orientation='h', y=1.02))

fig.write_html(str(OUTPUT_DIR / 'stage_feature_distributions.html'))
print(f"  Saved: stage_feature_distributions.html")

# =========================================================================
# 5. Propose new criteria
# =========================================================================
print("\n[4] PROPOSED NEW CRITERIA (based on median feature values)")
print("=" * 60)

for s in [1, 2, 3, 4]:
    subset = feat_df[feat_df['stage'] == s]
    print(f"\nStage {s} ({stage_names[s]}) — {len(subset)} samples:")
    for feat in all_features:
        vals = subset[feat].dropna()
        if len(vals) > 20:
            p25, p50, p75 = vals.quantile([0.25, 0.5, 0.75])
            print(f"  {feat:25s}: P25={p25:>8.2f}  P50={p50:>8.2f}  P75={p75:>8.2f}")

print("\nDone!")
