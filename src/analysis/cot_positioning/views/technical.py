"""
Technical Analysis View - Cycle Forecasting
Renders multi-granularity cycle forecasts for futures contracts
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def render_technical_view(contracts, price_tickers, project_root):
    """
    Render the Technical Analysis section with cycle forecasting

    Args:
        contracts: dictionary of contract metadata
        price_tickers: dictionary mapping contract codes to yfinance tickers
        project_root: project root path
    """
    st.header("🔧 Technical Analysis")

    # Create tabs
    tabs = st.tabs(["📊 All Instruments Table", "📈 Detailed Chart", "🔮 More Coming Soon"])

    with tabs[0]:
        render_all_instruments_table(contracts, price_tickers)

    with tabs[1]:
        render_detailed_chart_tab(contracts, price_tickers)

    with tabs[2]:
        st.info("🚧 Additional technical analysis tools coming soon...")
        st.markdown("""
        Future additions:
        - Elliott Wave Analysis
        - Fibonacci Retracements
        - Volume Profile
        - Market Structure Analysis
        """)


def generate_all_forecasts(contracts, price_tickers, forecast_days):
    """
    Generate forecasts for multiple instruments

    Args:
        contracts: dict of contract metadata
        price_tickers: dict of yfinance tickers
        forecast_days: number of days to forecast

    Returns:
        dict with contract code as key and forecast result as value
    """
    from src.analysis.cot_positioning.calculations.cycle_forecast import create_cycle_forecast

    results = {}
    progress_bar = st.progress(0)
    status_text = st.empty()

    total = len(contracts)
    for idx, (code, info) in enumerate(contracts.items(), 1):
        ticker = price_tickers.get(code)
        if not ticker:
            continue

        try:
            status_text.text(f"Processing {code} - {info['name']} ({idx}/{total})...")
            result = create_cycle_forecast(ticker, forecast_days=forecast_days, lookback_years=20)
            results[code] = {
                'success': True,
                'data': result,
                'name': info['name'],
                'category': info['category']
            }
        except Exception as e:
            logger.error(f"Failed to generate forecast for {code}: {str(e)}")
            results[code] = {
                'success': False,
                'error': str(e),
                'name': info['name'],
                'category': info['category']
            }

        progress_bar.progress(idx / total)

    progress_bar.empty()
    status_text.empty()

    return results


def find_confluence(short_turns, medium_turns, long_turns, window_days=3):
    """
    Detect cycle confluence within a time window

    Args:
        short_turns: list of (date, amplitude, type) tuples
        medium_turns: list of (date, amplitude, type) tuples
        long_turns: list of (date, amplitude, type) tuples
        window_days: maximum days apart to consider confluence

    Returns:
        dict with 'short_medium' and 'triple' confluence info
    """
    from datetime import timedelta

    result = {
        'short_medium': None,
        'triple': None
    }

    # Check short + medium confluence
    for s_date, s_amp, s_type in short_turns:
        for m_date, m_amp, m_type in medium_turns:
            days_apart = abs((s_date - m_date).days)
            if days_apart <= window_days and s_type == m_type:
                # Found confluence
                avg_date = s_date + (m_date - s_date) / 2
                result['short_medium'] = {
                    'date': avg_date,
                    'type': s_type,
                    'days_apart': days_apart,
                    's_date': s_date,
                    'm_date': m_date
                }
                break
        if result['short_medium']:
            break

    # Check triple confluence (short + medium + long)
    for s_date, s_amp, s_type in short_turns:
        for m_date, m_amp, m_type in medium_turns:
            for l_date, l_amp, l_type in long_turns:
                s_m_days = abs((s_date - m_date).days)
                s_l_days = abs((s_date - l_date).days)
                m_l_days = abs((m_date - l_date).days)

                if (s_m_days <= window_days and s_l_days <= window_days and
                    m_l_days <= window_days and s_type == m_type == l_type):
                    # Found triple confluence
                    avg_date = s_date + (m_date - s_date) / 3 + (l_date - s_date) / 3
                    max_days = max(s_m_days, s_l_days, m_l_days)
                    result['triple'] = {
                        'date': avg_date,
                        'type': s_type,
                        'max_days_apart': max_days,
                        's_date': s_date,
                        'm_date': m_date,
                        'l_date': l_date
                    }
                    break
            if result['triple']:
                break
        if result['triple']:
            break

    return result


def display_all_instruments_table(results, params, contracts):
    """Display table of all instruments with cycle confluence detection"""

    # Check if results is empty
    if not results:
        st.warning("⚠️ No instruments were processed")
        return

    # Summary stats (show FIRST, before checking table data)
    successful = sum(1 for r in results.values() if r['success'])
    failed = len(results) - successful

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Instruments", len(results))
    with col2:
        st.metric("Successful", successful)
    with col3:
        st.metric("Failed", failed)

    # Show failed instruments first if any
    if failed > 0:
        with st.expander(f"⚠️ Failed Instruments ({failed})", expanded=(successful == 0)):
            failed_list = [
                f"**{code}** - {r['name']}: {r.get('error', 'Unknown error')}"
                for code, r in results.items() if not r['success']
            ]
            for item in failed_list:
                st.write(f"- {item}")

    # If all failed, stop here
    if successful == 0:
        st.error("❌ All instruments failed to generate forecasts. Check errors above.")
        return

    # Build table data - ONE ROW PER INSTRUMENT
    table_data = []

    for code, result in results.items():
        if not result['success']:
            continue

        data = result['data']

        # Extract turning points for each cycle
        short_forecast = data['forecasts']['short']
        medium_forecast = data['forecasts']['medium']
        long_forecast = data['forecasts']['long']

        # Get next turns (peaks and troughs combined)
        short_turns = []
        for peak_date, peak_amp in short_forecast.get('peaks', [])[:3]:
            short_turns.append((peak_date, peak_amp, 'peak'))
        for trough_date, trough_amp in short_forecast.get('troughs', [])[:3]:
            short_turns.append((trough_date, trough_amp, 'trough'))
        short_turns.sort(key=lambda x: x[0])

        medium_turns = []
        for peak_date, peak_amp in medium_forecast.get('peaks', [])[:3]:
            medium_turns.append((peak_date, peak_amp, 'peak'))
        for trough_date, trough_amp in medium_forecast.get('troughs', [])[:3]:
            medium_turns.append((trough_date, trough_amp, 'trough'))
        medium_turns.sort(key=lambda x: x[0])

        long_turns = []
        for peak_date, peak_amp in long_forecast.get('peaks', [])[:3]:
            long_turns.append((peak_date, peak_amp, 'peak'))
        for trough_date, trough_amp in long_forecast.get('troughs', [])[:3]:
            long_turns.append((trough_date, trough_amp, 'trough'))
        long_turns.sort(key=lambda x: x[0])

        # Find confluence
        confluence = find_confluence(short_turns, medium_turns, long_turns, window_days=3)

        # Get next turn for each cycle
        short_next = short_turns[0] if short_turns else (None, None, None)
        medium_next = medium_turns[0] if medium_turns else (None, None, None)
        long_next = long_turns[0] if long_turns else (None, None, None)

        # Format confluence data
        sm_confluence = 'None'
        sm_date = None
        if confluence['short_medium']:
            sm_info = confluence['short_medium']
            sm_type_icon = '⬆️' if sm_info['type'] == 'peak' else '⬇️'
            sm_confluence = f"{sm_type_icon} {sm_info['type'].title()} (±{sm_info['days_apart']}d)"
            sm_date = sm_info['date']

        triple_confluence = 'None'
        triple_date = None
        if confluence['triple']:
            t_info = confluence['triple']
            t_type_icon = '⬆️' if t_info['type'] == 'peak' else '⬇️'
            triple_confluence = f"{t_type_icon} {t_info['type'].title()} (±{t_info['max_days_apart']}d)"
            triple_date = t_info['date']

        row = {
            'Code': code,
            'Name': result['name'],
            'Category': result['category'],
            'Short Turn': f"{'⬆️' if short_next[2] == 'peak' else '⬇️'} {short_next[2].title()}" if short_next[2] else 'N/A',
            'Short Date': short_next[0].strftime('%Y-%m-%d') if short_next[0] else 'N/A',
            'Medium Turn': f"{'⬆️' if medium_next[2] == 'peak' else '⬇️'} {medium_next[2].title()}" if medium_next[2] else 'N/A',
            'Medium Date': medium_next[0].strftime('%Y-%m-%d') if medium_next[0] else 'N/A',
            'Long Turn': f"{'⬆️' if long_next[2] == 'peak' else '⬇️'} {long_next[2].title()}" if long_next[2] else 'N/A',
            'Long Date': long_next[0].strftime('%Y-%m-%d') if long_next[0] else 'N/A',
            'S+M Confluence': sm_confluence,
            'S+M Date': sm_date.strftime('%Y-%m-%d') if sm_date else 'None',
            'Triple Confluence': triple_confluence,
            'Triple Date': triple_date.strftime('%Y-%m-%d') if triple_date else 'None',
        }
        table_data.append(row)

    if not table_data:
        st.warning("⚠️ No forecast data available")
        return

    # Convert to DataFrame
    df = pd.DataFrame(table_data)

    # Count confluences
    sm_count = len(df[df['S+M Confluence'] != 'None'])
    triple_count = len(df[df['Triple Confluence'] != 'None'])

    with col4:
        st.metric("Confluences", f"{sm_count} S+M | {triple_count} Triple")

    # Display table
    st.markdown("### 📋 Cycle Confluence Analysis")
    st.markdown("**Confluence:** Multiple cycles aligning within ±3 days (stronger signals)")

    # Filtering options
    st.markdown("#### 🔍 Filters & Sorting")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        search = st.text_input("Search", placeholder="Code or name...", key="search_conf")

    with col2:
        category_filter = st.multiselect(
            "Category",
            options=sorted(df['Category'].unique()),
            default=None,
            key="cat_filter"
        )

    with col3:
        confluence_filter = st.selectbox(
            "Show",
            ["All", "With S+M Confluence", "With Triple Confluence", "No Confluence"],
            key="conf_filter"
        )

    with col4:
        sort_by = st.selectbox(
            "Sort By",
            ["S+M Date", "Triple Date", "Short Date", "Code", "Category"],
            index=0,
            key="sort_conf"
        )

    # Apply filters
    filtered_df = df.copy()

    if search:
        filtered_df = filtered_df[
            filtered_df['Code'].str.contains(search, case=False) |
            filtered_df['Name'].str.contains(search, case=False)
        ]

    if category_filter:
        filtered_df = filtered_df[filtered_df['Category'].isin(category_filter)]

    if confluence_filter == "With S+M Confluence":
        filtered_df = filtered_df[filtered_df['S+M Confluence'] != 'None']
    elif confluence_filter == "With Triple Confluence":
        filtered_df = filtered_df[filtered_df['Triple Confluence'] != 'None']
    elif confluence_filter == "No Confluence":
        filtered_df = filtered_df[
            (filtered_df['S+M Confluence'] == 'None') &
            (filtered_df['Triple Confluence'] == 'None')
        ]

    # Sort
    if sort_by in ["S+M Date", "Triple Date", "Short Date"]:
        # Convert to datetime for proper sorting
        sort_col = sort_by
        filtered_df[f'{sort_col}_sort'] = pd.to_datetime(filtered_df[sort_col], errors='coerce')
        filtered_df = filtered_df.sort_values(f'{sort_col}_sort').drop(f'{sort_col}_sort', axis=1)
    else:
        filtered_df = filtered_df.sort_values(sort_by)

    # Display with styling
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        height=600
    )

    st.caption(f"Showing {len(filtered_df)} of {len(df)} instruments")

    # Download button
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"cycle_confluence_{params['months']}mo.csv",
        mime="text/csv"
    )


def render_all_instruments_table(contracts, price_tickers):
    """Render table view of all instruments with their cycle turning points"""
    st.subheader("📊 Cycle Turning Points - All Instruments")

    st.markdown("""
    **Quick Overview:** See upcoming peaks and troughs across all instruments at a glance.
    Use this to identify which markets have significant turning points coming up.
    """)

    # Settings
    col1, col2 = st.columns([2, 4])

    with col1:
        forecast_months = st.slider(
            "🔮 Forecast Horizon (months)",
            min_value=1,
            max_value=6,
            value=3,
            help="Number of months to forecast forward"
        )

    with col2:
        category_filter = st.multiselect(
            "📂 Categories",
            sorted(list(set([c['category'] for c in contracts.values()]))),
            default=None,
            help="Filter by asset category (empty = all)"
        )

    # Generate forecasts button
    if st.button("🚀 Generate Forecasts for All Instruments", type="primary", use_container_width=True):
        forecast_days = forecast_months * 30

        # Filter contracts
        filtered_contracts = {}
        for code, info in contracts.items():
            if code not in price_tickers:
                continue
            if category_filter and info['category'] not in category_filter:
                continue
            filtered_contracts[code] = info

        if not filtered_contracts:
            st.warning("⚠️ No instruments match the selected filters")
            return

        # Generate forecasts
        with st.spinner(f"Analyzing {len(filtered_contracts)} instruments..."):
            results = generate_all_forecasts(filtered_contracts, price_tickers, forecast_days)

        # Store in session state
        st.session_state['all_forecasts'] = results
        st.session_state['forecast_params'] = {
            'months': forecast_months
        }

        st.success(f"✅ Generated forecasts for {len(results)} instruments")

    # Display results if available
    if 'all_forecasts' in st.session_state:
        display_all_instruments_table(
            st.session_state['all_forecasts'],
            st.session_state['forecast_params'],
            contracts
        )


def render_detailed_chart_tab(contracts, price_tickers):
    """Render detailed chart view for selected instrument"""
    st.subheader("📈 Detailed Cycle Analysis")

    st.markdown("""
    **Pattern Matching (Analog Forecasting):** Find historical periods when cycles looked similar to today,
    then show what happened next. Cycles are extracted using wavelet transforms at three timeframes:
    - **Short**: ~40-60 days (daily data)
    - **Medium**: ~180-280 days (weekly data)
    - **Long**: ~540-720 days (monthly data)
    """)

    # Contract selection
    col1, col2, col3 = st.columns([2, 2, 4])

    with col1:
        # Group contracts by category
        categories = sorted(list(set([c['category'] for c in contracts.values()])))
        selected_category = st.selectbox(
            "📂 Category",
            categories,
            index=categories.index('Currencies') if 'Currencies' in categories else 0
        )

    with col2:
        # Filter contracts by category
        category_contracts = {k: v for k, v in contracts.items() if v['category'] == selected_category}

        # Get contract names for display
        contract_options = {f"{k} - {v['name']}": k for k, v in category_contracts.items()}
        contract_display = st.selectbox(
            "📊 Contract",
            list(contract_options.keys())
        )
        selected_contract = contract_options[contract_display]

    with col3:
        forecast_months = st.slider(
            "🔮 Forecast Horizon (months)",
            min_value=1,
            max_value=12,
            value=6,
            help="Number of months to forecast forward"
        )

    # Get ticker for selected contract
    if selected_contract not in price_tickers:
        st.warning(f"⚠️ No price ticker mapping found for {selected_contract}")
        return

    ticker = price_tickers[selected_contract]
    contract_name = contracts[selected_contract]['name']

    st.markdown("---")

    # Run forecast button
    if st.button("🚀 Generate Cycle Forecast", type="primary", use_container_width=True):
        with st.spinner(f"Analyzing {contract_name} cycles and finding historical patterns..."):
            try:
                # Import here to avoid loading dependencies until needed
                from src.analysis.cot_positioning.calculations.cycle_forecast import create_cycle_forecast

                # Create forecast
                forecast_days = forecast_months * 30

                st.info(f"📊 Fetching data for {ticker}...")
                result = create_cycle_forecast(ticker, forecast_days=forecast_days, lookback_years=20)

                # Store in session state
                st.session_state['cycle_forecast'] = result
                st.session_state['cycle_contract'] = selected_contract
                st.session_state['cycle_contract_name'] = contract_name

                st.success(f"✅ Forecast generated for {contract_name}")
                st.rerun()  # Force refresh to show results

            except Exception as e:
                st.error(f"❌ Error generating forecast: {str(e)}")
                st.error(f"**Ticker:** {ticker}")
                st.error(f"**Contract:** {selected_contract} - {contract_name}")

                # Show detailed error in expander
                with st.expander("🔍 Show Error Details"):
                    st.code(str(e))
                    import traceback
                    st.code(traceback.format_exc())

                logger.error(f"Cycle forecast error for {ticker}: {str(e)}", exc_info=True)
                return

    # Display results if available
    if 'cycle_forecast' in st.session_state:
        if st.session_state.get('cycle_contract') == selected_contract:
            display_cycle_forecast(
                st.session_state['cycle_forecast'],
                st.session_state['cycle_contract_name']
            )
        else:
            st.info(f"💡 Forecast available for **{st.session_state.get('cycle_contract_name', 'previous contract')}**. Click 'Generate Cycle Forecast' to analyze **{contract_name}**.")


def display_cycle_forecast(result, contract_name):
    """Display the cycle forecast results"""

    if result is None:
        st.error("❌ No forecast data available")
        return

    st.markdown("---")
    st.subheader(f"📊 Cycle Forecast Results: {contract_name}")

    # Debug info (collapsible)
    with st.expander("🔍 Data Info", expanded=False):
        st.write(f"**Ticker:** {result.get('ticker', 'N/A')}")
        st.write(f"**Data points:** {len(result.get('df_daily', []))} days")
        st.write(f"**Cycles extracted:** {', '.join(result.get('cycles', {}).keys())}")

        st.write("\n**Forecast Status:**")
        for cycle_type in ['short', 'medium', 'long']:
            if cycle_type in result.get('forecasts', {}):
                fc = result['forecasts'][cycle_type]
                st.write(f"  - {cycle_type.capitalize()}: {fc.get('forecast_len', 0)} days, "
                        f"{len(fc.get('matches', []))} matches, "
                        f"{len(fc.get('peaks', []))} peaks, {len(fc.get('troughs', []))} troughs")

    # Current position info
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Current Price", f"{result['last_price']:.4f}")
    with col2:
        st.metric("Last Update", result['last_date'].strftime('%Y-%m-%d'))
    with col3:
        st.metric("Forecast Horizon", f"{result['forecast_days']} days")
    with col4:
        forecast_end = result['forecast_dates'][-1] if len(result['forecast_dates']) > 0 else result['last_date']
        st.metric("Forecast To", forecast_end.strftime('%Y-%m-%d'))

    # Cycle periods summary
    st.markdown("#### 🔍 Detected Cycle Periods")
    col1, col2, col3 = st.columns(3)

    with col1:
        short = result['cycles']['short']
        st.info(f"**Short Cycle**\n\n{short['period_days']:.1f} days\n\nAmplitude: ±{short['amplitude']*100:.2f}%")

    with col2:
        medium = result['cycles']['medium']
        st.info(f"**Medium Cycle**\n\n{medium['period_days']:.1f} days\n\nAmplitude: ±{medium['amplitude']*100:.2f}%")

    with col3:
        long = result['cycles']['long']
        st.info(f"**Long Cycle**\n\n{long['period_days']:.1f} days\n\nAmplitude: ±{long['amplitude']*100:.2f}%")

    # Visualization
    st.markdown("#### 📈 Interactive Cycle Forecast")

    try:
        fig = create_cycle_forecast_plot(result, contract_name)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"❌ Error creating chart: {str(e)}")
        logger.error(f"Chart creation error: {str(e)}", exc_info=True)
        with st.expander("🔍 Show Chart Error Details"):
            st.code(str(e))
            import traceback
            st.code(traceback.format_exc())

    # Turning points
    st.markdown("#### 🎯 Forecast Turning Points")

    tab1, tab2, tab3 = st.tabs(["Short Cycle", "Medium Cycle", "Long Cycle"])

    with tab1:
        display_turning_points(result['forecasts']['short'], result['cycles']['short']['period_days'], "Short")

    with tab2:
        display_turning_points(result['forecasts']['medium'], result['cycles']['medium']['period_days'], "Medium")

    with tab3:
        display_turning_points(result['forecasts']['long'], result['cycles']['long']['period_days'], "Long")

    # Pattern matches
    with st.expander("🔎 View Historical Pattern Matches"):
        display_pattern_matches(result)


def create_cycle_forecast_plot(result, contract_name):
    """Create interactive Plotly figure for cycle forecast"""

    # Validate result data
    if not result or 'cycles' not in result:
        raise ValueError("Invalid result data: missing cycles information")

    if 'df_daily' not in result or len(result['df_daily']) == 0:
        raise ValueError("Invalid result data: no price data available")

    # Create subplots: 3 rows for short, medium, long
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(
            f"Short Cycle ({result['cycles']['short']['period_days']:.0f}d)",
            f"Medium Cycle ({result['cycles']['medium']['period_days']:.0f}d)",
            f"Long Cycle ({result['cycles']['long']['period_days']:.0f}d)"
        ),
        specs=[[{"secondary_y": True}],
               [{"secondary_y": True}],
               [{"secondary_y": True}]]
    )

    colors = {'short': '#E97451', 'medium': '#2E86AB', 'long': '#A23B72'}

    last_date = result['last_date']
    df_display = result['df_daily']

    # Plot each cycle
    for idx, (cycle_type, row) in enumerate([('short', 1), ('medium', 2), ('long', 3)], 1):
        cycle_data = result['cycles'][cycle_type]
        forecast_data = result['forecasts'][cycle_type]

        # Historical price (secondary y-axis)
        fig.add_trace(
            go.Scatter(
                x=df_display.index,
                y=np.log(df_display['Close']),
                name=f'ln(Price)',
                line=dict(color='white', width=2.5),
                showlegend=(row == 1),
                legendgroup='price'
            ),
            row=row, col=1, secondary_y=True
        )

        # Historical cycle (primary y-axis)
        hist_cycle = forecast_data['hist_cycle']
        norm_factor = forecast_data['norm_factor']
        hist_norm = hist_cycle / norm_factor

        fig.add_trace(
            go.Scatter(
                x=hist_norm.index,
                y=hist_norm.values,
                name=f'Historical Cycle',
                line=dict(color=colors[cycle_type], width=2.5),
                showlegend=(row == 1),
                legendgroup='hist_cycle'
            ),
            row=row, col=1, secondary_y=False
        )

        # Forecast start line
        fig.add_vline(
            x=last_date,
            line_dash="dash",
            line_color="red",
            opacity=0.5,
            row=row, col=1
        )

        # Forecast bounds and mean
        if forecast_data['forecast_len'] > 0:
            # Use the properly sliced forecast_dates from forecast_data
            cycle_forecast_dates = forecast_data['forecast_dates']

            if cycle_type in ['short', 'medium']:
                # Check if we have valid forecast data
                if (forecast_data['mean_forecast'] is not None and
                    forecast_data['upper_bound'] is not None and
                    forecast_data['lower_bound'] is not None and
                    len(cycle_forecast_dates) > 0):

                    # Shaded bounds
                    fig.add_trace(
                        go.Scatter(
                            x=list(cycle_forecast_dates) + list(cycle_forecast_dates[::-1]),
                            y=list(forecast_data['upper_bound']) + list(forecast_data['lower_bound'][::-1]),
                            fill='toself',
                            fillcolor=colors[cycle_type],
                            opacity=0.2,
                            line=dict(width=0),
                            name='2nd Extreme Bounds',
                            showlegend=(row == 1),
                            legendgroup='bounds'
                        ),
                        row=row, col=1, secondary_y=False
                    )

                    # Mean forecast
                    fig.add_trace(
                        go.Scatter(
                            x=cycle_forecast_dates,
                            y=forecast_data['mean_forecast'],
                            name='Mean Forecast',
                            line=dict(color='gold', width=3),
                            showlegend=(row == 1),
                            legendgroup='mean'
                        ),
                        row=row, col=1, secondary_y=False
                    )
                else:
                    # No forecast available - add annotation
                    fig.add_annotation(
                        text="Insufficient historical patterns for forecast",
                        xref="x domain", yref="y domain",
                        x=0.5, y=0.5,
                        showarrow=False,
                        font=dict(size=12, color="gray"),
                        row=row, col=1
                    )

            else:  # Long cycle - show individual analogs
                # Use the properly sliced forecast_dates from forecast_data
                cycle_forecast_dates = forecast_data.get('forecast_dates', [])

                if forecast_data['projections'] and len(forecast_data['projections']) > 0:
                    for i, proj in enumerate(forecast_data['projections']):
                        if proj['length'] > 0 and len(cycle_forecast_dates) >= proj['length']:
                            analog_dates = cycle_forecast_dates[:proj['length']]
                            analog_norm = proj['analog'] / norm_factor
                            fig.add_trace(
                                go.Scatter(
                                    x=analog_dates,
                                    y=analog_norm,
                                    name=f'Analog {i+1}' if row == 3 and i == 0 else None,
                                    line=dict(color=colors[cycle_type], width=2, dash='dash'),
                                    opacity=0.4,
                                    showlegend=(row == 3 and i == 0),
                                    legendgroup='analogs'
                                ),
                                row=row, col=1, secondary_y=False
                            )

                # Mean forecast
                if (forecast_data['mean_forecast'] is not None and
                    forecast_data['forecast_len'] > 0 and
                    len(cycle_forecast_dates) > 0):
                    fig.add_trace(
                        go.Scatter(
                            x=cycle_forecast_dates,
                            y=forecast_data['mean_forecast'],
                            name='Mean Forecast',
                            line=dict(color='gold', width=3),
                            showlegend=(row == 3),
                            legendgroup='mean'
                        ),
                        row=row, col=1, secondary_y=False
                    )
                else:
                    # No forecast available - add annotation
                    fig.add_annotation(
                        text="Insufficient historical patterns for forecast",
                        xref="x domain", yref="y domain",
                        x=0.5, y=0.5,
                        showarrow=False,
                        font=dict(size=12, color="gray"),
                        row=row, col=1
                    )

        # Zero line
        fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.3, row=row, col=1)

        # Update y-axes
        fig.update_yaxes(title_text="Cycle Amplitude", row=row, col=1, secondary_y=False, range=[-1.5, 1.5])
        fig.update_yaxes(title_text="ln(Price)", row=row, col=1, secondary_y=True)

    # Update layout
    fig.update_xaxes(title_text="Date", row=3, col=1)
    fig.update_layout(
        height=1200,
        title_text=f"{contract_name} - Multi-Granularity Cycle Forecast",
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    return fig


def display_turning_points(forecast_data, period, cycle_name):
    """Display peaks and troughs for a cycle"""

    peaks = forecast_data.get('peaks', [])
    troughs = forecast_data.get('troughs', [])

    # Check if forecast exists
    if forecast_data.get('forecast_len', 0) == 0:
        st.warning(f"⚠️ No forecast generated for {cycle_name} cycle - insufficient historical patterns")
        return

    if not peaks and not troughs:
        st.info(f"ℹ️ No clear turning points detected in {cycle_name} forecast (cycle may be trending)")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**⬆️ Peaks ({len(peaks)})**")
        if peaks:
            for date, amplitude in peaks:
                st.write(f"📅 {date.strftime('%Y-%m-%d')} | Amplitude: {amplitude:+.3f}")
        else:
            st.write("No peaks detected")

    with col2:
        st.markdown(f"**⬇️ Troughs ({len(troughs)})**")
        if troughs:
            for date, amplitude in troughs:
                st.write(f"📅 {date.strftime('%Y-%m-%d')} | Amplitude: {amplitude:+.3f}")
        else:
            st.write("No troughs detected")

    # Summary
    if peaks and troughs:
        next_turn = None
        if peaks and troughs:
            next_peak = min(peaks, key=lambda x: x[0])[0]
            next_trough = min(troughs, key=lambda x: x[0])[0]
            if next_peak < next_trough:
                next_turn = ("Peak", next_peak, max(peaks, key=lambda x: x[1])[1])
            else:
                next_turn = ("Trough", next_trough, min(troughs, key=lambda x: x[1])[1])

        if next_turn:
            turn_type, turn_date, turn_amp = next_turn
            st.success(f"**Next Expected {turn_type}:** {turn_date.strftime('%Y-%m-%d')} (Amplitude: {turn_amp:+.3f})")


def display_pattern_matches(result):
    """Display information about historical pattern matches"""

    for cycle_type in ['short', 'medium', 'long']:
        st.markdown(f"**{cycle_type.capitalize()} Cycle - Top 5 Historical Matches**")

        matches = result['forecasts'][cycle_type]['matches']
        df_daily = result['df_daily']

        if not matches:
            st.info(f"No matches found for {cycle_type} cycle")
            continue

        match_data = []
        for i, match in enumerate(matches, 1):
            start_date = df_daily.index[0]  # Note: matches use full data indices
            # We need to reconstruct dates from the original data
            # For display purposes, just show correlation
            match_data.append({
                'Rank': i,
                'Correlation': f"{match['correlation']:.3f}",
                'Quality': '⭐⭐⭐' if match['correlation'] > 0.9 else ('⭐⭐' if match['correlation'] > 0.8 else '⭐')
            })

        st.dataframe(pd.DataFrame(match_data), use_container_width=True, hide_index=True)

    st.markdown("""
    **Correlation Quality:**
    - ⭐⭐⭐ Excellent (>0.90): Very similar historical pattern
    - ⭐⭐ Good (0.80-0.90): Strong similarity
    - ⭐ Fair (<0.80): Moderate similarity
    """)
