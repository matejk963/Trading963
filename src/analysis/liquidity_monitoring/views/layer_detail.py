"""
Layer Detail View
Displays detailed breakdown of indicators within each layer
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from config.indicators import (
    LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
)
from calculations.liquidity_indicators import (
    calculate_layer_scores, aggregate_layer_score,
    calculate_roc_12m, calculate_yoy, calculate_cpi_momentum,
    calculate_net_liquidity, calculate_real_rate, calculate_yield_curve,
    calculate_sofr_effr_spread
)

logger = logging.getLogger(__name__)


def render_layer_detail(raw_data: pd.DataFrame, project_root: str):
    """
    Render detailed layer breakdown view

    Args:
        raw_data: DataFrame with raw FRED series
        project_root: Path to project root
    """
    st.header("Layer Detail View")

    if raw_data is None or raw_data.empty:
        st.error("No data available. Please update the data first.")
        return

    # Create tabs for each layer
    tab1, tab2, tab3 = st.tabs([
        "Layer 1: CB Liquidity",
        "Layer 2a: Wholesale",
        "Layer 2b: Economic Reality"
    ])

    with tab1:
        render_layer_tab(
            raw_data,
            LAYER1_INDICATORS,
            "Central Bank Liquidity",
            "Fed policy impulse - balance sheet, rates, yield curve",
            counterintuitive=False
        )

    with tab2:
        render_layer_tab(
            raw_data,
            LAYER2A_INDICATORS,
            "Private/Wholesale Liquidity",
            "Transmission through private sector - bank credit, credit spreads, dollar",
            counterintuitive=False
        )

    with tab3:
        st.warning("""
        **Counterintuitive Scoring:** Layer 2b scores economic weakness as *bullish* for liquidity.
        A weak economy forces the Central Bank to ease, which increases liquidity.
        """)
        render_layer_tab(
            raw_data,
            LAYER2B_INDICATORS,
            "Economic Reality Gauges",
            "Feedback loop - capacity, production, employment, inflation",
            counterintuitive=True
        )


def render_layer_tab(raw_data: pd.DataFrame, layer_config: dict,
                     layer_name: str, description: str,
                     counterintuitive: bool = False):
    """
    Render a single layer tab with indicator table and charts

    Args:
        raw_data: DataFrame with raw FRED series
        layer_config: Layer indicator configuration
        layer_name: Display name for the layer
        description: Layer description
        counterintuitive: Whether scoring is counterintuitive
    """
    st.subheader(layer_name)
    st.markdown(f"*{description}*")

    # Calculate scores
    try:
        results = calculate_layer_scores(raw_data, layer_config)
        total_score = aggregate_layer_score(results)
    except Exception as e:
        st.error(f"Error calculating layer scores: {e}")
        return

    # Display total score
    col1, col2 = st.columns([1, 3])
    with col1:
        score_color = "green" if total_score > 0 else "red" if total_score < 0 else "gray"
        st.markdown(f"""
        <div style="background-color: {score_color}; padding: 15px; border-radius: 8px; text-align: center;">
            <h3 style="color: white; margin: 0;">Score: {total_score:+d}</h3>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        # Score breakdown bar
        scored_indicators = results[results['score'] != 0]
        bullish = (scored_indicators['score'] > 0).sum()
        bearish = (scored_indicators['score'] < 0).sum()
        neutral = len(results) - bullish - bearish

        st.markdown(f"**Breakdown:** 🟢 {bullish} Bullish | 🔴 {bearish} Bearish | ⚪ {neutral} Neutral")

    st.markdown("---")

    # ========== INDICATOR TABLE ==========
    st.subheader("Indicator Breakdown")

    # Prepare display DataFrame
    display_df = results.copy()
    display_df['Score'] = display_df['score'].apply(lambda x: f"+{x}" if x > 0 else str(x))
    display_df['Signal'] = display_df['score'].apply(
        lambda x: "🟢 Bullish" if x > 0 else "🔴 Bearish" if x < 0 else "⚪ Neutral"
    )

    # Format values
    def format_value(row):
        if pd.isna(row['transformed_value']):
            return "N/A"
        if row['signal_type'] in ['roc_12m', 'roc_29m', 'yoy', 'momentum']:
            return f"{row['transformed_value']*100:.2f}%"
        else:
            return f"{row['transformed_value']:.2f}"

    display_df['Transformed'] = display_df.apply(format_value, axis=1)
    display_df['Raw'] = display_df['raw_value'].apply(
        lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
    )

    # Select columns for display
    table_df = display_df[['name', 'Raw', 'Transformed', 'Score', 'Signal']].copy()
    table_df.columns = ['Indicator', 'Current Value', 'Transformed', 'Score', 'Signal']

    # Color code the table
    def color_score(val):
        if '+' in str(val):
            return 'background-color: rgba(76, 175, 80, 0.3)'
        elif '-' in str(val) and val != '0':
            return 'background-color: rgba(244, 67, 54, 0.3)'
        return ''

    styled_df = table_df.style.map(color_score, subset=['Score'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    # ========== CHARTS ==========
    st.markdown("---")
    st.subheader("Historical Charts")

    # Get indicators with FRED codes (not derived, not component)
    chart_indicators = {
        k: v for k, v in layer_config.items()
        if v.get('fred_code') and not v.get('derived', False)
        and v.get('signal_type') != 'component'
    }

    # Also include derived indicators that can be charted
    derived_indicators = {
        k: v for k, v in layer_config.items()
        if v.get('derived', False)
    }

    # Calculate derived series for charting
    derived_series = {}
    for indicator_id, config in derived_indicators.items():
        if indicator_id == 'net_liquidity':
            if all(c in raw_data.columns for c in ['WALCL', 'WTREGEN', 'RRPONTSYD']):
                series = calculate_net_liquidity(
                    raw_data['WALCL'], raw_data['WTREGEN'], raw_data['RRPONTSYD'],
                    smooth=True, ema_span=10
                )
                # Show as 12m ROC %
                derived_series[indicator_id] = (calculate_roc_12m(series) * 100, '12m ROC %')

        elif indicator_id == 'real_policy_rate':
            if all(c in raw_data.columns for c in ['DFF', 'CPIAUCSL']):
                cpi_yoy = calculate_yoy(raw_data['CPIAUCSL']) * 100
                series = calculate_real_rate(raw_data['DFF'], cpi_yoy)
                derived_series[indicator_id] = (series, '%')

        elif indicator_id == 'yield_curve':
            if all(c in raw_data.columns for c in ['DGS10', 'DGS2']):
                series = calculate_yield_curve(raw_data['DGS10'], raw_data['DGS2'])
                derived_series[indicator_id] = (series, '%')

        elif indicator_id == 'sofr_effr_spread':
            if all(c in raw_data.columns for c in ['SOFR', 'EFFR']):
                series = calculate_sofr_effr_spread(raw_data['SOFR'], raw_data['EFFR'])
                derived_series[indicator_id] = (series, 'bps')

        elif indicator_id == 'cpi_momentum':
            if 'CPIAUCSL' in raw_data.columns:
                series = calculate_cpi_momentum(raw_data['CPIAUCSL']) * 100
                derived_series[indicator_id] = (series, '%')

    # Combine all chartable indicators
    all_chart_indicators = list(chart_indicators.items()) + [
        (k, derived_indicators[k]) for k in derived_series.keys()
    ]

    if not all_chart_indicators:
        st.info("No chart data available for this layer")
        return

    # Create multi-panel chart
    n_indicators = len(all_chart_indicators)
    n_cols = 2
    n_rows = (n_indicators + 1) // 2

    fig = make_subplots(
        rows=n_rows, cols=n_cols,
        subplot_titles=[v['name'] for _, v in all_chart_indicators],
        vertical_spacing=0.08,
        horizontal_spacing=0.08
    )

    colors = ['#2E86AB', '#A23B72', '#6BAA75', '#E97451', '#F18F01',
              '#8B4513', '#9370DB', '#CD5C5C', '#20B2AA', '#DAA520']

    for idx, (indicator_id, config) in enumerate(all_chart_indicators):
        row = idx // n_cols + 1
        col = idx % n_cols + 1
        color = colors[idx % len(colors)]

        # Check if this is a derived indicator
        if indicator_id in derived_series:
            plot_series, y_title = derived_series[indicator_id]
            plot_series = plot_series.dropna()
        else:
            fred_code = config['fred_code']
            if fred_code not in raw_data.columns:
                continue

            series = raw_data[fred_code].dropna()
            if series.empty:
                continue

            # Transform if needed
            signal_type = config.get('signal_type', 'level')
            if signal_type == 'roc_12m':
                plot_series = calculate_roc_12m(series) * 100  # Convert to %
                y_title = "12m ROC %"
            elif signal_type == 'yoy':
                plot_series = calculate_yoy(series) * 100
                y_title = "YoY %"
            else:
                plot_series = series
                y_title = config.get('units', '')

        if plot_series.empty:
            continue

        # Resample to weekly for cleaner chart
        plot_series = plot_series.resample('W').last().dropna()

        fig.add_trace(go.Scatter(
            x=plot_series.index,
            y=plot_series.values,
            mode='lines',
            name=config['name'],
            line=dict(color=color, width=1.5),
            showlegend=False,
            hovertemplate='%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>'
        ), row=row, col=col)

        # Add threshold lines if applicable
        signal_type = config.get('signal_type', 'level')
        if signal_type == 'level':
            bullish_thresh = config.get('bullish_threshold')
            bearish_thresh = config.get('bearish_threshold')

            if bullish_thresh is not None:
                fig.add_hline(
                    y=bullish_thresh, line_dash="dash", line_color="green",
                    opacity=0.5, row=row, col=col
                )
            if bearish_thresh is not None and bearish_thresh != bullish_thresh:
                fig.add_hline(
                    y=bearish_thresh, line_dash="dash", line_color="red",
                    opacity=0.5, row=row, col=col
                )
        else:
            # Add zero line for ROC indicators
            fig.add_hline(
                y=0, line_dash="dash", line_color="gray",
                opacity=0.5, row=row, col=col
            )

    # Update layout
    fig.update_layout(
        height=300 * n_rows,
        template='plotly_white',
        hovermode='x unified',
        showlegend=False
    )

    fig.update_xaxes(matches='x')

    st.plotly_chart(fig, use_container_width=True)

    # ========== DERIVED INDICATOR DETAILS ==========
    derived = {k: v for k, v in layer_config.items() if v.get('derived', False)}
    if derived:
        st.markdown("---")
        st.subheader("Derived Indicator Details")

        for indicator_id, config in derived.items():
            with st.expander(f"**{config['name']}** - {config.get('description', '')}"):
                st.markdown(f"Formula: `{config.get('formula', 'N/A')}`")

                # Show current value if calculated
                if indicator_id in results.index:
                    result = results.loc[indicator_id]
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Current Value", f"{result['transformed_value']:.2f}")
                    with col2:
                        score = result['score']
                        score_label = "🟢 Bullish" if score > 0 else "🔴 Bearish" if score < 0 else "⚪ Neutral"
                        st.metric("Score", f"{score:+d} ({score_label})")
