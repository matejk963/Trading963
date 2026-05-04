"""
RRG Service — adapts the Streamlit sector RRG for Flask.
Extracts pure calculation functions, adds Flask-compatible caching.
"""
import sys
import pandas as pd
import numpy as np
import colorsys
from pathlib import Path
from .cache import ttl_cache

# Add RRG module path and mock streamlit
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_RRG_PATH = str(_PROJECT_ROOT / 'src' / 'analysis' / 'sector_rrg')
if _RRG_PATH not in sys.path:
    sys.path.insert(0, _RRG_PATH)

import types
if 'streamlit' not in sys.modules or not hasattr(sys.modules['streamlit'], 'set_page_config'):
    _st = types.ModuleType('streamlit')
    _st.cache_data = lambda **kwargs: (lambda fn: fn)
    _st.set_page_config = lambda **kwargs: None
    _st.sidebar = type('obj', (object,), {
        'selectbox': lambda *a, **kw: None, 'slider': lambda *a, **kw: None,
        'checkbox': lambda *a, **kw: None, 'radio': lambda *a, **kw: None,
        'markdown': lambda *a, **kw: None, 'title': lambda *a, **kw: None,
    })()
    _st.title = lambda *a, **kw: None
    _st.markdown = lambda *a, **kw: None
    _st.columns = lambda *a, **kw: [type('col', (object,), {'__enter__': lambda s: s, '__exit__': lambda *a: None})()]
    _st.session_state = {}
    _st.rerun = lambda: None
    sys.modules['streamlit'] = _st

# Import calculation functions from the streamlit app
from streamlit_app import (
    ETF_DATASETS, FUTURES_GROUPS,
    wma, fetch_etf_data, fetch_futures_data,
    calculate_rs_ratio_etf, calculate_rs_momentum_etf,
    compute_etf_rrg, compute_futures_group_rrg, compute_intra_group_rrg,
    get_quadrant,
)

QUADRANT_COLORS = {
    'Leading': 'rgba(76,175,80,0.08)',
    'Weakening': 'rgba(255,152,0,0.08)',
    'Lagging': 'rgba(244,67,54,0.08)',
    'Improving': 'rgba(33,150,243,0.08)',
}
QUADRANT_TEXT_COLORS = {
    'Leading': 'rgba(76,175,80,0.4)',
    'Weakening': 'rgba(255,152,0,0.4)',
    'Lagging': 'rgba(244,67,54,0.4)',
    'Improving': 'rgba(33,150,243,0.4)',
}


# =========================================================================
# Data Fetching (with TTL cache)
# =========================================================================

def _fetch_etf(dataset_key, period):
    config = ETF_DATASETS[dataset_key]
    tickers = list(config['sectors'].keys())
    benchmark = config['benchmark']
    return fetch_etf_data(tickers, benchmark, period)


def _fetch_futures(period):
    return fetch_futures_data(period)


def get_etf_prices(dataset_key, period='2y'):
    return ttl_cache(f'rrg_etf_{dataset_key}_{period}', lambda: _fetch_etf(dataset_key, period), ttl=3600)


def get_futures_prices(period='2y'):
    return ttl_cache(f'rrg_futures_{period}', lambda: _fetch_futures(period), ttl=3600)


# =========================================================================
# Build name/color maps
# =========================================================================

def get_etf_name_color_map(dataset_key):
    config = ETF_DATASETS[dataset_key]
    return {ticker: (info[0], info[1]) for ticker, info in config['sectors'].items()}


def get_futures_group_name_color_map():
    return {name: (name, cfg['color']) for name, cfg in FUTURES_GROUPS.items()}


def get_intra_group_name_color_map(group_name):
    cfg = FUTURES_GROUPS[group_name]
    base_color = cfg['color']
    # Parse hex to HSV
    r, g, b = int(base_color[1:3], 16)/255, int(base_color[3:5], 16)/255, int(base_color[5:7], 16)/255
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    result = {}
    contracts = cfg['contracts']
    n = len(contracts)
    for i, (ticker, name) in enumerate(contracts.items()):
        ch = (h + i * 0.08 - n * 0.04) % 1.0
        cs = max(0.4, min(1.0, s + (i % 2) * 0.15 - 0.07))
        cv = max(0.5, min(1.0, v - i * 0.05))
        cr, cg, cb = colorsys.hsv_to_rgb(ch, cs, cv)
        color = f'#{int(cr*255):02x}{int(cg*255):02x}{int(cb*255):02x}'
        result[ticker] = (name, color)
    return result


# =========================================================================
# Build Plotly traces for RRG scatter
# =========================================================================

