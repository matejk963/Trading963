"""
Liquidity Service — adapts the Streamlit liquidity monitoring modules for Flask.
Imports calculation engines from src/analysis/liquidity_monitoring/ without duplication.
"""
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from .cache import ttl_cache

# Add the liquidity monitoring module to path
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_LIQ_PATH = str(_PROJECT_ROOT / 'src' / 'analysis' / 'liquidity_monitoring')
if _LIQ_PATH not in sys.path:
    sys.path.insert(0, _LIQ_PATH)

# Mock streamlit to prevent import errors in the liquidity modules
import types
_mock_st = types.ModuleType('streamlit')
_mock_st.cache_data = lambda **kwargs: (lambda fn: fn)  # no-op decorator
sys.modules.setdefault('streamlit', _mock_st)

# Now import the calculation modules
from config.indicators import (
    LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS,
    LAYER_WEIGHTS, REGIME_LABELS, TRANSMISSION_STAGES, FRED_SERIES,
)
from calculations.liquidity_indicators import (
    calculate_continuous_layer_scores,
    calculate_historical_continuous_totals,
)
from calculations.regime_classifier import (
    classify_regime, get_regime_description,
)
from calculations.transmission_chain import (
    calculate_stage_scores, calculate_stage_current, detect_transmission_break,
)
from data.loader import load_cached_data, resample_to_weekly

# Data paths
_DATA_DIR = _PROJECT_ROOT / 'data' / 'liquidity'
_CACHE_FILE = 'us_liquidity_raw.csv'


# =========================================================================
# Data Loading
# =========================================================================

def _load_raw_data():
    """Load raw FRED data from CSV cache."""
    df = load_cached_data(_CACHE_FILE)
    if df is None:
        raise FileNotFoundError(
            f'No liquidity data found at {_DATA_DIR / _CACHE_FILE}. '
            'Run the liquidity updater first.'
        )
    return df


def get_raw_data():
    """Get raw data with TTL caching (1 hour)."""
    return ttl_cache('liquidity_raw', _load_raw_data, ttl=3600)


# =========================================================================
# Liquidity Dashboard
# =========================================================================

def get_dashboard_data():
    """Compute all dashboard data: layer scores, regime, composite history."""
    def _compute():
        raw = get_raw_data()

        # Historical continuous scores
        hist = calculate_historical_continuous_totals(
            raw, LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
        )

        # Resample to weekly for chart clarity
        hist_weekly = resample_to_weekly(hist)

        # Current values (latest non-NaN)
        latest = hist.dropna(subset=['Composite']).iloc[-1]
        l1 = float(latest['L1'])
        l2a = float(latest['L2a'])
        l2b = float(latest['L2b'])
        composite = float(latest['Composite'])

        # Regime classification
        regime = classify_regime(l1, l2a, l2b)
        regime['description'] = get_regime_description(regime['regime_key'])

        return {
            'l1': l1, 'l2a': l2a, 'l2b': l2b, 'composite': composite,
            'regime': regime,
            'history': hist_weekly,
        }

    return ttl_cache('liquidity_dashboard', _compute, ttl=300)


