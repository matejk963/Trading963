"""
Fetch US CPI from FRED - Headline and Core CPI - All Available History
"""
import pandas as pd
from fredapi import Fred
from pathlib import Path

# FRED series IDs
HEADLINE_CPI = 'CPIAUCSL'  # All Items
CORE_CPI = 'CPILFESL'      # All Items Less Food & Energy

def fetch_cpi_data():
    """Fetch Headline and Core CPI from FRED - All available history"""

    print("=" * 80)
    print("FETCHING US CPI DATA FROM FRED")
    print("=" * 80)
    print()
    print(f"Headline CPI: {HEADLINE_CPI} (All Items)")
    print(f"Core CPI: {CORE_CPI} (All Items Less Food & Energy)")
    print(f"Frequency: Monthly")
    print(f"Base: 1982-84 = 100")
    print()

    try:
        # Load FRED API key
        api_key_file = Path('data/fred_api_key.txt')
        FRED_API_KEY = api_key_file.read_text().strip()
        fred = Fred(api_key=FRED_API_KEY)

        # Fetch all available data from FRED
        headline_series = fred.get_series(HEADLINE_CPI)
        core_series = fred.get_series(CORE_CPI)

        # Combine into single dataframe
        df = pd.DataFrame({
            'Headline_CPI': headline_series,
            'Core_CPI': core_series
        })

        # Calculate YoY inflation rates (%)
        df['Headline_YoY_%'] = df['Headline_CPI'].pct_change(periods=12) * 100
        df['Core_YoY_%'] = df['Core_CPI'].pct_change(periods=12) * 100

        # Calculate MoM inflation rates (%)
        df['Headline_MoM_%'] = df['Headline_CPI'].pct_change() * 100
        df['Core_MoM_%'] = df['Core_CPI'].pct_change() * 100

        print(f"✓ Fetched {len(df)} months of data")
        print(f"  Date range: {df.index.min().strftime('%B %Y')} to {df.index.max().strftime('%B %Y')}")
        print()
        print("=" * 80)
        print("US CPI DATA - LAST 24 MONTHS")
        print("=" * 80)
        print()

        # Display last 24 months with formatting
        pd.set_option('display.float_format', lambda x: f'{x:,.2f}')
        pd.set_option('display.max_rows', None)
        print(df.tail(24).to_string())
        print()

        # Summary statistics
        print("=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)
        print()
        print(f"Latest Month: {df.index[-1].strftime('%B %Y')}")
        print(f"Headline CPI: {df['Headline_CPI'].iloc[-1]:.2f}")
        print(f"Core CPI: {df['Core_CPI'].iloc[-1]:.2f}")
        print()
        print(f"Latest Headline YoY Inflation: {df['Headline_YoY_%'].iloc[-1]:.2f}%")
        print(f"Latest Core YoY Inflation: {df['Core_YoY_%'].iloc[-1]:.2f}%")
        print()
        print(f"Latest Headline MoM Inflation: {df['Headline_MoM_%'].iloc[-1]:.2f}%")
        print(f"Latest Core MoM Inflation: {df['Core_MoM_%'].iloc[-1]:.2f}%")
        print()

        # Calculate quarterly averages (using quarter start dates to match GDP data)
        print("=" * 80)
        print("QUARTERLY AVERAGES - LAST 20 QUARTERS")
        print("=" * 80)
        print()

        df_quarterly = df.resample('QS').mean()

        print(df_quarterly[['Headline_YoY_%', 'Core_YoY_%']].tail(20).to_string())
        print()

        # Save to CSV
        output_file = 'data/economic/fred_cpi_all.csv'
        df.to_csv(output_file)
        print(f"✓ Saved monthly data to: {output_file}")
        print(f"  Total: {len(df)} months of historical data")
        print()

        # Save quarterly summary
        output_file_q = 'data/economic/fred_cpi_quarterly.csv'
        df_quarterly.to_csv(output_file_q)
        print(f"✓ Saved quarterly averages to: {output_file_q}")
        print(f"  Total: {len(df_quarterly)} quarters")

        return df, df_quarterly

    except Exception as e:
        print(f"ERROR: Failed to fetch data from FRED")
        print(f"Error: {e}")
        return None, None

if __name__ == '__main__':
    fetch_cpi_data()