def build_rrg_traces(tail_data, name_color_map, show_trails=True):
    """Build Plotly traces for RRG scatter plot."""
    traces = []

    all_x, all_y = [], []
    for df in tail_data.values():
        all_x.extend(df['rs_ratio'].values)
        all_y.extend(df['rs_momentum'].values)

    if not all_x:
        return [], {}

    margin = 0.3
    x_min = min(min(all_x), 100) - margin
    x_max = max(max(all_x), 100) + margin
    y_min = min(min(all_y), 100) - margin
    y_max = max(max(all_y), 100) + margin

    for key, df in tail_data.items():
        name, color = name_color_map.get(key, (key, '#999'))
        latest = df.iloc[-1]
        quadrant = get_quadrant(latest['rs_ratio'], latest['rs_momentum'])

        # Trail
        if show_trails and len(df) > 1:
            traces.append({
                'type': 'scatter', 'mode': 'lines',
                'x': [round(v, 3) for v in df['rs_ratio']], 'y': [round(v, 3) for v in df['rs_momentum']],
                'line': {'color': color, 'width': 1.5}, 'opacity': 0.4,
                'showlegend': False, 'hoverinfo': 'skip', 'legendgroup': key,
            })

        # Latest point
        traces.append({
            'type': 'scatter', 'mode': 'markers+text',
            'x': [round(latest['rs_ratio'], 3)], 'y': [round(latest['rs_momentum'], 3)],
            'marker': {'size': 14, 'color': color, 'line': {'width': 2, 'color': 'white'}},
            'text': [name], 'textposition': 'top center',
            'textfont': {'size': 11, 'color': color},
            'name': f'{name} ({quadrant})', 'legendgroup': key,
            'hovertemplate': f'<b>{name}</b><br>Quadrant: {quadrant}<br>RS-Ratio: %{{x:.2f}}<br>RS-Mom: %{{y:.2f}}<extra></extra>',
        })

    # Layout with quadrant shading
    layout = {
        'height': 600,
        'xaxis': {'title': 'RS-Ratio', 'zeroline': False},
        'yaxis': {'title': 'RS-Momentum', 'zeroline': False},
        'legend': {'x': 1.02, 'y': 1, 'font': {'size': 10}},
        'margin': {'r': 200},
        'shapes': [
            # Quadrant shading
            {'type': 'rect', 'x0': 100, 'y0': 100, 'x1': x_max+1, 'y1': y_max+1, 'fillcolor': QUADRANT_COLORS['Leading'], 'line_width': 0, 'layer': 'below'},
            {'type': 'rect', 'x0': 100, 'y0': y_min-1, 'x1': x_max+1, 'y1': 100, 'fillcolor': QUADRANT_COLORS['Weakening'], 'line_width': 0, 'layer': 'below'},
            {'type': 'rect', 'x0': x_min-1, 'y0': y_min-1, 'x1': 100, 'y1': 100, 'fillcolor': QUADRANT_COLORS['Lagging'], 'line_width': 0, 'layer': 'below'},
            {'type': 'rect', 'x0': x_min-1, 'y0': 100, 'x1': 100, 'y1': y_max+1, 'fillcolor': QUADRANT_COLORS['Improving'], 'line_width': 0, 'layer': 'below'},
            # Cross lines
            {'type': 'line', 'x0': x_min-1, 'x1': x_max+1, 'y0': 100, 'y1': 100, 'line': {'color': 'rgba(255,255,255,0.2)', 'width': 1, 'dash': 'dash'}},
            {'type': 'line', 'x0': 100, 'x1': 100, 'y0': y_min-1, 'y1': y_max+1, 'line': {'color': 'rgba(255,255,255,0.2)', 'width': 1, 'dash': 'dash'}},
        ],
        'annotations': [
            {'x': 100 + (x_max-100)*0.5, 'y': 100 + (y_max-100)*0.5, 'text': '<b>LEADING</b>', 'showarrow': False, 'font': {'size': 14, 'color': QUADRANT_TEXT_COLORS['Leading']}},
            {'x': 100 + (x_max-100)*0.5, 'y': y_min + (100-y_min)*0.5, 'text': '<b>WEAKENING</b>', 'showarrow': False, 'font': {'size': 14, 'color': QUADRANT_TEXT_COLORS['Weakening']}},
            {'x': x_min + (100-x_min)*0.5, 'y': y_min + (100-y_min)*0.5, 'text': '<b>LAGGING</b>', 'showarrow': False, 'font': {'size': 14, 'color': QUADRANT_TEXT_COLORS['Lagging']}},
            {'x': x_min + (100-x_min)*0.5, 'y': 100 + (y_max-100)*0.5, 'text': '<b>IMPROVING</b>', 'showarrow': False, 'font': {'size': 14, 'color': QUADRANT_TEXT_COLORS['Improving']}},
        ],
    }

    return traces, layout


