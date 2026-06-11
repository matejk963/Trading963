"""RRG quadrant geometry — the section-PRIVATE deep core (spec §4.3, §10).

The Relative Rotation Graph RS-ratio / RS-momentum maths + tail geometry +
quadrant classification. A **single consumer** (the RRG section) → not kernel
(spec §4.3: "RRG quadrant geometry is a section-private core").

This file is the relocation target for FLAG-5: the `compute_*` functions and the
`ETF_DATASETS` / `FUTURES_GROUPS` config previously imported out of
`src/analysis/sector_rrg/streamlit_app.py` (via a `sys.path` injection + a faked
`streamlit` module in the old `macro/rrg_service.py:13-42`). The math is COPIED
verbatim from the streamlit app (read-copy — the streamlit app is left untouched);
there is **zero** streamlit import here.

Source-blind on data: the section hands this core a `symbol × date` price panel
(fetched via `DataSource.time_series`), never a fetcher. All `yf.download` /
`fetch_etf_data` / `fetch_futures_data` logic lives in the DataSource submodules
(`(time_series, etf)` / `(time_series, futures)`), not here.

Parity (spec PRD / FLAG-5): the RS-ratio/momentum numbers this core produces match
the old `streamlit_app.compute_etf_rrg` / `compute_futures_group_rrg` /
`compute_intra_group_rrg` exactly — same EMA/WMA windows, same endogenous benchmark.

Debug logging is off by default (`MKTT_LOG_LEVEL=DEBUG`).
"""
from __future__ import annotations

import colorsys
import logging
import os
from typing import Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("mktt.sections.rrg.quadrant")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


# =========================================================================
# Configuration (relocated from streamlit_app.py:20-93 — read-copy)
# =========================================================================

ETF_DATASETS = {
    "US Sectors": {
        "benchmark": "RSP",
        "benchmark_name": "S&P 500 Equal Weight",
        "sectors": {
            "XLK": ("Technology", "#2196F3"),
            "XLF": ("Financials", "#4CAF50"),
            "XLV": ("Health Care", "#9C27B0"),
            "XLE": ("Energy", "#FF9800"),
            "XLI": ("Industrials", "#795548"),
            "XLC": ("Communication", "#E91E63"),
            "XLY": ("Cons. Discretionary", "#00BCD4"),
            "XLP": ("Cons. Staples", "#8BC34A"),
            "XLU": ("Utilities", "#FFC107"),
            "XLRE": ("Real Estate", "#607D8B"),
            "XLB": ("Materials", "#F44336"),
        },
    },
    "Europe Sectors": {
        "benchmark": "^STOXX",
        "benchmark_name": "STOXX Europe 600",
        "sectors": {
            "EXV6.DE": ("Basic Resources", "#F44336"),
            "EXH1.DE": ("Oil & Gas", "#FF9800"),
            "EXV1.DE": ("Banks", "#4CAF50"),
            "EXV4.DE": ("Health Care", "#9C27B0"),
            "EXV5.DE": ("Automobiles", "#795548"),
            "EXH4.DE": ("Industrials", "#00BCD4"),
            "EXV3.DE": ("Technology", "#2196F3"),
            "EXH7.DE": ("Telecom", "#E91E63"),
            "EXH3.DE": ("Food & Beverage", "#8BC34A"),
            "EXH8.DE": ("Utilities", "#FFC107"),
            "EXV8.DE": ("Insurance", "#607D8B"),
            "EXH5.DE": ("Chemicals", "#AB47BC"),
        },
    },
    "Global Markets": {
        "benchmark": "URTH",
        "benchmark_name": "MSCI World (URTH)",
        "sectors": {
            "SPY": ("US - S&P 500", "#2196F3"),
            "VGK": ("Europe", "#4CAF50"),
            "EWG": ("Germany", "#FF9800"),
            "EWQ": ("France", "#9C27B0"),
            "EWJ": ("Japan", "#E91E63"),
            "FXI": ("China", "#F44336"),
            "EWA": ("Australia", "#00BCD4"),
            "EWU": ("UK", "#795548"),
            "EWC": ("Canada", "#8BC34A"),
            "EEM": ("Emerging Markets", "#FFC107"),
        },
    },
}

