"""
CFTC CoT Positioning Dashboard - Streamlit App
Interactive web-based dashboard for analyzing commercial trader positioning
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import os
import sys
import logging
import traceback
import time
from functools import wraps

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
logger.info("STREAMLIT DASHBOARD STARTING")
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

# Contract metadata
CONTRACTS = {
    # Currencies
    'DXY': {'name': 'DOLLAR INDEX (Combined)', 'category': 'Currencies', 'cftc_name': 'AGGREGATE_CURRENCIES'},  # Special aggregate
    '6E': {'name': 'EURO FX', 'category': 'Currencies', 'cftc_name': 'EURO FX - CHICAGO MERCANTILE EXCHANGE'},
    '6J': {'name': 'JAPANESE YEN', 'category': 'Currencies', 'cftc_name': 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE'},
    '6B': {'name': 'BRITISH POUND', 'category': 'Currencies', 'cftc_name': ['BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE', 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE']},
    '6C': {'name': 'CANADIAN DOLLAR', 'category': 'Currencies', 'cftc_name': 'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6S': {'name': 'SWISS FRANC', 'category': 'Currencies', 'cftc_name': 'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE'},
    '6A': {'name': 'AUSTRALIAN DOLLAR', 'category': 'Currencies', 'cftc_name': 'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6N': {'name': 'NEW ZEALAND DOLLAR', 'category': 'Currencies', 'cftc_name': 'NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6L': {'name': 'BRAZILIAN REAL', 'category': 'Currencies', 'cftc_name': 'BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE'},

    # Indices
    'ES': {'name': 'S&P 500', 'category': 'Indices', 'cftc_name': 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'},
    'NQ': {'name': 'NASDAQ 100', 'category': 'Indices', 'cftc_name': 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'},
    'YM': {'name': 'DOW JONES', 'category': 'Indices', 'cftc_name': 'DJIA Consolidated - CHICAGO BOARD OF TRADE'},
    'RTY': {'name': 'RUSSELL 2000', 'category': 'Indices', 'cftc_name': 'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE'},
    'VX': {'name': 'VIX', 'category': 'Indices', 'cftc_name': 'VIX FUTURES - CBOE FUTURES EXCHANGE'},

    # Energy
    'CL': {'name': 'CRUDE OIL WTI', 'category': 'Energy', 'cftc_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE'},
    'BZ': {'name': 'CRUDE OIL BRENT', 'category': 'Energy', 'cftc_name': 'BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE'},
    'NG': {'name': 'NATURAL GAS', 'category': 'Energy', 'cftc_name': 'NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE'},
    'RB': {'name': 'RBOB GASOLINE', 'category': 'Energy', 'cftc_name': 'GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE'},
    'HO': {'name': 'HEATING OIL', 'category': 'Energy', 'cftc_name': 'NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE'},

    # Metals
    'GC': {'name': 'GOLD', 'category': 'Metals', 'cftc_name': 'GOLD - COMMODITY EXCHANGE INC.'},
    'SI': {'name': 'SILVER', 'category': 'Metals', 'cftc_name': 'SILVER - COMMODITY EXCHANGE INC.'},
    'HG': {'name': 'COPPER', 'category': 'Metals', 'cftc_name': 'COPPER- #1 - COMMODITY EXCHANGE INC.'},
    'PL': {'name': 'PLATINUM', 'category': 'Metals', 'cftc_name': 'PLATINUM - NEW YORK MERCANTILE EXCHANGE'},
    'PA': {'name': 'PALLADIUM', 'category': 'Metals', 'cftc_name': 'PALLADIUM - NEW YORK MERCANTILE EXCHANGE'},

    # Grains
    'ZC': {'name': 'CORN', 'category': 'Grains', 'cftc_name': 'CORN - CHICAGO BOARD OF TRADE'},
    'ZW': {'name': 'WHEAT', 'category': 'Grains', 'cftc_name': 'WHEAT - CHICAGO BOARD OF TRADE'},
    'ZS': {'name': 'SOYBEANS', 'category': 'Grains', 'cftc_name': 'SOYBEANS - CHICAGO BOARD OF TRADE'},
    'ZM': {'name': 'SOYBEAN MEAL', 'category': 'Grains', 'cftc_name': 'SOYBEAN MEAL - CHICAGO BOARD OF TRADE'},
    'ZL': {'name': 'SOYBEAN OIL', 'category': 'Grains', 'cftc_name': 'SOYBEAN OIL - CHICAGO BOARD OF TRADE'},
    'ZO': {'name': 'OAT', 'category': 'Grains', 'cftc_name': 'OATS - CHICAGO BOARD OF TRADE'},
    'ZR': {'name': 'ROUGH RICE', 'category': 'Grains', 'cftc_name': 'ROUGH RICE - CHICAGO BOARD OF TRADE'},

    # Softs
    'KC': {'name': 'COFFEE', 'category': 'Softs', 'cftc_name': 'COFFEE C - ICE FUTURES U.S.'},
    'SB': {'name': 'SUGAR', 'category': 'Softs', 'cftc_name': 'SUGAR NO. 11 - ICE FUTURES U.S.'},
    'CC': {'name': 'COCOA', 'category': 'Softs', 'cftc_name': 'COCOA - ICE FUTURES U.S.'},
    'CT': {'name': 'COTTON', 'category': 'Softs', 'cftc_name': 'COTTON NO. 2 - ICE FUTURES U.S.'},
    'OJ': {'name': 'ORANGE JUICE', 'category': 'Softs', 'cftc_name': 'FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.'},
    'LBS': {'name': 'LUMBER', 'category': 'Softs', 'cftc_name': 'RANDOM LENGTH LUMBER - CHICAGO MERCANTILE EXCHANGE'},

    # Meats
    'LE': {'name': 'LIVE CATTLE', 'category': 'Meats', 'cftc_name': 'LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'GF': {'name': 'FEEDER CATTLE', 'category': 'Meats', 'cftc_name': 'FEEDER CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'HE': {'name': 'LEAN HOGS', 'category': 'Meats', 'cftc_name': 'LEAN HOGS - CHICAGO MERCANTILE EXCHANGE'},

    # Bonds (ordered by maturity: 2Y, 5Y, 10Y, 30Y, Ultra 10Y, Ultra 30Y)
    'ZT': {'name': '2-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 2Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 1},
    'ZF': {'name': '5-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 5Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 2},
    'ZN': {'name': '10-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 10Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 3},
    'ZB': {'name': '30-YEAR BOND', 'category': 'Bonds', 'cftc_name': 'UST BOND - CHICAGO BOARD OF TRADE', 'sort_order': 4},
    'TN': {'name': 'ULTRA 10-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'ULTRA UST 10Y - CHICAGO BOARD OF TRADE', 'sort_order': 5},
    'UB': {'name': 'ULTRA 30-YEAR BOND', 'category': 'Bonds', 'cftc_name': 'ULTRA UST BOND - CHICAGO BOARD OF TRADE', 'sort_order': 6},
}

@st.cache_data(ttl=3600)
@log_function
def load_cftc_data():
    """Load CFTC data from combined file"""
    try:
        data_file = os.path.join(PROJECT_ROOT, 'data', 'cftc', 'legacy_long_format_combined_2005_2025.csv')

        logger.info(f"Loading CFTC data from: {data_file}")
        logger.info(f"File exists: {os.path.exists(data_file)}")
        if os.path.exists(data_file):
            file_size_mb = os.path.getsize(data_file) / (1024 * 1024)
            logger.info(f"File size: {file_size_mb:.2f} MB")

        if not os.path.exists(data_file):
            error_msg = f"Data file not found: {data_file}"
            logger.error(error_msg)
            st.error(error_msg)
            return None

        logger.info("Reading CSV file...")
        df = pd.read_csv(data_file)
        logger.info(f"✓ Loaded {len(df):,} records")
        logger.info(f"✓ Dataframe shape: {df.shape} (rows × columns)")
        logger.info(f"✓ Memory usage: {df.memory_usage(deep=True).sum() / (1024**2):.2f} MB")
        logger.info(f"Columns ({len(df.columns)}): {df.columns.tolist()[:10]}...")  # First 10 cols

        # Normalize column names: remove parentheses
        # Convert "Commercial_Positions-Long_(All)" → "Commercial_Positions-Long_All"
        df.columns = [col.replace('_(All)', '_All').replace('_(Old)', '_Old').replace('(', '').replace(')', '')
                      for col in df.columns]

        # Handle duplicate columns (some files have both normalized and unnormalized names)
        # Keep only the first occurrence of each column
        df = df.loc[:, ~df.columns.duplicated()]
        logger.info(f"✓ Normalized column names (removed parentheses) - {len(df.columns)} unique columns")

        # Validate data quality
        null_counts = df.isnull().sum()
        if null_counts.sum() > 0:
            logger.warning(f"Found {null_counts.sum():,} null values across {(null_counts > 0).sum()} columns")
            for col in null_counts[null_counts > 0].head(5).index:
                logger.warning(f"  - {col}: {null_counts[col]:,} nulls")
        else:
            logger.info("✓ No null values found")

        # Use the correct date column
        logger.info("Detecting date column...")
        if 'As_of_Date_in_Form_YYYY-MM-DD' in df.columns:
            logger.info("✓ Using 'As_of_Date_in_Form_YYYY-MM-DD' column")
            # Use format='mixed' to handle both ISO and MM/DD/YYYY formats
            df['Date'] = pd.to_datetime(df['As_of_Date_in_Form_YYYY-MM-DD'], format='mixed', errors='coerce')
        elif 'As of Date in Form YYYY-MM-DD' in df.columns:
            logger.info("✓ Using 'As of Date in Form YYYY-MM-DD' column")
            df['Date'] = pd.to_datetime(df['As of Date in Form YYYY-MM-DD'], format='mixed', errors='coerce')
        elif 'Report_Date_as_MM_DD_YYYY' in df.columns:
            logger.info("✓ Using 'Report_Date_as_MM_DD_YYYY' column")
            df['Date'] = pd.to_datetime(df['Report_Date_as_MM_DD_YYYY'], format='mixed', errors='coerce')
        else:
            error_msg = f"No recognized date column found. Available columns: {df.columns.tolist()}"
            logger.error(f"✗ {error_msg}")
            st.error(error_msg)
            return None

        # Drop rows with invalid dates
        before_drop = len(df)
        df = df.dropna(subset=['Date'])
        after_drop = len(df)
        if before_drop != after_drop:
            logger.warning(f"Dropped {before_drop - after_drop} records with invalid dates")

        # Strip trailing spaces from contract names (issue in older data files)
        if 'Market_and_Exchange_Names' in df.columns:
            df['Market_and_Exchange_Names'] = df['Market_and_Exchange_Names'].str.strip()
        elif 'Market and Exchange Names' in df.columns:
            df['Market and Exchange Names'] = df['Market and Exchange Names'].str.strip()

        logger.info(f"✓ Date range: {df['Date'].min()} to {df['Date'].max()}")
        logger.info(f"✓ Total unique dates: {df['Date'].nunique()}")

        # Validate unique contracts
        unique_contracts = df['Market_and_Exchange_Names'].nunique()
        logger.info(f"✓ Found {unique_contracts} unique contracts in data")

        return df

    except Exception as e:
        error_msg = f"Error loading CFTC data: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        st.error(f"Error loading data: {str(e)}")
        st.code(traceback.format_exc())
        return None

@log_function
def calculate_positioning(df, contract_name, lookback_years):
    """Calculate positioning metrics for a contract - all trader categories

    contract_name can be:
    - A single string: "GOLD - COMMODITY EXCHANGE INC."
    - A list of strings: ["10-YEAR U.S. TREASURY NOTES", "UST 10Y NOTE"] (for contracts with name changes)
    - Special: "AGGREGATE_CURRENCIES" - aggregates all currency contracts
    """
    try:
        # Special handling for AGGREGATE_CURRENCIES
        if contract_name == 'AGGREGATE_CURRENCIES':
            logger.info(f"Processing AGGREGATE_CURRENCIES (summing all currency contracts) with {lookback_years}y lookback")

            # Define all currency contracts to aggregate
            currency_contracts = [
                'EURO FX - CHICAGO MERCANTILE EXCHANGE',
                'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE',
                ['BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE', 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE'],
                'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE',
                'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE',
                'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE',
                'NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE',
            ]

            # Collect all currency data
            all_currency_data = []
            for curr_name in currency_contracts:
                if isinstance(curr_name, list):
                    # Handle contracts with multiple names (like British Pound)
                    for name in curr_name:
                        temp_df = df[df['Market_and_Exchange_Names'] == name].copy()
                        if len(temp_df) > 0:
                            all_currency_data.append(temp_df)
                else:
                    temp_df = df[df['Market_and_Exchange_Names'] == curr_name].copy()
                    if len(temp_df) > 0:
                        all_currency_data.append(temp_df)

            if not all_currency_data:
                logger.warning("✗ No currency data found for aggregation")
                return None

            # Combine all currency data
            combined_df = pd.concat(all_currency_data, ignore_index=True)
            logger.info(f"  - Found {len(combined_df)} total currency records from {len(all_currency_data)} sources")

            # Aggregate by date (sum all positions for each date)
            # NOTE: Long currency positions = SHORT dollar positions, so we REVERSE the positions
            contract_df = combined_df.groupby('As_of_Date_in_Form_YYYY-MM-DD').agg({
                'Open_Interest_All': 'sum',
                'Commercial_Positions-Long_All': 'sum',
                'Commercial_Positions-Short_All': 'sum',
                'Noncommercial_Positions-Long_All': 'sum',
                'Noncommercial_Positions-Short_All': 'sum',
                'Nonreportable_Positions-Long_All': 'sum',
                'Nonreportable_Positions-Short_All': 'sum',
            }).reset_index()

            # REVERSE positions: Long EUR = Short USD, so flip long/short
            # Swap the long and short positions to represent dollar (not foreign currency)
            contract_df['Commercial_Long_Temp'] = contract_df['Commercial_Positions-Long_All'].copy()
            contract_df['Commercial_Positions-Long_All'] = contract_df['Commercial_Positions-Short_All']
            contract_df['Commercial_Positions-Short_All'] = contract_df['Commercial_Long_Temp']

            contract_df['Noncommercial_Long_Temp'] = contract_df['Noncommercial_Positions-Long_All'].copy()
            contract_df['Noncommercial_Positions-Long_All'] = contract_df['Noncommercial_Positions-Short_All']
            contract_df['Noncommercial_Positions-Short_All'] = contract_df['Noncommercial_Long_Temp']

            contract_df['Nonreportable_Long_Temp'] = contract_df['Nonreportable_Positions-Long_All'].copy()
            contract_df['Nonreportable_Positions-Long_All'] = contract_df['Nonreportable_Positions-Short_All']
            contract_df['Nonreportable_Positions-Short_All'] = contract_df['Nonreportable_Long_Temp']

            # Drop temporary columns
            contract_df = contract_df.drop(columns=['Commercial_Long_Temp', 'Noncommercial_Long_Temp', 'Nonreportable_Long_Temp'])

            # Convert date to datetime and create Date column
            contract_df['As_of_Date_in_Form_YYYY-MM-DD'] = pd.to_datetime(contract_df['As_of_Date_in_Form_YYYY-MM-DD'])
            contract_df['Date'] = contract_df['As_of_Date_in_Form_YYYY-MM-DD']  # Add Date column for consistency
            contract_df = contract_df.sort_values('Date')

            logger.info(f"  - Aggregated to {len(contract_df)} unique dates")
            display_name = "AGGREGATE_CURRENCIES"

        else:
            # Handle single name or list of names
            if isinstance(contract_name, list):
                contract_names = contract_name
                display_name = contract_names[0]  # Use first name for logging
                logger.info(f"Processing {len(contract_names)} contract names with {lookback_years}y lookback")
                for name in contract_names:
                    logger.info(f"  - Searching: {name}")
            else:
                contract_names = [contract_name]
                display_name = contract_name
                logger.info(f"Processing {contract_name} with {lookback_years}y lookback")

            # Filter for this contract (combine data from all names)
            contract_dfs = []
            for name in contract_names:
                temp_df = df[df['Market_and_Exchange_Names'] == name].copy()
                if len(temp_df) > 0:
                    logger.info(f"  - Found {len(temp_df)} records for {name}")
                    contract_dfs.append(temp_df)

            if not contract_dfs:
                logger.warning(f"✗ No data found for any contract name: {contract_names}")
                return None

            # Combine all data
            contract_df = pd.concat(contract_dfs, ignore_index=True)

            # Remove duplicates if any (by date)
            contract_df = contract_df.drop_duplicates(subset=['As_of_Date_in_Form_YYYY-MM-DD'], keep='first')

            logger.info(f"  - Total combined: {len(contract_df)} records from {len(contract_dfs)} source(s)")

        # Calculate net positions for all 3 categories
        # Commercial (smart money)
        contract_df['Commercial_Net_Long'] = (
            contract_df['Commercial_Positions-Long_All'] -
            contract_df['Commercial_Positions-Short_All']
        )
        contract_df['Commercial_Net_Pct'] = (
            contract_df['Commercial_Net_Long'] / contract_df['Open_Interest_All']
        ) * 100

        # Non-Commercial (large speculators)
        contract_df['NonCommercial_Net_Long'] = (
            contract_df['Noncommercial_Positions-Long_All'] -
            contract_df['Noncommercial_Positions-Short_All']
        )
        contract_df['NonCommercial_Net_Pct'] = (
            contract_df['NonCommercial_Net_Long'] / contract_df['Open_Interest_All']
        ) * 100

        # Non-Reportable (small traders)
        contract_df['NonReportable_Net_Long'] = (
            contract_df['Nonreportable_Positions-Long_All'] -
            contract_df['Nonreportable_Positions-Short_All']
        )
        contract_df['NonReportable_Net_Pct'] = (
            contract_df['NonReportable_Net_Long'] / contract_df['Open_Interest_All']
        ) * 100

        # Sort by date
        contract_df = contract_df.sort_values('Date')
        logger.info(f"  - Date range: {contract_df['Date'].min()} to {contract_df['Date'].max()}")

        # Calculate lookback statistics
        lookback_date = datetime.now() - timedelta(days=lookback_years*365)
        lookback_df = contract_df[contract_df['Date'] >= lookback_date]
        logger.info(f"  - Lookback years requested: {lookback_years}")
        logger.info(f"  - Today's date: {datetime.now().strftime('%Y-%m-%d')}")
        logger.info(f"  - Lookback cutoff calculated: {lookback_date.strftime('%Y-%m-%d')}")
        logger.info(f"  - Lookback data date range: {lookback_df['Date'].min()} to {lookback_df['Date'].max()}")
        logger.info(f"  - Records in lookback period: {len(lookback_df)} / {len(contract_df)}")

        if len(lookback_df) == 0:
            logger.warning(f"✗ No data in lookback period")
            return None

        # Calculate stats for all 3 categories
        def calc_stats(category_col):
            """Calculate statistics for a trader category"""
            current = lookback_df.iloc[-1][category_col]
            mean = lookback_df[category_col].mean()
            std = lookback_df[category_col].std()
            min_val = lookback_df[category_col].min()
            max_val = lookback_df[category_col].max()

            # Z-score
            z = (current - mean) / std if std > 0 else 0

            # Percentile
            pct = (lookback_df[category_col] < current).sum() / len(lookback_df) * 100

            # Status
            if pct >= 95:
                status = "EXTREME LONG"
                color = "🟢"
            elif pct >= 80:
                status = "Strong Long"
                color = "🟩"
            elif pct <= 5:
                status = "EXTREME SHORT"
                color = "🔴"
            elif pct <= 20:
                status = "Strong Short"
                color = "🟥"
            else:
                status = "Neutral"
                color = "⚪"

            return {
                'current': current,
                'mean': mean,
                'std': std,
                'min': min_val,
                'max': max_val,
                'z_score': z,
                'percentile': pct,
                'status': status,
                'color': color
            }

        logger.info(f"  - Calculating stats for 3 trader categories...")
        commercial = calc_stats('Commercial_Net_Pct')
        noncommercial = calc_stats('NonCommercial_Net_Pct')
        nonreportable = calc_stats('NonReportable_Net_Pct')

        logger.info(f"  ✓ Positioning calculated:")
        logger.info(f"    COM: {commercial['status']:15s} | Z={commercial['z_score']:6.2f} | Pct={commercial['percentile']:5.1f}%")
        logger.info(f"    NC:  {noncommercial['status']:15s} | Z={noncommercial['z_score']:6.2f} | Pct={noncommercial['percentile']:5.1f}%")
        logger.info(f"    NR:  {nonreportable['status']:15s} | Z={nonreportable['z_score']:6.2f} | Pct={nonreportable['percentile']:5.1f}%")

        return {
            'commercial': commercial,
            'noncommercial': noncommercial,
            'nonreportable': nonreportable,
            'data': contract_df,
            'lookback_data': lookback_df,
            'latest_date': contract_df.iloc[-1]['Date']
        }

    except Exception as e:
        logger.error(f"Error calculating positioning: {str(e)}\n{traceback.format_exc()}")
        return None

def plot_contract(contract_data, contract_code, contract_info):
    """Create plotly chart for contract - shows all 3 trader categories with FULL history"""
    fig = go.Figure()

    # Use full data for plotting (not filtered by lookback period)
    df = contract_data['data']
    logger.info(f"Plotting {contract_code}: {len(df)} records from {df['Date'].min()} to {df['Date'].max()} (FULL HISTORY)")

    # Commercial (blue)
    fig.add_trace(go.Scatter(
        x=df['Date'],
        y=df['Commercial_Net_Pct'],
        mode='lines',
        name='Commercial',
        line=dict(color='#2E86AB', width=2),
        hovertemplate='Commercial: %{y:.2f}%<extra></extra>'
    ))

    # Non-Commercial (orange)
    fig.add_trace(go.Scatter(
        x=df['Date'],
        y=df['NonCommercial_Net_Pct'],
        mode='lines',
        name='Non-Commercial',
        line=dict(color='#E97451', width=2),
        hovertemplate='Non-Commercial: %{y:.2f}%<extra></extra>'
    ))

    # Non-Reportable (green)
    fig.add_trace(go.Scatter(
        x=df['Date'],
        y=df['NonReportable_Net_Pct'],
        mode='lines',
        name='Non-Reportable',
        line=dict(color='#6BAA75', width=2),
        hovertemplate='Non-Reportable: %{y:.2f}%<extra></extra>'
    ))

    # Open Interest on secondary y-axis (gray, semi-transparent)
    fig.add_trace(go.Scatter(
        x=df['Date'],
        y=df['Open_Interest_All'],
        mode='lines',
        name='Open Interest',
        line=dict(color='rgba(128, 128, 128, 0.3)', width=1),
        fill='tozeroy',
        fillcolor='rgba(220, 220, 220, 0.2)',
        yaxis='y2',
        hovertemplate='OI: %{y:,.0f}<extra></extra>'
    ))

    # Add zero line
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="gray",
        line_width=1
    )

    # Mark current positions
    current_commercial = df.iloc[-1]['Commercial_Net_Pct']
    current_noncommercial = df.iloc[-1]['NonCommercial_Net_Pct']
    current_date = df.iloc[-1]['Date']

    fig.add_trace(go.Scatter(
        x=[current_date, current_date],
        y=[current_commercial, current_noncommercial],
        mode='markers',
        name='Current',
        marker=dict(size=10, color=['#2E86AB', '#E97451']),
        showlegend=False,
        hoverinfo='skip'
    ))

    # Format date range for title
    date_start = df['Date'].min().strftime('%Y-%m-%d')
    date_end = df['Date'].max().strftime('%Y-%m-%d')
    years_span = (df['Date'].max() - df['Date'].min()).days / 365.25

    fig.update_layout(
        title=f"{contract_info['name']} ({contract_code}) - Net Position % OI<br><sub>Period: {date_start} to {date_end} ({years_span:.1f} years, {len(df)} data points)</sub>",
        xaxis_title="Date",
        yaxis_title="Net Position % of Open Interest",
        hovermode='x unified',
        height=450,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        plot_bgcolor='white',
        xaxis=dict(showgrid=True, gridcolor='lightgray'),
        yaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=True),
        yaxis2=dict(
            title="Open Interest",
            overlaying='y',
            side='right',
            showgrid=False
        )
    )

    return fig

# Main app
@log_function
def main():
    st.title("📊 CFTC Commitments of Traders - Analysis Dashboard")

    try:
        # Initialize session state first
        if 'active_section' not in st.session_state:
            st.session_state.active_section = "positioning"

        # Navigation buttons for different sections
        st.markdown("---")
        col1, col2, col3, col4 = st.columns([2, 2, 2, 4])

        with col1:
            if st.button("📈 **Futures Positioning**", use_container_width=True,
                        type="primary" if st.session_state.active_section == "positioning" else "secondary"):
                st.session_state.active_section = "positioning"
        with col2:
            if st.button("🌍 Macro", use_container_width=True,
                        type="primary" if st.session_state.active_section == "macro" else "secondary"):
                st.session_state.active_section = "macro"
        with col3:
            if st.button("📊 More Analysis", use_container_width=True,
                        type="primary" if st.session_state.active_section == "more_analysis" else "secondary"):
                st.session_state.active_section = "more_analysis"

        st.markdown("---")

        # ========== SECTION 1: FUTURES POSITIONING DASHBOARD ==========
        if st.session_state.active_section == "positioning":
            # Sidebar controls for Futures Positioning section
            with st.sidebar:
                st.header("⚙️ Settings")

                lookback_years = st.slider(
                    "Lookback Period (years)",
                    min_value=1,
                    max_value=20,
                    value=5,
                    help="Historical period for calculating Z-scores, percentiles, and status in tables. Charts always show full history (2005-2025)."
                )
                logger.info(f"User selected lookback period: {lookback_years} years")

                st.markdown("---")

                trader_category = st.selectbox(
                    "📊 Primary Trader Category",
                    options=['Commercial', 'Non-Commercial', 'Non-Reportable'],
                    index=0,
                    help="Which trader type to use for sorting and ranking",
                    key='trader_category_selector'
                )
                logger.info(f"User selected trader category: {trader_category}")

                st.markdown("""
                **Trader Types:**
                - **Commercial**: Producers, hedgers (smart money)
                - **Non-Commercial**: Large speculators, funds
                - **Non-Reportable**: Small retail traders
                """)

                st.markdown("---")

                category_filter = st.multiselect(
                    "Filter by Asset Category",
                    options=['All'] + sorted(list(set([v['category'] for v in CONTRACTS.values()]))),
                    default=['All']
                )

                # Handle Streamlit state bug where multiselect returns integers
                if isinstance(category_filter, list) and len(category_filter) > 0 and isinstance(category_filter[0], int):
                    category_options = ['All'] + sorted(list(set([v['category'] for v in CONTRACTS.values()])))
                    category_filter = [category_options[i] for i in category_filter]
                    logger.warning(f"category_filter contained integers, converted to: {category_filter}")

                logger.info(f"User selected asset filters: {category_filter}")

                st.markdown("---")

                sort_options = ['Symbol', 'Z-Score', 'Percentile', 'Current %']
                sort_by = st.selectbox(
                    "Sort By",
                    options=sort_options,
                    index=1
                )
                # Handle case where sort_by might be int (Streamlit state bug)
                if isinstance(sort_by, int):
                    sort_by = sort_options[sort_by]
                    logger.warning(f"sort_by was int, converted to: {sort_by}")
                logger.info(f"User selected sort by: {sort_by}")

                sort_ascending = st.checkbox("Ascending", value=False)

                st.markdown("---")
                st.markdown("### 📖 Legend")
                st.markdown("""
                🟢 **EXTREME LONG** (>95th percentile)
                🟩 **Strong Long** (>80th percentile)
                ⚪ **Neutral** (20-80th percentile)
                🟥 **Strong Short** (<20th percentile)
                🔴 **EXTREME SHORT** (<5th percentile)
                """)

                st.markdown("---")
                st.markdown("### 🔄 Database Update")

                # Show current database status
                from src.data_fetchers.cot_database_updater import COTDatabaseUpdater
                updater = COTDatabaseUpdater(PROJECT_ROOT)
                status = updater.get_current_status()

                if status['exists']:
                    st.info(f"**Current Status:**\n- Records: {status['records']:,}\n- Latest: {status['latest_date'].strftime('%Y-%m-%d')}\n- Days behind: {status['days_behind']}")

                # Update button
                if st.button("🔄 Update Data", key="update_db_button", help="Download and integrate latest CFTC data"):
                    with st.spinner("Updating database..."):
                        logger.info("User initiated database update")
                        success, message = updater.update_database()

                        if success:
                            st.success("✅ " + message)
                            logger.info(f"Database update successful: {message}")
                            st.info("🔄 Clearing cache and reloading data...")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("❌ " + message)
                            logger.error(f"Database update failed: {message}")

            st.markdown("**All Trader Categories Analysis Across 41 Futures Contracts**")
            st.markdown("*Commercial | Non-Commercial | Non-Reportable*")
            st.info("💡 Charts display full historical data (2005-2025). Use the slider to adjust lookback period for table statistics only.")

            # Load data
            logger.info(f"Loading CFTC data with lookback={lookback_years}")
            with st.spinner("Loading CFTC data..."):
                df = load_cftc_data()

            if df is None:
                logger.error("Failed to load CFTC data")
                st.error("Failed to load data. Please check that data files exist.")
                st.info(f"Check log file for details: {LOG_FILE}")
                return

            logger.info(f"Successfully loaded {len(df):,} records from CFTC")
            st.success(f"✅ Loaded {len(df):,} records from CFTC")

            # Calculate positioning for all contracts
            total_contracts = len(CONTRACTS)
            logger.info("="*60)
            logger.info(f"CALCULATING POSITIONING FOR {total_contracts} CONTRACTS")
            logger.info("="*60)

            results = {}
            start_time = time.time()

            for idx, (code, info) in enumerate(CONTRACTS.items(), 1):
                logger.info(f"[{idx}/{total_contracts}] Processing {code} - {info['name']}...")
                data = calculate_positioning(df, info['cftc_name'], lookback_years)
                if data:
                    results[code] = {**data, 'info': info}
                    logger.info(f"  ✓ {code} completed")
                else:
                    logger.warning(f"  ✗ {code} failed - no data returned")

            elapsed = time.time() - start_time
            logger.info("="*60)
            logger.info(f"✓ POSITIONING CALCULATION COMPLETE")
            logger.info(f"  Success: {len(results)}/{total_contracts} contracts")
            logger.info(f"  Time: {elapsed:.2f}s ({elapsed/total_contracts:.2f}s per contract)")
            logger.info("="*60)

            # Filter by category
            if 'All' not in category_filter and len(category_filter) > 0:
                before_filter = len(results)
                results = {k: v for k, v in results.items() if v['info']['category'] in category_filter}
                logger.info(f"Filtered from {before_filter} to {len(results)} contracts")

            # Map trader category to data key
            # Handle case where trader_category might be int (Streamlit state bug)
            if isinstance(trader_category, int):
                trader_options_list = ['Commercial', 'Non-Commercial', 'Non-Reportable']
                trader_category = trader_options_list[trader_category]
                logger.warning(f"trader_category was int, converted to: {trader_category}")

            category_key = trader_category.lower().replace('-', '')
            logger.info(f"Using category key: {category_key}")

            # Create summary dataframe with all three trader categories
            summary_data = []
            for code, data in results.items():
                primary = data[category_key]  # Selected category for sorting
                summary_data.append({
                    'Symbol': code,
                    'Name': data['info']['name'],
                    'Asset Cat': data['info']['category'],
                    'Status': primary['color'],
                    # Primary category (selected)
                    'Current %': primary['current'],
                    'Z-Score': primary['z_score'],
                    'Percentile': primary['percentile'],
                    # All three categories for comparison
                    'COM %': data['commercial']['current'],
                    'NC %': data['noncommercial']['current'],
                    'NR %': data['nonreportable']['current'],
                    'Latest': data['latest_date'].strftime('%Y-%m-%d')
                })

            summary_df = pd.DataFrame(summary_data)
            logger.info(f"Created summary dataframe with {len(summary_df)} rows")

            # Check if dataframe is empty
            if len(summary_df) == 0:
                st.warning(f"⚠️ No contracts available with the selected filters. Try adjusting the lookback period or asset category filters.")
                logger.warning("Summary dataframe is empty - cannot display table")
                return

            # Sort by selected category
            sort_col_map = {
                'Symbol': 'Symbol',
                'Z-Score': 'Z-Score',
                'Percentile': 'Percentile',
                'Current %': 'Current %'
            }
            summary_df = summary_df.sort_values(sort_col_map[sort_by], ascending=sort_ascending)
            logger.info(f"Sorted by {sort_by} (ascending={sort_ascending})")

            # Display summary table
            st.header(f"📋 Market Summary - Sorted by {trader_category}")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                extreme_longs = len([d for d in results.values() if d[category_key]['percentile'] >= 95])
                st.metric(f"{trader_category} - Extreme Longs", extreme_longs)
            with col2:
                extreme_shorts = len([d for d in results.values() if d[category_key]['percentile'] <= 5])
                st.metric(f"{trader_category} - Extreme Shorts", extreme_shorts)
            with col3:
                avg_z = np.mean([d[category_key]['z_score'] for d in results.values()])
                st.metric(f"{trader_category} - Avg Z", f"{avg_z:.2f}")
            with col4:
                st.metric("Total Contracts", len(results))

            # Create tabs for different views
            tab1, tab2, tab3, tab4 = st.tabs(["📊 All Contracts", "🟢 Top 10 Longs", "🔴 Top 10 Shorts", "📈 Group Stats"])

            # Common column config
            column_config = {
                'Status': st.column_config.TextColumn('Status', width='small'),
                'Asset Cat': st.column_config.TextColumn('Asset Cat', width='small'),
                'Current %': st.column_config.NumberColumn(f'{trader_category} %', format="%.2f"),
                'Z-Score': st.column_config.NumberColumn(f'{trader_category} Z', format="%.2f"),
                'Percentile': st.column_config.NumberColumn(f'{trader_category} Pctl', format="%.1f"),
                'COM %': st.column_config.NumberColumn('COM %', format="%.2f", help="Commercial net %"),
                'NC %': st.column_config.NumberColumn('NC %', format="%.2f", help="Non-Commercial net %"),
                'NR %': st.column_config.NumberColumn('NR %', format="%.2f", help="Non-Reportable net %"),
            }

            with tab1:
                st.markdown(f"**All {len(summary_df)} contracts** sorted by {trader_category} {sort_by}")
                st.dataframe(
                    summary_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config
                )

            with tab2:
                # Top 10 Longs (highest percentiles)
                top_longs = summary_df.nlargest(10, 'Percentile')
                st.markdown(f"**Top 10 Long Positions** - Highest {trader_category} percentiles (most bullish)")
                st.dataframe(
                    top_longs,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config
                )

            with tab3:
                # Top 10 Shorts (lowest percentiles)
                top_shorts = summary_df.nsmallest(10, 'Percentile')
                st.markdown(f"**Top 10 Short Positions** - Lowest {trader_category} percentiles (most bearish)")
                st.dataframe(
                    top_shorts,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config
                )

            with tab4:
                # Asset category statistics
                st.markdown(f"**Average Statistics by Asset Category** - Based on {trader_category}")
                st.caption("*Note: Dollar Index excluded from Currencies average*")

                # Calculate stats by asset category
                category_stats = {}
                for code, data in results.items():
                    cat = data['info']['category']

                    # Skip Dollar Index when calculating Currencies average
                    if cat == 'Currencies' and code == 'DXY':
                        continue

                    if cat not in category_stats:
                        category_stats[cat] = {
                            'z_scores': [],
                            'percentiles': [],
                            'current_pcts': [],
                            'count': 0
                        }
                    category_stats[cat]['z_scores'].append(data[category_key]['z_score'])
                    category_stats[cat]['percentiles'].append(data[category_key]['percentile'])
                    category_stats[cat]['current_pcts'].append(data[category_key]['current'])
                    category_stats[cat]['count'] += 1

                # Build table
                group_stats = []
                for cat in sorted(category_stats.keys()):
                    stats = category_stats[cat]
                    group_stats.append({
                        'Asset Category': cat,
                        'Contracts': stats['count'],
                        'Avg Z-Score': f"{np.mean(stats['z_scores']):.2f}",
                        'Avg Percentile': f"{np.mean(stats['percentiles']):.1f}%",
                        'Avg Current %': f"{np.mean(stats['current_pcts']):.2f}%"
                    })

                group_stats_df = pd.DataFrame(group_stats)
                st.dataframe(group_stats_df, use_container_width=True, hide_index=True)

            # Individual contract charts
            st.header("📈 Individual Contract Charts")

            # Group by category
            categories = {}
            for code, data in results.items():
                cat = data['info']['category']
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((code, data))

            # Display charts by category
            for category, contracts in sorted(categories.items()):
                with st.expander(f"**{category}** ({len(contracts)} contracts)", expanded=False):
                    # First, create a summary table for all contracts in this category
                    st.markdown(f"### {category} Contracts Summary")

                    # Sort contracts - use sort_order for Bonds, alphabetical for others
                    if category == 'Bonds':
                        sorted_contracts = sorted(contracts, key=lambda x: CONTRACTS[x[0]].get('sort_order', 999))
                    else:
                        sorted_contracts = sorted(contracts)

                    table_data = []
                    for code, data in sorted_contracts:
                        table_data.append({
                            'Code': code,
                            'Name': data['info']['name'],
                            'COM Status': data['commercial']['status'],
                            'COM Current %': f"{data['commercial']['current']:.1f}%",
                            'COM Z-Score': f"{data['commercial']['z_score']:.2f}",
                            'COM Pctl': f"{data['commercial']['percentile']:.0f}%",
                            'NC Status': data['noncommercial']['status'],
                            'NC Current %': f"{data['noncommercial']['current']:.1f}%",
                            'NC Z-Score': f"{data['noncommercial']['z_score']:.2f}",
                            'NC Pctl': f"{data['noncommercial']['percentile']:.0f}%",
                            'NR Status': data['nonreportable']['status'],
                            'NR Current %': f"{data['nonreportable']['current']:.1f}%",
                            'NR Z-Score': f"{data['nonreportable']['z_score']:.2f}",
                            'NR Pctl': f"{data['nonreportable']['percentile']:.0f}%",
                        })

                    category_df = pd.DataFrame(table_data)
                    st.dataframe(category_df, use_container_width=True, height=min(400, (len(contracts) + 1) * 35))

                    st.markdown("---")
                    st.markdown(f"### Individual Charts")

                    # Then display individual charts below
                    for code, data in sorted_contracts:
                        st.markdown(f"#### {code} - {data['info']['name']}")

                        # Show compact metrics in 3 columns
                        col1, col2, col3 = st.columns(3)

                        with col1:
                            st.markdown("**Commercial**")
                            st.write(f"Status: {data['commercial']['status']}")
                            st.write(f"Current: {data['commercial']['current']:.1f}%")
                            st.write(f"Z-Score: {data['commercial']['z_score']:.2f}")
                            st.write(f"Percentile: {data['commercial']['percentile']:.0f}%")

                        with col2:
                            st.markdown("**Non-Commercial**")
                            st.write(f"Status: {data['noncommercial']['status']}")
                            st.write(f"Current: {data['noncommercial']['current']:.1f}%")
                            st.write(f"Z-Score: {data['noncommercial']['z_score']:.2f}")
                            st.write(f"Percentile: {data['noncommercial']['percentile']:.0f}%")

                        with col3:
                            st.markdown("**Non-Reportable**")
                            st.write(f"Status: {data['nonreportable']['status']}")
                            st.write(f"Current: {data['nonreportable']['current']:.1f}%")
                            st.write(f"Z-Score: {data['nonreportable']['z_score']:.2f}")
                            st.write(f"Percentile: {data['nonreportable']['percentile']:.0f}%")

                        # Chart below
                        fig = plot_contract(data, code, data['info'])
                        st.plotly_chart(fig, use_container_width=True)

                        st.markdown("---")

            # Final summary logging
            logger.info("="*60)
            logger.info("DASHBOARD RENDERING COMPLETE")
            logger.info(f"  - Lookback period: {lookback_years} years")
            logger.info(f"  - Primary trader category: {trader_category}")
            logger.info(f"  - Contracts displayed: {len(results)}")
            logger.info(f"  - Asset filters: {category_filter}")
            logger.info(f"  - Sorted by: {sort_by} (ascending={sort_ascending})")

            # Count extremes for final summary
            extreme_longs = sum(1 for d in results.values() if d[category_key]['percentile'] >= 95)
            extreme_shorts = sum(1 for d in results.values() if d[category_key]['percentile'] <= 5)
            avg_z = np.mean([d[category_key]['z_score'] for d in results.values()])

            logger.info(f"  - Extreme Longs ({trader_category}): {extreme_longs}")
            logger.info(f"  - Extreme Shorts ({trader_category}): {extreme_shorts}")
            logger.info(f"  - Average Z-Score ({trader_category}): {avg_z:.2f}")
            logger.info("="*60)

        # ========== SECTION 2: MACRO DASHBOARD ==========
        elif st.session_state.active_section == "macro":
            # Sidebar for Macro section (currently empty)
            with st.sidebar:
                st.header("⚙️ Macro Settings")
                st.info("Macro dashboard settings will be added here")

            st.header("🌍 Macro Economic Dashboard")

            # Tabs for different regions
            tab1, tab2 = st.tabs(["🇺🇸 US", "🌐 More Regions (Coming Soon)"])

            with tab1:
                # Create sub-tabs for US economic indicators
                us_subtab1, us_subtab2 = st.tabs(["📊 4-Quadrant View", "📈 Leading Indices"])

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

            with tab2:
                st.info("🚧 Additional regions (EU, China, Japan) will be added here")

        # ========== SECTION 3: MORE ANALYSIS (PLACEHOLDER) ==========
        elif st.session_state.active_section == "more_analysis":
            st.header("📊 More Analysis Tools")
            st.info("🚧 Additional analysis features will be added here")
            st.markdown("""
            **Planned Features:**
            - Cross-asset correlation analysis
            - Historical positioning trends
            - Divergence detection
            - Custom portfolio positioning
            """)

    except Exception as e:
        error_msg = f"Fatal error in main(): {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())

        st.error("❌ An error occurred while rendering the dashboard")
        st.error(str(e))

        with st.expander("📋 Error Details"):
            st.code(traceback.format_exc())
            st.info(f"Full logs available at: {LOG_FILE}")

if __name__ == "__main__":
    try:
        logger.info("="*80)
        logger.info(f"SESSION START - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Streamlit version: {st.__version__}")
        logger.info(f"Pandas version: {pd.__version__}")
        logger.info("="*80)

        main()

        logger.info("="*80)
        logger.info(f"SESSION END - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)

    except Exception as e:
        logger.error("="*80)
        logger.error(f"FATAL ERROR AT STARTUP: {str(e)}")
        logger.error(traceback.format_exc())
        logger.error("="*80)
        print(f"\n❌ ERROR: {str(e)}")
        print(f"\nCheck log file for details: {LOG_FILE}")
