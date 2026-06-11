"""PCA-regime classifier (Writer-fed) — ported from ``update_classifications.py``
part 2 (lines 142-202) + ``sandbox/.../pca_stage_classifier.py``
(``compute_features`` / ``extract_latest_cross_section``).

Pipeline (verbatim behaviour):
1. compute 20 scale-invariant cross-sectional features from the OHLCV panels +
   benchmark (``FEATURE_NAMES``),
2. take the latest date's cross-section, drop symbols with any NaN feature,
3. cross-sectional z-score (clip ±5),
4. PCA (≤20 components), enforce PC1 sign (positive = bullish via ``log_close_ma200``),
5. KMeans 5-cluster on PC1-PC5, sort clusters by mean PC1 (0=Declining … 4=Strong Leader).

A Writer-fed classifier (adr/0001): a separate unit the Writer runs alongside the
kernel; produces the ``regime`` column (the sorted cluster code 0-4) per symbol.

Inputs are the **raw wide** OHLCV panels + the benchmark close. The Writer adapts
the long ``symbol × date`` raw panel to wide before calling :func:`classify`.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("mktt.computed.classifiers.pca_regime")

COLUMN = "regime"

# 0=Declining … 4=Strong Leader (sorted by mean PC1, legacy cluster_names).
LABELS = {0: "Declining", 1: "Distributing", 2: "Erupting", 3: "Quiet Uptrend", 4: "Strong Leader"}

# 20 scale-invariant features (verbatim from pca_stage_classifier.FEATURE_NAMES).
FEATURE_NAMES = [
    "log_close_ma200", "log_close_ma50", "log_ma50_ma200", "log_ma150_ma200",
    "ma200_pctchg_63d", "ma200_pctchg_21d", "ma50_pctchg_21d",
    "adr_20", "adr_ratio",
    "pos_52w", "pct_from_high", "pct_from_low",
    "rs_rank", "rs_rank_velocity", "rs_line_slope_63d",
    "log_updown_vol", "log_vol_ratio", "distribution_ratio",
    "log_close_ma20", "log_return_21d",
]

N_CLUSTERS = 5
RANDOM_STATE = 42
_MIN_HISTORY = 252


def compute_features(close, high, low, volume, spy_close):
    """20 scale-invariant features as wide DataFrames (dates × tickers).

    Verbatim port of ``pca_stage_classifier.compute_features``.
    """
    valid = close.notna().sum() >= _MIN_HISTORY
    tickers = valid[valid].index.tolist()
    close = close[tickers]
    high = high[[t for t in tickers if t in high.columns]]
    low = low[[t for t in tickers if t in low.columns]]
    volume = volume[[t for t in tickers if t in volume.columns]]
    common = list(set(close.columns) & set(high.columns) & set(low.columns) & set(volume.columns))
    close, high, low, volume = close[common], high[common], low[common], volume[common]

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()

    high_52w = close.rolling(252, min_periods=126).max()
    low_52w = close.rolling(252, min_periods=126).min()

    spy_aligned = spy_close.reindex(close.index).ffill()
    rs_line = close.div(spy_aligned, axis=0)

    up_day = (close > close.shift(1)).astype(float)
    down_day = (close < close.shift(1)).astype(float)
    vol_up_50 = (volume * up_day).rolling(50).sum()
    vol_down_50 = (volume * down_day).rolling(50).sum().clip(lower=1)

    vol_ma_50 = volume.rolling(50).mean()
    dist_day = ((close < close.shift(1)) & (volume > vol_ma_50)).astype(float)
    dist_days_25 = dist_day.rolling(25).sum()

    daily_range_pct = (high / low - 1) * 100
    adr_20 = daily_range_pct.rolling(20).mean()
    adr_252 = daily_range_pct.rolling(252, min_periods=126).mean()

    returns_126d = close.pct_change(126)

    features = {}
    features["log_close_ma200"] = np.log(close / ma200)
    features["log_close_ma50"] = np.log(close / ma50)
    features["log_ma50_ma200"] = np.log(ma50 / ma200)
    features["log_ma150_ma200"] = np.log(ma150 / ma200)
    features["ma200_pctchg_63d"] = ma200.pct_change(63)
    features["ma200_pctchg_21d"] = ma200.pct_change(21)
    features["ma50_pctchg_21d"] = ma50.pct_change(21)
    features["adr_20"] = adr_20
    features["adr_ratio"] = adr_20 / adr_252.clip(lower=0.01)
    range_52w = (high_52w - low_52w).clip(lower=0.01)
    features["pos_52w"] = ((close - low_52w) / range_52w).clip(0, 1)
    features["pct_from_high"] = (close / high_52w - 1) * 100
    features["pct_from_low"] = (close / low_52w - 1) * 100
    features["rs_rank"] = returns_126d.rank(axis=1, pct=True)
    features["rs_rank_velocity"] = features["rs_rank"].diff(21)
    features["rs_line_slope_63d"] = (rs_line / rs_line.shift(63) - 1)
    features["log_updown_vol"] = np.log(vol_up_50 / vol_down_50)
    features["log_vol_ratio"] = np.log(volume.rolling(5).mean() / volume.rolling(60).mean().clip(lower=1))
    features["distribution_ratio"] = dist_days_25 / 25
    features["log_close_ma20"] = np.log(close / ma20)
    features["log_return_21d"] = np.log(close / close.shift(21))

    return features, common


def _extract_latest_cross_section(features, tickers):
    """Latest date's cross-section (n_stocks × 20), NaN rows dropped.

    Verbatim port of ``pca_stage_classifier.extract_latest_cross_section``.
    """
    rows = {fname: features[fname].iloc[-1] for fname in FEATURE_NAMES}
    df = pd.DataFrame(rows, index=tickers)
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    return df


def classify(close, high, low, volume, spy_close, random_state: int = RANDOM_STATE) -> pd.Series:
    """Return a per-symbol ``regime`` code 0-4 (Series indexed by symbol).

    Args are the **wide** (dates × tickers) OHLCV panels and the benchmark close
    series. Verbatim port of ``update_classifications.py`` part 2.
    """
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA

    features, common = compute_features(close, high, low, volume, spy_close)
    cross_section = _extract_latest_cross_section(features, common)
    if len(cross_section) < N_CLUSTERS:
        logger.debug("pca_regime: only %d stocks — too few to cluster", len(cross_section))
        return pd.Series(dtype="float64", name=COLUMN, index=pd.Index([], name="symbol"))

    z = (cross_section - cross_section.mean()) / cross_section.std().clip(lower=1e-8)
    z = z.clip(-5, 5)

    pca = PCA(n_components=min(20, len(FEATURE_NAMES), len(z)))
    scores = pca.fit_transform(z.values)

    idx_trend = FEATURE_NAMES.index("log_close_ma200")
    if pca.components_[0, idx_trend] < 0:
        pca.components_[0] *= -1
        scores[:, 0] *= -1

    n_pc = min(5, scores.shape[1])
    scores_df = pd.DataFrame(scores[:, :n_pc], index=z.index,
                             columns=[f"PC{i + 1}" for i in range(n_pc)])

    km = KMeans(n_clusters=N_CLUSTERS, n_init=20, random_state=random_state)
    labels = km.fit_predict(scores_df.values)

    cluster_means = {c: scores_df.iloc[labels == c, 0].mean() for c in range(N_CLUSTERS)}
    sorted_clusters = sorted(cluster_means, key=cluster_means.get)
    remap = {old: new for new, old in enumerate(sorted_clusters)}
    labels_sorted = np.array([remap[l] for l in labels])

    out = pd.Series(labels_sorted, index=scores_df.index, name=COLUMN).astype("int64")
    out.index.name = "symbol"
    logger.debug("pca_regime: %d symbols, counts=%s", len(out), out.value_counts().to_dict())
    return out