def build_dashboard_response():
    """Build JSON response for the liquidity dashboard API."""
    data = get_dashboard_data()
    regime = data['regime']
    hist = data['history']

    # Determine bias class for CSS
    bias = regime['bias'].lower()
    if bias not in ('bullish', 'bearish'):
        bias = 'neutral'

    # Build Plotly traces
    dates = [d.strftime('%Y-%m-%d') for d in hist.index]

    traces = [
        {
            'type': 'scatter', 'mode': 'lines', 'x': dates,
            'y': [round(v, 3) if pd.notna(v) else None for v in hist['L1']],
            'name': 'L1 (CB)', 'line': {'color': '#2E86AB', 'width': 2},
            'yaxis': 'y',
        },
        {
            'type': 'scatter', 'mode': 'lines', 'x': dates,
            'y': [round(v, 3) if pd.notna(v) else None for v in hist['L2a']],
            'name': 'L2a (Private)', 'line': {'color': '#A23B72', 'width': 2},
            'yaxis': 'y',
        },
        {
            'type': 'scatter', 'mode': 'lines', 'x': dates,
            'y': [round(v, 3) if pd.notna(v) else None for v in hist['L2b']],
            'name': 'L2b (Economy)', 'line': {'color': '#6BAA75', 'width': 2},
            'yaxis': 'y',
        },
        {
            'type': 'scatter', 'mode': 'lines', 'x': dates,
            'y': [round(v, 3) if pd.notna(v) else None for v in hist['Composite']],
            'name': 'Composite', 'line': {'color': '#4f8cf7', 'width': 3},
            'yaxis': 'y2',
        },
    ]

    # Reference bands
    for ref_val in [1, -1]:
        traces.append({
            'type': 'scatter', 'mode': 'lines',
            'x': [dates[0], dates[-1]], 'y': [ref_val, ref_val],
            'line': {'color': 'rgba(255,255,255,0.15)', 'width': 1, 'dash': 'dot'},
            'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y',
        })
    for ref_val in [0.5, -0.5]:
        traces.append({
            'type': 'scatter', 'mode': 'lines',
            'x': [dates[0], dates[-1]], 'y': [ref_val, ref_val],
            'line': {'color': 'rgba(255,255,255,0.15)', 'width': 1, 'dash': 'dot'},
            'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y2',
        })

    # Recession shading
    recessions = [('2007-12-01', '2009-06-01'), ('2020-02-01', '2020-04-01')]
    for start, end in recessions:
        traces.append({
            'type': 'scatter', 'mode': 'none',
            'x': [start, start, end, end, start],
            'y': [-5, 5, 5, -5, -5],
            'fill': 'toself', 'fillcolor': 'rgba(255,0,0,0.06)',
            'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y',
        })

    layout = {
        'height': 550,
        'yaxis': {
            'title': 'Layer Z-Scores', 'domain': [0.35, 1],
            'zeroline': True, 'zerolinecolor': 'rgba(255,255,255,0.2)',
        },
        'yaxis2': {
            'title': 'Composite', 'domain': [0, 0.30],
            'zeroline': True, 'zerolinecolor': 'rgba(255,255,255,0.2)',
        },
        'xaxis': {'rangeslider': {'visible': False}},
        'shapes': [{
            'type': 'line', 'xref': 'paper', 'x0': 0, 'x1': 1,
            'yref': 'paper', 'y0': 0.32, 'y1': 0.32,
            'line': {'color': 'rgba(255,255,255,0.1)', 'width': 1},
        }],
    }

    return {
        'l1': data['l1'], 'l2a': data['l2a'], 'l2b': data['l2b'],
        'composite': data['composite'],
        'regime_label': regime['regime'],
        'bias': bias,
        'regime_description': regime['description'],
        'traces': traces,
        'layout': layout,
    }


# =========================================================================
# Layer Detail
# =========================================================================