def build_positions_table(tail_data, name_color_map):
    """Build HTML table of current positions with sortable headers."""
    q_colors = {'Leading': '#10b981', 'Weakening': '#f59e0b', 'Lagging': '#ef4444', 'Improving': '#4f8cf7'}
    rows = []
    for key, df in tail_data.items():
        name, color = name_color_map.get(key, (key, '#999'))
        latest = df.iloc[-1]
        quadrant = get_quadrant(latest['rs_ratio'], latest['rs_momentum'])
        qc = q_colors.get(quadrant, '#888')
        rows.append(
            f'<tr data-ratio="{latest["rs_ratio"]:.4f}" data-mom="{latest["rs_momentum"]:.4f}" data-quad="{quadrant}">'
            f'<td style="color:{color};font-weight:600">{name}</td>'
            f'<td style="color:{qc}">{quadrant}</td>'
            f'<td>{latest["rs_ratio"]:.2f}</td>'
            f'<td>{latest["rs_momentum"]:.2f}</td></tr>'
        )
    return (
        '<table class="data-table" id="rrg-pos-table"><thead><tr>'
        '<th onclick="sortRRGTable(0,\'str\')">Asset</th>'
        '<th onclick="sortRRGTable(1,\'str\')">Quadrant</th>'
        '<th onclick="sortRRGTable(2,\'num\')">RS-Ratio</th>'
        '<th onclick="sortRRGTable(3,\'num\')">RS-Mom</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


# =========================================================================
# Main API response builders
# =========================================================================

def _serialize_full_data(full_data, name_color_map):
    """Serialize full RRG time series for client-side date replay."""
    result = {}
    for key, df in full_data.items():
        name, color = name_color_map.get(key, (key, '#999'))
        dates = [d.strftime('%Y-%m-%d') for d in df.index]
        result[key] = {
            'name': name, 'color': color,
            'dates': dates,
            'rs_ratio': [round(v, 3) for v in df['rs_ratio']],
            'rs_momentum': [round(v, 3) for v in df['rs_momentum']],
        }
    return result


def build_rrg_response(dataset='us', period='2y', window=13, trail=8):
    """Build JSON response for RRG API."""
    window = int(window)
    trail = int(trail)
    momentum_window = max(4, window // 3)
    length_days = window * 5
    tail_length = trail

    if dataset == 'futures':
        return _build_futures_group_response(period, window, tail_length)

    dataset_map = {'us': 'US Sectors', 'europe': 'Europe Sectors', 'global': 'Global Markets'}
    dataset_key = dataset_map.get(dataset, 'US Sectors')

    try:
        prices = get_etf_prices(dataset_key, period)
    except Exception as e:
        return {'error': f'Failed to fetch data: {e}'}

    if prices is None or prices.empty:
        return {'error': 'No price data available'}

    config = ETF_DATASETS[dataset_key]
    name_color_map = get_etf_name_color_map(dataset_key)

    tail_data, full_data = compute_etf_rrg(prices, config['benchmark'], length_days, momentum_window * 5, tail_length)

    if not tail_data:
        return {'error': 'Not enough data for RRG calculation'}

    traces, layout = build_rrg_traces(tail_data, name_color_map, show_trails=True)
    table_html = build_positions_table(tail_data, name_color_map)

    # Include full data for date slider replay
    full_serialized = _serialize_full_data(full_data, name_color_map)
    all_dates = sorted(set(d for v in full_serialized.values() for d in v['dates']))

    return {
        'traces': traces, 'layout': layout, 'table_html': table_html,
        'full_data': full_serialized, 'all_dates': all_dates,
    }


def _build_futures_group_response(period, window, tail_length):
    """Build RRG response for futures groups overview."""
    try:
        prices = get_futures_prices(period)
    except Exception as e:
        return {'error': f'Failed to fetch futures data: {e}'}

    if prices is None or prices.empty:
        return {'error': 'No futures price data'}

    selected_groups = list(FUTURES_GROUPS.keys())
    name_color_map = get_futures_group_name_color_map()

    result = compute_futures_group_rrg(prices, window, tail_length, selected_groups)
    if not result or len(result) < 2:
        return {'error': 'Not enough groups for RRG'}

    tail_data, full_data = result
    traces, layout = build_rrg_traces(tail_data, name_color_map, show_trails=True)
    table_html = build_positions_table(tail_data, name_color_map)

    full_serialized = _serialize_full_data(full_data, name_color_map)
    all_dates = sorted(set(d for v in full_serialized.values() for d in v['dates']))

    return {'traces': traces, 'layout': layout, 'table_html': table_html,
            'full_data': full_serialized, 'all_dates': all_dates}


def build_rrg_drill_response(group, period='2y', window=13, trail=8):
    """Build JSON response for intra-group RRG drill-down."""
    window = int(window)
    trail = int(trail)

    if group not in FUTURES_GROUPS:
        return {'error': f'Unknown group: {group}'}

    try:
        prices = get_futures_prices(period)
    except Exception as e:
        return {'error': f'Failed to fetch data: {e}'}

    group_config = FUTURES_GROUPS[group]
    name_color_map = get_intra_group_name_color_map(group)

    tail_data, full_data = compute_intra_group_rrg(prices, window, trail, group_config)

    if not tail_data:
        return {'error': f'Not enough data for {group} intra-group RRG'}

    traces, layout = build_rrg_traces(tail_data, name_color_map, show_trails=True)
    table_html = build_positions_table(tail_data, name_color_map)
    layout['title'] = {'text': f'{group} — Intra-group Rotation', 'font': {'size': 14}}

    full_serialized = _serialize_full_data(full_data, name_color_map)
    all_dates = sorted(set(d for v in full_serialized.values() for d in v['dates']))

    return {'traces': traces, 'layout': layout, 'table_html': table_html,
            'full_data': full_serialized, 'all_dates': all_dates}
