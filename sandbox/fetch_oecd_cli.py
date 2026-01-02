"""
Fetch OECD Composite Leading Indicator (CLI) for US
"""
import pandas as pd
from fredapi import Fred
from pathlib import Path

# OECD CLI series ID for United States
OECD_CLI_USA = 'USALOLITONOSTSAM'  # US Composite Leading Indicator (Amplitude adjusted)

def fetch_oecd_cli():
    """Fetch OECD Composite Leading Indicator for US - All available history"""

    print("=" * 80)
    print("FETCHING OECD COMPOSITE LEADING INDICATOR - UNITED STATES")
    print("=" * 80)
    print()
    print(f"Series: {OECD_CLI_USA}")
    print(f"Frequency: Monthly")
    print(f"Base: 100 = Long-term trend")
    print(f"Lead time: 6-9 months for turning points")
    print()

    try:
        # Load FRED API key
        api_key_file = Path('data/fred_api_key.txt')
        FRED_API_KEY = api_key_file.read_text().strip()
        fred = Fred(api_key=FRED_API_KEY)

        # Fetch all available data from FRED
        series = fred.get_series(OECD_CLI_USA)
        df_all = pd.DataFrame({OECD_CLI_USA: series})

        # Rename column
        df_all = df_all.rename(columns={OECD_CLI_USA: 'OECD_CLI'})

        # Calculate MoM change
        df_all['MoM_Change'] = df_all['OECD_CLI'].diff()

        # Calculate 3-month moving average for trend
        df_all['CLI_3M_MA'] = df_all['OECD_CLI'].rolling(window=3).mean()

        print(f"✓ Fetched {len(df_all)} months of data")
        print(f"  Date range: {df_all.index.min().strftime('%B %Y')} to {df_all.index.max().strftime('%B %Y')}")
        print()
        print("=" * 80)
        print("OECD COMPOSITE LEADING INDICATOR - US (LAST 24 MONTHS)")
        print("=" * 80)
        print()

        pd.set_option('display.float_format', lambda x: f'{x:,.2f}')
        pd.set_option('display.max_rows', None)
        print(df_all.tail(24).to_string())
        print()

        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print()
        print(f"Latest Month: {df_all.index[-1].strftime('%B %Y')}")
        print(f"Latest CLI: {df_all['OECD_CLI'].iloc[-1]:.2f}")
        print(f"Latest MoM Change: {df_all['MoM_Change'].iloc[-1]:+.2f}")
        print(f"3-Month MA: {df_all['CLI_3M_MA'].iloc[-1]:.2f}")
        print()

        # Trend analysis
        latest = df_all['OECD_CLI'].iloc[-1]
        trend_3m = df_all['OECD_CLI'].iloc[-3:].mean()
        trend_6m = df_all['OECD_CLI'].iloc[-6:].mean()

        if latest > 100:
            print(f"Signal: Above trend (100) - Economy expanding above potential")
        else:
            print(f"Signal: Below trend (100) - Economy expanding below potential")

        if trend_3m > trend_6m:
            print(f"Trend: Rising (3M avg: {trend_3m:.2f} > 6M avg: {trend_6m:.2f}) - Strengthening")
        else:
            print(f"Trend: Falling (3M avg: {trend_3m:.2f} < 6M avg: {trend_6m:.2f}) - Weakening")

        print()

        # Save to CSV
        import os
        os.makedirs('data/economic', exist_ok=True)

        output_file = 'data/economic/oecd_cli_usa.csv'
        df_all.to_csv(output_file)
        print(f"✓ Saved to: {output_file}")
        print(f"  Total: {len(df_all)} months of historical data")

        return df_all

    except Exception as e:
        print(f"ERROR: Failed to fetch OECD CLI data")
        print(f"Error: {e}")
        return None

if __name__ == '__main__':
    fetch_oecd_cli()
