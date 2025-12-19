"""
13F Quarterly Data Pipeline - Memory-Efficient Batch Processing

Strategy:
1. Fetch complete quarterly data from SEC EDGAR bulk downloads
2. Process each quarter completely (sector classification + aggregation)
3. Save quarterly results to disk
4. Clear memory before next quarter
5. Build comprehensive time series from quarterly results

Data Source: SEC EDGAR bulk data (https://www.sec.gov/edgar/sec-api-documentation)
"""

import pandas as pd
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
import time
import gc
from io import BytesIO
from zipfile import ZipFile

# SEC Headers
HEADERS = {'User-Agent': 'Trading Research krajcovic@example.com'}

# Directories
DATA_DIR = Path('data/13f')
QUARTERLY_DIR = DATA_DIR / 'quarterly_results'
QUARTERLY_DIR.mkdir(parents=True, exist_ok=True)

# Load sector mapping
print("Loading sector mapping...")
sector_mapping = pd.read_csv(DATA_DIR / 'openfigi_ticker_mapping.csv')
sector_mapping = sector_mapping[['cusip', 'sector']].dropna()
sector_mapping = sector_mapping.set_index('cusip')
print(f"Loaded {len(sector_mapping):,} sector mappings")

def get_sector(cusip):
    """Get sector for a CUSIP"""
    try:
        if cusip in sector_mapping.index:
            sector = sector_mapping.loc[cusip, 'sector']
            if isinstance(sector, pd.Series):
                sector = sector.iloc[0]
            if pd.notna(sector):
                return sector
    except:
        pass
    return 'Other'

def get_quarter_end_dates(start_year=2019, end_year=2025):
    """Generate list of quarter-end dates to fetch"""
    quarters = []
    for year in range(start_year, end_year + 1):
        for month in [3, 6, 9, 12]:  # Q1, Q2, Q3, Q4
            # 13F filings are due 45 days after quarter end
            quarter_end = datetime(year, month, 1)
            if month == 3:
                quarter_end = datetime(year, 3, 31)
            elif month == 6:
                quarter_end = datetime(year, 6, 30)
            elif month == 9:
                quarter_end = datetime(year, 9, 30)
            else:
                quarter_end = datetime(year, 12, 31)

            if quarter_end <= datetime.now():
                quarters.append(quarter_end)

    return sorted(quarters)

def fetch_quarter_filings_from_sec(quarter_date):
    """
    Fetch all 13F-HR filings for a quarter from SEC EDGAR

    Approach: Query SEC submissions index for the filing period
    13F filings are due 45 days after quarter end
    """
    print(f"\n{'='*100}")
    print(f"FETCHING QUARTER: {quarter_date.strftime('%Y-Q%q')} (period ending {quarter_date.date()})")
    print(f"{'='*100}")

    # Calculate filing deadline (45 days after quarter end)
    filing_deadline = quarter_date + timedelta(days=45)

    # Search window: quarter end to filing deadline
    start_date = quarter_date.strftime('%Y-%m-%d')
    end_date = filing_deadline.strftime('%Y-%m-%d')

    print(f"Filing window: {start_date} to {end_date}")

    # This is a simplified approach - in production you'd use SEC's full-text search
    # or their bulk data downloads for the specific quarter
    # For now, we'll return a placeholder that indicates we need to use the existing
    # holdings_master_20quarters.parquet and filter by quarter

    print("Note: Using existing holdings data - filtering by quarter")
    return None

