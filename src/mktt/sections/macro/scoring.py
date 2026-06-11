"""Macro liquidity layer-scoring — the section-PRIVATE deep core (spec §4.3, §10).

The Howell/Boucher 3-layer Global Liquidity scoring engine: per-indicator
continuous Z-scores, layer composites, regime classification, and the 7-stage
transmission chain. A **single consumer** (the Macro section) → not kernel
(spec §4.3: "macro layer-scoring is a section-private core").

This file is the relocation target for FLAG-5: the indicator config + the
`calculate_*` / `classify_regime` / transmission-chain functions previously
imported out of `src/analysis/liquidity_monitoring/` (via a `sys.path` injection
+ a faked `streamlit` module in the old `macro/liquidity_service.py:14-39`). The
math is COPIED verbatim from those modules (read-copy — the originals are left
untouched); there is **zero** streamlit import here, and **zero** FRED / network
/ CSV-loading code (that is the DataSource's job — the section hands this core a
raw `date × FRED-code` frame fetched via `data.time_series`).

Parity (PRD / FLAG-5): the layer / regime / overlay / transmission numbers this
core produces match the old
`liquidity_indicators.calculate_*` / `regime_classifier.classify_regime` /
`transmission_chain.*` exactly — same windows, same thresholds, same weights.

Debug logging is off by default (`MKTT_LOG_LEVEL=DEBUG`).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("mktt.sections.macro.scoring")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


# =========================================================================
# Configuration (relocated from liquidity_monitoring/config/indicators.py)
# =========================================================================

LAYER1_INDICATORS = {
    'fed_balance_sheet': {'fred_code': 'WALCL', 'name': 'Fed Balance Sheet',
        'description': 'Total Assets of Federal Reserve', 'frequency': 'weekly',
        'units': 'billions_usd', 'signal_type': 'component'},
    'tga': {'fred_code': 'WTREGEN', 'name': 'Treasury General Account',
        'description': 'Treasury cash balance at Fed - drains reserves when rising',
        'frequency': 'weekly', 'units': 'billions_usd', 'signal_type': 'component'},
    'rrp': {'fred_code': 'RRPONTSYD', 'name': 'Reverse Repo Facility',
        'description': 'ON RRP usage - liquidity drain when high', 'frequency': 'daily',
        'units': 'billions_usd', 'signal_type': 'component'},
    'fed_funds': {'fred_code': 'DFF', 'name': 'Fed Funds Rate',
        'description': 'Effective Federal Funds Rate', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'component'},
    'core_pce': {'fred_code': 'PCEPILFE', 'name': 'Core PCE Price Index',
        'description': "Fed's preferred inflation measure for real rate calculation",
        'frequency': 'monthly', 'units': 'index', 'signal_type': 'component'},
    'cpi': {'fred_code': 'CPIAUCSL', 'name': 'CPI All Items',
        'description': 'Consumer Price Index - cross-check; used in L2b',
        'frequency': 'monthly', 'units': 'index', 'signal_type': 'component'},
    'dgs10': {'fred_code': 'DGS10', 'name': '10-Year Treasury',
        'description': '10-Year Treasury Constant Maturity Rate', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'component'},
    'dgs2': {'fred_code': 'DGS2', 'name': '2-Year Treasury',
        'description': '2-Year Treasury Constant Maturity Rate', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'component'},
    'tips_5y': {'fred_code': 'DFII5', 'name': '5Y TIPS Real Yield',
        'description': 'Market-implied real rate - confirmation signal (not scored). Replaced DFII2 (discontinued).',
        'frequency': 'daily', 'units': 'percent', 'signal_type': 'component'},
    'net_liquidity': {'fred_code': None, 'name': 'Fed Net Liquidity',
        'description': 'WALCL - TGA - RRP (actual liquidity in system)',
        'frequency': 'weekly', 'units': 'billions_usd', 'signal_type': 'roc_12m',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': False,
        'derived': True, 'formula': 'WALCL - WTREGEN - RRPONTSYD'},
    'real_policy_rate': {'fred_code': None, 'name': 'Real Policy Rate',
        'description': 'DFF - Core PCE YoY. Negative = CB subsidising borrowing = bullish',
        'frequency': 'monthly', 'units': 'percent', 'signal_type': 'level',
        'bullish_threshold': 0, 'bearish_threshold': 1.0, 'invert': True,
        'derived': True, 'formula': 'DFF - PCEPILFE_YoY', 'zlb_weight': 0.5},
}

LAYER2A_INDICATORS = {
    'rrp_direction': {'fred_code': 'RRPONTSYD', 'name': 'RRP Direction',
        'description': 'Falling RRP = cash entering private system', 'frequency': 'daily',
        'units': 'billions_usd', 'signal_type': 'roc_4w', 'bullish_threshold': 0,
        'bearish_threshold': 0, 'invert': True},
    'sofr_effr_spread': {'fred_code': None, 'name': 'SOFR-EFFR Spread',
        'description': 'Repo stress indicator', 'frequency': 'daily',
        'units': 'basis_points', 'signal_type': 'level', 'bullish_threshold': 5,
        'bearish_threshold': 15, 'invert': True, 'derived': True,
        'formula': '(SOFR - EFFR) * 100'},
    'mmf_assets': {'fred_code': 'WRMFNS', 'name': 'MMF Total Assets (All)',
        'description': 'Total Money Market Fund Assets - not seasonally adjusted. Replaced WRMFSL (discontinued 2021).',
        'frequency': 'weekly', 'units': 'billions_usd', 'signal_type': 'roc_12m',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': False},
    'mmf_deployed': {'fred_code': None, 'name': 'MMF Deployed Cash',
        'description': 'WRMFNS - RRPONTSYD = cash in private markets (not parked at Fed)',
        'frequency': 'weekly', 'units': 'billions_usd', 'signal_type': 'roc_12m',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': False,
        'derived': True, 'formula': 'WRMFNS - RRPONTSYD'},
    'hy_spread': {'fred_code': 'BAMLH0A0HYM2', 'name': 'HY Credit Spread',
        'description': 'ICE BofA US High Yield OAS', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'level', 'bullish_threshold': 4.0,
        'bearish_threshold': 6.0, 'invert': True},
    'ig_spread': {'fred_code': 'BAMLC0A0CM', 'name': 'IG Credit Spread',
        'description': 'ICE BofA US Corporate OAS', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'level', 'bullish_threshold': 1.0,
        'bearish_threshold': 2.0, 'invert': True},
    'vix': {'fred_code': 'VIXCLS', 'name': 'VIX',
        'description': 'CBOE Volatility Index - collateral haircut proxy',
        'frequency': 'daily', 'units': 'index', 'signal_type': 'level',
        'bullish_threshold': 16, 'bearish_threshold': 25, 'invert': True},
    'nfci': {'fred_code': 'NFCI', 'name': 'Chicago Fed NFCI',
        'description': 'National Financial Conditions Index (negative = loose)',
        'frequency': 'weekly', 'units': 'index', 'signal_type': 'level',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': True},
    'sofr': {'fred_code': 'SOFR', 'name': 'SOFR',
        'description': 'Secured Overnight Financing Rate', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'component'},
    'effr': {'fred_code': 'EFFR', 'name': 'EFFR',
        'description': 'Effective Federal Funds Rate', 'frequency': 'daily',
        'units': 'percent', 'signal_type': 'component'},
    'bank_credit': {'fred_code': 'TOTLL', 'name': 'Bank Credit Total',
        'description': 'Total Loans and Leases at Commercial Banks (H.8)',
        'frequency': 'weekly', 'units': 'billions_usd', 'signal_type': 'roc_12m',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': False},
    'ci_loans': {'fred_code': 'BUSLOANS', 'name': 'C&I Loans',
        'description': 'Commercial and Industrial Loans', 'frequency': 'weekly',
        'units': 'billions_usd', 'signal_type': 'roc_12m', 'bullish_threshold': 0,
        'bearish_threshold': 0, 'invert': False},
    'm2': {'fred_code': 'M2SL', 'name': 'M2 Money Supply',
        'description': 'M2 Money Stock', 'frequency': 'weekly',
        'units': 'billions_usd', 'signal_type': 'roc_12m', 'bullish_threshold': 0,
        'bearish_threshold': 0, 'invert': False},
}

LAYER2B_INDICATORS = {
    'capacity_util': {'fred_code': 'TCU', 'name': 'Capacity Utilization',
        'description': 'Total Industry Capacity Utilization', 'frequency': 'monthly',
        'units': 'percent', 'signal_type': 'level', 'bullish_threshold': 78,
        'neutral_high': 81.5, 'bearish_threshold': 81.5, 'invert': True,
        'counterintuitive': True},
    'industrial_prod': {'fred_code': 'INDPRO', 'name': 'Industrial Production',
        'description': 'Industrial Production Index', 'frequency': 'monthly',
        'units': 'index', 'signal_type': 'roc_12m', 'bullish_threshold': 5,
        'bearish_threshold': 7, 'invert': True, 'counterintuitive': True},
    'unemployment': {'fred_code': 'UNRATE', 'name': 'Unemployment Rate',
        'description': 'Civilian Unemployment Rate', 'frequency': 'monthly',
        'units': 'percent', 'signal_type': 'roc_29m', 'bullish_threshold': 0,
        'bearish_threshold': 0, 'invert': False, 'counterintuitive': True},
    'cpi_level': {'fred_code': 'CPIAUCSL', 'name': 'CPI Level',
        'description': 'CPI YoY for inflation assessment', 'frequency': 'monthly',
        'units': 'percent', 'signal_type': 'yoy', 'bullish_threshold': 3.2,
        'neutral_high': 5.0, 'bearish_threshold': 5.0, 'invert': True,
        'counterintuitive': True},
    'cpi_momentum': {'fred_code': 'CPIAUCSL', 'name': 'CPI Momentum',
        'description': '3-month annualized vs 12-month (deceleration signal)',
        'frequency': 'monthly', 'units': 'percent', 'signal_type': 'momentum',
        'bullish_threshold': 0, 'bearish_threshold': 0, 'invert': False,
        'counterintuitive': True, 'derived': True, 'formula': 'CPI_3M_ANN - CPI_12M'},
    'ppi_final_demand': {'fred_code': 'PPIFIS', 'name': 'PPI Final Demand Services',
        'description': 'Producer Price Index - Final Demand Services. Replaced NAPMPRIC (discontinued on FRED).',
        'frequency': 'monthly', 'units': 'index', 'signal_type': 'roc_18m',
        'bullish_threshold': 18, 'bearish_threshold': 25, 'invert': True,
        'counterintuitive': True},
    'ppi_commodities': {'fred_code': 'PPIACO', 'name': 'PPI All Commodities',
        'description': 'Producer Price Index - All Commodities. ROC: decelerating = bullish',
        'frequency': 'monthly', 'units': 'index', 'signal_type': 'roc_12m',
        'bullish_threshold': 0, 'bearish_threshold': 5, 'invert': True,
        'counterintuitive': True},
}

REGIME_LABELS = {
    (1, 1, 1): 'Early Cycle - Max Bullish',
    (1, 1, -1): 'Late Easing - Recovery Underway',
    (1, -1, 1): 'Transmission Broken - CB Not Transmitting',
    (-1, 1, -1): 'Late Cycle - Tightening Hot Economy',
    (-1, -1, 1): 'Contraction - Tightening Weakening Economy',
    (-1, -1, -1): 'Maximum Contraction',
    (1, 0, 1): 'Early Recovery',
    (1, 1, 0): 'Mid Easing',
    (1, 0, 0): 'CB Easing - Mixed Signals',
    (0, 1, 1): 'Private Expansion',
    (0, 1, -1): 'Late Private Expansion',
    (0, 0, 1): 'Economy Weakening',
    (-1, 0, -1): 'Stagflation Risk',
    (-1, 1, 0): 'Tightening - Private Resilient',
    (-1, 0, 0): 'CB Tightening - Mixed Signals',
    (0, -1, 1): 'Credit Contraction',
    (0, -1, -1): 'Late Cycle Stress',
    (0, 0, -1): 'Economy Overheating',
    (1, -1, -1): 'Policy Disconnect',
    (-1, 1, 1): 'Soft Landing Attempt',
    (1, -1, 0): 'Easing - Private Weak',
    (-1, -1, 0): 'Deep Contraction',
    (0, 1, 0): 'Private Neutral',
    (0, -1, 0): 'Private Weak',
    (1, 0, -1): 'Policy Lag',
    (-1, 0, 1): 'Recession Risk',
    (0, 0, 0): 'Neutral',
}

LAYER_WEIGHTS = {'L1': 0.40, 'L2a': 0.35, 'L2b': 0.25}

LAYER_SCORE_RANGES = {'L1': (-2, 2), 'L2a': (-11, 11), 'L2b': (-7, 7)}

TRANSMISSION_STAGES = {
    1: {'name': 'CB Impulse Created', 'question': 'Did the CB inject?',
        'indicators': {
            'net_liquidity': {'source': 'L1', 'signal': 'Positive = injecting'},
            'real_policy_rate': {'source': 'L1', 'signal': 'Negative = accommodative'},
            'tga_direction': {'fred_code': 'WTREGEN', 'signal_type': 'roc_4w',
                              'invert': True, 'signal': 'Falling = releasing cash'}}},
    2: {'name': 'Wholesale Activation', 'question': 'Is the plumbing turning over?',
        'indicators': {
            'rrp_direction': {'source': 'L2a', 'signal': 'Falling = cash leaving Fed'},
            'sofr_effr_spread': {'source': 'L2a', 'signal': '<5bp = healthy'},
            'mmf_deployed': {'source': 'L2a', 'signal': 'Rising = cash in private system'}}},
    3: {'name': 'Risk Appetite', 'question': 'Is the market willing to extend credit?',
        'indicators': {
            'hy_spread': {'source': 'L2a', 'signal': 'Compressing = risk appetite'},
            'ig_spread': {'source': 'L2a', 'signal': 'Confirmation'},
            'vix': {'source': 'L2a', 'signal': 'Falling = haircuts contracting'},
            'nfci': {'source': 'L2a', 'signal': 'Negative = loose conditions'}}},
    4: {'name': 'Bank Credit Expansion', 'question': 'Is it crossing into the real economy?',
        'indicators': {
            'bank_credit': {'source': 'L2a', 'signal': 'Accelerating'},
            'ci_loans': {'source': 'L2a', 'signal': 'Business credit drawing'},
            'm2': {'source': 'L2a', 'signal': 'Money supply expanding'}}},
    5: {'name': 'Asset Price Response', 'question': 'Are markets pricing in the liquidity?',
        'indicators': {
            'sp500': {'fred_code': 'SP500', 'signal_type': 'roc_12m',
                      'signal': 'Equity repricing'}}},
    6: {'name': 'Real Economy Response', 'question': 'Has it reached the ground?',
        'indicators': {
            'industrial_prod': {'source': 'L2b', 'invert_for_stage': True,
                                'signal': 'Accelerating'},
            'capacity_util': {'source': 'L2b', 'invert_for_stage': True,
                              'signal': 'Rising toward 80%'},
            'unemployment': {'source': 'L2b', 'invert_for_stage': True,
                             'signal': 'Falling = demand absorbing labor'}}},
    7: {'name': 'Cycle Reversal Warning', 'question': 'Is the CB about to tighten?',
        'indicators': {
            'cpi_momentum': {'source': 'L2b', 'signal': 'Positive = acceleration'},
            'cpi_level': {'source': 'L2b', 'signal': '>3.2% = pressure building'},
            'ppi_final_demand': {'source': 'L2b', 'signal': '>18% = upstream inflation'},
            'capacity_util_hot': {'source': 'L2b', 'signal': '>81.5% = running hot'}}},
}

STAGE_FRED_CODES = ['SP500']


def get_all_fred_codes():
    """Return list of all unique FRED codes to fetch (the macro `time_series` ids)."""
    codes = set()
    for layer in [LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS]:
        for key, config in layer.items():
            if config.get('fred_code') and not config.get('derived', False):
                codes.add(config['fred_code'])
    for code in STAGE_FRED_CODES:
        codes.add(code)
    return sorted(list(codes))


FRED_SERIES = get_all_fred_codes()


# =========================================================================
# Rate-of-change (relocated from calculations/liquidity_indicators.py)
# =========================================================================

def calculate_roc(series: pd.Series, periods: int = 252) -> pd.Series:
    return series.pct_change(periods=periods)


def calculate_roc_12m(series: pd.Series) -> pd.Series:
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            periods = 12
        elif avg_gap > 4:
            periods = 52
        else:
            periods = 252
    else:
        periods = 12
    return calculate_roc(series, periods=periods)


def calculate_roc_29m(series: pd.Series) -> pd.Series:
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            periods = 29
        elif avg_gap > 4:
            periods = 29 * 4
        else:
            periods = 29 * 21
    else:
        periods = 29
    return calculate_roc(series, periods=periods)


def calculate_roc_4w(series: pd.Series) -> pd.Series:
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            periods = 1
        elif avg_gap > 4:
            periods = 4
        else:
            periods = 20
    else:
        periods = 4
    return calculate_roc(series, periods=periods)


def calculate_roc_18m(series: pd.Series) -> pd.Series:
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            periods = 18
        elif avg_gap > 4:
            periods = 78
        else:
            periods = 378
    else:
        periods = 18
    return calculate_roc(series, periods=periods)


def calculate_yoy(series: pd.Series) -> pd.Series:
    return series.pct_change(periods=12)


# =========================================================================
# Z-scores
# =========================================================================

def calculate_rolling_zscore(series: pd.Series, window: int = 1260,
                             min_periods: int = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(window // 4, 60)

    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()
    rolling_std = rolling_std.replace(0, np.nan)
    zscore = (series - rolling_mean) / rolling_std
    zscore = zscore.clip(-10, 10)
    return zscore


def calculate_zscore_5y(series: pd.Series) -> pd.Series:
    return calculate_rolling_zscore(series, window=1260)


def calculate_yoy_zscore(series: pd.Series, yoy_periods: int = 252,
                         zscore_window: int = 1260) -> pd.Series:
    yoy = series.pct_change(periods=yoy_periods)
    return calculate_rolling_zscore(yoy, window=zscore_window)


def calculate_continuous_indicator_score(series: pd.Series, config: dict) -> pd.Series:
    signal_type = config.get('signal_type', 'level')
    invert = config.get('invert', False)

    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            yoy_periods = 12
            zscore_window = 60
        elif avg_gap > 4:
            yoy_periods = 52
            zscore_window = 260
        else:
            yoy_periods = 252
            zscore_window = 1260
    else:
        yoy_periods = 12
        zscore_window = 60

    if signal_type in ['roc_12m', 'roc_29m', 'roc_4w', 'roc_18m', 'yoy']:
        if signal_type == 'roc_29m':
            change = calculate_roc_29m(series)
        elif signal_type == 'roc_4w':
            change = calculate_roc_4w(series)
        elif signal_type == 'roc_18m':
            change = calculate_roc_18m(series)
        else:
            change = series.pct_change(periods=yoy_periods)
        zscore = calculate_rolling_zscore(change, window=zscore_window)

    elif signal_type == 'momentum':
        momentum = calculate_cpi_momentum(series)
        zscore = calculate_rolling_zscore(momentum, window=zscore_window)

    elif signal_type == 'level':
        zscore = calculate_rolling_zscore(series, window=zscore_window)

    elif signal_type == 'level_change':
        if config.get('units') in ['percent', 'basis_points', 'index']:
            change = series.diff(periods=yoy_periods)
        else:
            change = series.pct_change(periods=yoy_periods)
        zscore = calculate_rolling_zscore(change, window=zscore_window)

    else:
        zscore = calculate_yoy_zscore(series, yoy_periods, zscore_window)

    if invert:
        zscore = -zscore

    return zscore


def calculate_continuous_layer_scores(raw_data: pd.DataFrame,
                                       layer_config: dict) -> pd.DataFrame:
    score_series = {}

    for indicator_id, config in layer_config.items():
        fred_code = config.get('fred_code')
        signal_type = config.get('signal_type', 'level')

        if config.get('derived', False):
            if indicator_id == 'net_liquidity':
                if all(c in raw_data.columns for c in ['WALCL', 'WTREGEN', 'RRPONTSYD']):
                    net_liq = calculate_net_liquidity(
                        raw_data['WALCL'], raw_data['WTREGEN'], raw_data['RRPONTSYD'],
                        smooth=True, ema_span=10)
                    if len(net_liq.dropna()) >= 50:
                        zscore = calculate_continuous_indicator_score(net_liq.dropna(), config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'real_policy_rate':
                if all(c in raw_data.columns for c in ['DFF', 'PCEPILFE']):
                    real_rate, zlb_flag = calculate_real_policy_rate(
                        raw_data['DFF'], raw_data['PCEPILFE'])
                    real_rate_clean = real_rate.dropna()
                    if len(real_rate_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(real_rate_clean, config)
                        zlb_weight = config.get('zlb_weight', 0.5)
                        if not zlb_flag.empty and zlb_flag.iloc[-1]:
                            zscore = zscore * zlb_weight
                        score_series[indicator_id] = zscore

            elif indicator_id == 'mmf_deployed':
                if all(c in raw_data.columns for c in ['WRMFNS', 'RRPONTSYD']):
                    deployed = calculate_mmf_deployed(
                        raw_data['WRMFNS'], raw_data['RRPONTSYD'])
                    deployed_clean = deployed.dropna()
                    if len(deployed_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(deployed_clean, config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'sofr_effr_spread':
                if all(c in raw_data.columns for c in ['SOFR', 'EFFR']):
                    spread = calculate_sofr_effr_spread(raw_data['SOFR'], raw_data['EFFR'])
                    spread_clean = spread.dropna()
                    if len(spread_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(spread_clean, config)
                        score_series[indicator_id] = zscore

            elif indicator_id == 'cpi_momentum':
                if 'CPIAUCSL' in raw_data.columns:
                    momentum = calculate_cpi_momentum(raw_data['CPIAUCSL'])
                    momentum_clean = momentum.dropna()
                    if len(momentum_clean) >= 50:
                        zscore = calculate_continuous_indicator_score(momentum_clean, config)
                        score_series[indicator_id] = zscore

            continue

        if signal_type == 'component':
            continue

        if fred_code not in raw_data.columns:
            logger.warning("Missing data for %s (%s)", indicator_id, fred_code)
            continue

        series = raw_data[fred_code].dropna()
        if len(series) < 50:
            continue

        zscore = calculate_continuous_indicator_score(series, config)
        score_series[indicator_id] = zscore

    if score_series:
        result = pd.DataFrame(score_series)
        result = result.ffill()
        return result
    return pd.DataFrame()


def calculate_historical_continuous_totals(raw_data: pd.DataFrame,
                                            l1_config: dict,
                                            l2a_config: dict,
                                            l2b_config: dict) -> pd.DataFrame:
    l1_scores = calculate_continuous_layer_scores(raw_data, l1_config)
    l2a_scores = calculate_continuous_layer_scores(raw_data, l2a_config)
    l2b_scores = calculate_continuous_layer_scores(raw_data, l2b_config)

    empty_dt_series = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    l1_mean = l1_scores.mean(axis=1, skipna=True) if not l1_scores.empty else empty_dt_series
    l2a_mean = l2a_scores.mean(axis=1, skipna=True) if not l2a_scores.empty else empty_dt_series
    l2b_mean = l2b_scores.mean(axis=1, skipna=True) if not l2b_scores.empty else empty_dt_series

    result = pd.DataFrame({'L1': l1_mean, 'L2a': l2a_mean, 'L2b': l2b_mean})
    result = result.ffill()
    result_filled = result.fillna(0)

    result['Composite'] = (
        result_filled['L1'] * 0.40 +
        result_filled['L2a'] * 0.35 +
        result_filled['L2b'] * 0.25
    )

    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, errors='coerce')
        result = result[result.index.notna()]

    cutoff = pd.Timestamp('2005-01-01')
    return result.loc[result.index >= cutoff]


# =========================================================================
# CPI momentum
# =========================================================================

def calculate_cpi_momentum(cpi_series: pd.Series) -> pd.Series:
    cpi_monthly = cpi_series.resample('MS').last().dropna()
    change_3m = cpi_monthly.pct_change(periods=3)
    annualized_3m = (1 + change_3m) ** 4 - 1
    change_12m = cpi_monthly.pct_change(periods=12)
    momentum = annualized_3m - change_12m
    return momentum


# =========================================================================
# Derived series
# =========================================================================

def calculate_net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series,
                            smooth: bool = True, ema_span: int = 5) -> pd.Series:
    df = pd.DataFrame({'WALCL': walcl, 'TGA': tga, 'RRP': rrp})
    df = df.ffill()

    if smooth:
        df['WALCL'] = df['WALCL'].ewm(span=ema_span, adjust=False).mean()
        df['TGA'] = df['TGA'].ewm(span=ema_span, adjust=False).mean()
        df['RRP'] = df['RRP'].ewm(span=ema_span, adjust=False).mean()

    cutoff = pd.Timestamp('2010-01-01')
    result = pd.Series(index=df.index, dtype=float)
    result[df.index < cutoff] = df.loc[df.index < cutoff, 'WALCL'] - df.loc[df.index < cutoff, 'TGA']
    result[df.index >= cutoff] = df.loc[df.index >= cutoff, 'WALCL'] - df.loc[df.index >= cutoff, 'TGA'] - df.loc[df.index >= cutoff, 'RRP']

    return result


def calculate_real_rate(fed_funds: pd.Series, cpi_yoy: pd.Series) -> pd.Series:
    df = pd.DataFrame({'FF': fed_funds, 'CPI': cpi_yoy})
    df = df.ffill()
    return df['FF'] - df['CPI']


def calculate_yield_curve(dgs10: pd.Series, dgs2: pd.Series) -> pd.Series:
    df = pd.DataFrame({'DGS10': dgs10, 'DGS2': dgs2})
    df = df.ffill()
    return df['DGS10'] - df['DGS2']


def calculate_real_policy_rate(dff: pd.Series, core_pce: pd.Series,
                                zlb_threshold: float = 0.25) -> Tuple[pd.Series, pd.Series]:
    pce_yoy = core_pce.pct_change(periods=12) * 100
    df = pd.DataFrame({'FF': dff, 'PCE_YoY': pce_yoy})
    df = df.ffill()
    real_rate = df['FF'] - df['PCE_YoY']
    zlb_flag = df['FF'] <= zlb_threshold
    return real_rate, zlb_flag


def calculate_mmf_deployed(wrmfsl: pd.Series, rrpontsyd: pd.Series) -> pd.Series:
    df = pd.DataFrame({'MMF': wrmfsl, 'RRP': rrpontsyd})
    df = df.ffill()
    return df['MMF'] - df['RRP']


def calculate_sofr_effr_spread(sofr: pd.Series, effr: pd.Series) -> pd.Series:
    df = pd.DataFrame({'SOFR': sofr, 'EFFR': effr})
    df = df.ffill()
    return (df['SOFR'] - df['EFFR']) * 100


# =========================================================================
# Composite
# =========================================================================

def calculate_composite_score(l1_score: float, l2a_score: float, l2b_score: float,
                              weights: dict = None) -> float:
    if weights is None:
        weights = {'L1': 0.40, 'L2a': 0.35, 'L2b': 0.25}
    return (l1_score * weights['L1'] +
            l2a_score * weights['L2a'] +
            l2b_score * weights['L2b'])


# =========================================================================
# Regime classification (relocated from calculations/regime_classifier.py)
# =========================================================================

def get_layer_direction(layer_score: float, threshold: float = 0.5) -> int:
    if layer_score > threshold:
        return 1
    elif layer_score < -threshold:
        return -1
    return 0


def classify_regime(l1_score: float, l2a_score: float, l2b_score: float,
                    threshold: float = 0.5) -> Dict:
    l1_dir = get_layer_direction(l1_score, threshold)
    l2a_dir = get_layer_direction(l2a_score, threshold)
    l2b_dir = get_layer_direction(l2b_score, threshold)

    regime_key = (l1_dir, l2a_dir, l2b_dir)
    regime_label = REGIME_LABELS.get(regime_key, 'Undefined Regime')

    total_direction = l1_dir + l2a_dir + l2b_dir
    if total_direction > 0:
        bias = 'Bullish'
    elif total_direction < 0:
        bias = 'Bearish'
    else:
        bias = 'Neutral'

    if total_direction >= 2:
        color = 'green'
    elif total_direction == 1:
        color = 'lightgreen'
    elif total_direction == 0:
        color = 'yellow'
    elif total_direction == -1:
        color = 'orange'
    else:
        color = 'red'

    return {
        'regime': regime_label,
        'regime_key': regime_key,
        'l1_direction': l1_dir,
        'l2a_direction': l2a_dir,
        'l2b_direction': l2b_dir,
        'total_direction': total_direction,
        'bias': bias,
        'color': color,
        'l1_label': _direction_to_label(l1_dir, 'CB'),
        'l2a_label': _direction_to_label(l2a_dir, 'Private'),
        'l2b_label': _direction_to_label(l2b_dir, 'Economy'),
    }


def _direction_to_label(direction: int, layer_name: str) -> str:
    if direction > 0:
        if layer_name == 'CB':
            return 'Easing'
        elif layer_name == 'Private':
            return 'Expanding'
        else:
            return 'Weakening'
    elif direction < 0:
        if layer_name == 'CB':
            return 'Tightening'
        elif layer_name == 'Private':
            return 'Contracting'
        else:
            return 'Overheating'
    else:
        return 'Neutral'


def get_regime_description(regime_key: Tuple[int, int, int]) -> str:
    descriptions = {
        (1, 1, 1): (
            "Central bank is easing, private sector is expanding, and economy is weak. "
            "This is the most bullish setup - maximum liquidity support with room to run. "
            "Historically leads to strong risk asset performance."),
        (1, 1, -1): (
            "Central bank is easing and private sector expanding, but economy is overheating. "
            "Recovery is underway but inflation may force CB to reconsider. "
            "Late-stage easing cycle - watch for policy pivot."),
        (1, -1, 1): (
            "Central bank is easing but private sector not transmitting. "
            "This indicates transmission mechanism is broken - banks not lending despite CB support. "
            "May require additional policy intervention or structural reforms."),
        (-1, 1, -1): (
            "Central bank is tightening into a strong economy while private sector still expanding. "
            "Classic late-cycle dynamics - economy running hot, CB trying to cool it. "
            "Private sector momentum may persist but watch for credit tightening effects."),
        (-1, -1, 1): (
            "Central bank is tightening and private sector contracting while economy weakens. "
            "Potential policy error - tightening into weakness. "
            "High risk of recession if this persists. Watch for policy pivot signals."),
        (-1, -1, -1): (
            "Maximum contraction across all layers. Economy overheating despite tight policy. "
            "Stagflation risk is elevated. Bearish for risk assets. "
            "This regime typically precedes significant market drawdowns."),
        (0, 0, 0): (
            "All layers neutral - transition period with no clear direction. "
            "Markets may be range-bound. Wait for clearer signals."),
    }
    return descriptions.get(regime_key, "Mixed signals across layers. Monitor for emerging trends.")


# =========================================================================
# Transmission chain (relocated from calculations/transmission_chain.py)
# =========================================================================

def _detect_zscore_window(series):
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            return 60
        elif avg_gap > 4:
            return 260
    return 1260


def calculate_stage_scores(raw_data: pd.DataFrame) -> Dict[int, pd.Series]:
    l1_scores = calculate_continuous_layer_scores(raw_data, LAYER1_INDICATORS)
    l2a_scores = calculate_continuous_layer_scores(raw_data, LAYER2A_INDICATORS)
    l2b_scores = calculate_continuous_layer_scores(raw_data, LAYER2B_INDICATORS)

    all_layer_scores = {}
    for col in l1_scores.columns:
        all_layer_scores[col] = l1_scores[col]
    for col in l2a_scores.columns:
        all_layer_scores[col] = l2a_scores[col]
    for col in l2b_scores.columns:
        all_layer_scores[col] = l2b_scores[col]

    stage_results = {}

    for stage_num, stage_config in TRANSMISSION_STAGES.items():
        stage_indicator_series = []

        for ind_id, ind_config in stage_config['indicators'].items():
            series = None

            if 'source' in ind_config:
                source_id = ind_id
                if source_id == 'capacity_util_hot':
                    source_id = 'capacity_util'

                if source_id in all_layer_scores:
                    series = all_layer_scores[source_id].copy()
                    if ind_config.get('invert_for_stage', False):
                        series = -series
            else:
                fred_code = ind_config.get('fred_code')
                if fred_code and fred_code in raw_data.columns:
                    raw_series = raw_data[fred_code].dropna()
                    if len(raw_series) >= 50:
                        signal_type = ind_config.get('signal_type', 'roc_12m')
                        if signal_type == 'roc_4w':
                            raw_series = raw_series.ewm(span=8, adjust=False).mean()
                        fake_config = {
                            'signal_type': signal_type,
                            'invert': ind_config.get('invert', False)
                        }
                        series = calculate_continuous_indicator_score(raw_series, fake_config)

            if series is not None and not series.empty:
                stage_indicator_series.append(series)

        if stage_indicator_series:
            combined = pd.DataFrame({f'ind_{i}': s for i, s in enumerate(stage_indicator_series)})
            combined = combined.ffill()
            stage_mean = combined.mean(axis=1, skipna=True)
            stage_results[stage_num] = stage_mean.ewm(span=4, adjust=False).mean()

    return stage_results


def calculate_stage_current(raw_data: pd.DataFrame) -> Dict[int, dict]:
    stage_series = calculate_stage_scores(raw_data)
    results = {}

    for stage_num, stage_config in TRANSMISSION_STAGES.items():
        score = np.nan
        if stage_num in stage_series:
            s = stage_series[stage_num].dropna()
            if not s.empty:
                score = s.iloc[-1]

        if np.isnan(score):
            status = 'neutral'
        elif score > 0.3:
            status = 'positive'
        elif score < -0.3:
            status = 'negative'
        else:
            status = 'neutral'

        results[stage_num] = {
            'score': score,
            'status': status,
            'name': stage_config['name'],
            'question': stage_config['question'],
        }

    return results


def detect_transmission_break(stage_scores: Dict[int, dict]) -> Tuple[Optional[int], str]:
    scores = {k: v['score'] for k, v in stage_scores.items() if not np.isnan(v['score'])}

    if not scores:
        return None, 'No Data'

    if scores.get(1, 0) < -0.3:
        return None, 'No CB Impulse'

    prev_positive = False
    for stage in range(1, 8):
        if stage not in scores:
            continue
        if scores[stage] > 0.3:
            prev_positive = True
        elif prev_positive and scores[stage] < -0.3:
            return stage, _get_break_label(stage)

    last_positive = 0
    for stage in range(1, 8):
        if stage in scores and scores[stage] > 0.3:
            last_positive = stage

    return None, _get_flow_label(last_positive, scores)


def _get_break_label(break_stage: int) -> str:
    labels = {
        2: 'Trapped Liquidity - QE not transmitting',
        3: 'Wholesale active, risk appetite absent',
        4: 'Spreads tight, banks not lending',
        5: 'Credit flowing, assets not responding',
        6: 'Assets repricing, real economy not responding',
        7: 'Cycle peak - reversal risk building',
    }
    return labels.get(break_stage, f'Break at Stage {break_stage}')


def _get_flow_label(last_positive: int, scores: dict) -> str:
    if scores.get(5, 0) > 0.3:
        if any(scores.get(s, 0) < -0.3 for s in [2, 3, 4]):
            return 'Asset rally without transmission - FRAGILE'

    labels = {
        0: 'No positive stages',
        1: 'Impulse only - waiting for transmission',
        2: 'Early - impulse created, transmission starting',
        3: 'Mid cycle - risk appetite returning',
        4: 'Mid cycle - credit expanding',
        5: 'Late mid - assets pricing in',
        6: 'Late cycle - fully transmitted, watch Stage 7',
        7: 'Cycle peak - reversal risk building',
    }
    return labels.get(last_positive, 'Unknown')


CYCLE_COLORS = {
    'Early - impulse created, transmission starting': 'blue',
    'Mid cycle - risk appetite returning': 'green',
    'Mid cycle - credit expanding': 'green',
    'Late mid - assets pricing in': 'yellow',
    'Late cycle - fully transmitted, watch Stage 7': 'orange',
    'Cycle peak - reversal risk building': 'red',
    'Trapped Liquidity - QE not transmitting': 'red',
    'Wholesale active, risk appetite absent': 'red',
    'Spreads tight, banks not lending': 'red',
    'Asset rally without transmission - FRAGILE': 'red',
    'No CB Impulse': 'gray',
    'No positive stages': 'gray',
    'Impulse only - waiting for transmission': 'blue',
}


# =========================================================================
# Weekly resampling helper (relocated from data/loader.resample_to_weekly)
# =========================================================================

def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill mixed frequencies, then resample to Friday weekly close.

    Relocated from `liquidity_monitoring/data/loader.resample_to_weekly` — the only
    loader helper the service used for chart clarity. The FRED fetch / CSV-cache
    code in that loader stays in `src/analysis/` (the DataSource owns sourcing now).
    """
    df_filled = df.ffill()
    return df_filled.resample('W-FRI').last()