def build_layer_detail_response(layer_id):
    """Build JSON response for layer detail view."""
    raw = get_raw_data()

    layer_map = {'1': LAYER1_INDICATORS, '2a': LAYER2A_INDICATORS, '2b': LAYER2B_INDICATORS}
    layer_name = {'1': 'Layer 1 — CB Liquidity', '2a': 'Layer 2a — Private/Wholesale', '2b': 'Layer 2b — Economic Reality'}

    config = layer_map.get(layer_id)
    if not config:
        return {'error': f'Unknown layer: {layer_id}'}

    scores = calculate_continuous_layer_scores(raw, config)
    if scores.empty:
        return {'error': 'No data for layer'}

    weekly = resample_to_weekly(scores)
    dates = [d.strftime('%Y-%m-%d') for d in weekly.index]

    # Build traces — one per indicator
    colors = ['#33ff00', '#ffb000', '#05d9e8', '#ff2a6d', '#ff6e27', '#A23B72', '#6BAA75', '#FFD700', '#888888', '#ff3333', '#2E86AB']
    traces = []
    for i, col in enumerate(weekly.columns):
        color = colors[i % len(colors)]
        vals = [round(v, 3) if pd.notna(v) else None for v in weekly[col]]
        traces.append({
            'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': vals,
            'name': col.replace('_', ' ').title(), 'line': {'color': color, 'width': 1.5},
        })

    # Zero line
    traces.append({
        'type': 'scatter', 'mode': 'lines',
        'x': [dates[0], dates[-1]], 'y': [0, 0],
        'line': {'color': 'rgba(255,255,255,0.3)', 'width': 1, 'dash': 'dash'},
        'showlegend': False, 'hoverinfo': 'skip',
    })

    # Indicator table HTML
    latest = scores.iloc[-1] if not scores.empty else pd.Series()
    rows_html = ''
    for col in scores.columns:
        val = latest.get(col, None)
        if pd.notna(val):
            val_f = f'{val:+.2f}'
            cls = 'pos' if val > 0 else 'neg'
        else:
            val_f = '—'
            cls = ''
        name = col.replace('_', ' ').title()
        ind_cfg = config.get(col, {})
        signal = ind_cfg.get('signal_type', '')
        rows_html += f'<tr><td>{name}</td><td>{signal}</td><td class="{cls}">{val_f}</td></tr>'

    indicators_html = (
        f'<table class="data-table"><thead><tr><th>Indicator</th><th>Type</th><th>Z-Score</th></tr></thead>'
        f'<tbody>{rows_html}</tbody></table>'
    )

    layout = {
        'height': 450,
        'title': {'text': layer_name.get(layer_id, ''), 'font': {'size': 14}},
    }

    return {'traces': traces, 'layout': layout, 'indicators_html': indicators_html}


# =========================================================================
# Asset Overlay
# =========================================================================

def build_overlay_response(asset='SPY'):
    """Build JSON response for asset overlay view."""
    import yfinance as yf

    def _compute():
        raw = get_raw_data()
        hist = calculate_historical_continuous_totals(
            raw, LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
        )

        # Fetch asset price
        ticker = yf.Ticker(asset)
        price_df = ticker.history(period='10y')
        if price_df.empty:
            return None
        price = price_df['Close']
        price.index = price.index.tz_localize(None)

        # Resample both to weekly
        hist_w = resample_to_weekly(hist)
        price_w = price.resample('W-FRI').last()

        # Align
        common = hist_w.index.intersection(price_w.index)
        if len(common) < 10:
            return None

        return {
            'dates': [d.strftime('%Y-%m-%d') for d in common],
            'price': [round(float(price_w.loc[d]), 2) for d in common],
            'composite': [round(float(hist_w.loc[d, 'Composite']), 3) if pd.notna(hist_w.loc[d, 'Composite']) else None for d in common],
            'l1': [round(float(hist_w.loc[d, 'L1']), 3) if pd.notna(hist_w.loc[d, 'L1']) else None for d in common],
            'l2a': [round(float(hist_w.loc[d, 'L2a']), 3) if pd.notna(hist_w.loc[d, 'L2a']) else None for d in common],
            'l2b': [round(float(hist_w.loc[d, 'L2b']), 3) if pd.notna(hist_w.loc[d, 'L2b']) else None for d in common],
        }

    data = ttl_cache(f'overlay_{asset}', _compute, ttl=3600)
    if data is None:
        return {'error': f'No data for {asset}'}

    traces = [
        {
            'type': 'scatter', 'mode': 'lines', 'x': data['dates'], 'y': data['price'],
            'name': asset, 'line': {'color': '#33ff00', 'width': 2}, 'yaxis': 'y',
        },
        {
            'type': 'scatter', 'mode': 'lines', 'x': data['dates'], 'y': data['composite'],
            'name': 'Composite', 'line': {'color': '#ffb000', 'width': 2}, 'yaxis': 'y2',
        },
    ]

    # Zero line on composite axis
    traces.append({
        'type': 'scatter', 'mode': 'lines',
        'x': [data['dates'][0], data['dates'][-1]], 'y': [0, 0],
        'line': {'color': 'rgba(255,176,0,0.3)', 'width': 1, 'dash': 'dash'},
        'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y2',
    })

    layout = {
        'height': 500,
        'yaxis': {'title': asset + ' Price', 'side': 'left'},
        'yaxis2': {'title': 'Composite Z-Score', 'side': 'right', 'overlaying': 'y',
                   'zeroline': True, 'zerolinecolor': 'rgba(255,176,0,0.3)'},
    }

    return {'traces': traces, 'layout': layout}


