"""
Refetch 13F Holdings Data Quarter-by-Quarter - ALL Filing Dates

Memory-Efficient Pipeline:
1. Fetch one quarter's raw 13F-HR filings from SEC (ALL 401 institutions)
2. Parse XML and extract holdings
3. Apply sector classification using ALL filing dates (not just major date)
4. Aggregate to sector level and save results
5. Delete raw data
6. Move to next quarter

This ensures we capture the COMPLETE institutional picture for each quarter.
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
import time
import gc

# SEC Configuration
HEADERS = {'User-Agent': 'Trading Research krajcovic@example.com'}
SEC_RATE_LIMIT = 0.1  # 10 requests per second max

# Directories
DATA_DIR = Path('data/13f')
QUARTERLY_DIR = DATA_DIR / 'quarterly_results_all_dates'
RAW_DIR = DATA_DIR / 'raw_temp'
QUARTERLY_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Load sector mapping
print("Loading sector mapping...")
sector_mapping = pd.read_csv(DATA_DIR / 'openfigi_ticker_mapping.csv')
sector_mapping = sector_mapping[['cusip', 'sector']].dropna()
sector_mapping = sector_mapping.set_index('cusip')
print(f"Loaded {len(sector_mapping):,} sector mappings")

# Load list of institutions to track
institutions_file = DATA_DIR / 'top_401_filers.csv'
institutions_df = pd.read_csv(institutions_file)
TRACKED_CIKS = institutions_df['cik'].astype(str).str.zfill(10).tolist()
print(f"Tracking {len(TRACKED_CIKS)} institutions\n")

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

def get_quarters_to_fetch(start_year=2019, end_year=2025):
    """Generate list of quarters to fetch"""
    quarters = []
    for year in range(start_year, end_year + 1):
        for q in [1, 2, 3, 4]:
            if q == 1:
                quarter_end = datetime(year, 3, 31)
            elif q == 2:
                quarter_end = datetime(year, 6, 30)
            elif q == 3:
                quarter_end = datetime(year, 9, 30)
            else:
                quarter_end = datetime(year, 12, 31)

            # Only fetch completed quarters
            if quarter_end <= datetime.now():
                quarters.append({
                    'year': year,
                    'quarter': q,
                    'quarter_end': quarter_end,
                    'quarter_str': f"{year}-Q{q}"
                })

    return quarters

def fetch_cik_13f_filing_for_quarter(cik, quarter_end):
    """Fetch the 13F-HR filing for a CIK for a specific quarter"""
    filing_start = quarter_end
    filing_end = quarter_end + timedelta(days=60)

    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR&dateb={filing_end.strftime('%Y%m%d')}&datea={filing_start.strftime('%Y%m%d')}&owner=exclude&count=5&output=atom"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        time.sleep(SEC_RATE_LIMIT)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'xml')

            for entry in soup.find_all('entry'):
                filing_date_elem = entry.find('filing-date')
                accession_elem = entry.find('accession-number')

                if filing_date_elem and accession_elem:
                    filing_date = datetime.strptime(filing_date_elem.text.strip(), '%Y-%m-%d')

                    if filing_start <= filing_date <= filing_end:
                        return {
                            'accession': accession_elem.text.strip(),
                            'filing_date': filing_date
                        }

    except Exception as e:
        print(f"    Error fetching filings for CIK {cik}: {e}")

    return None

def discover_holdings_xml_url(cik, accession):
    """Find the holdings XML file URL from filing index"""
    accession_clean = accession.replace('-', '')
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.htm"

    try:
        response = requests.get(index_url, headers=HEADERS, timeout=15)
        time.sleep(SEC_RATE_LIMIT)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.xml' in href.lower() and 'xsl' not in href.lower():
                    if href.startswith('/Archives'):
                        xml_url = f"https://www.sec.gov{href}"
                    elif href.startswith('http'):
                        xml_url = href
                    else:
                        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{href}"

                    if 'primary_doc.xml' not in href.lower():
                        try:
                            test_resp = requests.get(xml_url, headers=HEADERS, timeout=10)
                            time.sleep(SEC_RATE_LIMIT)

                            if test_resp.status_code == 200:
                                content_lower = test_resp.text.lower()
                                if 'infotable' in content_lower and 'cusip' in content_lower:
                                    return xml_url
                        except:
                            continue

    except Exception as e:
        pass

    return None

def parse_holdings_xml(xml_content, cik, filing_date):
    """Parse 13F holdings XML and extract positions"""
    holdings = []

    try:
        root = ET.fromstring(xml_content)
        info_tables = root.findall('.//{*}infoTable')

        if not info_tables:
            info_tables = root.findall('.//infoTable')

        for info_table in info_tables:
            try:
                cusip_elem = info_table.find('.//{*}cusip')
                if cusip_elem is None:
                    cusip_elem = info_table.find('.//cusip')

                if cusip_elem is None:
                    continue

                cusip = cusip_elem.text.strip() if cusip_elem.text else None
                if not cusip:
                    continue

                name_elem = info_table.find('.//{*}nameOfIssuer')
                if name_elem is None:
                    name_elem = info_table.find('.//nameOfIssuer')
                issuer_name = name_elem.text.strip() if name_elem is not None and name_elem.text else ''

                value_elem = info_table.find('.//{*}value')
                if value_elem is None:
                    value_elem = info_table.find('.//value')

                value = 0
                if value_elem is not None and value_elem.text:
                    try:
                        value = float(value_elem.text.strip())
                    except:
                        value = 0

                shares_elem = info_table.find('.//{*}sshPrnamt')
                if shares_elem is None:
                    shares_elem = info_table.find('.//sshPrnamt')

                shares = 0
                if shares_elem is not None and shares_elem.text:
                    try:
                        shares = float(shares_elem.text.strip())
                    except:
                        shares = 0

                holdings.append({
                    'cik': cik,
                    'filing_date': filing_date,
                    'cusip': cusip,
                    'issuer_name': issuer_name,
                    'value_thousands': value,
                    'shares': shares
                })

            except Exception as e:
                continue

    except Exception as e:
        print(f"    Error parsing XML: {e}")

    return holdings

def fetch_quarter_data(quarter_info):
    """
    Fetch all 13F filings for a quarter
    Returns: DataFrame of holdings
    """
    quarter_str = quarter_info['quarter_str']
    quarter_end = quarter_info['quarter_end']

    print(f"\n{'='*100}")
    print(f"FETCHING QUARTER: {quarter_str} (ending {quarter_end.date()})")
    print(f"{'='*100}")

    # Check if already processed
    output_file = QUARTERLY_DIR / f'sector_agg_{quarter_str.lower().replace("-", "_")}.csv'
    if output_file.exists():
        print(f"  ✓ Already processed - skipping")
        return None

    all_holdings = []
    successful_ciks = 0
    failed_ciks = 0

    total_institutions = len(TRACKED_CIKS)

    for idx, cik in enumerate(sorted(TRACKED_CIKS), 1):
        if idx % 20 == 0:
            print(f"  Progress: {idx}/{total_institutions} institutions ({successful_ciks} successful, {failed_ciks} failed)")

        # Find filing for this quarter
        filing_info = fetch_cik_13f_filing_for_quarter(cik, quarter_end)

        if not filing_info:
            failed_ciks += 1
            continue

        accession = filing_info['accession']
        filing_date = filing_info['filing_date']

        # Get holdings XML URL
        xml_url = discover_holdings_xml_url(cik, accession)

        if not xml_url:
            failed_ciks += 1
            continue

        # Download XML
        try:
            xml_response = requests.get(xml_url, headers=HEADERS, timeout=15)
            time.sleep(SEC_RATE_LIMIT)

            if xml_response.status_code == 200:
                holdings = parse_holdings_xml(xml_response.text, cik, filing_date)
                all_holdings.extend(holdings)
                successful_ciks += 1
            else:
                failed_ciks += 1

        except Exception as e:
            failed_ciks += 1
            continue

    print(f"\n  Complete: {successful_ciks} institutions fetched, {failed_ciks} failed")
    print(f"  Total holdings: {len(all_holdings):,}")

    if len(all_holdings) == 0:
        print(f"  WARNING: No holdings data for {quarter_str}")
        return None

    # Convert to DataFrame
    holdings_df = pd.DataFrame(all_holdings)

    # Save raw holdings for this quarter
    raw_file = RAW_DIR / f'holdings_{quarter_str.lower().replace("-", "_")}.parquet'
    holdings_df.to_parquet(raw_file, index=False)
    print(f"  Saved raw holdings: {raw_file.name}")

    return holdings_df

def process_quarter_holdings(holdings_df, quarter_str):
    """
    Process quarter holdings:
    - Apply sector classification to ALL filing dates
    - Aggregate by sector
    - Save results
    - Clean up raw data
    """
    print(f"\n  Processing {quarter_str}...")

    if holdings_df is None or len(holdings_df) == 0:
        return

    # Apply sector classification
    print(f"    Classifying {len(holdings_df):,} holdings across ALL filing dates...")
    holdings_df['sector'] = holdings_df['cusip'].apply(get_sector)

    # Get filing date distribution
    filing_dates = holdings_df.groupby('filing_date')['cik'].nunique().reset_index()
    filing_dates.columns = ['filing_date', 'num_institutions']
    filing_dates = filing_dates.sort_values('filing_date')

    print(f"    Filing dates found: {len(filing_dates)}")
    print(f"    Date range: {filing_dates['filing_date'].min().date()} to {filing_dates['filing_date'].max().date()}")
    print(f"    Total unique institutions: {holdings_df['cik'].nunique()}")

    # CRITICAL: Aggregate ALL filing dates, not just major date
    print(f"    Aggregating ALL {holdings_df['cik'].nunique()} institutions across ALL {len(filing_dates)} filing dates...")

    sector_agg = holdings_df.groupby('sector').agg({
        'value_thousands': 'sum',
        'cik': 'nunique',
        'cusip': 'nunique'
    }).reset_index()

    sector_agg.columns = ['sector', 'aum_dollars', 'num_institutions', 'num_stocks']
    sector_agg['aum_billions'] = sector_agg['aum_dollars'] / 1_000_000_000

    total_aum = sector_agg['aum_billions'].sum()
    sector_agg['allocation_%'] = (sector_agg['aum_billions'] / total_aum) * 100

    # Use the most common filing date for reference
    major_filing_date = holdings_df['filing_date'].mode()[0]

    sector_agg['filing_date'] = major_filing_date
    sector_agg['quarter'] = quarter_str
    sector_agg['num_filing_dates'] = len(filing_dates)
    sector_agg['total_institutions_all_dates'] = holdings_df['cik'].nunique()

    # Save results
    output_file = QUARTERLY_DIR / f'sector_agg_{quarter_str.lower().replace("-", "_")}.csv'
    sector_agg.to_csv(output_file, index=False)

    print(f"    Saved: {output_file.name}")
    print(f"    Total AUM (ALL dates): ${total_aum:.1f}B across {len(sector_agg)} sectors")
    print(f"    Institutions: {holdings_df['cik'].nunique()} across {len(filing_dates)} filing dates")

    # Clean up raw data
    raw_file = RAW_DIR / f'holdings_{quarter_str.lower().replace("-", "_")}.parquet'
    if raw_file.exists():
        raw_file.unlink()
        print(f"    Cleaned up raw data")

    # Force garbage collection
    del holdings_df
    gc.collect()

def build_master_timeseries():
    """Combine all quarterly results into master timeseries"""
    print(f"\n{'='*100}")
    print("BUILDING MASTER TIMESERIES")
    print(f"{'='*100}")

    quarterly_files = sorted(QUARTERLY_DIR.glob('sector_agg_*.csv'))

    if len(quarterly_files) == 0:
        print("No quarterly files found!")
        return

    print(f"Found {len(quarterly_files)} quarterly results")

    all_quarters = []
    for file in quarterly_files:
        df = pd.read_csv(file)
        df['filing_date'] = pd.to_datetime(df['filing_date'])
        all_quarters.append(df)

    timeseries_df = pd.concat(all_quarters, ignore_index=True)
    timeseries_df = timeseries_df.sort_values(['filing_date', 'sector'])

    # Save
    output_file = DATA_DIR / 'sector_flows_timeseries_all_dates.csv'
    timeseries_df.to_csv(output_file, index=False)

    print(f"\nSaved: {output_file.name}")
    print(f"  Records: {len(timeseries_df):,}")
    print(f"  Quarters: {timeseries_df['quarter'].nunique()}")
    print(f"  Date range: {timeseries_df['filing_date'].min().date()} to {timeseries_df['filing_date'].max().date()}")

    return timeseries_df

def main():
    """Main pipeline"""
    print(f"\n{'='*100}")
    print("13F DATA REFETCH PIPELINE - ALL FILING DATES PER QUARTER")
    print(f"{'='*100}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Get quarters to fetch
    quarters = get_quarters_to_fetch(start_year=2019, end_year=2025)
    print(f"Total quarters to fetch: {len(quarters)}")
    print(f"Range: {quarters[0]['quarter_str']} to {quarters[-1]['quarter_str']}")
    print(f"\nStrategy: For each quarter, aggregate ALL filing dates (not just major date)")
    print(f"Expected coverage: ~90% of institutional AUM per quarter\n")

    # Process each quarter
    for quarter_info in quarters:
        try:
            # Fetch raw data
            holdings_df = fetch_quarter_data(quarter_info)

            # Process and save (ALL filing dates)
            if holdings_df is not None:
                process_quarter_holdings(holdings_df, quarter_info['quarter_str'])

        except Exception as e:
            print(f"\nERROR processing {quarter_info['quarter_str']}: {e}")
            continue

    # Build master timeseries
    build_master_timeseries()

    print(f"\n{'='*100}")
    print("PIPELINE COMPLETE")
    print(f"{'='*100}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nResults in: {QUARTERLY_DIR}/")
    print(f"Master file: data/13f/sector_flows_timeseries_all_dates.csv")
    print(f"{'='*100}\n")

if __name__ == '__main__':
    main()