def process_quarter_batch(quarter_date, all_holdings_df):
    """
    Process a single quarter of data:
    1. Filter holdings to quarter
    2. Apply sector classification
    3. Aggregate by sector
    4. Save results
    5. Return aggregated data
    """
    quarter_str = quarter_date.strftime('%Y-Q%q')
    print(f"\n[Processing] {quarter_str}")

    # Filter to this quarter's major reporting date
    # We need to find the major filing date closest to the quarter deadline
    filing_deadline = quarter_date + timedelta(days=45)

    # Get filings within 60 days of quarter end
    window_start = quarter_date
    window_end = quarter_date + timedelta(days=60)

    quarter_holdings = all_holdings_df[
        (all_holdings_df['filing_date'] >= window_start) &
        (all_holdings_df['filing_date'] <= window_end)
    ].copy()

    if len(quarter_holdings) == 0:
        print(f"  No holdings found for {quarter_str}")
        return None

    # Find the major reporting date (most institutions filing)
    filings_by_date = quarter_holdings.groupby('filing_date')['cik'].nunique()
    major_date = filings_by_date.idxmax()
    num_institutions = filings_by_date.max()

    print(f"  Major filing date: {major_date.date()} ({num_institutions} institutions)")

    # Filter to major date only
    quarter_holdings = quarter_holdings[quarter_holdings['filing_date'] == major_date].copy()

    # Apply sector classification
    print(f"  Classifying {len(quarter_holdings):,} holdings...")
    quarter_holdings['sector'] = quarter_holdings['cusip'].apply(get_sector)

    # Calculate sector aggregates
    sector_agg = quarter_holdings.groupby('sector').agg({
        'value_thousands': 'sum',
        'cik': 'nunique',
        'cusip': 'nunique'
    }).reset_index()

    sector_agg.columns = ['sector', 'aum_dollars', 'num_institutions', 'num_stocks']
    sector_agg['aum_billions'] = sector_agg['aum_dollars'] / 1_000_000_000

    total_aum = sector_agg['aum_billions'].sum()
    sector_agg['allocation_%'] = (sector_agg['aum_billions'] / total_aum) * 100

    sector_agg['filing_date'] = major_date
    sector_agg['quarter'] = quarter_str
    sector_agg['quarter_end'] = quarter_date

    # Save quarterly result
    output_file = QUARTERLY_DIR / f'sector_agg_{quarter_str.replace("Q", "q")}.csv'
    sector_agg.to_csv(output_file, index=False)
    print(f"  Saved: {output_file.name}")
    print(f"  Total AUM: ${total_aum:.1f}B across {len(sector_agg)} sectors")

    # Clean up
    del quarter_holdings
    gc.collect()

    return sector_agg

def build_time_series():
    """Combine all quarterly results into time series"""
    print(f"\n{'='*100}")
    print("BUILDING TIME SERIES FROM QUARTERLY RESULTS")
    print(f"{'='*100}")

    quarterly_files = sorted(QUARTERLY_DIR.glob('sector_agg_*.csv'))

    if len(quarterly_files) == 0:
        print("No quarterly files found!")
        return None

    print(f"Found {len(quarterly_files)} quarterly result files")

    # Load and combine
    all_quarters = []
    for file in quarterly_files:
        df = pd.read_csv(file)
        df['filing_date'] = pd.to_datetime(df['filing_date'])
        df['quarter_end'] = pd.to_datetime(df['quarter_end'])
        all_quarters.append(df)

    timeseries_df = pd.concat(all_quarters, ignore_index=True)
    timeseries_df = timeseries_df.sort_values(['quarter_end', 'sector'])

    # Save master timeseries
    output_file = DATA_DIR / 'sector_flows_timeseries_batched.csv'
    timeseries_df.to_csv(output_file, index=False)
    print(f"\nSaved master timeseries: {output_file}")
    print(f"  Records: {len(timeseries_df):,}")
    print(f"  Quarters: {timeseries_df['quarter'].nunique()}")
    print(f"  Date range: {timeseries_df['quarter_end'].min().date()} to {timeseries_df['quarter_end'].max().date()}")

    return timeseries_df

