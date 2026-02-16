"""
CFTC CoT Positioning Dashboard - Streamlit App (Modularized)
Interactive web-based dashboard for analyzing commercial trader positioning
"""
import streamlit as st
import os
import sys
import logging
from datetime import datetime
from functools import wraps
import time

# Setup logging
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_FILE = os.path.join(PROJECT_ROOT, 'tools', 'streamlit_dashboard.log')

# Configure logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Decorator for function timing and entry/exit logging
def log_function(func):
    """Decorator to log function entry/exit and execution time"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.info(f">>> Entering {func_name}()")
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"<<< Exiting {func_name}() - Completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"<<< ERROR in {func_name}() after {elapsed:.2f}s: {str(e)}")
            raise
    return wrapper

# Log startup
logger.info("="*80)
logger.info("STREAMLIT DASHBOARD STARTING (Modularized)")
logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"Log file: {LOG_FILE}")
logger.info(f"Project root: {PROJECT_ROOT}")
logger.info("="*80)

# Set page config (must be first Streamlit command)
st.set_page_config(
    page_title="CoT Positioning Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add project root to path
sys.path.insert(0, PROJECT_ROOT)

# Import modular components
from src.analysis.cot_positioning.config.contracts import CONTRACTS, PRICE_TICKERS
from src.analysis.cot_positioning.views.positioning import render_positioning_view
from src.analysis.cot_positioning.views.macro import render_macro_view
from src.analysis.cot_positioning.views.technical import render_technical_view


@log_function
def main():
    """Main application entry point"""
    st.title("📊 CFTC Commitments of Traders - Analysis Dashboard")

    try:
        # Initialize session state first
        if 'active_section' not in st.session_state:
            st.session_state.active_section = "positioning"

        # Navigation buttons for different sections
        st.markdown("---")
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

        with col1:
            if st.button("📈 **Futures Positioning**", use_container_width=True,
                        type="primary" if st.session_state.active_section == "positioning" else "secondary",
                        key="nav_positioning"):
                if st.session_state.active_section != "positioning":
                    st.session_state.active_section = "positioning"
                    st.rerun()
        with col2:
            if st.button("🌍 **Macro**", use_container_width=True,
                        type="primary" if st.session_state.active_section == "macro" else "secondary",
                        key="nav_macro"):
                if st.session_state.active_section != "macro":
                    st.session_state.active_section = "macro"
                    st.rerun()
        with col3:
            if st.button("🔧 **Technical**", use_container_width=True,
                        type="primary" if st.session_state.active_section == "technical" else "secondary",
                        key="nav_technical"):
                if st.session_state.active_section != "technical":
                    st.session_state.active_section = "technical"
                    st.rerun()
        with col4:
            if st.button("📊 **More Analysis**", use_container_width=True,
                        type="primary" if st.session_state.active_section == "more_analysis" else "secondary",
                        key="nav_more"):
                if st.session_state.active_section != "more_analysis":
                    st.session_state.active_section = "more_analysis"
                    st.rerun()

        st.markdown("---")

        # Render the active section
        if st.session_state.active_section == "positioning":
            render_positioning_view(CONTRACTS, PROJECT_ROOT)

        elif st.session_state.active_section == "macro":
            render_macro_view(PROJECT_ROOT)

        elif st.session_state.active_section == "technical":
            render_technical_view(CONTRACTS, PRICE_TICKERS, PROJECT_ROOT)

        elif st.session_state.active_section == "more_analysis":
            st.header("📊 More Analysis")
            st.info("🚧 Additional analysis tools coming soon...")
            st.markdown("""
            Future additions:
            - Historical backtests of positioning signals
            - Seasonal patterns analysis
            - Cross-market correlations
            - Custom screeners and alerts
            """)

    except Exception as e:
        logger.error(f"Error in main(): {str(e)}", exc_info=True)
        st.error(f"An error occurred: {str(e)}")
        st.info(f"Check log file for details: {LOG_FILE}")


if __name__ == "__main__":
    main()
