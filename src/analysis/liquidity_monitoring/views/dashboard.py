"""
Main Liquidity Dashboard View
Displays composite scores, regime classification, and historical charts
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from config.indicators import (
    LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS,
    LAYER_WEIGHTS, LAYER_SCORE_RANGES
)
from calculations.liquidity_indicators import (
    calculate_layer_scores, aggregate_layer_score,
    calculate_composite_score, calculate_historical_layer_totals
)
from calculations.regime_classifier import (
    classify_regime, get_regime_description, get_regime_statistics
)

logger = logging.getLogger(__name__)


def render_dashboard(raw_data: pd.DataFrame, project_root: str):
    """
    Render the main liquidity dashboard

    Args:
        raw_data: DataFrame with raw FRED series
        project_root: Path to project root
    """
    st.header("US Global Liquidity Dashboard")
    st.markdown("*Based on Michael Howell's 3-layer framework (Capital Wars, 2020)*")

    if raw_data is None or raw_data.empty:
        st.error("No data available. Please update the data first.")
        return

    # Calculate current layer scores
    try:
        l1_results = calculate_layer_scores(raw_data, LAYER1_INDICATORS)
        l2a_results = calculate_layer_scores(raw_data, LAYER2A_INDICATORS)
        l2b_results = calculate_layer_scores(raw_data, LAYER2B_INDICATORS)

        l1_score = aggregate_layer_score(l1_results)
        l2a_score = aggregate_layer_score(l2a_results)
        l2b_score = aggregate_layer_score(l2b_results)

        composite = calculate_composite_score(l1_score, l2a_score, l2b_score)

        # Classify regime
        regime = classify_regime(l1_score, l2a_score, l2b_score)

    except Exception as e:
        st.error(f"Error calculating scores: {e}")
        logger.error(f"Calculation error: {e}")
        return

    # ========== REGIME DISPLAY ==========
    st.markdown("---")

    # Large regime label with color
    regime_colors = {
        'green': '#4CAF50',
        'lightgreen': '#8BC34A',
        'yellow': '#FFC107',
        'orange': '#FF9800',
        'red': '#F44336'
    }
    color = regime_colors.get(regime['color'], '#9E9E9E')

    st.markdown(f"""
    <div style="background-color: {color}; padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
        <h2 style="color: white; margin: 0;">{regime['regime']}</h2>
        <p style="color: white; margin: 5px 0 0 0; font-size: 18px;">Overall Bias: {regime['bias']}</p>
    </div>
    """, unsafe_allow_html=True)

    # Layer direction summary
    col1, col2, col3 = st.columns(3)

    with col1:
        l1_icon = "🟢" if regime['l1_direction'] > 0 else "🔴" if regime['l1_direction'] < 0 else "🟡"
        st.markdown(f"**Layer 1 (CB):** {l1_icon} {regime['l1_label']}")

    with col2:
        l2a_icon = "🟢" if regime['l2a_direction'] > 0 else "🔴" if regime['l2a_direction'] < 0 else "🟡"
        st.markdown(f"**Layer 2a (Private):** {l2a_icon} {regime['l2a_label']}")

    with col3:
        l2b_icon = "🟢" if regime['l2b_direction'] > 0 else "🔴" if regime['l2b_direction'] < 0 else "🟡"
        st.markdown(f"**Layer 2b (Economy):** {l2b_icon} {regime['l2b_label']}")

    # Regime description
    with st.expander("Regime Interpretation"):
        st.markdown(get_regime_description(regime['regime_key']))
        st.markdown("""
        **Layer 2b Note:** Economic Reality uses *counterintuitive* scoring.
        A weak economy signals that the Central Bank will ease policy, which is bullish for liquidity.
        """)

    # ========== SCORE METRICS ==========
    st.markdown("---")
    st.subheader("Current Scores")

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    with metric_col1:
        l1_range = LAYER_SCORE_RANGES['L1']
        st.metric(
            "Layer 1 (CB Liquidity)",
            f"{l1_score:+d}",
            f"Range: {l1_range[0]} to {l1_range[1]}"
        )

    with metric_col2:
        l2a_range = LAYER_SCORE_RANGES['L2a']
        st.metric(
            "Layer 2a (Wholesale)",
            f"{l2a_score:+d}",
            f"Range: {l2a_range[0]} to {l2a_range[1]}"
        )

    with metric_col3:
        l2b_range = LAYER_SCORE_RANGES['L2b']
        st.metric(
            "Layer 2b (Economic)",
            f"{l2b_score:+d}",
            f"Range: {l2b_range[0]} to {l2b_range[1]}"
        )

    with metric_col4:
        st.metric(
            "Composite Score",
            f"{composite:.2f}",
            f"Weighted: {LAYER_WEIGHTS['L1']*100:.0f}/{LAYER_WEIGHTS['L2a']*100:.0f}/{LAYER_WEIGHTS['L2b']*100:.0f}"
        )

    # ========== HISTORICAL CHART ==========
    st.markdown("---")
    st.subheader("Historical Liquidity Scores")

    try:
        historical = calculate_historical_layer_totals(
            raw_data, LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS
        )

        if not historical.empty:
            # Resample to weekly for cleaner chart
            historical_weekly = historical.resample('W').last().dropna()

            # Create chart
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Layer Scores Over Time', 'Composite Score'),
                vertical_spacing=0.12,
                row_heights=[0.6, 0.4]
            )

            # Layer scores
            fig.add_trace(go.Scatter(
                x=historical_weekly.index,
                y=historical_weekly['L1'],
                mode='lines',
                name='L1 (CB)',
                line=dict(color='#2E86AB', width=2),
                hovertemplate='%{x|%Y-%m-%d}<br>L1: %{y:+.1f}<extra></extra>'
            ), row=1, col=1)

            fig.add_trace(go.Scatter(
                x=historical_weekly.index,
                y=historical_weekly['L2a'],
                mode='lines',
                name='L2a (Private)',
                line=dict(color='#A23B72', width=2),
                hovertemplate='%{x|%Y-%m-%d}<br>L2a: %{y:+.1f}<extra></extra>'
            ), row=1, col=1)

            fig.add_trace(go.Scatter(
                x=historical_weekly.index,
                y=historical_weekly['L2b'],
                mode='lines',
                name='L2b (Economy)',
                line=dict(color='#6BAA75', width=2),
                hovertemplate='%{x|%Y-%m-%d}<br>L2b: %{y:+.1f}<extra></extra>'
            ), row=1, col=1)

            # Zero line
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)

            # Composite score
            fig.add_trace(go.Scatter(
                x=historical_weekly.index,
                y=historical_weekly['Composite'],
                mode='lines',
                name='Composite',
                line=dict(color='#2c3e50', width=3),
                fill='tozeroy',
                fillcolor='rgba(44, 62, 80, 0.1)',
                hovertemplate='%{x|%Y-%m-%d}<br>Composite: %{y:.2f}<extra></extra>'
            ), row=2, col=1)

            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)

            # Add recession shading (major recessions)
            recession_periods = [
                ('2007-12-01', '2009-06-01'),
                ('2020-02-01', '2020-04-01')
            ]
            for start, end in recession_periods:
                for row in [1, 2]:
                    fig.add_vrect(
                        x0=start, x1=end,
                        fillcolor="red", opacity=0.1,
                        layer="below", line_width=0,
                        row=row, col=1
                    )

            # Layout
            fig.update_yaxes(title_text="Score", row=1, col=1)
            fig.update_yaxes(title_text="Composite", row=2, col=1)
            fig.update_xaxes(title_text="Date", row=2, col=1)
            fig.update_xaxes(matches='x')

            fig.update_layout(
                height=700,
                template='plotly_white',
                hovermode='x unified',
                legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
            )

            st.plotly_chart(fig, use_container_width=True)

        else:
            st.warning("Insufficient data for historical chart")

    except Exception as e:
        st.error(f"Error generating historical chart: {e}")
        logger.error(f"Historical chart error: {e}")

    # ========== DATA FRESHNESS ==========
    st.markdown("---")
    st.caption(f"Data through: {raw_data.index.max().strftime('%Y-%m-%d')}")


def render_score_gauge(score: float, min_val: float, max_val: float, title: str):
    """Render a gauge chart for a score"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={'text': title},
        gauge={
            'axis': {'range': [min_val, max_val]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [min_val, min_val/2], 'color': "#FFCCCB"},
                {'range': [min_val/2, 0], 'color': "#FFE4B5"},
                {'range': [0, max_val/2], 'color': "#FFFACD"},
                {'range': [max_val/2, max_val], 'color': "#90EE90"},
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 0
            }
        }
    ))

    fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
    return fig
