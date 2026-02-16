"""
Futures positioning dashboard view
Main view for CFTC COT positioning analysis
"""
import streamlit as st
import pandas as pd
import time
import logging
import numpy as np
import hashlib

from components.sidebar import render_sidebar
from components.contracts_table import render_contracts_table
from components.groups_view import render_groups_view
from components.individual_charts import render_individual_charts
from calculations.cot_indicators import calculate_positioning
from data.loader import load_cftc_data, fetch_price_data

logger = logging.getLogger(__name__)


def calculate_all_positioning_internal(df, contracts_dict):
    """
    Calculate positioning for all contracts - internal function

    Args:
        df: CFTC dataframe
        contracts_dict: Dictionary of contract configurations

    Returns:
        dict: Results for all contracts
    """
    logger.info("="*60)
    logger.info(f"⚠️ CALCULATING POSITIONING FOR {len(contracts_dict)} CONTRACTS (FRESH CALCULATION)")
    logger.info("="*60)

    results = {}
    start_time = time.time()

    for idx, (code, info) in enumerate(contracts_dict.items(), 1):
        logger.info(f"[{idx}/{len(contracts_dict)}] Processing {code} - {info['name']}...")
        data = calculate_positioning(df, info['cftc_name'])
        if data:
            results[code] = {**data, 'info': info}
            logger.info(f"  ✓ {code} completed")
        else:
            logger.warning(f"  ✗ {code} failed - no data returned")

    elapsed = time.time() - start_time
    logger.info("="*60)
    logger.info(f"✓ POSITIONING CALCULATION COMPLETE")
    logger.info(f"  Success: {len(results)}/{len(contracts_dict)} contracts")
    logger.info(f"  Time: {elapsed:.2f}s ({elapsed/len(contracts_dict):.2f}s per contract)")
    logger.info("="*60)

    return results


def get_cached_positioning(df, df_hash, contracts):
    """
    Get positioning results from session state cache or calculate if needed

    Args:
        df: CFTC dataframe
        df_hash: Hash of the dataframe
        contracts: Dictionary of contract configurations

    Returns:
        dict: Results for all contracts
    """
    # Initialize cache in session state
    if 'positioning_cache' not in st.session_state:
        st.session_state.positioning_cache = {}

    cache_key = f"positioning_{df_hash}"

    # Check if results are cached
    if cache_key in st.session_state.positioning_cache:
        logger.info("✅ USING CACHED POSITIONING RESULTS")
        return st.session_state.positioning_cache[cache_key]

    # Calculate fresh results
    results = calculate_all_positioning_internal(df, contracts)

    # Store in cache
    st.session_state.positioning_cache[cache_key] = results

    # Keep only the latest cache (clear old ones)
    if len(st.session_state.positioning_cache) > 2:
        old_keys = list(st.session_state.positioning_cache.keys())[:-1]
        for old_key in old_keys:
            del st.session_state.positioning_cache[old_key]
        logger.info("🗑️ Cleared old cache entries")

    return results