# =========================================================================
# Transmission Chain
# =========================================================================

def build_transmission_response():
    """Build JSON response for transmission chain view."""
    def _compute():
        raw = get_raw_data()
        stage_scores = calculate_stage_scores(raw)
        current = calculate_stage_current(raw)
        brk = detect_transmission_break(current)
        return stage_scores, current, brk

    stage_scores, current, brk = ttl_cache('transmission', _compute, ttl=300)
    break_stage, regime_label = brk

    # Flow diagram HTML
    stage_names = {
        1: 'CB Impulse', 2: 'Wholesale', 3: 'Risk Appetite',
        4: 'Bank Credit', 5: 'Asset Response', 6: 'Real Economy', 7: 'Reversal Warning'
    }

    flow_html = ''
    for i in range(1, 8):
        stage_info = current.get(i, {})
        score = stage_info.get('score', 0) if isinstance(stage_info, dict) else float(stage_info)
        if pd.isna(score):
            score = 0
        if score > 0.3:
            cls = 'bullish'
            arrow = ' → ' if i < 7 else ''
        elif score < -0.3:
            cls = 'bearish'
            arrow = ' ✕ ' if i < 7 else ''
        else:
            cls = 'neutral'
            arrow = ' ⇢ ' if i < 7 else ''

        flow_html += (
            f'<div class="score-card" style="min-width:100px">'
            f'<div class="label">S{i}</div>'
            f'<div class="value {"pos" if score > 0 else "neg"}">{score:+.2f}</div>'
            f'<div class="label" style="font-size:12px">{stage_names[i]}</div>'
            f'</div>'
        )
        if i < 7:
            color = '#33ff00' if score > 0.3 else '#ff3333' if score < -0.3 else '#ffb000'
            flow_html += f'<span style="color:{color};font-size:20px">{arrow}</span>'

    # Historical chart traces
    traces = []
    colors_map = {1: '#2E86AB', 2: '#A23B72', 3: '#6BAA75', 4: '#FFD700', 5: '#33ff00', 6: '#ff6e27', 7: '#ff3333'}

    for stage_num, series in stage_scores.items():
        if series is None or series.empty:
            continue
        weekly = series.resample('W-FRI').last().dropna()
        dates = [d.strftime('%Y-%m-%d') for d in weekly.index]
        vals = [round(float(v), 3) for v in weekly.values]
        domain = 'y' if stage_num <= 4 else 'y2'
        traces.append({
            'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': vals,
            'name': f'S{stage_num} {stage_names[stage_num]}',
            'line': {'color': colors_map.get(stage_num, '#888'), 'width': 1.5},
            'yaxis': domain,
        })

    layout = {
        'height': 500,
        'yaxis': {'title': 'Stages 1-4 (Impulse→Credit)', 'domain': [0.35, 1]},
        'yaxis2': {'title': 'Stages 5-7 (Assets→Reversal)', 'domain': [0, 0.30]},
        'shapes': [{
            'type': 'line', 'xref': 'paper', 'x0': 0, 'x1': 1,
            'yref': 'paper', 'y0': 0.32, 'y1': 0.32,
            'line': {'color': 'rgba(255,255,255,0.1)', 'width': 1},
        }],
    }

    return {
        'flow_html': flow_html,
        'break_stage': break_stage,
        'regime_label': regime_label,
        'traces': traces,
        'layout': layout,
    }
