"""
COT positioning calculations
Calculates COT Index and Z-Score indicators for all trader categories
"""
import pandas as pd
import numpy as np
import logging
import traceback
from functools import wraps

logger = logging.getLogger(__name__)


def log_function(func):
    """Decorator to log function entry/exit"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.info(f"→ {func_name}()")
        try:
            result = func(*args, **kwargs)
            logger.info(f"← {func_name}() completed")
            return result
        except Exception as e:
            logger.error(f"✗ {func_name}() failed: {str(e)}")
            raise
    return wrapper


@log_function
def calculate_positioning(df, contract_name):
    """Calculate positioning metrics for a contract - all trader categories

    contract_name can be:
    - A single string: "GOLD - COMMODITY EXCHANGE INC."
    - A list of strings: ["10-YEAR U.S. TREASURY NOTES", "UST 10Y NOTE"] (for contracts with name changes)
    - Special: "AGGREGATE_CURRENCIES" - aggregates all currency contracts

    Calculates:
    - COT Index 75w (short-term normalized positioning)
    - COT Index 225w (long-term normalized positioning)
    - COT Z-Score (6w change with 156w lookback)
    """
    try:
        # Special handling for AGGREGATE_CURRENCIES
        if contract_name == 'AGGREGATE_CURRENCIES':
            logger.info(f"Processing AGGREGATE_CURRENCIES (summing all currency contracts)")

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
                logger.info(f"Processing {len(contract_names)} contract names")
                for name in contract_names:
                    logger.info(f"  - Searching: {name}")
            else:
                contract_names = [contract_name]
                display_name = contract_name
                logger.info(f"Processing {contract_name}")

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

        # ========== COT INDEX & Z-SCORE CALCULATIONS ==========
        # Calculate indicators for all 3 trader categories
        for category, col in [('Commercial', 'Commercial_Net_Pct'),
                              ('NonCommercial', 'NonCommercial_Net_Pct'),
                              ('NonReportable', 'NonReportable_Net_Pct')]:

            # COT Index 75w (short-term)
            contract_df[f'{category}_Min_75w'] = contract_df[col].rolling(
                window=75, min_periods=37
            ).min()
            contract_df[f'{category}_Max_75w'] = contract_df[col].rolling(
                window=75, min_periods=37
            ).max()
            range_diff_75w = contract_df[f'{category}_Max_75w'] - contract_df[f'{category}_Min_75w']
            contract_df[f'{category}_COT_Index_75w'] = np.where(
                range_diff_75w > 0,
                ((contract_df[col] - contract_df[f'{category}_Min_75w']) / range_diff_75w) * 100,
                50.0
            )

            # COT Index 225w (long-term)
            contract_df[f'{category}_Min_225w'] = contract_df[col].rolling(
                window=225, min_periods=112
            ).min()
            contract_df[f'{category}_Max_225w'] = contract_df[col].rolling(
                window=225, min_periods=112
            ).max()
            range_diff_225w = contract_df[f'{category}_Max_225w'] - contract_df[f'{category}_Min_225w']
            contract_df[f'{category}_COT_Index_225w'] = np.where(
                range_diff_225w > 0,
                ((contract_df[col] - contract_df[f'{category}_Min_225w']) / range_diff_225w) * 100,
                50.0
            )

            # COT Z-Score: Z-score of 6w change using 156w rolling stats
            contract_df[f'{category}_6w_Change'] = contract_df[col] - contract_df[col].shift(6)
            contract_df[f'{category}_6w_Change_Mean'] = contract_df[f'{category}_6w_Change'].rolling(
                window=156, min_periods=78
            ).mean()
            contract_df[f'{category}_6w_Change_Std'] = contract_df[f'{category}_6w_Change'].rolling(
                window=156, min_periods=78
            ).std()
            contract_df[f'{category}_COT_ZScore'] = np.where(
                contract_df[f'{category}_6w_Change_Std'] > 0,
                (contract_df[f'{category}_6w_Change'] - contract_df[f'{category}_6w_Change_Mean']) / contract_df[f'{category}_6w_Change_Std'],
                0.0
            )

        logger.info(f"  - COT Index 75w, 225w, and Z-Score calculated")

        # Extract latest values for all 3 categories
        if len(contract_df) == 0:
            logger.warning(f"✗ No data available")
            return None

        def calc_stats(category_col, category_name):
            """Extract latest indicator values for a trader category"""
            current = contract_df.iloc[-1][category_col]
            cot_index_75w = contract_df.iloc[-1][f'{category_name}_COT_Index_75w']
            cot_index_225w = contract_df.iloc[-1][f'{category_name}_COT_Index_225w']
            cot_zscore = contract_df.iloc[-1][f'{category_name}_COT_ZScore']

            # Calculate 4-week change in COT Index 75w
            if len(contract_df) >= 5:
                cot_index_75w_4w_ago = contract_df.iloc[-5][f'{category_name}_COT_Index_75w']
                cot_index_75w_4w_change = cot_index_75w - cot_index_75w_4w_ago
            else:
                cot_index_75w_4w_change = 0.0

            return {
                'current': current,
                'cot_index_75w': cot_index_75w,
                'cot_index_225w': cot_index_225w,
                'cot_zscore': cot_zscore,
                'cot_index_75w_4w_change': cot_index_75w_4w_change
            }

        logger.info(f"  - Extracting latest values for 3 trader categories...")
        commercial = calc_stats('Commercial_Net_Pct', 'Commercial')
        noncommercial = calc_stats('NonCommercial_Net_Pct', 'NonCommercial')
        nonreportable = calc_stats('NonReportable_Net_Pct', 'NonReportable')

        logger.info(f"  ✓ Positioning calculated:")
        logger.info(f"    COM: Index75={commercial['cot_index_75w']:5.1f} | Index225={commercial['cot_index_225w']:5.1f} | ZScore={commercial['cot_zscore']:+6.2f}")
        logger.info(f"    NC:  Index75={noncommercial['cot_index_75w']:5.1f} | Index225={noncommercial['cot_index_225w']:5.1f} | ZScore={noncommercial['cot_zscore']:+6.2f}")
        logger.info(f"    NR:  Index75={nonreportable['cot_index_75w']:5.1f} | Index225={nonreportable['cot_index_225w']:5.1f} | ZScore={nonreportable['cot_zscore']:+6.2f}")

        return {
            'commercial': commercial,
            'noncommercial': noncommercial,
            'nonreportable': nonreportable,
            'data': contract_df,
            'latest_date': contract_df.iloc[-1]['Date']
        }

    except Exception as e:
        logger.error(f"Error calculating positioning: {str(e)}\n{traceback.format_exc()}")
        return None