# Futures Group RRG — per spec (relocated from streamlit_app.py:75-93).
FUTURES_GROUPS = {
    "Bonds": {"contracts": {"ZB=F": "US 30Y", "ZN=F": "US 10Y", "ZF=F": "US 5Y", "ZT=F": "US 2Y"},
              "color": "#2196F3"},
    "Indices": {"contracts": {"YM=F": "Dow", "ES=F": "S&P 500", "NQ=F": "Nasdaq", "RTY=F": "Russell"},
                "color": "#4CAF50"},
    "FX": {"contracts": {"DX=F": "USD Index", "6E=F": "EUR", "6C=F": "CAD", "6J=F": "JPY",
                         "6B=F": "GBP", "6S=F": "CHF", "6A=F": "AUD"},
           "color": "#9C27B0", "invert": ["DX=F"]},
    "Energy": {"contracts": {"CL=F": "Crude", "NG=F": "NatGas", "RB=F": "Gasoline", "HO=F": "HeatOil"},
               "color": "#FF9800"},
    "Metals": {"contracts": {"HG=F": "Copper", "GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "PA=F": "Palladium"},
               "color": "#F44336"},
    "Grains": {"contracts": {"ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soy", "ZL=F": "SoyOil", "ZM=F": "SoyMeal"},
               "color": "#8BC34A"},
    "Softs": {"contracts": {"KC=F": "Coffee", "CC=F": "Cocoa", "CT=F": "Cotton", "SB=F": "Sugar"},
              "color": "#FFC107"},
    "Meats": {"contracts": {"LE=F": "LiveCattle", "GF=F": "FeederCattle", "HE=F": "LeanHogs"},
              "color": "#795548"},
}

#: dataset query key -> ETF_DATASETS key (relocated from rrg_service.build_rrg_response:244).
DATASET_KEYS = {"us": "US Sectors", "europe": "Europe Sectors", "global": "Global Markets"}


# =========================================================================
# Core Calculations (relocated from streamlit_app.py:100-305 — read-copy)
# =========================================================================

def wma(series, length):
    """Weighted Moving Average — heavier weight on recent data."""
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(window=length, min_periods=length // 2).apply(
        lambda x: np.dot(x[-len(weights):], weights[-len(x):]) / weights[-len(x):].sum(),
        raw=True,
    )


# --- ETF RRG (EMA-based, external benchmark) -----------------------------

def calculate_rs_ratio_etf(price, benchmark, window=13):
    """RS-Ratio: EMA-smoothed RS / SMA * 100."""
    rs_raw = price / benchmark
    rs_smooth = rs_raw.ewm(span=window, adjust=False).mean()
    rs_sma = rs_smooth.rolling(window=window, min_periods=window // 2).mean()
    return (rs_smooth / rs_sma) * 100


def calculate_rs_momentum_etf(rs_ratio, momentum_window=4):
    """RS-Momentum: EMA-smoothed RS-Ratio / SMA * 100."""
    rs_smooth = rs_ratio.ewm(span=momentum_window, adjust=False).mean()
    rs_sma = rs_smooth.rolling(window=momentum_window, min_periods=momentum_window // 2).mean()
    return (rs_smooth / rs_sma) * 100


def compute_etf_rrg(prices, benchmark_ticker, lookback, momentum_window, tail_length):
    """Compute RRG for ETF datasets. Returns (tail_data, full_data)."""
    benchmark = prices[benchmark_ticker]
    tail_results = {}
    full_results = {}
    for ticker in prices.columns:
        if ticker == benchmark_ticker:
            continue
        rs_ratio = calculate_rs_ratio_etf(prices[ticker], benchmark, window=lookback)
        rs_momentum = calculate_rs_momentum_etf(rs_ratio, momentum_window=momentum_window)
        combined = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum}).dropna()
        if len(combined) >= tail_length:
            tail_results[ticker] = combined.iloc[-tail_length:]
            full_results[ticker] = combined
    return tail_results, full_results


# --- Futures Group RRG (WMA-based, endogenous benchmark, per spec) --------

def compute_futures_group_rrg(prices, length, tail_length, selected_groups):
    """Full Futures Group RRG per spec (relocated from streamlit_app.py:195-259).

    1. Normalize each contract: price / WMA(price, length)
    2. Invert DX
    3. Build equal-weighted group indices
    4. Build endogenous aggregate benchmark
    5. JdK RS-Ratio and RS-Momentum using WMA
    """
    normalized = {}
    for group_name, group_config in FUTURES_GROUPS.items():
        if group_name not in selected_groups:
            continue
        invert_list = group_config.get("invert", [])
        for ticker in group_config["contracts"]:
            if ticker not in prices.columns:
                continue
            series = prices[ticker].dropna()
            if len(series) < length * 2:
                continue
            w = wma(series, length)
            if ticker in invert_list:
                normalized[ticker] = w / series
            else:
                normalized[ticker] = series / w

    if not normalized:
        return {}

    norm_df = pd.DataFrame(normalized).ffill()

    group_indices = {}
    for group_name, group_config in FUTURES_GROUPS.items():
        if group_name not in selected_groups:
            continue
        group_tickers = [t for t in group_config["contracts"] if t in norm_df.columns]
        if group_tickers:
            group_indices[group_name] = norm_df[group_tickers].mean(axis=1)

    if len(group_indices) < 2:
        return {}

    group_df = pd.DataFrame(group_indices).dropna()
    g_agg = group_df.mean(axis=1)

    tail_results = {}
    full_results = {}
    for group_name in group_df.columns:
        rs = group_df[group_name] / g_agg
        wma_rs = wma(rs, length)
        rs_ratio = wma(rs / wma_rs, length) * 100
        rs_momentum = rs_ratio / wma(rs_ratio, length) * 100

        combined = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum}).dropna()
        if len(combined) >= tail_length:
            tail_results[group_name] = combined.iloc[-tail_length:]
            full_results[group_name] = combined

    return tail_results, full_results


