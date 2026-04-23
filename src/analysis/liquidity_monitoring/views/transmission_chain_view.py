"""
Transmission Chain View
Shows 7-stage liquidity flow from CB impulse to real economy
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from calculations.transmission_chain import (
    calculate_stage_scores,
    calculate_stage_current,
    detect_transmission_break,
    CYCLE_COLORS
)
from config.indicators import TRANSMISSION_STAGES

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    'positive': '#4CAF50',
    'neutral': '#FFC107',
    'negative': '#F44336',
}

ARROW_STYLES = {
    'flowing': {'color': '#4CAF50', 'symbol': '→'},
    'partial': {'color': '#FFC107', 'symbol': '⇢'},
    'broken':  {'color': '#F44336', 'symbol': '✕'},
    'grey':    {'color': '#9E9E9E', 'symbol': '→'},
}


def render_transmission_chain(raw_data: pd.DataFrame, project_root: str):
    """Render the transmission chain view"""
    st.header("Liquidity Transmission Chain")
    st.markdown("*7-stage flow: CB impulse → wholesale → credit → real economy*")

    if raw_data is None or raw_data.empty:
        st.error("No data available.")
        return

    try:
        # Calculate current stage scores
        with st.spinner("Calculating transmission stages..."):
            stage_current = calculate_stage_current(raw_data)
            break_stage, regime_label = detect_transmission_break(stage_current)

        # Regime banner
        regime_color = CYCLE_COLORS.get(regime_label, '#9E9E9E')
        color_map = {'blue': '#2196F3', 'green': '#4CAF50', 'yellow': '#FFC107',
                     'orange': '#FF9800', 'red': '#F44336', 'gray': '#9E9E9E'}
        banner_color = color_map.get(regime_color, regime_color)

        st.markdown(f"""
        <div style="background-color: {banner_color}; padding: 15px; border-radius: 10px;
                    text-align: center; margin-bottom: 15px;">
            <h3 style="color: white; margin: 0;">{regime_label}</h3>
            {f'<p style="color: white; margin: 5px 0 0 0;">Break at Stage {break_stage}: {TRANSMISSION_STAGES[break_stage]["name"]}</p>' if break_stage else ''}
        </div>
        """, unsafe_allow_html=True)

        # Stage cards
        _render_stage_cards(stage_current, break_stage)

        # Historical chart
        st.markdown("---")
        st.subheader("Historical Stage Scores")
        _render_historical_chart(raw_data)

    except Exception as e:
        st.error(f"Error rendering transmission chain: {e}")
        logger.error(f"Transmission chain error: {e}", exc_info=True)


def _render_stage_cards(stage_current, break_stage):
    """Render the 7 stage cards with flow arrows"""

    for stage_num in range(1, 8):
        if stage_num not in stage_current:
            continue

        stage = stage_current[stage_num]
        color = STATUS_COLORS.get(stage['status'], '#9E9E9E')
        score = stage['score']
        score_str = f"{score:+.2f}" if not np.isnan(score) else "N/A"

        # Flow arrow between stages
        if stage_num > 1:
            prev_stage = stage_current.get(stage_num - 1, {})
            prev_status = prev_stage.get('status', 'neutral')

            if prev_status == 'positive' and stage['status'] == 'positive':
                arrow = ARROW_STYLES['flowing']
            elif prev_status == 'positive' and stage['status'] == 'neutral':
                arrow = ARROW_STYLES['partial']
            elif prev_status == 'positive' and stage['status'] == 'negative':
                arrow = ARROW_STYLES['broken']
            else:
                arrow = ARROW_STYLES['grey']

            is_break = break_stage == stage_num
            arrow_label = "BREAK" if is_break else ""

            st.markdown(f"""
            <div style="text-align: center; margin: 5px 0; font-size: 20px; color: {arrow['color']};">
                {arrow['symbol']} {arrow_label}
            </div>
            """, unsafe_allow_html=True)

        # Stage card
        stage_config = TRANSMISSION_STAGES.get(stage_num, {})
        indicators_html = ""
        for ind_id, ind_config in stage_config.get('indicators', {}).items():
            indicators_html += f"<span style='font-size: 12px; color: #666;'>{ind_config.get('signal', ind_id)}</span><br>"

        st.markdown(f"""
        <div style="border: 2px solid {color}; border-radius: 10px; padding: 12px;
                    margin: 5px 0; background-color: rgba({','.join(str(int(color.lstrip('#')[i:i+2], 16)) for i in (0, 2, 4))}, 0.08);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="font-size: 14px;">Stage {stage_num}: {stage['name']}</strong>
                    <br><em style="font-size: 12px; color: #888;">{stage['question']}</em>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 24px; font-weight: bold; color: {color};">{score_str}</span>
                </div>
            </div>
            <div style="margin-top: 8px; border-top: 1px solid #eee; padding-top: 6px;">
                {indicators_html}
            </div>
        </div>
        """, unsafe_allow_html=True)


def _render_historical_chart(raw_data):
    """Render historical stage scores chart"""
    try:
        stage_series = calculate_stage_scores(raw_data)

        if not stage_series:
            st.warning("No historical stage data available")
            return

        # Resample to weekly
        stage_weekly = {}
        for stage_num, series in stage_series.items():
            stage_weekly[stage_num] = series.resample('W-FRI').last()

        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=('Stages 1-4 (Impulse → Credit)', 'Stages 5-7 (Assets → Reversal)'),
            vertical_spacing=0.12,
            row_heights=[0.5, 0.5]
        )

        colors = {
            1: '#2196F3', 2: '#00BCD4', 3: '#4CAF50', 4: '#8BC34A',
            5: '#FFC107', 6: '#FF9800', 7: '#F44336'
        }
        names = {
            1: 'S1: CB Impulse', 2: 'S2: Wholesale', 3: 'S3: Risk Appetite',
            4: 'S4: Bank Credit', 5: 'S5: Asset Prices', 6: 'S6: Real Economy',
            7: 'S7: Reversal Warning'
        }

        for stage_num in range(1, 5):
            if stage_num in stage_weekly:
                s = stage_weekly[stage_num]
                fig.add_trace(go.Scatter(
                    x=s.index, y=s.values,
                    mode='lines',
                    name=names.get(stage_num, f'Stage {stage_num}'),
                    line=dict(color=colors.get(stage_num, '#999'), width=1.5),
                    hovertemplate='%{x|%Y-%m-%d}<br>%{fullData.name}: %{y:+.2f}<extra></extra>'
                ), row=1, col=1)

        for stage_num in range(5, 8):
            if stage_num in stage_weekly:
                s = stage_weekly[stage_num]
                fig.add_trace(go.Scatter(
                    x=s.index, y=s.values,
                    mode='lines',
                    name=names.get(stage_num, f'Stage {stage_num}'),
                    line=dict(color=colors.get(stage_num, '#999'), width=1.5),
                    hovertemplate='%{x|%Y-%m-%d}<br>%{fullData.name}: %{y:+.2f}<extra></extra>'
                ), row=2, col=1)

        for row in [1, 2]:
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=row, col=1)
            fig.add_hline(y=0.3, line_dash="dot", line_color="green", opacity=0.3, row=row, col=1)
            fig.add_hline(y=-0.3, line_dash="dot", line_color="red", opacity=0.3, row=row, col=1)

        # Recession shading
        for start, end in [('2007-12-01', '2009-06-01'), ('2020-02-01', '2020-04-01')]:
            for row in [1, 2]:
                fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.1,
                              layer="below", line_width=0, row=row, col=1)

        fig.update_yaxes(title_text="Z-Score", range=[-3, 3], row=1, col=1)
        fig.update_yaxes(title_text="Z-Score", range=[-3, 3], row=2, col=1)
        fig.update_xaxes(matches='x')

        fig.update_layout(
            height=700,
            template='plotly_white',
            hovermode='x unified',
            legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error generating historical chart: {e}")
        logger.error(f"Historical chart error: {e}", exc_info=True)
