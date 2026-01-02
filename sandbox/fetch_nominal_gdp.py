"""
Fetch US Nominal GDP from FRED - Last 10 Years
"""
import pandas as pd
from fredapi import Fred
from pathlib import Path

# FRED series ID for Nominal GDP (Quarterly, Seasonally Adjusted Annual Rate)
# GDP = Gross Domestic Product (Current Dollars)
GDP_SERIES = 'GDP'

def fetch_nominal_gdp():
    """Fetch Nominal GDP from FRED - All available history"""

    print("=" * 80)
    print("FETCHING US NOMINAL GDP FROM FRED")
    print("=" * 80)
    print()
    print(f"Series: {GDP_SERIES} (Gross Domestic Product)")
    print(f"Frequency: Quarterly, Seasonally Adjusted Annual Rate")
    print(f"Units: Billions of Current Dollars")
    print()

    try:
        # Load FRED API key
        api_key_file = Path('data/fred_api_key.txt')
        FRED_API_KEY = api_key_file.read_text().strip()
        fred = Fred(api_key=FRED_API_KEY)

        # Fetch all available data from FRED
        series = fred.get_series(GDP_SERIES)
        df = pd.DataFrame({GDP_SERIES: series})

        # Calculate quarter-over-quarter growth rate (%)
        df['QoQ_Growth_%'] = df[GDP_SERIES].pct_change() * 100

        # Calculate year-over-year growth rate (%)
        df['YoY_Growth_%'] = df[GDP_SERIES].pct_change(periods=4) * 100

        # Rename column for clarity
        df = df.rename(columns={GDP_SERIES: 'Nominal_GDP_Billions'})

        print(f"✓ Fetched {len(df)} quarters of data")
        print(f"  Date range: {df.index.min().strftime('%Y-Q%q')} to {df.index.max().strftime('%Y-Q%q')}")
        print()
        print("=" * 80)
        print("US NOMINAL GDP - LAST 20 QUARTERS")
        print("=" * 80)
        print()

        # Display with formatting
        pd.set_option('display.float_format', lambda x: f'{x:,.2f}')
        print(df.tail(20).to_string())
        print()

        # Summary statistics
        print("=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)
        print()
        print(f"Latest Quarter: {df.index[-1].strftime('%Y-Q%q')}")
        print(f"Latest GDP: ${df['Nominal_GDP_Billions'].iloc[-1]:,.2f} billion")
        print(f"Latest QoQ Growth: {df['QoQ_Growth_%'].iloc[-1]:.2f}%")
        if 'YoY_Growth_%' in df.columns:
            print(f"Latest YoY Growth: {df['YoY_Growth_%'].iloc[-1]:.2f}%")
        print()
        print(f"Average QoQ Growth (last 20 quarters): {df['QoQ_Growth_%'].tail(20).mean():.2f}%")
        if 'YoY_Growth_%' in df.columns:
            print(f"Average YoY Growth (last 20 quarters): {df['YoY_Growth_%'].tail(20).mean():.2f}%")
        print()

        # Save to CSV
        output_file = 'data/economic/fred_nominal_gdp_all.csv'
        import os
        os.makedirs('data/economic', exist_ok=True)
        df.to_csv(output_file)
        print(f"✓ Saved to: {output_file}")
        print(f"  Total: {len(df)} quarters of historical data")

        return df

    except Exception as e:
        print(f"ERROR: Failed to fetch data from FRED")
        print(f"Error: {e}")
        print()
        print("Note: pandas_datareader may have rate limits or connection issues")
        print("Alternative: Get FRED API key at https://fred.stlouisfed.org/docs/api/api_key.html")
        return None

if __name__ == '__main__':
    fetch_nominal_gdp()