def render_positioning_view(contracts, project_root):
    """
    Render the futures positioning dashboard view

    Args:
        contracts: Dictionary of contract configurations
        project_root: Path to project root directory
    """
    logger.info("="*80)
    logger.info("RENDER_POSITIONING_VIEW CALLED - NEW CODE VERSION WITH TIMING")
    logger.info("="*80)

    import time
    view_start = time.time()

    # Sidebar controls
    logger.info("[TIMING] Starting sidebar render...")
    sidebar_start = time.time()
    trader_category, category_filter = render_sidebar(contracts, project_root)
    logger.info(f"[TIMING] Sidebar completed in {time.time() - sidebar_start:.3f}s")

    st.markdown("**Futures Positioning Analysis Across 41 Contracts**")
    st.markdown(f"*Showing {trader_category} positioning with lookback analysis*")

    # Load data
    logger.info("[TIMING] Starting CFTC data load...")
    data_load_start = time.time()
    with st.spinner("Loading CFTC data..."):
        df = load_cftc_data()
    logger.info(f"[TIMING] CFTC data load completed in {time.time() - data_load_start:.3f}s")

    if df is None:
        logger.error("Failed to load CFTC data")
        st.error("Failed to load data. Please check that data files exist.")
        return

    logger.info(f"Successfully loaded {len(df):,} records from CFTC")

    # Create a hash of the dataframe for cache key (using standardized Date column)
    logger.info("[TIMING] Creating dataframe hash...")
    hash_start = time.time()
    df_hash = hashlib.md5(f"{len(df)}_{df['Date'].min()}_{df['Date'].max()}".encode()).hexdigest()
    logger.info(f"[TIMING] Hash created in {time.time() - hash_start:.3f}s | Hash: {df_hash[:12]}...")

    # Get positioning results (from cache if available)
    logger.info("[TIMING] Getting positioning results (checking cache)...")
    positioning_start = time.time()
    results = get_cached_positioning(df, df_hash, contracts)
    logger.info(f"[TIMING] Positioning results obtained in {time.time() - positioning_start:.3f}s")

    if not results:
        logger.error("Failed to calculate positioning")
        st.error("Failed to calculate positioning data.")
        return

    # Show success message (cache status shown in logs)
    st.success(f"✅ Loaded {len(df):,} records | Processed {len(results)} contracts")

    # Map trader category to data key
    # Handle case where trader_category might be int (Streamlit state bug)
    if isinstance(trader_category, int):
        trader_options_list = ['Commercial', 'Non-Commercial', 'Non-Reportable']
        trader_category = trader_options_list[trader_category]
        logger.warning(f"trader_category was int, converted to: {trader_category}")

    category_key = trader_category.lower().replace('-', '')
    logger.info(f"Using category key: {category_key}")

    # Copy results for charts (no recalculation needed)
    logger.info("[TIMING] Preparing results for display...")
    filter_start = time.time()
    results_for_charts = dict(results)

    # Filter for charts
    if 'All' not in category_filter and len(category_filter) > 0:
        results_for_charts = {k: v for k, v in results_for_charts.items() if v['info']['category'] in category_filter}

    # Filter by category
    if 'All' not in category_filter and len(category_filter) > 0:
        before_filter = len(results)
        results = {k: v for k, v in results.items() if v['info']['category'] in category_filter}
        logger.info(f"Filtered from {before_filter} to {len(results)} contracts")
    logger.info(f"[TIMING] Filtering completed in {time.time() - filter_start:.3f}s")

    # Check if any results
    if len(results) == 0:
        st.warning(f"⚠️ No contracts available with selected filters")
    else:
        # Create sub-tabs for All Contracts and Group
        logger.info("[TIMING] Starting tabs rendering...")
        tabs_start = time.time()
        subtab_all, subtab_group = st.tabs(["📊 All Contracts", "📈 Group"])

        with subtab_all:
            table_start = time.time()
            render_contracts_table(results, trader_category, category_key)
            logger.info(f"[TIMING] Contracts table rendered in {time.time() - table_start:.3f}s")

        with subtab_group:
            group_start = time.time()
            render_groups_view(results, trader_category, category_key)
            logger.info(f"[TIMING] Groups view rendered in {time.time() - group_start:.3f}s")

        logger.info(f"[TIMING] Tabs completed in {time.time() - tabs_start:.3f}s")

    # Individual contract charts
    logger.info("[TIMING] Starting individual charts rendering...")
    charts_start = time.time()
    render_individual_charts(results_for_charts, contracts, fetch_price_data, trader_category, category_key)
    logger.info(f"[TIMING] Individual charts completed in {time.time() - charts_start:.3f}s")

    # Final summary logging
    total_time = time.time() - view_start
    logger.info("="*60)
    logger.info(f"[TIMING] TOTAL VIEW RENDER TIME: {total_time:.3f}s")
    logger.info("="*60)
    logger.info("DASHBOARD RENDERING COMPLETE")
    logger.info(f"  - Trader category: {trader_category}")
    logger.info(f"  - Contracts displayed: {len(results_for_charts)}")
    logger.info(f"  - Asset filters: {category_filter}")

    # Count extremes for final summary
    extreme_longs = sum(1 for d in results_for_charts.values() if d[category_key]['cot_index_75w'] >= 95)
    extreme_shorts = sum(1 for d in results_for_charts.values() if d[category_key]['cot_index_75w'] <= 5)
    avg_z = np.mean([d[category_key]['cot_zscore'] for d in results_for_charts.values()])

    logger.info(f"  - Extreme Longs ({trader_category}, Index75w >= 95): {extreme_longs}")
    logger.info(f"  - Extreme Shorts ({trader_category}, Index75w <= 5): {extreme_shorts}")
    logger.info(f"  - Average Z-Score ({trader_category}): {avg_z:.2f}")
    logger.info("="*60)