def calculate_qoq_flows(timeseries_df):
    """Calculate quarter-over-quarter flows"""
    print(f"\n{'='*100}")
    print("CALCULATING QUARTER-OVER-QUARTER FLOWS")
    print(f"{'='*100}")

    quarters = sorted(timeseries_df['quarter_end'].unique())

    qoq_flows = []

    for i in range(1, len(quarters)):
        prev_quarter = quarters[i-1]
        curr_quarter = quarters[i]

        prev_data = timeseries_df[timeseries_df['quarter_end'] == prev_quarter].set_index('sector')
        curr_data = timeseries_df[timeseries_df['quarter_end'] == curr_quarter].set_index('sector')

        all_sectors = set(prev_data.index) | set(curr_data.index)

        for sector in all_sectors:
            prev_aum = prev_data.loc[sector, 'aum_billions'] if sector in prev_data.index else 0
            curr_aum = curr_data.loc[sector, 'aum_billions'] if sector in curr_data.index else 0
            prev_pct = prev_data.loc[sector, 'allocation_%'] if sector in prev_data.index else 0
            curr_pct = curr_data.loc[sector, 'allocation_%'] if sector in curr_data.index else 0

            change_billions = curr_aum - prev_aum
            change_pct = ((curr_aum / prev_aum) - 1) * 100 if prev_aum > 0 else 0
            allocation_change = curr_pct - prev_pct

            qoq_flows.append({
                'quarter_end': curr_quarter,
                'quarter': f"{curr_quarter.year}-Q{(curr_quarter.month-1)//3 + 1}",
                'sector': sector,
                'aum_billions': curr_aum,
                'prev_aum_billions': prev_aum,
                'change_billions': change_billions,
                'change_%': change_pct,
                'allocation_%': curr_pct,
                'prev_allocation_%': prev_pct,
                'allocation_change_bp': allocation_change * 100
            })

    qoq_df = pd.DataFrame(qoq_flows)

    # Save QoQ flows
    output_file = DATA_DIR / 'sector_qoq_flows_batched.csv'
    qoq_df.to_csv(output_file, index=False)
    print(f"Saved QoQ flows: {output_file}")

    return qoq_df

def main():
    """Main pipeline"""
    print(f"\n{'='*100}")
    print("13F QUARTERLY BATCH PROCESSING PIPELINE")
    print(f"{'='*100}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Load existing holdings data
    print("\n[1/4] Loading existing holdings data...")
    holdings_file = DATA_DIR / 'holdings_master_20quarters.parquet'

    if not holdings_file.exists():
        print(f"ERROR: Holdings file not found: {holdings_file}")
        print("Please run the holdings fetch script first")
        return

    all_holdings = pd.read_parquet(holdings_file)
    all_holdings['filing_date'] = pd.to_datetime(all_holdings['filing_date'])
    print(f"Loaded {len(all_holdings):,} holdings records")

    # Get available quarters from the data
    print("\n[2/4] Identifying available quarters...")
    filings_per_date = all_holdings.groupby('filing_date')['cik'].nunique().reset_index()
    filings_per_date.columns = ['filing_date', 'num_institutions']
    major_dates = filings_per_date[filings_per_date['num_institutions'] >= 100].sort_values('filing_date')

    print(f"Found {len(major_dates)} major reporting dates (100+ institutions)")

    # Map each major date to its quarter
    quarters_to_process = []
    for _, row in major_dates.iterrows():
        filing_date = row['filing_date']
        # Infer quarter end from filing date (typically ~45 days after quarter end)
        quarter_month = ((filing_date.month - 2) // 3) * 3 + 3
        if quarter_month <= 0:
            quarter_month = 12
            quarter_year = filing_date.year - 1
        else:
            quarter_year = filing_date.year

        # Adjust for Q1-Q4
        if quarter_month == 3:
            quarter_end = datetime(quarter_year, 3, 31)
        elif quarter_month == 6:
            quarter_end = datetime(quarter_year, 6, 30)
        elif quarter_month == 9:
            quarter_end = datetime(quarter_year, 9, 30)
        else:
            quarter_end = datetime(quarter_year, 12, 31)

        quarters_to_process.append((quarter_end, filing_date))

    # Remove duplicates
    quarters_to_process = list(set([q[0] for q in quarters_to_process]))
    quarters_to_process.sort()

    print(f"Processing {len(quarters_to_process)} quarters")

    # Process each quarter
    print("\n[3/4] Processing quarters...")
    for quarter_end in quarters_to_process:
        try:
            process_quarter_batch(quarter_end, all_holdings)
        except Exception as e:
            print(f"ERROR processing {quarter_end}: {e}")
            continue

    # Build time series
    print("\n[4/4] Building time series and calculating flows...")
    timeseries_df = build_time_series()

    if timeseries_df is not None:
        qoq_df = calculate_qoq_flows(timeseries_df)

        print(f"\n{'='*100}")
        print("PIPELINE COMPLETE")
        print(f"{'='*100}")
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\nOutput files:")
        print(f"  - sector_flows_timeseries_batched.csv")
        print(f"  - sector_qoq_flows_batched.csv")
        print(f"  - {len(quarters_to_process)} quarterly result files in quarterly_results/")
        print(f"{'='*100}")

if __name__ == '__main__':
    main()
