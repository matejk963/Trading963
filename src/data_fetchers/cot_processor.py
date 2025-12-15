"""
CoT Data Processor - Extract Net Positions and % of Open Interest

This module processes raw CFTC CoT data to calculate:
- Total Open Interest
- Net Long positions (Long - Short) for each trader category
- Net Long as % of Open Interest
"""

import pandas as pd
from typing import Optional
from pathlib import Path


class CoTProcessor:
    """Process CoT data to extract key positioning metrics."""

    def __init__(self):
        """Initialize the CoT Processor."""
        pass

    def calculate_net_positions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate net positions and percentages for all trader categories.

        Args:
            df: Raw CoT DataFrame

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

        # Calculate net positions for each category
        df['Dealer_Net_Long'] = df['Dealer_Positions_Long_All'] - df['Dealer_Positions_Short_All']
        df['Asset_Mgr_Net_Long'] = df['Asset_Mgr_Positions_Long_All'] - df['Asset_Mgr_Positions_Short_All']
        df['Lev_Money_Net_Long'] = df['Lev_Money_Positions_Long_All'] - df['Lev_Money_Positions_Short_All']
        df['Other_Rept_Net_Long'] = df['Other_Rept_Positions_Long_All'] - df['Other_Rept_Positions_Short_All']
        df['NonRept_Net_Long'] = df['NonRept_Positions_Long_All'] - df['NonRept_Positions_Short_All']

        # Calculate as % of Open Interest
        df['Dealer_Net_Pct'] = (df['Dealer_Net_Long'] / df['Open_Interest_All']) * 100
        df['Asset_Mgr_Net_Pct'] = (df['Asset_Mgr_Net_Long'] / df['Open_Interest_All']) * 100
        df['Lev_Money_Net_Pct'] = (df['Lev_Money_Net_Long'] / df['Open_Interest_All']) * 100
        df['Other_Rept_Net_Pct'] = (df['Other_Rept_Net_Long'] / df['Open_Interest_All']) * 100
        df['NonRept_Net_Pct'] = (df['NonRept_Net_Long'] / df['Open_Interest_All']) * 100

        # Select relevant columns
        result = df[[
            'Market_and_Exchange_Names',
            'Report_Date',
            'Open_Interest_All',
            'Dealer_Net_Long',
            'Dealer_Net_Pct',
            'Asset_Mgr_Net_Long',
            'Asset_Mgr_Net_Pct',
            'Lev_Money_Net_Long',
            'Lev_Money_Net_Pct',
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
            'Dealer_Net_Contracts',
            'Dealer_Net_Pct_OI',
            'Asset_Mgr_Net_Contracts',
            'Asset_Mgr_Net_Pct_OI',
            'Lev_Money_Net_Contracts',
            'Lev_Money_Net_Pct_OI',
            'Other_Rept_Net_Contracts',
            'Other_Rept_Net_Pct_OI',
            'NonRept_Net_Contracts',
            'NonRept_Net_Pct_OI',
        ]

        return result

    def get_latest_positions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Get the most recent positions for all markets.

        Args:
            df: Processed CoT DataFrame

        Returns:
            DataFrame with latest positions for each market
        """
        # Get the latest date for each market
        latest = df.sort_values('Date').groupby('Market').tail(1).reset_index(drop=True)
        return latest.sort_values('Open_Interest', ascending=False)

    def get_market_history(self, df: pd.DataFrame, market_name: str) -> pd.DataFrame:
        """
        Get historical positions for a specific market.

        Args:
            df: Processed CoT DataFrame
            market_name: Name of the market

        Returns:
            DataFrame with historical positions sorted by date
        """
        market_data = df[df['Market'] == market_name].copy()
        return market_data.sort_values('Date')

    def save_processed_data(self, df: pd.DataFrame, output_path: str) -> None:
        """
        Save processed data to CSV.

        Args:
            df: Processed CoT DataFrame
            output_path: Path to save CSV file
        """
        df.to_csv(output_path, index=False)
        print(f"Saved processed data to: {output_path}")


def main():
    """Example usage of the CoT Processor."""
    import sys
    sys.path.insert(0, '/mnt/c/Users/krajcovic/Documents/GitHub/Trading963')
    from src.data_fetchers.cftc_fetcher import CFTCLegacyFetcher

    # Load raw data
    print("=" * 80)
    print("LOADING RAW COT DATA")
    print("=" * 80)
    fetcher = CFTCLegacyFetcher()
    raw_df = fetcher.load_legacy_data("data/cftc/fut_fin_txt_2025/FinFutYY.txt")

    # Process data
    print("\n" + "=" * 80)
    print("PROCESSING DATA")
    print("=" * 80)
    processor = CoTProcessor()
    processed_df = processor.calculate_net_positions(raw_df)

    print(f"Processed {len(processed_df)} records")
    print(f"Date range: {processed_df['Date'].min()} to {processed_df['Date'].max()}")
    print(f"Markets: {processed_df['Market'].nunique()}")

    # Get latest positions
    print("\n" + "=" * 80)
    print("LATEST POSITIONS (TOP 10 BY OPEN INTEREST)")
    print("=" * 80)
    latest = processor.get_latest_positions(processed_df)

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.float_format', lambda x: f'{x:,.1f}')

    print(latest.head(10).to_string(index=False))

    # Show specific market detail
    print("\n" + "=" * 80)
    print("E-MINI S&P 500 - DETAILED VIEW")
    print("=" * 80)

    sp500_data = processor.get_market_history(
        processed_df,
        'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'
    )

    print("\nLatest 5 weeks:")
    print(sp500_data.tail(5).to_string(index=False))

    # Save processed data
    print("\n" + "=" * 80)
    print("SAVING PROCESSED DATA")
    print("=" * 80)
    processor.save_processed_data(processed_df, "data/cftc/cot_net_positions_2025.csv")

    print("\n" + "=" * 80)
    print("SUMMARY TABLE - LATEST POSITIONS")
    print("=" * 80)

    # Create a cleaner summary view
    summary = latest[[
        'Market',
        'Date',
        'Open_Interest',
        'Dealer_Net_Pct_OI',
        'Asset_Mgr_Net_Pct_OI',
        'Lev_Money_Net_Pct_OI'
    ]].copy()

    summary.columns = ['Market', 'Date', 'OI', 'Dealer %', 'Asset Mgr %', 'Lev Money %']

    print("\nTop 15 Markets by Open Interest:")
    print(summary.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
