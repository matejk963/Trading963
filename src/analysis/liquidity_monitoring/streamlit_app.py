"""
Global Liquidity Monitoring Dashboard
Main Streamlit application entry point

Based on Michael Howell's 3-layer Global Liquidity Index framework
(Capital Wars, 2020)

Run with: streamlit run src/analysis/liquidity_monitoring/streamlit_app.py
"""
import streamlit as st
import os
import sys
import logging
from pathlib import Path

# Setup path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Global Liquidity Monitor",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Imports after path setup
from data.loader import load_liquidity_data, get_data_freshness
from liquidity_updater import update_liquidity_data, get_update_status
from views.dashboard import render_dashboard
from views.layer_detail import render_layer_detail
from views.asset_overlay import render_asset_overlay
from views.transmission_chain_view import render_transmission_chain


def main():
    """Main application entry point"""

    # ========== SIDEBAR ==========
    with st.sidebar:
        st.title("💧 Liquidity Monitor")
        st.markdown("---")

        # Data status
        st.subheader("📊 Data Status")
        status = get_update_status()

        if status.get('has_data'):
            st.success(status['message'])
            st.caption(f"Series: {status.get('series_count', 'N/A')}")
            st.caption(f"Records: {status.get('record_count', 'N/A')}")
        else:
            st.warning(status['message'])

        # Update button
        st.markdown("---")
        if st.button("🔄 Update Data", use_container_width=True):
            with st.spinner("Fetching data from FRED..."):
                result = update_liquidity_data()

                if result['success']:
                    st.success(f"✓ {result['message']}")
                    if result.get('new_records'):
                        st.info(f"Added {result['new_records']} new records")
                    if result.get('failed_series'):
                        st.warning(f"Failed: {result['failed_series']}")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(result['message'])

        # Framework info
        st.markdown("---")
        st.subheader("ℹ️ About")

        with st.expander("Framework Overview"):
            st.markdown("""
            **3-Layer Liquidity Framework**

            Based on Michael Howell's *Capital Wars* (2020):

            1. **Layer 1 - CB Liquidity**
               - Fed Balance Sheet
               - Net Liquidity (BS - TGA - RRP)
               - Real Policy Rate
               - Yield Curve

            2. **Layer 2a - Private/Wholesale**
               - Bank Credit
               - M2 Money Supply
               - Credit Spreads
               - Dollar Strength
               - VIX / NFCI

            3. **Layer 2b - Economic Reality**
               - Capacity Utilization
               - Industrial Production
               - Unemployment
               - Inflation Momentum

            *Layer 2b uses counterintuitive scoring:
            weak economy = CB eases = bullish*
            """)

        with st.expander("Scoring Convention"):
            st.markdown("""
            **Per-Indicator Scoring:**
            - **+1** = Bullish for liquidity
            - **0** = Neutral
            - **-1** = Bearish for liquidity

            **Composite Weights:**
            - L1 (CB): 40%
            - L2a (Private): 35%
            - L2b (Economy): 25%

            **Regime Classification:**
            Based on direction (+/-) of each layer.
            Example: (+,+,+) = Early Cycle - Max Bullish
            """)

        st.markdown("---")
        st.caption("Data Source: FRED API")
        st.caption(f"v1.0 | US-Only")

    # ========== MAIN CONTENT ==========

    # Load data
    data_result = load_liquidity_data()
    raw_data = data_result.get('raw_data')

    if raw_data is None:
        st.warning("No data available. Click 'Update Data' in the sidebar to fetch from FRED.")
        st.info("""
        **First-time setup:**
        1. Ensure you have a FRED API key in `data/fred_api_key.txt`
        2. Click the 'Update Data' button in the sidebar
        3. Wait for data to download (~30 seconds)

        Get a free FRED API key at: https://fred.stlouisfed.org/docs/api/api_key.html
        """)
        return

    # Navigation tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Dashboard", "🔍 Layer Details", "📈 Asset Overlay", "🔗 Transmission Chain"
    ])

    with tab1:
        render_dashboard(raw_data, PROJECT_ROOT)

    with tab2:
        render_layer_detail(raw_data, PROJECT_ROOT)

    with tab3:
        render_asset_overlay(raw_data, PROJECT_ROOT)

    with tab4:
        render_transmission_chain(raw_data, PROJECT_ROOT)


if __name__ == "__main__":
    main()
