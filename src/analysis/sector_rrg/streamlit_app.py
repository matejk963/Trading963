"""
Relative Rotation Graph (RRG)
Supports ETF-based sector rotation and Futures Group rotation (JdK methodology).

Run with: streamlit run src/analysis/sector_rrg/streamlit_app.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import colorsys
import plotly.graph_objects as go
import yfinance as yf

st.set_page_config(page_title="RRG Dashboard", page_icon="🔄", layout="wide")

# =============================================================================
# Configuration
# =============================================================================

ETF_DATASETS = {
    'US Sectors': {
        'benchmark': 'RSP',
        'benchmark_name': 'S&P 500 Equal Weight',
        'sectors': {
            'XLK': ('Technology', '#2196F3'),
            'XLF': ('Financials', '#4CAF50'),
            'XLV': ('Health Care', '#9C27B0'),
            'XLE': ('Energy', '#FF9800'),
            'XLI': ('Industrials', '#795548'),
            'XLC': ('Communication', '#E91E63'),
            'XLY': ('Cons. Discretionary', '#00BCD4'),
            'XLP': ('Cons. Staples', '#8BC34A'),
            'XLU': ('Utilities', '#FFC107'),
            'XLRE': ('Real Estate', '#607D8B'),
            'XLB': ('Materials', '#F44336'),
        }
    },
    'Europe Sectors': {
        'benchmark': '^STOXX',
        'benchmark_name': 'STOXX Europe 600',
        'sectors': {
            'EXV6.DE': ('Basic Resources', '#F44336'),
            'EXH1.DE': ('Oil & Gas', '#FF9800'),
            'EXV1.DE': ('Banks', '#4CAF50'),
            'EXV4.DE': ('Health Care', '#9C27B0'),
            'EXV5.DE': ('Automobiles', '#795548'),
            'EXH4.DE': ('Industrials', '#00BCD4'),
            'EXV3.DE': ('Technology', '#2196F3'),
            'EXH7.DE': ('Telecom', '#E91E63'),
            'EXH3.DE': ('Food & Beverage', '#8BC34A'),
            'EXH8.DE': ('Utilities', '#FFC107'),
            'EXV8.DE': ('Insurance', '#607D8B'),
            'EXH5.DE': ('Chemicals', '#AB47BC'),
        }
    },
    'Global Markets': {
        'benchmark': 'URTH',
        'benchmark_name': 'MSCI World (URTH)',
        'sectors': {
            'SPY': ('US - S&P 500', '#2196F3'),
            'VGK': ('Europe', '#4CAF50'),
            'EWG': ('Germany', '#FF9800'),
            'EWQ': ('France', '#9C27B0'),
            'EWJ': ('Japan', '#E91E63'),
            'FXI': ('China', '#F44336'),
            'EWA': ('Australia', '#00BCD4'),
            'EWU': ('UK', '#795548'),
            'EWC': ('Canada', '#8BC34A'),
            'EEM': ('Emerging Markets', '#FFC107'),
        }
    },
}

# Futures Group RRG — per spec
FUTURES_GROUPS = {
    'Bonds':   {'contracts': {'ZB=F': 'US 30Y', 'ZN=F': 'US 10Y', 'ZF=F': 'US 5Y', 'ZT=F': 'US 2Y'},
                'color': '#2196F3'},
    'Indices': {'contracts': {'YM=F': 'Dow', 'ES=F': 'S&P 500', 'NQ=F': 'Nasdaq', 'RTY=F': 'Russell'},
                'color': '#4CAF50'},
    'FX':      {'contracts': {'DX=F': 'USD Index', '6E=F': 'EUR', '6C=F': 'CAD', '6J=F': 'JPY',
                              '6B=F': 'GBP', '6S=F': 'CHF', '6A=F': 'AUD'},
                'color': '#9C27B0', 'invert': ['DX=F']},
    'Energy':  {'contracts': {'CL=F': 'Crude', 'NG=F': 'NatGas', 'RB=F': 'Gasoline', 'HO=F': 'HeatOil'},
                'color': '#FF9800'},
    'Metals':  {'contracts': {'HG=F': 'Copper', 'GC=F': 'Gold', 'SI=F': 'Silver', 'PL=F': 'Platinum', 'PA=F': 'Palladium'},
                'color': '#F44336'},
    'Grains':  {'contracts': {'ZC=F': 'Corn', 'ZW=F': 'Wheat', 'ZS=F': 'Soy', 'ZL=F': 'SoyOil', 'ZM=F': 'SoyMeal'},
                'color': '#8BC34A'},
    'Softs':   {'contracts': {'KC=F': 'Coffee', 'CC=F': 'Cocoa', 'CT=F': 'Cotton', 'SB=F': 'Sugar'},
                'color': '#FFC107'},
    'Meats':   {'contracts': {'LE=F': 'LiveCattle', 'GF=F': 'FeederCattle', 'HE=F': 'LeanHogs'},
                'color': '#795548'},
}


# =============================================================================
# Core Calculations
# =============================================================================

def wma(series, length):
    """Weighted Moving Average — heavier weight on recent data"""
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(window=length, min_periods=length // 2).apply(
        lambda x: np.dot(x[-len(weights):], weights[-len(x):]) / weights[-len(x):].sum(),
        raw=True
    )


@st.cache_data(ttl=3600)
def fetch_etf_data(tickers, benchmark, period='2y'):
    """Fetch adjusted close prices for ETF tickers"""
    all_tickers = [benchmark] + list(tickers)
    raw = yf.download(all_tickers, period=period, progress=False, auto_adjust=True)

    if isinstance(raw.columns, pd.MultiIndex):
        if 'Close' in raw.columns.get_level_values(0):
            df = raw['Close'].copy()
        else:
            df = raw.iloc[:, raw.columns.get_level_values(0) == raw.columns.get_level_values(0)[0]].copy()
            df.columns = df.columns.droplevel(0)
    else:
        df = raw[['Close']].copy()
        df.columns = [all_tickers[0]]

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)

    return df


@st.cache_data(ttl=3600)
def fetch_futures_data(period='2y'):
    """Fetch all futures contracts for group RRG"""
    all_tickers = []
    for group_config in FUTURES_GROUPS.values():
        all_tickers.extend(group_config['contracts'].keys())

    all_tickers = list(set(all_tickers))
    raw = yf.download(all_tickers, period=period, progress=False, auto_adjust=True)

    if isinstance(raw.columns, pd.MultiIndex):
        if 'Close' in raw.columns.get_level_values(0):
            df = raw['Close'].copy()
        else:
            df = raw.iloc[:, raw.columns.get_level_values(0) == raw.columns.get_level_values(0)[0]].copy()
            df.columns = df.columns.droplevel(0)
    else:
        df = raw
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)

    return df


# =============================================================================
# ETF RRG Calculations (EMA-based, external benchmark)
# =============================================================================

def calculate_rs_ratio_etf(price, benchmark, window=13):
    """RS-Ratio: EMA-smoothed RS / SMA * 100"""
    rs_raw = price / benchmark
    rs_smooth = rs_raw.ewm(span=window, adjust=False).mean()
    rs_sma = rs_smooth.rolling(window=window, min_periods=window // 2).mean()
    return (rs_smooth / rs_sma) * 100


def calculate_rs_momentum_etf(rs_ratio, momentum_window=4):
    """RS-Momentum: EMA-smoothed RS-Ratio / SMA * 100"""
    rs_smooth = rs_ratio.ewm(span=momentum_window, adjust=False).mean()
    rs_sma = rs_smooth.rolling(window=momentum_window, min_periods=momentum_window // 2).mean()
    return (rs_smooth / rs_sma) * 100


def compute_etf_rrg(prices, benchmark_ticker, lookback, momentum_window, tail_length):
    """Compute RRG for ETF datasets"""
    benchmark = prices[benchmark_ticker]
    results = {}
    for ticker in prices.columns:
        if ticker == benchmark_ticker:
            continue
        rs_ratio = calculate_rs_ratio_etf(prices[ticker], benchmark, window=lookback)
        rs_momentum = calculate_rs_momentum_etf(rs_ratio, momentum_window=momentum_window)
        combined = pd.DataFrame({'rs_ratio': rs_ratio, 'rs_momentum': rs_momentum}).dropna()
        if len(combined) >= tail_length:
            results[ticker] = combined.iloc[-tail_length:]
    return results


# =============================================================================
# Futures Group RRG Calculations (WMA-based, endogenous benchmark, per spec)
# =============================================================================

def compute_futures_group_rrg(prices, length, tail_length, selected_groups):
    """
    Full Futures Group RRG per spec:
    1. Normalize each contract: price / WMA(price, length)
    2. Invert DX
    3. Build equal-weighted group indices
    4. Build endogenous aggregate benchmark
    5. JdK RS-Ratio and RS-Momentum using WMA
    """
    # Step 1+2: Normalize all contracts
    normalized = {}
    for group_name, group_config in FUTURES_GROUPS.items():
        if group_name not in selected_groups:
            continue
        invert_list = group_config.get('invert', [])
        for ticker in group_config['contracts']:
            if ticker not in prices.columns:
                continue
            series = prices[ticker].dropna()
            if len(series) < length * 2:
                continue
            w = wma(series, length)
            if ticker in invert_list:
                # Inverted normalization: WMA / price
                normalized[ticker] = w / series
            else:
                normalized[ticker] = series / w

    if not normalized:
        return {}

    norm_df = pd.DataFrame(normalized).ffill()

    # Step 3: Build group indices (equal-weight average of normalized contracts)
    group_indices = {}
    for group_name, group_config in FUTURES_GROUPS.items():
        if group_name not in selected_groups:
            continue
        group_tickers = [t for t in group_config['contracts'] if t in norm_df.columns]
        if group_tickers:
            group_indices[group_name] = norm_df[group_tickers].mean(axis=1)

    if len(group_indices) < 2:
        return {}

    group_df = pd.DataFrame(group_indices).dropna()

    # Step 4: Endogenous aggregate benchmark
    g_agg = group_df.mean(axis=1)

    # Step 5: JdK RS-Ratio and RS-Momentum using WMA
    results = {}
    for group_name in group_df.columns:
        rs = group_df[group_name] / g_agg
        wma_rs = wma(rs, length)
        rs_ratio = wma(rs / wma_rs, length) * 100
        rs_momentum = rs_ratio / wma(rs_ratio, length) * 100

        combined = pd.DataFrame({'rs_ratio': rs_ratio, 'rs_momentum': rs_momentum}).dropna()
        if len(combined) >= tail_length:
            results[group_name] = combined.iloc[-tail_length:]

    return results


def compute_intra_group_rrg(prices, length, tail_length, group_config):
    """
    Intra-group RRG: individual contracts within a single group relative to each other.
    Same WMA/endogenous benchmark methodology as group-level, applied to contracts.
    """
    invert_list = group_config.get('invert', [])

    # Step 1: Normalize each contract
    normalized = {}
    for ticker in group_config['contracts']:
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
        return {}

    norm_df = pd.DataFrame(normalized).ffill().dropna()

    # Step 2: Endogenous benchmark (equal-weight of all contracts in group)
    benchmark = norm_df.mean(axis=1)

    # Step 3: JdK RS-Ratio and RS-Momentum using WMA
    results = {}
    for ticker in norm_df.columns:
        rs = norm_df[ticker] / benchmark
        wma_rs = wma(rs, length)
        rs_ratio = wma(rs / wma_rs, length) * 100
        rs_momentum = rs_ratio / wma(rs_ratio, length) * 100

        combined = pd.DataFrame({'rs_ratio': rs_ratio, 'rs_momentum': rs_momentum}).dropna()
        if len(combined) >= tail_length:
            results[ticker] = combined.iloc[-tail_length:]

    return results


# =============================================================================
# Common
# =============================================================================

def get_quadrant(ratio, momentum):
    if ratio >= 100 and momentum >= 100:
        return 'Leading'
    elif ratio >= 100 and momentum < 100:
        return 'Weakening'
    elif ratio < 100 and momentum < 100:
        return 'Lagging'
    else:
        return 'Improving'


# =============================================================================
# Plotting
# =============================================================================

def plot_rrg(rrg_data, tail_length, show_trails, name_color_map):
    """Create the RRG scatter plot"""
    fig = go.Figure()

    all_x, all_y = [], []
    for df in rrg_data.values():
        all_x.extend(df['rs_ratio'].values)
        all_y.extend(df['rs_momentum'].values)

    margin = 0.3
    x_min = min(min(all_x), 100) - margin
    x_max = max(max(all_x), 100) + margin
    y_min = min(min(all_y), 100) - margin
    y_max = max(max(all_y), 100) + margin

    # Quadrant shading
    fig.add_shape(type="rect", x0=100, y0=100, x1=x_max+1, y1=y_max+1,
                  fillcolor="rgba(76,175,80,0.08)", line_width=0, layer="below")
    fig.add_shape(type="rect", x0=100, y0=y_min-1, x1=x_max+1, y1=100,
                  fillcolor="rgba(255,152,0,0.08)", line_width=0, layer="below")
    fig.add_shape(type="rect", x0=x_min-1, y0=y_min-1, x1=100, y1=100,
                  fillcolor="rgba(244,67,54,0.08)", line_width=0, layer="below")
    fig.add_shape(type="rect", x0=x_min-1, y0=100, x1=100, y1=y_max+1,
                  fillcolor="rgba(33,150,243,0.08)", line_width=0, layer="below")

    lx, rx = x_min + (100 - x_min) * 0.5, 100 + (x_max - 100) * 0.5
    ly, hy = y_min + (100 - y_min) * 0.5, 100 + (y_max - 100) * 0.5

    fig.add_annotation(x=rx, y=hy, text="<b>LEADING</b>", showarrow=False,
                       font=dict(size=14, color="rgba(76,175,80,0.4)"))
    fig.add_annotation(x=rx, y=ly, text="<b>WEAKENING</b>", showarrow=False,
                       font=dict(size=14, color="rgba(255,152,0,0.4)"))
    fig.add_annotation(x=lx, y=ly, text="<b>LAGGING</b>", showarrow=False,
                       font=dict(size=14, color="rgba(244,67,54,0.4)"))
    fig.add_annotation(x=lx, y=hy, text="<b>IMPROVING</b>", showarrow=False,
                       font=dict(size=14, color="rgba(33,150,243,0.4)"))

    fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
    fig.add_vline(x=100, line_dash="dash", line_color="gray", opacity=0.5)

    for key, df in rrg_data.items():
        name, color = name_color_map.get(key, (key, '#999'))
        latest = df.iloc[-1]
        quadrant = get_quadrant(latest['rs_ratio'], latest['rs_momentum'])

        if show_trails and len(df) > 1:
            fig.add_trace(go.Scatter(
                x=df['rs_ratio'], y=df['rs_momentum'],
                mode='lines', line=dict(color=color, width=1.5),
                opacity=0.4, showlegend=False, hoverinfo='skip'
            ))
            n_points = len(df)
            sizes = np.linspace(4, 10, n_points)
            opacities = np.linspace(0.2, 0.8, n_points)
            for i in range(0, n_points - 1, max(1, n_points // 6)):
                fig.add_trace(go.Scatter(
                    x=[df.iloc[i]['rs_ratio']], y=[df.iloc[i]['rs_momentum']],
                    mode='markers',
                    marker=dict(size=sizes[i], color=color, opacity=opacities[i]),
                    showlegend=False,
                    hovertemplate=f'{name}<br>Date: {df.index[i].strftime("%Y-%m-%d")}<br>'
                                 f'RS-Ratio: %{{x:.1f}}<br>RS-Mom: %{{y:.1f}}<extra></extra>'
                ))

        fig.add_trace(go.Scatter(
            x=[latest['rs_ratio']], y=[latest['rs_momentum']],
            mode='markers+text',
            marker=dict(size=14, color=color, line=dict(width=2, color='white')),
            text=[key], textposition='top center',
            textfont=dict(size=11, color=color, family='Arial Black'),
            name=f'{key} - {name} ({quadrant})',
            hovertemplate=f'<b>{key} - {name}</b><br>Quadrant: {quadrant}<br>'
                         f'RS-Ratio: %{{x:.2f}}<br>RS-Momentum: %{{y:.2f}}<extra></extra>'
        ))

    fig.update_layout(
        title=dict(text='Relative Rotation Graph', font=dict(size=18)),
        xaxis=dict(title='RS-Ratio →', zeroline=False),
        yaxis=dict(title='RS-Momentum →', zeroline=False),
        height=700, template='plotly_white',
        legend=dict(x=1.02, y=1, font=dict(size=10)),
        margin=dict(r=200),
    )
    return fig


def plot_rs_ratio_history(rrg_data, name_color_map):
    """Plot RS-Ratio time series"""
    fig = go.Figure()
    for key, df in rrg_data.items():
        name, color = name_color_map.get(key, (key, '#999'))
        fig.add_trace(go.Scatter(
            x=df.index, y=df['rs_ratio'],
            mode='lines', name=key,
            line=dict(color=color, width=1.5),
            hovertemplate=f'{name}<br>%{{x|%Y-%m-%d}}<br>RS-Ratio: %{{y:.2f}}<extra></extra>'
        ))
    fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title='RS-Ratio History', yaxis_title='RS-Ratio',
        height=400, template='plotly_white',
        legend=dict(orientation='h', y=-0.15)
    )
    return fig


# =============================================================================
# Main App
# =============================================================================

def main():
    st.title("🔄 Relative Rotation Graph")
    st.markdown("*Clockwise rotation: Leading → Weakening → Lagging → Improving*")

    all_dataset_names = list(ETF_DATASETS.keys()) + ['Futures Groups']

    with st.sidebar:
        st.subheader("Dataset")
        dataset_name = st.selectbox("Select Universe", all_dataset_names)
        is_futures = dataset_name == 'Futures Groups'

        st.markdown("---")
        st.subheader("Parameters")

        period = st.selectbox("Data Period", ['1y', '2y', '3y', '5y'], index=1)

        if is_futures:
            length = st.slider("WMA Length (weeks)", 5, 52, 20,
                               help="Normalization and JdK smoothing window")
        else:
            lookback = st.slider("RS-Ratio Window (weeks)", 4, 104, 13)
            momentum_window = st.slider("Momentum Window (weeks)", 2, 26, 4)

        tail_length = st.slider("Trail Length (weeks)", 1, 52, 5 if not is_futures else 10)
        show_trails = st.checkbox("Show Trails", value=True)

        st.markdown("---")

        if is_futures:
            futures_views = ['Groups Overview'] + list(FUTURES_GROUPS.keys())
            futures_view = st.selectbox("View", futures_views,
                                        help="Groups Overview = groups vs groups; "
                                             "individual group = contracts within that group")
            is_intra_group = futures_view != 'Groups Overview'

            st.markdown("---")

            if not is_intra_group:
                st.subheader("Groups")
                selected_groups = {}
                for group_name, group_config in FUTURES_GROUPS.items():
                    if st.checkbox(f"{group_name} ({len(group_config['contracts'])})",
                                   value=True, key=f"fut_{group_name}"):
                        selected_groups[group_name] = group_config
                st.markdown("---")
                st.caption("Benchmark: Endogenous (equal-weight all groups)")
            else:
                intra_config = FUTURES_GROUPS[futures_view]
                st.subheader(f"{futures_view} Contracts")
                selected_contracts = {}
                for ticker, name in intra_config['contracts'].items():
                    if st.checkbox(f"{ticker} — {name}", value=True,
                                   key=f"intra_{futures_view}_{ticker}"):
                        selected_contracts[ticker] = name
                st.markdown("---")
                st.caption(f"Benchmark: Endogenous (equal-weight {futures_view} contracts)")

            st.caption("Method: JdK WMA per spec")
        else:
            dataset = ETF_DATASETS[dataset_name]
            benchmark = dataset['benchmark']
            sector_config = dataset['sectors']
            st.subheader("Sectors")
            selected = {}
            for ticker, (name, color) in sector_config.items():
                if st.checkbox(f"{ticker} - {name}", value=True, key=f"{dataset_name}_{ticker}"):
                    selected[ticker] = (name, color)
            st.markdown("---")
            st.caption(f"Benchmark: {benchmark} ({dataset['benchmark_name']})")

        st.caption("Data: Yahoo Finance")

    # ===== Futures Groups mode =====
    if is_futures:
        with st.spinner("Fetching futures data..."):
            prices_raw = fetch_futures_data(period=period)

        if prices_raw is None or prices_raw.empty:
            st.error("Could not fetch futures data.")
            return

        # Weekly resample
        prices = prices_raw.resample('W-FRI').last().ffill()

        # Date slider
        min_date, max_date = prices.index.min().date(), prices.index.max().date()
        as_of_date = st.slider("As-of Date", min_value=min_date, max_value=max_date,
                               value=max_date, format="YYYY-MM-DD")
        prices = prices.loc[prices.index <= pd.Timestamp(as_of_date)]

        if len(prices) < 50:
            st.warning("Not enough data.")
            return

        if not is_intra_group:
            # Groups Overview
            if len(selected_groups) < 2:
                st.warning("Select at least 2 groups.")
                return

            rrg_data = compute_futures_group_rrg(prices, length, tail_length, set(selected_groups.keys()))
            name_color_map = {g: (g, cfg['color']) for g, cfg in selected_groups.items()}
        else:
            # Intra-group: contracts within a single group
            if len(selected_contracts) < 2:
                st.warning("Select at least 2 contracts.")
                return

            # Build a filtered config with only selected contracts
            filtered_config = {
                'contracts': {t: n for t, n in intra_config['contracts'].items()
                              if t in selected_contracts},
                'invert': intra_config.get('invert', []),
            }
            rrg_data = compute_intra_group_rrg(prices, length, tail_length, filtered_config)

            # Generate distinct colors for contracts within the group
            base_color = intra_config['color']
            n_contracts = len(selected_contracts)
            # Parse base hex color, then spread hues around it
            base_rgb = tuple(int(base_color.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4))
            base_h, base_s, base_v = colorsys.rgb_to_hsv(*base_rgb)
            contract_colors = {}
            for i, ticker in enumerate(selected_contracts):
                h = (base_h + (i * 0.08) - (n_contracts * 0.04)) % 1.0
                s = max(0.4, min(1.0, base_s + (i % 2) * 0.15 - 0.07))
                v = max(0.5, min(1.0, base_v - i * 0.05))
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                contract_colors[ticker] = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'

            name_color_map = {t: (selected_contracts[t], contract_colors[t])
                              for t in selected_contracts}

    # ===== ETF mode =====
    else:
        if not selected:
            st.warning("Select at least one sector.")
            return

        with st.spinner("Fetching price data..."):
            prices_raw = fetch_etf_data(tuple(selected.keys()), benchmark, period=period)

        if prices_raw is None or prices_raw.empty:
            st.error("Could not fetch price data.")
            return

        prices_smoothed = prices_raw.rolling(window=5, min_periods=1).mean()
        prices = prices_smoothed.resample('W-FRI').last().ffill()

        min_date, max_date = prices.index.min().date(), prices.index.max().date()
        as_of_date = st.slider("As-of Date", min_value=min_date, max_value=max_date,
                               value=max_date, format="YYYY-MM-DD")
        prices = prices.loc[prices.index <= pd.Timestamp(as_of_date)]

        if len(prices) < 30:
            st.warning("Not enough data.")
            return

        rrg_data = compute_etf_rrg(prices, benchmark, lookback, momentum_window, tail_length)
        name_color_map = selected if not is_futures else {}

    if not rrg_data:
        st.warning("Insufficient data for RRG calculation.")
        return

    # Current positions table
    st.markdown("---")
    col1, col2 = st.columns([3, 1])

    with col2:
        st.subheader("Current Positions")
        positions = []
        for key, df in rrg_data.items():
            latest = df.iloc[-1]
            name, _ = name_color_map.get(key, (key, ''))
            quadrant = get_quadrant(latest['rs_ratio'], latest['rs_momentum'])
            positions.append({
                'Name': name if name != key else key,
                'Quadrant': quadrant,
                'RS-Ratio': f"{latest['rs_ratio']:.1f}",
                'RS-Mom': f"{latest['rs_momentum']:.1f}",
            })

        pos_df = pd.DataFrame(positions)

        def color_quadrant(val):
            colors = {
                'Leading': 'background-color: rgba(76,175,80,0.2)',
                'Weakening': 'background-color: rgba(255,152,0,0.2)',
                'Lagging': 'background-color: rgba(244,67,54,0.2)',
                'Improving': 'background-color: rgba(33,150,243,0.2)',
            }
            return colors.get(val, '')

        styled = pos_df.style.map(color_quadrant, subset=['Quadrant'])
        st.dataframe(styled, hide_index=True, use_container_width=True)

    with col1:
        fig = plot_rrg(rrg_data, tail_length, show_trails, name_color_map)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    fig_hist = plot_rs_ratio_history(rrg_data, name_color_map)
    st.plotly_chart(fig_hist, use_container_width=True)


if __name__ == '__main__':
    main()
