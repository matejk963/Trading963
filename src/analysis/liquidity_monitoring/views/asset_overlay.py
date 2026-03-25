"""
Asset Overlay View
Shows optimized composite indicators alongside asset class prices
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from config.indicators import LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
from calculations.liquidity_indicators import (
    calculate_continuous_layer_scores,
    calculate_historical_continuous_totals
)

logger = logging.getLogger(__name__)

# Optimal lag configurations from analysis
OPTIMAL_LAGS = {
    'SPY': {
        'L2a_hy_spread': -26, 'L2a_ig_spread': -26, 'L2a_nfci': -26,
        'L2b_cpi_level': -4, 'L2b_capacity_util': 10, 'L2b_ppi_commodities': -2,
        'L2b_industrial_prod': -26, 'L1_net_liquidity': 8, 'L2a_ci_loans': -26,
        'L2b_unemployment': 2, 'L2a_bank_credit': -26, 'L2a_m2': -2, 'L2a_mmf_assets': -26
    },
    'QQQ': {
        'L2b_cpi_level': -8, 'L2b_capacity_util': 0, 'L2b_ppi_commodities': -4,
        'L2a_ig_spread': -26, 'L2a_nfci': -26, 'L2b_industrial_prod': 26,
        'L2a_hy_spread': -26, 'L2b_unemployment': 0, 'L1_net_liquidity': 2,
        'L2a_ci_loans': -26, 'L2a_bank_credit': -26, 'L2a_m2': -6, 'L2a_mmf_assets': 23
    },
    'IWM': {
        'L2b_capacity_util': 4, 'L2b_cpi_level': -4, 'L2a_nfci': -26,
        'L2b_industrial_prod': 26, 'L2a_ig_spread': -26, 'L2b_ppi_commodities': -3,
        'L2a_hy_spread': -26, 'L2b_unemployment': 1, 'L1_net_liquidity': 8,
        'L2a_m2': -2, 'L2a_mmf_assets': -26, 'L2a_ci_loans': -26, 'L2a_bank_credit': -26
    },
    'HYG': {
        'L2b_capacity_util': 4, 'L2b_cpi_level': -6, 'L2b_industrial_prod': 25,
        'L2a_hy_spread': 22, 'L2a_bank_credit': -26, 'L2a_ci_loans': -26,
        'L2b_ppi_commodities': -4, 'L2a_nfci': -26, 'L2a_ig_spread': 26,
        'L2b_unemployment': 2, 'L1_net_liquidity': 3, 'L2a_mmf_assets': -26, 'L2a_m2': -3
    },
    'TLT': {
        'L2a_m2': 26, 'L2b_cpi_level': 23, 'L1_net_liquidity': 10,
        'L2b_capacity_util': 14, 'L2a_mmf_assets': -26, 'L2b_industrial_prod': 26,
        'L2a_ci_loans': -26, 'L2a_hy_spread': 8, 'L2b_ppi_commodities': 23,
        'L2a_nfci': 1, 'L2b_unemployment': -26, 'L2a_ig_spread': -26, 'L2a_bank_credit': -7
    },
    'GLD': {
        'L2a_m2': 26, 'L2b_unemployment': -17, 'L2b_cpi_level': -3,
        'L2a_bank_credit': -10, 'L2a_ci_loans': -4, 'L2b_capacity_util': -24,
        'L1_net_liquidity': 18, 'L2a_nfci': -22, 'L2b_industrial_prod': 9,
        'L2b_ppi_commodities': 26, 'L2a_ig_spread': 26, 'L2a_mmf_assets': 26, 'L2a_hy_spread': 26
    },
    'UUP': {
        'L2b_capacity_util': -3, 'L2b_cpi_level': -9, 'L2b_industrial_prod': 26,
        'L2a_nfci': -26, 'L2b_ppi_commodities': 0, 'L1_net_liquidity': 4,
        'L2b_unemployment': 11, 'L2a_bank_credit': -26, 'L2a_m2': -3,
        'L2a_hy_spread': 5, 'L2a_ig_spread': 0, 'L2a_ci_loans': -26, 'L2a_mmf_assets': 12
    },
    'DBC': {
        'L2b_unemployment': 26, 'L2b_industrial_prod': -26, 'L2b_ppi_commodities': -26,
        'L2b_capacity_util': 26, 'L2b_cpi_level': -26, 'L2a_m2': 25,
        'L2a_bank_credit': -21, 'L1_net_liquidity': 8, 'L2a_mmf_assets': -26,
        'L2a_hy_spread': -19, 'L2a_ci_loans': -24, 'L2a_ig_spread': -12, 'L2a_nfci': 18
    },
    'USO': {
        'L2b_industrial_prod': -26, 'L2b_ppi_commodities': -26, 'L2b_cpi_level': -26,
        'L2b_unemployment': 26, 'L2a_m2': 26, 'L2b_capacity_util': 26,
        'L2a_bank_credit': -22, 'L2a_hy_spread': -18, 'L2a_ci_loans': -25,
        'L1_net_liquidity': 13, 'L2a_mmf_assets': -26, 'L2a_ig_spread': -12, 'L2a_nfci': -13
    },
    'LQD': {
        'L2b_cpi_level': -16, 'L2b_ppi_commodities': -18, 'L2b_capacity_util': -14,
        'L2a_hy_spread': 26, 'L2b_industrial_prod': 10, 'L2a_m2': 26,
        'L2a_bank_credit': -26, 'L2a_ig_spread': 26, 'L2b_unemployment': -3,
        'L2a_nfci': -26, 'L2a_mmf_assets': 18, 'L1_net_liquidity': -2, 'L2a_ci_loans': -26
    }
}

# Optimal layer weights from analysis
OPTIMAL_WEIGHTS = {
    'SPY': {'L1': 0.0, 'L2a': 0.6, 'L2b': 0.4},
    'QQQ': {'L1': 0.0, 'L2a': 0.6, 'L2b': 0.4},
    'IWM': {'L1': 0.0, 'L2a': 0.6, 'L2b': 0.4},
    'HYG': {'L1': 0.1, 'L2a': 0.0, 'L2b': 0.9},
    'TLT': {'L1': 1.0, 'L2a': 0.0, 'L2b': 0.0},
    'GLD': {'L1': 0.2, 'L2a': 0.8, 'L2b': 0.0},
    'UUP': {'L1': 0.0, 'L2a': 0.4, 'L2b': 0.6},
    'DBC': {'L1': 0.5, 'L2a': 0.5, 'L2b': 0.0},
    'USO': {'L1': 0.0, 'L2a': 0.3, 'L2b': 0.7},
    'LQD': {'L1': 0.0, 'L2a': 0.0, 'L2b': 1.0}
}

ASSET_NAMES = {
    'SPY': 'S&P 500',
    'QQQ': 'NASDAQ 100',
    'IWM': 'Russell 2000',
    'HYG': 'High Yield Bonds',
    'TLT': 'Long Treasury (20Y+)',
    'GLD': 'Gold',
    'UUP': 'US Dollar',
    'DBC': 'Commodities',
    'USO': 'Oil (WTI)',
    'LQD': 'IG Bonds'
}


def fetch_asset_prices():
    """Fetch asset prices from Yahoo Finance"""
    try:
        import yfinance as yf
        tickers = list(OPTIMAL_LAGS.keys())
        df = yf.download(tickers, start='2005-01-01', progress=False, auto_adjust=True)['Close']
        return df
    except Exception as e:
        logger.error(f"Error fetching asset prices: {e}")
        return None


@st.cache_data(ttl=3600)
def get_cached_asset_prices():
    """Cache asset prices for 1 hour"""
    return fetch_asset_prices()


def calculate_optimized_composite(indicators_weekly, asset, lags, weights):
    """
    Calculate optimized composite for an asset using optimal lags and weights
    """
    # Shift indicators by optimal lags
    shifted = pd.DataFrame(index=indicators_weekly.index)

    for indicator, lag in lags.items():
        if indicator in indicators_weekly.columns:
            shifted[indicator] = indicators_weekly[indicator].shift(lag)

    # Group by layer
    l1_cols = [c for c in shifted.columns if c.startswith('L1_')]
    l2a_cols = [c for c in shifted.columns if c.startswith('L2a_')]
    l2b_cols = [c for c in shifted.columns if c.startswith('L2b_')]

    l1_mean = shifted[l1_cols].mean(axis=1) if l1_cols else pd.Series(0, index=shifted.index)
    l2a_mean = shifted[l2a_cols].mean(axis=1) if l2a_cols else pd.Series(0, index=shifted.index)
    l2b_mean = shifted[l2b_cols].mean(axis=1) if l2b_cols else pd.Series(0, index=shifted.index)

    # Apply optimal weights
    composite = (
        weights['L1'] * l1_mean +
        weights['L2a'] * l2a_mean +
        weights['L2b'] * l2b_mean
    )

    return composite, l1_mean, l2a_mean, l2b_mean


def render_asset_overlay(raw_data: pd.DataFrame, project_root: str):
    """
    Render asset overlay view showing optimized composites vs asset prices
    """
    st.header("Asset Overlay - Optimized Composites")
    st.markdown("*Liquidity signals with optimal indicator lags overlaid on asset prices*")

    if raw_data is None or raw_data.empty:
        st.error("No liquidity data available.")
        return

    # Calculate all indicator Z-scores
    with st.spinner("Calculating indicator Z-scores..."):
        l1_scores = calculate_continuous_layer_scores(raw_data, LAYER1_INDICATORS)
        l2a_scores = calculate_continuous_layer_scores(raw_data, LAYER2A_INDICATORS)
        l2b_scores = calculate_continuous_layer_scores(raw_data, LAYER2B_INDICATORS)

        # Combine all indicators
        all_indicators = pd.DataFrame()
        for col in l1_scores.columns:
            all_indicators[f'L1_{col}'] = l1_scores[col]
        for col in l2a_scores.columns:
            all_indicators[f'L2a_{col}'] = l2a_scores[col]
        for col in l2b_scores.columns:
            all_indicators[f'L2b_{col}'] = l2b_scores[col]

        # Resample to weekly
        indicators_weekly = all_indicators.resample('W-FRI').last().ffill()

    # Fetch asset prices
    with st.spinner("Fetching asset prices..."):
        asset_prices = get_cached_asset_prices()

    if asset_prices is None or asset_prices.empty:
        st.error("Could not fetch asset prices. Please check your internet connection.")
        return

    # Asset selection
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_asset = st.selectbox(
            "Select Asset",
            options=list(OPTIMAL_LAGS.keys()),
            format_func=lambda x: f"{x} - {ASSET_NAMES.get(x, x)}"
        )
    with col2:
        show_layers = st.checkbox("Show Layer Breakdown", value=False)
    with col3:
        show_yoy = st.checkbox("Show Fwd 12M Returns", value=True)

    # Calculate optimized composite for selected asset
    if selected_asset not in OPTIMAL_LAGS:
        st.warning(f"No optimal configuration for {selected_asset}")
        return

    lags = OPTIMAL_LAGS[selected_asset]
    weights = OPTIMAL_WEIGHTS[selected_asset]

    composite, l1_mean, l2a_mean, l2b_mean = calculate_optimized_composite(
        indicators_weekly, selected_asset, lags, weights
    )

    # Also calculate baseline composite (no shifts, default weights)
    baseline_composite = calculate_historical_continuous_totals(
        raw_data, LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
    )['Composite'].resample('W-FRI').last()

    # Get asset price
    if selected_asset not in asset_prices.columns:
        st.warning(f"No price data for {selected_asset}")
        return

    asset_price = asset_prices[selected_asset].resample('W-FRI').last()

    # Calculate forward 12-month returns (what happens in next 52 weeks)
    asset_fwd_12m = (asset_price.shift(-52) / asset_price - 1) * 100  # As percentage

    # Align all data
    if show_yoy:
        common_idx = composite.dropna().index.intersection(asset_fwd_12m.dropna().index)
    else:
        common_idx = composite.dropna().index.intersection(asset_price.dropna().index)

    if len(common_idx) < 50:
        st.warning("Insufficient overlapping data")
        return

    # Display weights
    st.markdown(f"""
    **Optimal Configuration for {ASSET_NAMES.get(selected_asset, selected_asset)}:**
    - Layer Weights: L1={weights['L1']:.0%}, L2a={weights['L2a']:.0%}, L2b={weights['L2b']:.0%}
    """)

    # Show key lag information
    with st.expander("View Indicator Lags"):
        lag_df = pd.DataFrame([
            {'Indicator': k, 'Lag (weeks)': v, 'Lead/Lag': 'Lead' if v < 0 else 'Lag' if v > 0 else 'Coincident'}
            for k, v in sorted(lags.items(), key=lambda x: abs(x[1]), reverse=True)
        ])
        st.dataframe(lag_df, hide_index=True)

    # Create chart
    asset_title = f'{ASSET_NAMES.get(selected_asset, selected_asset)} Forward 12M Return %' if show_yoy else f'{ASSET_NAMES.get(selected_asset, selected_asset)} Price'

    if show_layers:
        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=(
                asset_title,
                'Layer Signals (Shifted)',
                'Composite Signals'
            ),
            vertical_spacing=0.08,
            row_heights=[0.4, 0.3, 0.3],
            specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]]
        )
    else:
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=(
                asset_title,
                'Optimized Composite Signal'
            ),
            vertical_spacing=0.1,
            row_heights=[0.5, 0.5],
            specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
        )

    # Row 1: Asset price or Forward Returns
    if show_yoy:
        # Plot forward 12M returns
        fig.add_trace(go.Scatter(
            x=asset_fwd_12m.loc[common_idx].index,
            y=asset_fwd_12m.loc[common_idx].values,
            mode='lines',
            name=f'{selected_asset} Fwd 12M',
            line=dict(color='#2c3e50', width=2),
            fill='tozeroy',
            fillcolor='rgba(44, 62, 80, 0.1)',
            hovertemplate='%{x|%Y-%m-%d}<br>Fwd 12M: %{y:+.1f}%<extra></extra>'
        ), row=1, col=1)

        # Add composite on secondary axis
        fig.add_trace(go.Scatter(
            x=composite.loc[common_idx].index,
            y=composite.loc[common_idx].values,
            mode='lines',
            name='Optimized Signal',
            line=dict(color='#e74c3c', width=2),
            hovertemplate='%{x|%Y-%m-%d}<br>Signal: %{y:+.2f}<extra></extra>'
        ), row=1, col=1, secondary_y=True)

        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)
        fig.update_yaxes(title_text="Forward 12M Return %", row=1, col=1)
        fig.update_yaxes(title_text="Signal (Z-Score)", range=[-3, 3], row=1, col=1, secondary_y=True)
    else:
        # Plot price
        fig.add_trace(go.Scatter(
            x=asset_price.loc[common_idx].index,
            y=asset_price.loc[common_idx].values,
            mode='lines',
            name=selected_asset,
            line=dict(color='#2c3e50', width=2),
            hovertemplate='%{x|%Y-%m-%d}<br>Price: $%{y:.2f}<extra></extra>'
        ), row=1, col=1)

        # Add composite on secondary axis
        fig.add_trace(go.Scatter(
            x=composite.loc[common_idx].index,
            y=composite.loc[common_idx].values,
            mode='lines',
            name='Optimized Signal',
            line=dict(color='#e74c3c', width=1.5, dash='dot'),
            opacity=0.7,
            hovertemplate='%{x|%Y-%m-%d}<br>Signal: %{y:+.2f}<extra></extra>'
        ), row=1, col=1, secondary_y=True)

        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Signal", row=1, col=1, secondary_y=True)

    if show_layers:
        # Row 2: Layer breakdown
        fig.add_trace(go.Scatter(
            x=l1_mean.loc[common_idx].index,
            y=l1_mean.loc[common_idx].values,
            mode='lines',
            name='L1 (CB)',
            line=dict(color='#2E86AB', width=1.5),
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=l2a_mean.loc[common_idx].index,
            y=l2a_mean.loc[common_idx].values,
            mode='lines',
            name='L2a (Private)',
            line=dict(color='#A23B72', width=1.5),
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=l2b_mean.loc[common_idx].index,
            y=l2b_mean.loc[common_idx].values,
            mode='lines',
            name='L2b (Economy)',
            line=dict(color='#6BAA75', width=1.5),
        ), row=2, col=1)

        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)

        # Row 3: Composites comparison
        fig.add_trace(go.Scatter(
            x=composite.loc[common_idx].index,
            y=composite.loc[common_idx].values,
            mode='lines',
            name='Optimized',
            line=dict(color='#e74c3c', width=2),
            fill='tozeroy',
            fillcolor='rgba(231, 76, 60, 0.1)',
        ), row=3, col=1)

        fig.add_trace(go.Scatter(
            x=baseline_composite.loc[common_idx].index,
            y=baseline_composite.loc[common_idx].values,
            mode='lines',
            name='Baseline',
            line=dict(color='#95a5a6', width=1.5, dash='dash'),
        ), row=3, col=1)

        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=3, col=1)
        fig.update_yaxes(title_text="Z-Score", range=[-3, 3], row=2, col=1)
        fig.update_yaxes(title_text="Composite", range=[-2, 2], row=3, col=1)
    else:
        # Row 2: Composite comparison
        fig.add_trace(go.Scatter(
            x=composite.loc[common_idx].index,
            y=composite.loc[common_idx].values,
            mode='lines',
            name='Optimized',
            line=dict(color='#e74c3c', width=2),
            fill='tozeroy',
            fillcolor='rgba(231, 76, 60, 0.1)',
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=baseline_composite.loc[common_idx].index,
            y=baseline_composite.loc[common_idx].values,
            mode='lines',
            name='Baseline (40/35/25)',
            line=dict(color='#95a5a6', width=1.5, dash='dash'),
        ), row=2, col=1)

        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)
        fig.update_yaxes(title_text="Composite Z-Score", range=[-2, 2], row=2, col=1)

    # Recession shading
    recession_periods = [
        ('2007-12-01', '2009-06-01'),
        ('2020-02-01', '2020-04-01')
    ]
    n_rows = 3 if show_layers else 2
    for start, end in recession_periods:
        for row in range(1, n_rows + 1):
            fig.add_vrect(
                x0=start, x1=end,
                fillcolor="red", opacity=0.1,
                layer="below", line_width=0,
                row=row, col=1
            )

    fig.update_xaxes(matches='x')
    fig.update_layout(
        height=800 if show_layers else 600,
        template='plotly_white',
        hovermode='x unified',
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
    )

    st.plotly_chart(fig, use_container_width=True)

    # Correlation statistics
    st.markdown("---")
    st.subheader("Performance Statistics")

    from scipy import stats

    # Forward correlation (signal vs future 1Y returns) - this is what we show in chart
    forward_data = pd.DataFrame({
        'optimized': composite,
        'baseline': baseline_composite,
        'fwd_ret': asset_fwd_12m / 100  # Convert back to decimal for consistency
    }).dropna()

    col1, col2, col3, col4 = st.columns(4)

    if len(forward_data) > 50:
        opt_corr, opt_pval = stats.pearsonr(forward_data['optimized'], forward_data['fwd_ret'])
        base_corr, base_pval = stats.pearsonr(forward_data['baseline'], forward_data['fwd_ret'])

        with col1:
            st.metric(
                "Optimized Corr (vs Fwd 12M)",
                f"{opt_corr:+.3f}",
                help="Correlation between current signal and next 12-month return"
            )

        with col2:
            st.metric(
                "Baseline Corr (vs Fwd 12M)",
                f"{base_corr:+.3f}",
                help="Baseline uses default 40/35/25 weights, no lag shifts"
            )

        with col3:
            improvement = opt_corr - base_corr
            st.metric(
                "Correlation Gain",
                f"{improvement:+.3f}",
                delta=f"{(improvement / abs(base_corr) * 100):+.1f}%" if base_corr != 0 else "N/A"
            )

        with col4:
            # Show statistical significance
            st.metric(
                "P-Value (Optimized)",
                f"{opt_pval:.4f}",
                delta="Significant" if opt_pval < 0.05 else "Not Sig.",
                delta_color="normal" if opt_pval < 0.05 else "inverse"
            )

    # Multi-asset view
    st.markdown("---")
    st.subheader("All Assets Overview")

    # Calculate current signals for all assets
    current_signals = []
    for asset in OPTIMAL_LAGS.keys():
        if asset in asset_prices.columns:
            lags = OPTIMAL_LAGS[asset]
            weights = OPTIMAL_WEIGHTS[asset]
            comp, _, _, _ = calculate_optimized_composite(indicators_weekly, asset, lags, weights)

            if not comp.empty:
                latest = comp.dropna().iloc[-1]
                current_signals.append({
                    'Asset': f"{asset} - {ASSET_NAMES.get(asset, asset)}",
                    'Signal': latest,
                    'Bias': 'Bullish' if latest > 0.5 else 'Bearish' if latest < -0.5 else 'Neutral'
                })

    signals_df = pd.DataFrame(current_signals)
    if not signals_df.empty:
        signals_df = signals_df.sort_values('Signal', ascending=False)

        # Color code
        def color_signal(val):
            if val > 0.5:
                return 'background-color: rgba(76, 175, 80, 0.3)'
            elif val < -0.5:
                return 'background-color: rgba(244, 67, 54, 0.3)'
            return ''

        styled = signals_df.style.map(color_signal, subset=['Signal'])
        styled = styled.format({'Signal': '{:+.2f}'})
        st.dataframe(styled, hide_index=True, use_container_width=True)
