"""
CoT Disaggregated Data Processor - For agricultural commodities like corn

Trader categories in disaggregated reports:
- Producer/Merchant: Farmers, grain elevators, processors
- Swap Dealers: Banks and financial institutions dealing in swaps
- Managed Money: Hedge funds, CTAs (speculators)
- Other Reportables: Other large traders
- Non-Reportables: Small traders
"""

import pandas as pd
from typing import Optional


class CoTDisaggregatedProcessor:
    """Process disaggregated CoT data to extract key positioning metrics."""

    def __init__(self):
        """Initialize the CoT Disaggregated Processor."""
        pass

    def calculate_net_positions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate net positions and percentages for all trader categories.

        Args:
            df: Raw disaggregated CoT DataFrame

        Returns:
            DataFrame with simplified net position metrics
        """
        # Convert date column
        df['Report_Date'] = pd.to_datetime(df['Report_Date_as_YYYY-MM-DD'])

        # Convert numeric columns
        numeric_cols = [col for col in df.columns if any(x in col for x in
            ['Positions', 'Open_Interest'])]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Calculate net positions for each category (All positions)
        df['Prod_Merc_Net_Long'] = df['Prod_Merc_Positions_Long_All'] - df['Prod_Merc_Positions_Short_All']
        df['Swap_Net_Long'] = df['Swap_Positions_Long_All'] - df['Swap__Positions_Short_All']
        df['M_Money_Net_Long'] = df['M_Money_Positions_Long_All'] - df['M_Money_Positions_Short_All']
        df['Other_Rept_Net_Long'] = df['Other_Rept_Positions_Long_All'] - df['Other_Rept_Positions_Short_All']
        df['NonRept_Net_Long'] = df['NonRept_Positions_Long_All'] - df['NonRept_Positions_Short_All']

        # Calculate as % of Open Interest
        df['Prod_Merc_Net_Pct'] = (df['Prod_Merc_Net_Long'] / df['Open_Interest_All']) * 100
        df['Swap_Net_Pct'] = (df['Swap_Net_Long'] / df['Open_Interest_All']) * 100
        df['M_Money_Net_Pct'] = (df['M_Money_Net_Long'] / df['Open_Interest_All']) * 100
        df['Other_Rept_Net_Pct'] = (df['Other_Rept_Net_Long'] / df['Open_Interest_All']) * 100
        df['NonRept_Net_Pct'] = (df['NonRept_Net_Long'] / df['Open_Interest_All']) * 100

        # Select relevant columns
        result = df[[
            'Market_and_Exchange_Names',
            'Report_Date',
            'Open_Interest_All',
            'Prod_Merc_Net_Long',
            'Prod_Merc_Net_Pct',
            'Swap_Net_Long',
            'Swap_Net_Pct',
            'M_Money_Net_Long',
            'M_Money_Net_Pct',
            'Other_Rept_Net_Long',
            'Other_Rept_Net_Pct',
            'NonRept_Net_Long',
            'NonRept_Net_Pct',
        ]].copy()

        # Rename for clarity
        result.columns = [
            'Market',
            'Date',
            'Open_Interest',
            'Prod_Merc_Net_Contracts',
            'Prod_Merc_Net_Pct_OI',
            'Swap_Net_Contracts',
            'Swap_Net_Pct_OI',
            'M_Money_Net_Contracts',
            'M_Money_Net_Pct_OI',
            'Other_Rept_Net_Contracts',
            'Other_Rept_Net_Pct_OI',
            'NonRept_Net_Contracts',
            'NonRept_Net_Pct_OI',
        ]

        return result