def compute_intra_group_rrg(prices, length, tail_length, group_config):
    """Intra-group RRG: contracts within one group vs each other.

    Same WMA/endogenous benchmark methodology as group-level
    (relocated from streamlit_app.py:262-305).
    """
    invert_list = group_config.get("invert", [])

    normalized = {}
    for ticker in group_config["contracts"]:
        if ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if len(series) < length * 2:
            continue
        w = wma(series, length)
        if ticker in invert_list:
            normalized[ticker] = w / series
        else:
            normalized[ticker] = series / w

    if len(normalized) < 2:
        return {}, {}

    norm_df = pd.DataFrame(normalized).ffill().dropna()
    benchmark = norm_df.mean(axis=1)

    tail_results = {}
    full_results = {}
    for ticker in norm_df.columns:
        rs = norm_df[ticker] / benchmark
        wma_rs = wma(rs, length)
        rs_ratio = wma(rs / wma_rs, length) * 100
        rs_momentum = rs_ratio / wma(rs_ratio, length) * 100

        combined = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum}).dropna()
        if len(combined) >= tail_length:
            tail_results[ticker] = combined.iloc[-tail_length:]
            full_results[ticker] = combined

    return tail_results, full_results


# =========================================================================
# Quadrant classification (relocated from streamlit_app.py:312-320)
# =========================================================================

def get_quadrant(ratio, momentum):
    if ratio >= 100 and momentum >= 100:
        return "Leading"
    elif ratio >= 100 and momentum < 100:
        return "Weakening"
    elif ratio < 100 and momentum < 100:
        return "Lagging"
    else:
        return "Improving"


# =========================================================================
# Name/color maps (relocated from rrg_service.py:85-110)
# =========================================================================

def etf_name_color_map(dataset_key: str) -> Dict[str, Tuple[str, str]]:
    config = ETF_DATASETS[dataset_key]
    return {ticker: (info[0], info[1]) for ticker, info in config["sectors"].items()}


def futures_group_name_color_map() -> Dict[str, Tuple[str, str]]:
    return {name: (name, cfg["color"]) for name, cfg in FUTURES_GROUPS.items()}


def intra_group_name_color_map(group_name: str) -> Dict[str, Tuple[str, str]]:
    cfg = FUTURES_GROUPS[group_name]
    base_color = cfg["color"]
    r, g, b = (int(base_color[1:3], 16) / 255, int(base_color[3:5], 16) / 255,
               int(base_color[5:7], 16) / 255)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    result = {}
    contracts = cfg["contracts"]
    n = len(contracts)
    for i, (ticker, name) in enumerate(contracts.items()):
        ch = (h + i * 0.08 - n * 0.04) % 1.0
        cs = max(0.4, min(1.0, s + (i % 2) * 0.15 - 0.07))
        cv = max(0.5, min(1.0, v - i * 0.05))
        cr, cg, cb = colorsys.hsv_to_rgb(ch, cs, cv)
        color = f"#{int(cr*255):02x}{int(cg*255):02x}{int(cb*255):02x}"
        result[ticker] = (name, color)
    return result
