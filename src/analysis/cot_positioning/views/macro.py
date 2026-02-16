"""
Macro economic dashboard view
Displays US and global economic indicators (GDP, CPI, leading indices, ISM PMI)
"""
import streamlit as st
import pandas as pd
import os
import logging
import traceback
from plotly.subplots import make_subplots
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


def render_macro_view(project_root):
    """
    Render the macro economic dashboard view

    Args:
        project_root: Path to project root directory
    """
    PROJECT_ROOT = project_root
    
    # Sidebar for Macro section (currently empty, will be populated per-tab)
    with st.sidebar:
        st.header("⚙️ Macro Settings")
        st.info("Settings will appear here based on active tab")

    st.header("🌍 Macro Economic Dashboard")

    # Tabs for different regions
    tab1, tab2 = st.tabs(["🇺🇸 US", "🌐 More Regions (Coming Soon)"])

    with tab1:
        # Create sub-tabs for US economic indicators
        us_subtab1, us_subtab2, us_subtab3 = st.tabs(["📊 4-Quadrant View", "📈 Leading Indices", "🏭 ISM PMI"])

        # ========== US SUB-TAB 1: 4-QUADRANT VIEW ==========
        with us_subtab1:
            st.markdown("**US Economic Indicators - 4 Quadrant View**")
            st.markdown("*Real GDP | Headline CPI | Core CPI | Nominal GDP*")

            try:
                # Load economic data (all available history)
                gdp_df = pd.read_csv(os.path.join(PROJECT_ROOT, 'data/economic/fred_real_gdp_all.csv'), index_col=0, parse_dates=True)
                nominal_gdp_df = pd.read_csv(os.path.join(PROJECT_ROOT, 'data/economic/fred_nominal_gdp_all.csv'), index_col=0, parse_dates=True)
                cpi_df = pd.read_csv(os.path.join(PROJECT_ROOT, 'data/economic/fred_cpi_quarterly.csv'), index_col=0, parse_dates=True)

                # Create 2x2 subplot figure with shared x-axis
                fig_quad = make_subplots(
                    rows=2, cols=2,
                    subplot_titles=('Nominal GDP Growth (YoY %)',
                                  'Headline CPI (YoY %, All Items)',
                                  'Real GDP Growth (YoY %)',
                                  'Core CPI (YoY %, Excl. Food & Energy)'),
                    shared_xaxes=True,
                    vertical_spacing=0.12,
                    horizontal_spacing=0.10,
                    specs=[[{"secondary_y": False}, {"secondary_y": False}],
                           [{"secondary_y": False}, {"secondary_y": False}]]
                )

                # Q1: Nominal GDP YoY Growth (row 1, col 1)
                fig_quad.add_trace(go.Scatter(
                    x=nominal_gdp_df.index,
                    y=nominal_gdp_df['YoY_Growth_%'],
                    mode='lines',
                    name='Nominal GDP YoY',
                    line=dict(color='#A23B72', width=2),
                    hovertemplate='%{x|%Y-Q%q}<br>Nominal GDP YoY: %{y:.2f}%<extra></extra>',
                    showlegend=False
                ), row=1, col=1)

                fig_quad.add_hline(y=0, line_dash="dash", line_color="gray",
                                 opacity=0.5, row=1, col=1)

                # Q2: Headline CPI (row 1, col 2)
                fig_quad.add_trace(go.Scatter(
                    x=cpi_df.index,
                    y=cpi_df['Headline_YoY_%'],
                    mode='lines+markers',
                    name='Headline CPI YoY',
                    line=dict(color='#6BAA75', width=2),
                    marker=dict(size=3),
                    hovertemplate='%{x|%Y-Q%q}<br>Headline CPI: %{y:.2f}%<extra></extra>',
                    showlegend=False
                ), row=1, col=2)

                fig_quad.add_hline(y=2.0, line_dash="dash", line_color="gray",
                                 opacity=0.5, row=1, col=2)

                # Q3: Real GDP YoY Growth (row 2, col 1)
                fig_quad.add_trace(go.Scatter(
                    x=gdp_df.index,
                    y=gdp_df['YoY_Growth_%'],
                    mode='lines',
                    name='Real GDP YoY Growth',
                    line=dict(color='#2E86AB', width=2),
                    hovertemplate='%{x|%Y-Q%q}<br>Real GDP YoY: %{y:.2f}%<extra></extra>',
                    showlegend=False
                ), row=2, col=1)

                fig_quad.add_hline(y=0, line_dash="dash", line_color="gray",
                                 opacity=0.5, row=2, col=1)

                # Q4: Core CPI (row 2, col 2)
                fig_quad.add_trace(go.Scatter(
                    x=cpi_df.index,
                    y=cpi_df['Core_YoY_%'],
                    mode='lines+markers',
                    name='Core CPI YoY',
                    line=dict(color='#E97451', width=2),
                    marker=dict(size=3),
                    hovertemplate='%{x|%Y-Q%q}<br>Core CPI: %{y:.2f}%<extra></extra>',
                    showlegend=False
                ), row=2, col=2)

                fig_quad.add_hline(y=2.0, line_dash="dash", line_color="gray",
                                 opacity=0.5, row=2, col=2)

                # Update axes labels
                fig_quad.update_yaxes(title_text="YoY Growth %", row=1, col=1)  # Nominal GDP
                fig_quad.update_yaxes(title_text="YoY %", row=1, col=2)  # Headline CPI
                fig_quad.update_yaxes(title_text="YoY Growth %", row=2, col=1)  # Real GDP
                fig_quad.update_yaxes(title_text="YoY %", row=2, col=2)  # Core CPI

                fig_quad.update_xaxes(title_text="Quarter", row=2, col=1)
                fig_quad.update_xaxes(title_text="Quarter", row=2, col=2)

                # Update layout with shared x-axis
                fig_quad.update_xaxes(matches='x')
                fig_quad.update_layout(
                    height=750,
                    template='plotly_white',
                    hovermode='x unified'
                )

                st.plotly_chart(fig_quad, use_container_width=True)

                # Summary metrics
                st.markdown("---")
                st.markdown("**Current Values**")
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

                with metric_col1:
                    nominal_gdp_yoy = nominal_gdp_df['YoY_Growth_%'].iloc[-1]
                    nominal_gdp_qoq = nominal_gdp_df['QoQ_Growth_%'].iloc[-1]
                    st.metric(
                        "Nominal GDP Growth",
                        f"{nominal_gdp_yoy:.2f}% YoY",
                        f"{nominal_gdp_qoq:+.2f}% QoQ"
                    )

                with metric_col2:
                    latest_headline = cpi_df['Headline_YoY_%'].iloc[-1]
                    headline_mom = cpi_df['Headline_MoM_%'].iloc[-1]
                    st.metric(
                        "Headline CPI",
                        f"{latest_headline:.2f}% YoY",
                        f"{headline_mom:+.2f}% MoM"
                    )

                with metric_col3:
                    gdp_yoy = gdp_df['YoY_Growth_%'].iloc[-1]
                    gdp_qoq = gdp_df['QoQ_Growth_%'].iloc[-1]
                    st.metric(
                        "Real GDP Growth",
                        f"{gdp_yoy:.2f}% YoY",
                        f"{gdp_qoq:+.2f}% QoQ"
                    )

                with metric_col4:
                    latest_core = cpi_df['Core_YoY_%'].iloc[-1]
                    core_mom = cpi_df['Core_MoM_%'].iloc[-1]
                    st.metric(
                        "Core CPI",
                        f"{latest_core:.2f}% YoY",
                        f"{core_mom:+.2f}% MoM"
                    )

            except FileNotFoundError as e:
                st.error(f"❌ Economic data files not found. Please run the data fetcher scripts first.")
                st.info("""
                Run these scripts in the sandbox folder:
                - `python fetch_fred_gdp.py`
                - `python fetch_nominal_gdp.py`
                - `python fetch_fred_cpi.py`
                """)
            except Exception as e:
                st.error(f"Error loading economic data: {str(e)}")
                logger.error(f"Error in macro section: {str(e)}\n{traceback.format_exc()}")

        # ========== US SUB-TAB 2: LEADING INDICES ==========
        with us_subtab2:
            st.markdown("**Leading Economic Indicators**")
            st.markdown("*Duncan Index (interest-rate sensitive) | OECD CLI (6-9 month lead)*")

            # Update buttons for leading indices
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("📥 Update Duncan Index", use_container_width=True, key="update_duncan"):
                    with st.spinner("Fetching Duncan Index from FRED..."):
                        try:
                            from src.analysis.cot_positioning.leading_index_updater import update_duncan_index
                            result = update_duncan_index()

                            if result['success']:
                                st.success(f"✓ {result['message']}")
                                st.info(f"📊 Added {result['added_quarters']} quarter(s) | Current: {result['current_value']:.2f}%")
                                st.rerun()
                            else:
                                st.info(result['message'])
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

            with col2:
                if st.button("📥 Update OECD CLI", use_container_width=True, key="update_oecd"):
                    with st.spinner("Fetching OECD CLI from FRED..."):
                        try:
                            from src.analysis.cot_positioning.leading_index_updater import update_oecd_cli
                            result = update_oecd_cli()

                            if result['success']:
                                st.success(f"✓ {result['message']}")
                                st.info(f"📊 Added {result['added_months']} month(s) | Current: {result['current_value']:.2f}")
                                st.rerun()
                            else:
                                st.info(result['message'])
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

            st.markdown("---")

            try:
                # Load leading indices data
                duncan_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic_indicators/duncan_leading_index.csv'),
                    index_col=0, parse_dates=True
                )
                equip_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic_indicators/equipment_subcomponents.csv'),
                    index_col=0, parse_dates=True
                )
                res_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic_indicators/residential_subcomponents.csv'),
                    index_col=0, parse_dates=True
                )
                cli_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/oecd_cli_usa.csv'),
                    index_col=0, parse_dates=True
                )
                nominal_gdp_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/fred_nominal_gdp_all.csv'),
                    index_col=0, parse_dates=True
                )

                # Recession periods for shading
                recession_periods = [
                    ('2001-03-01', '2001-11-01'),
                    ('2007-12-01', '2009-06-01'),
                    ('2020-02-01', '2020-04-01')
                ]

                # Create subplot figure with shared x-axis
                fig_leading = make_subplots(
                    rows=2, cols=1,
                    subplot_titles=('Leading Indices vs GDP Growth',
                                  'Duncan Index - Component Breakdown'),
                    vertical_spacing=0.12,
                    specs=[[{"secondary_y": True}],
                           [{"secondary_y": False}]],
                    row_heights=[0.5, 0.5]
                )

                # ===== SUBPLOT 1: Leading Indices vs GDP Growth =====
                # Duncan Index (left y-axis)
                fig_leading.add_trace(go.Scatter(
                    x=duncan_df.index,
                    y=duncan_df['duncan_index'],
                    mode='lines',
                    name='Duncan Leading Index',
                    line=dict(color='#2c3e50', width=3),
                    hovertemplate='%{x|%Y-Q%q}<br>Duncan Index: %{y:.2f}% of GDP<extra></extra>'
                ), row=1, col=1, secondary_y=False)

                # OECD CLI (left y-axis) - rescaled to match Duncan Index scale
                # Normalize OECD CLI to similar range as Duncan Index for visualization
                cli_normalized = ((cli_df['OECD_CLI'] - 100) * 0.2) + duncan_df['duncan_index'].mean()
                fig_leading.add_trace(go.Scatter(
                    x=cli_df.index,
                    y=cli_normalized,
                    mode='lines',
                    name='OECD CLI (normalized)',
                    line=dict(color='#A23B72', width=2.5),
                    hovertemplate='%{x|%b %Y}<br>OECD CLI: ' + cli_df['OECD_CLI'].astype(str) + '<extra></extra>'
                ), row=1, col=1, secondary_y=False)

                # Real GDP YoY (right y-axis)
                fig_leading.add_trace(go.Scatter(
                    x=duncan_df.index,
                    y=duncan_df['gdp_yoy'],
                    mode='lines',
                    name='Real GDP YoY',
                    line=dict(color='#27ae60', width=2),
                    hovertemplate='%{x|%Y-Q%q}<br>Real GDP YoY: %{y:.2f}%<extra></extra>'
                ), row=1, col=1, secondary_y=True)

                # Nominal GDP YoY (right y-axis, hidden by default)
                fig_leading.add_trace(go.Scatter(
                    x=nominal_gdp_df.index,
                    y=nominal_gdp_df['YoY_Growth_%'],
                    mode='lines',
                    name='Nominal GDP YoY',
                    line=dict(color='#e67e22', width=2, dash='dash'),
                    visible='legendonly',
                    hovertemplate='%{x|%Y-Q%q}<br>Nominal GDP YoY: %{y:.2f}%<extra></extra>'
                ), row=1, col=1, secondary_y=True)

                # Add recession shading to first subplot
                for start, end in recession_periods:
                    fig_leading.add_vrect(
                        x0=start, x1=end,
                        fillcolor="red", opacity=0.1,
                        layer="below", line_width=0,
                        row=1, col=1
                    )

                # ===== SUBPLOT 2: Components Breakdown (Overlayed) =====
                fig_leading.add_trace(go.Scatter(
                    x=duncan_df.index,
                    y=duncan_df['durable_goods_pct'],
                    mode='lines',
                    name='Durable Goods',
                    line=dict(color='#3498db', width=2.5),
                    hovertemplate='%{x|%Y-Q%q}<br>Durable Goods: %{y:.2f}%<extra></extra>'
                ), row=2, col=1)

                fig_leading.add_trace(go.Scatter(
                    x=duncan_df.index,
                    y=duncan_df['residential_pct'],
                    mode='lines',
                    name='Residential',
                    line=dict(color='#e74c3c', width=2.5),
                    hovertemplate='%{x|%Y-Q%q}<br>Residential: %{y:.2f}%<extra></extra>'
                ), row=2, col=1)

                fig_leading.add_trace(go.Scatter(
                    x=duncan_df.index,
                    y=duncan_df['equipment_pct'],
                    mode='lines',
                    name='Equipment',
                    line=dict(color='#f39c12', width=2.5),
                    hovertemplate='%{x|%Y-Q%q}<br>Equipment: %{y:.2f}%<extra></extra>'
                ), row=2, col=1)

                # Add recession shading to second subplot
                for start, end in recession_periods:
                    fig_leading.add_vrect(
                        x0=start, x1=end,
                        fillcolor="red", opacity=0.1,
                        layer="below", line_width=0,
                        row=2, col=1
                    )

                # Update y-axes labels
                fig_leading.update_yaxes(title_text="Leading Indices (% of GDP / Normalized)",
                                      row=1, col=1, secondary_y=False)
                fig_leading.update_yaxes(title_text="GDP YoY %",
                                      row=1, col=1, secondary_y=True)
                fig_leading.update_yaxes(title_text="% of GDP", row=2, col=1)

                # Update x-axes with shared zoom
                fig_leading.update_xaxes(title_text="Quarter", row=2, col=1)
                fig_leading.update_xaxes(matches='x')

                # Update layout
                fig_leading.update_layout(
                    height=900,
                    template='plotly_white',
                    hovermode='x unified',
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                )

                st.plotly_chart(fig_leading, use_container_width=True)

                # ===== METRICS =====
                st.markdown("---")
                st.markdown("**Current Values (Latest Quarter)**")

                metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)

                with metric_col1:
                    current_duncan = duncan_df['duncan_index'].iloc[-1]
                    peak_duncan = duncan_df['duncan_index'].max()
                    st.metric(
                        "Duncan Index",
                        f"{current_duncan:.2f}%",
                        f"Peak: {peak_duncan:.2f}%"
                    )

                with metric_col2:
                    current_durable = duncan_df['durable_goods_pct'].iloc[-1]
                    st.metric(
                        "Durable Goods",
                        f"{current_durable:.2f}%",
                        f"{(current_durable / current_duncan * 100):.1f}% of index"
                    )

                with metric_col3:
                    current_residential = duncan_df['residential_pct'].iloc[-1]
                    st.metric(
                        "Residential",
                        f"{current_residential:.2f}%",
                        f"{(current_residential / current_duncan * 100):.1f}% of index"
                    )

                with metric_col4:
                    current_equipment = duncan_df['equipment_pct'].iloc[-1]
                    st.metric(
                        "Equipment",
                        f"{current_equipment:.2f}%",
                        f"{(current_equipment / current_duncan * 100):.1f}% of index"
                    )

                with metric_col5:
                    latest_cli = cli_df['OECD_CLI'].iloc[-1]
                    cli_change = cli_df['MoM_Change'].iloc[-1]
                    st.metric(
                        "OECD CLI",
                        f"{latest_cli:.2f}",
                        f"{cli_change:+.2f} MoM"
                    )

                # ===== SUB-COMPONENTS (EXPANDABLE) =====
                st.markdown("---")
                with st.expander("📊 View Detailed Sub-Components"):
                    # Create combined subplot for sub-components
                    fig_sub = make_subplots(
                        rows=2, cols=1,
                        subplot_titles=('Equipment Investment Sub-Components',
                                      'Residential Investment Sub-Components'),
                        vertical_spacing=0.15,
                        row_heights=[0.5, 0.5]
                    )

                    # Equipment sub-components
                    fig_sub.add_trace(go.Scatter(
                        x=equip_df.index,
                        y=equip_df['info_processing_pct'],
                        mode='lines',
                        name='Info Processing',
                        line=dict(color='#3498db', width=2),
                        hovertemplate='%{x|%Y-Q%q}<br>Info Processing: %{y:.2f}%<extra></extra>'
                    ), row=1, col=1)

                    fig_sub.add_trace(go.Scatter(
                        x=equip_df.index,
                        y=equip_df['transportation_pct'],
                        mode='lines',
                        name='Transportation',
                        line=dict(color='#9b59b6', width=2),
                        hovertemplate='%{x|%Y-Q%q}<br>Transportation: %{y:.2f}%<extra></extra>'
                    ), row=1, col=1)

                    # Residential sub-components
                    fig_sub.add_trace(go.Scatter(
                        x=res_df.index,
                        y=res_df['single_family_pct'],
                        mode='lines',
                        name='Single-Family',
                        line=dict(color='#3498db', width=2),
                        hovertemplate='%{x|%Y-Q%q}<br>Single-Family: %{y:.2f}%<extra></extra>'
                    ), row=2, col=1)

                    fig_sub.add_trace(go.Scatter(
                        x=res_df.index,
                        y=res_df['multi_family_pct'],
                        mode='lines',
                        name='Multi-Family',
                        line=dict(color='#e74c3c', width=2),
                        hovertemplate='%{x|%Y-Q%q}<br>Multi-Family: %{y:.2f}%<extra></extra>'
                    ), row=2, col=1)

                    # Update axes
                    fig_sub.update_yaxes(title_text="% of GDP", row=1, col=1)
                    fig_sub.update_yaxes(title_text="% of GDP", row=2, col=1)
                    fig_sub.update_xaxes(title_text="Quarter", row=2, col=1)
                    fig_sub.update_xaxes(matches='x')

                    # Update layout
                    fig_sub.update_layout(
                        height=600,
                        template='plotly_white',
                        hovermode='x unified',
                        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                    )

                    st.plotly_chart(fig_sub, use_container_width=True)

                    # Metrics
                    st.markdown("**Latest Values**")
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        latest_info = equip_df['info_processing_pct'].iloc[-1]
                        st.metric("Info Processing", f"{latest_info:.2f}%")
                    with col2:
                        latest_trans = equip_df['transportation_pct'].iloc[-1]
                        st.metric("Transportation", f"{latest_trans:.2f}%")
                    with col3:
                        latest_single = res_df['single_family_pct'].iloc[-1]
                        st.metric("Single-Family", f"{latest_single:.2f}%")
                    with col4:
                        latest_multi = res_df['multi_family_pct'].iloc[-1]
                        st.metric("Multi-Family", f"{latest_multi:.2f}%")

            except FileNotFoundError as e:
                st.error(f"❌ Leading indices data files not found.")
                st.info("""
                Run these scripts in the sandbox folder:
                - `python calculate_duncan_leading_index.py`
                - `python export_subcomponents_for_streamlit.py`
                - `python fetch_oecd_cli.py`
                """)
            except Exception as e:
                st.error(f"Error loading leading indices data: {str(e)}")
                logger.error(f"Error in leading indices section: {str(e)}\n{traceback.format_exc()}")


        # ========== US SUB-TAB 3: ISM PMI ==========
        with us_subtab3:
            st.markdown("**ISM Purchasing Managers' Index (PMI)**")
            st.markdown("*Values above 50 indicate expansion, below 50 indicate contraction*")

            # ISM Data Updater - at top of tab
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("📥 Update Manufacturing", use_container_width=True, key="update_ism_mfg"):
                    with st.spinner("Fetching Manufacturing PMI from ISM.org..."):
                        try:
                            from src.analysis.cot_positioning.ism_updater import update_ism_data
                            result = update_ism_data('manufacturing')

                            if result['success']:
                                st.success(f"✓ {result['message']}")
                                st.info(f"📊 {result['indicators_count']} indicators | Growing: {result['growing_count']} | Contracting: {result['contracting_count']}")
                                st.rerun()
                            else:
                                st.warning(result['message'])
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

            with col2:
                if st.button("📥 Update Services", use_container_width=True, key="update_ism_svc"):
                    with st.spinner("Fetching Services PMI from ISM.org..."):
                        try:
                            from src.analysis.cot_positioning.ism_updater import update_ism_data
                            result = update_ism_data('services')

                            if result['success']:
                                st.success(f"✓ {result['message']}")
                                st.info(f"📊 {result['indicators_count']} indicators | Growing: {result['growing_count']} | Contracting: {result['contracting_count']}")
                                st.rerun()
                            else:
                                st.warning(result['message'])
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

            with col3:
                st.caption("*Fetches from ISM.org (primary) or PR Newswire (fallback)*")

            st.markdown("---")

            try:
                # Load ISM data (corrected with PR Newswire values)
                ism_mfg_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/dbnomics_ism_manufacturing.csv'),
                    index_col=0, parse_dates=True
                )
                ism_services_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/dbnomics_ism_services.csv'),
                    index_col=0, parse_dates=True
                )

                # Load sector rankings
                ism_mfg_sectors_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/ism_manufacturing_sector_rankings.csv'),
                    parse_dates=['Date']
                )
                ism_services_sectors_df = pd.read_csv(
                    os.path.join(PROJECT_ROOT, 'data/economic/ism_services_sector_rankings.csv'),
                    parse_dates=['Date']
                )

                # Create tabs for Manufacturing and Services
                ism_tab1, ism_tab2 = st.tabs(["🏭 Manufacturing PMI", "💼 Services PMI"])

                # ========== MANUFACTURING PMI TAB ==========
                with ism_tab1:
                    st.markdown("**Manufacturing PMI and Sub-Indices**")

                    # Create sub-tabs for each indicator
                    indicator_tabs = st.tabs([col.replace('_', ' ') for col in ism_mfg_df.columns])

                    # Color scheme
                    colors = {
                        'PMI': '#2E86AB',
                        'New_Orders': '#A23B72',
                        'Production': '#6BAA75',
                        'Employment': '#E97451',
                        'Prices': '#F18F01',
                        'Supplier_Deliveries': '#8B4513',
                        'Inventories': '#9370DB',
                        'Backlog': '#CD5C5C',
                        'New_Export_Orders': '#20B2AA',
                        'Imports': '#DAA520',
                        'Customers_Inventories': '#708090'
                    }

                    # For each indicator, create a tab with chart + sector ranking table
                    for tab_idx, col in enumerate(ism_mfg_df.columns):
                        with indicator_tabs[tab_idx]:
                            # Create chart for this indicator
                            fig = go.Figure()

                            fig.add_trace(go.Scatter(
                                x=ism_mfg_df.index,
                                y=ism_mfg_df[col],
                                mode='lines',
                                name=col.replace('_', ' '),
                                line=dict(
                                    color=colors.get(col, '#666666'),
                                    width=2
                                ),
                                hovertemplate='%{x|%Y-%m}<br>%{y:.1f}<extra></extra>'
                            ))

                            # Add 50 line
                            fig.add_hline(
                                y=50,
                                line_dash="solid",
                                line_color="rgba(255, 0, 0, 0.3)",
                                line_width=1.5,
                                annotation_text="50 (Expansion/Contraction)",
                                annotation_position="right"
                            )

                            # Get actual data range
                            actual_start_date = ism_mfg_df.index.min()
                            actual_end_date = ism_mfg_df.index.max()

                            fig.update_layout(
                                title=f"{col.replace('_', ' ')} Index",
                                xaxis_title="Date",
                                yaxis_title="Index Value",
                                height=400,
                                template='plotly_white',
                                hovermode='x unified',
                                showlegend=False,
                                margin=dict(l=50, r=50, t=50, b=50)
                            )

                            fig.update_xaxes(range=[actual_start_date, actual_end_date])

                            st.plotly_chart(fig, use_container_width=True)

                            # Show latest value
                            latest_value = ism_mfg_df[col].iloc[-1]
                            prev_value = ism_mfg_df[col].iloc[-2]
                            change = latest_value - prev_value if pd.notna(latest_value) and pd.notna(prev_value) else None

                            col1, col2, col3 = st.columns(3)
                            with col1:
                                status = "🟢 EXPANSION" if latest_value > 50 else "🔴 CONTRACTION"
                                st.metric(
                                    "Latest Value",
                                    f"{latest_value:.1f}",
                                    f"{change:+.1f}" if change else None
                                )
                            with col2:
                                st.metric("Status", status)
                            with col3:
                                st.metric("Latest Month", ism_mfg_df.index[-1].strftime('%B %Y'))

                            # Sector rankings table
                            st.markdown("---")
                            st.markdown("**📊 Sector Rankings Over Time**")
                            st.markdown("*Rank 1 = Most Expanding | Higher Rank = Most Contracting*")

                            # Filter sector rankings for this specific indicator
                            indicator_sectors = ism_mfg_sectors_df[ism_mfg_sectors_df['Indicator'] == col].copy()

                            if len(indicator_sectors) > 0:
                                # Pivot the sector data to create sectors as rows, months as columns
                                sector_pivot = indicator_sectors.pivot(
                                    index='Sector',
                                    columns='Date',
                                    values='Rank'
                                )

                                # Sort by latest month's rank
                                latest_month_col = sector_pivot.columns[-1]
                                sector_pivot = sector_pivot.sort_values(by=latest_month_col)

                                # Format column headers as month names
                                sector_pivot.columns = [col.strftime('%b %Y') for col in sector_pivot.columns]

                                # Style the dataframe with color coding
                                def color_rank(val):
                                    if pd.isna(val):
                                        return ''
                                    # Green for low ranks (expanding), red for high ranks (contracting)
                                    if val <= 5:
                                        return 'background-color: rgba(76, 175, 80, 0.3)'  # Green
                                    elif val >= 10:
                                        return 'background-color: rgba(244, 67, 54, 0.3)'  # Red
                                    else:
                                        return 'background-color: rgba(255, 193, 7, 0.2)'  # Yellow

                                styled_df = sector_pivot.style.applymap(color_rank).format(precision=0, na_rep='-')

                                # Display table
                                st.dataframe(
                                    styled_df,
                                    use_container_width=True,
                                    height=500
                                )
                            else:
                                st.info(f"No sector ranking data available for {col.replace('_', ' ')}")

                # ========== SERVICES PMI TAB ==========
                with ism_tab2:
                    st.markdown("**Services (Non-Manufacturing) PMI and Sub-Indices**")

                    # Create sub-tabs for each indicator
                    services_indicator_tabs = st.tabs([col.replace('_', ' ') for col in ism_services_df.columns])

                    # Color scheme for services
                    colors_services = {
                        'PMI': '#2E86AB',
                        'Business_Activity': '#A23B72',
                        'New_Orders': '#6BAA75',
                        'Employment': '#E97451',
                        'Prices': '#F18F01',
                        'Supplier_Deliveries': '#8B4513',
                        'Inventories': '#9370DB',
                        'Backlog': '#CD5C5C',
                        'New_Export_Orders': '#20B2AA',
                        'Imports': '#DAA520',
                        'Inventory_Sentiment': '#708090'
                    }

                    # For each indicator, create a tab with chart + sector ranking table
                    for tab_idx, col in enumerate(ism_services_df.columns):
                        with services_indicator_tabs[tab_idx]:
                            # Create chart for this indicator
                            fig = go.Figure()

                            fig.add_trace(go.Scatter(
                                x=ism_services_df.index,
                                y=ism_services_df[col],
                                mode='lines',
                                name=col.replace('_', ' '),
                                line=dict(
                                    color=colors_services.get(col, '#666666'),
                                    width=2
                                ),
                                hovertemplate='%{x|%Y-%m}<br>%{y:.1f}<extra></extra>'
                            ))

                            # Add 50 line
                            fig.add_hline(
                                y=50,
                                line_dash="solid",
                                line_color="rgba(255, 0, 0, 0.3)",
                                line_width=1.5,
                                annotation_text="50 (Expansion/Contraction)",
                                annotation_position="right"
                            )

                            # Get actual data range
                            actual_start_date_services = ism_services_df.index.min()
                            actual_end_date_services = ism_services_df.index.max()

                            fig.update_layout(
                                title=f"{col.replace('_', ' ')} Index",
                                xaxis_title="Date",
                                yaxis_title="Index Value",
                                height=400,
                                template='plotly_white',
                                hovermode='x unified',
                                showlegend=False,
                                margin=dict(l=50, r=50, t=50, b=50)
                            )

                            fig.update_xaxes(range=[actual_start_date_services, actual_end_date_services])

                            st.plotly_chart(fig, use_container_width=True)

                            # Show latest value
                            latest_value = ism_services_df[col].iloc[-1]
                            prev_value = ism_services_df[col].iloc[-2]
                            change = latest_value - prev_value if pd.notna(latest_value) and pd.notna(prev_value) else None

                            col1, col2, col3 = st.columns(3)
                            with col1:
                                status = "🟢 EXPANSION" if latest_value > 50 else "🔴 CONTRACTION"
                                st.metric(
                                    "Latest Value",
                                    f"{latest_value:.1f}",
                                    f"{change:+.1f}" if change else None
                                )
                            with col2:
                                st.metric("Status", status)
                            with col3:
                                st.metric("Latest Month", ism_services_df.index[-1].strftime('%B %Y'))

                            # Sector rankings table
                            st.markdown("---")
                            st.markdown("**📊 Sector Rankings Over Time**")
                            st.markdown("*Rank 1 = Most Expanding | Higher Rank = Most Contracting*")

                            # Filter sector rankings for this specific indicator
                            indicator_sectors_services = ism_services_sectors_df[ism_services_sectors_df['Indicator'] == col].copy()

                            if len(indicator_sectors_services) > 0:
                                # Pivot the sector data to create sectors as rows, months as columns
                                sector_pivot_services = indicator_sectors_services.pivot(
                                    index='Sector',
                                    columns='Date',
                                    values='Rank'
                                )

                                # Sort by latest month's rank
                                latest_month_col_services = sector_pivot_services.columns[-1]
                                sector_pivot_services = sector_pivot_services.sort_values(by=latest_month_col_services)

                                # Format column headers as month names
                                sector_pivot_services.columns = [col.strftime('%b %Y') for col in sector_pivot_services.columns]

                                # Style the dataframe with color coding
                                def color_rank_services(val):
                                    if pd.isna(val):
                                        return ''
                                    # Green for low ranks (expanding), red for high ranks (contracting)
                                    if val <= 5:
                                        return 'background-color: rgba(76, 175, 80, 0.3)'  # Green
                                    elif val >= 11:
                                        return 'background-color: rgba(244, 67, 54, 0.3)'  # Red
                                    else:
                                        return 'background-color: rgba(255, 193, 7, 0.2)'  # Yellow

                                styled_df_services = sector_pivot_services.style.applymap(color_rank_services).format(precision=0, na_rep='-')

                                # Display table
                                st.dataframe(
                                    styled_df_services,
                                    use_container_width=True,
                                    height=500
                                )
                            else:
                                st.info(f"No sector ranking data available for {col.replace('_', ' ')}")

            except FileNotFoundError as e:
                st.error(f"❌ ISM data files not found. Please run the data fetcher scripts first.")
                st.info("""
                Run these scripts in the sandbox folder:
                - `python sandbox/fetch_dbnomics_ism.py`
                - `python sandbox/update_ism_from_prnewswire.py`
                - `python sandbox/create_indicator_specific_sector_rankings.py`

                Required files in data/economic/:
                - dbnomics_ism_manufacturing.csv
                - dbnomics_ism_services.csv
                - ism_manufacturing_sector_rankings.csv
                - ism_services_sector_rankings.csv
                """)
            except Exception as e:
                st.error(f"Error loading ISM data: {str(e)}")
                logger.error(f"Error in ISM section: {str(e)}\n{traceback.format_exc()}")

    with tab2:
        st.info("🚧 Additional regions (EU, China, Japan) will be added here")

