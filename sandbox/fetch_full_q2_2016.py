"""
Full Fetch: Q2 2016 from SEC EDGAR - All 401 Institutions

Fetches complete Q2 2016 quarter data to:
1. Validate historical data availability
2. Generate sector flows for Q2 2016
3. Compare with post-2023 data to show real institutional flow patterns
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
import time

# SEC Configuration
HEADERS = {'User-Agent': 'Trading Research krajcovic@example.com'}
SEC_RATE_LIMIT = 0.1

# Directories
DATA_DIR = Path('data/13f')
HISTORICAL_DIR = DATA_DIR / 'historical_q2_2016'
HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

# Load sector mapping
print("Loading sector mapping...")
sector_mapping = pd.read_csv(DATA_DIR / 'openfigi_ticker_mapping.csv')
sector_mapping = sector_mapping[['cusip', 'sector']].dropna()
sector_mapping = sector_mapping.set_index('cusip')
print(f"Loaded {len(sector_mapping):,} sector mappings")

# Load institutions
institutions_df = pd.read_csv(DATA_DIR / 'top_401_filers.csv')
TRACKED_CIKS = institutions_df['cik'].astype(str).str.zfill(10).tolist()
print(f"Tracking {len(TRACKED_CIKS)} institutions")

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

def fetch_cik_13f_filing_for_quarter(cik, quarter_end):
    """Fetch 13F-HR filing for a CIK for Q2 2016"""
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
    """Find holdings XML URL"""
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
    """Parse holdings XML"""
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

print("="*100)
print("FULL FETCH: Q2 2016 (Quarter ending June 30, 2016)")
print("="*100)

quarter_end = datetime(2016, 6, 30)
print(f"\nQuarter end: {quarter_end.date()}")
print(f"Filing window: {quarter_end.date()} to {(quarter_end + timedelta(days=60)).date()}")
print(f"\nFetching from {len(TRACKED_CIKS)} institutions...")
print(f"Estimated time: ~{len(TRACKED_CIKS) * 0.3 / 60:.1f} minutes\n")

all_holdings = []
successful = 0
failed = 0
failed_ciks = []

for idx, cik in enumerate(TRACKED_CIKS, 1):
    if idx % 20 == 0:
        print(f"Progress: {idx}/{len(TRACKED_CIKS)} institutions ({successful} successful, {failed} failed)")

    filing_info = fetch_cik_13f_filing_for_quarter(cik, quarter_end)

    if not filing_info:
        failed += 1
        failed_ciks.append(cik)
        continue

    accession = filing_info['accession']
    filing_date = filing_info['filing_date']

    xml_url = discover_holdings_xml_url(cik, accession)

    if not xml_url:
        failed += 1
        failed_ciks.append(cik)
        continue

    try:
        xml_response = requests.get(xml_url, headers=HEADERS, timeout=15)
        time.sleep(SEC_RATE_LIMIT)

        if xml_response.status_code == 200:
            holdings = parse_holdings_xml(xml_response.text, cik, filing_date)
            all_holdings.extend(holdings)
            successful += 1
        else:
            failed += 1
            failed_ciks.append(cik)
    except Exception as e:
        failed += 1
        failed_ciks.append(cik)

print("\n" + "="*100)
print("FETCH RESULTS")
print("="*100)
print(f"Successful: {successful}/{len(TRACKED_CIKS)} institutions ({successful/len(TRACKED_CIKS)*100:.1f}%)")
print(f"Failed: {failed}/{len(TRACKED_CIKS)} institutions")
print(f"Total holdings: {len(all_holdings):,}")

if len(all_holdings) > 0:
    # Convert to DataFrame
    holdings_df = pd.DataFrame(all_holdings)

    # Save raw holdings
    holdings_df.to_parquet(HISTORICAL_DIR / 'holdings_q2_2016_full.parquet', index=False)
    print(f"\nSaved raw holdings: {HISTORICAL_DIR / 'holdings_q2_2016_full.parquet'}")

    # Apply sector classification
    print(f"\nClassifying sectors...")
    holdings_df['sector'] = holdings_df['cusip'].apply(get_sector)

    # Get major filing date
    major_filing_date = holdings_df['filing_date'].mode()[0]
    holdings_df = holdings_df[holdings_df['filing_date'] == major_filing_date].copy()

    print(f"Major filing date: {major_filing_date.date()} ({holdings_df['cik'].nunique()} institutions)")

    # Aggregate by sector
    sector_agg = holdings_df.groupby('sector').agg({
        'value_thousands': 'sum',
        'cik': 'nunique',
        'cusip': 'nunique'
    }).reset_index()

    sector_agg.columns = ['sector', 'aum_dollars', 'num_institutions', 'num_stocks']
    sector_agg['aum_billions'] = sector_agg['aum_dollars'] / 1_000_000_000

    total_aum = sector_agg['aum_billions'].sum()
    sector_agg['allocation_%'] = (sector_agg['aum_billions'] / total_aum) * 100

    sector_agg = sector_agg.sort_values('aum_billions', ascending=False)

    print(f"\nSECTOR BREAKDOWN (Q2 2016)")
    print("="*100)
    print(f"{'Sector':<30} {'AUM ($B)':>12} {'Allocation %':>12} {'# Institutions':>15} {'# Stocks':>10}")
    print("-"*100)

    for _, row in sector_agg.iterrows():
        if row['sector'] != 'Other':
            print(f"{row['sector']:<30} ${row['aum_billions']:>11.1f} {row['allocation_%']:>11.1f}% {row['num_institutions']:>14,} {row['num_stocks']:>9,}")

    print("-"*100)
    print(f"{'TOTAL':<30} ${total_aum:>11.1f}B {100.0:>11.1f}% {holdings_df['cik'].nunique():>14,} {holdings_df['cusip'].nunique():>9,}")

    # Save sector aggregates
    sector_agg['quarter'] = '2016-Q2'
    sector_agg['filing_date'] = major_filing_date
    sector_agg.to_csv(HISTORICAL_DIR / 'sector_agg_q2_2016.csv', index=False)

    print(f"\nSaved sector aggregates: {HISTORICAL_DIR / 'sector_agg_q2_2016.csv'}")

    # Compare with latest 2023+ data
    print("\n" + "="*100)
    print("COMPARISON WITH POST-2023 DATA")
    print("="*100)

    # Load latest quarterly result
    quarterly_files = sorted((DATA_DIR / 'quarterly_results').glob('sector_agg_*.csv'))
    if quarterly_files:
        latest_file = quarterly_files[-1]
        latest_df = pd.read_csv(latest_file)
        latest_quarter = latest_df['quarter'].iloc[0]

        print(f"\nComparing Q2 2016 vs {latest_quarter}:")
        print("-"*100)
        print(f"{'Sector':<30} {'2016 AUM':>12} {'2016 %':>10} {f'{latest_quarter} AUM':>12} {f'{latest_quarter} %':>10} {'Change':>12}")
        print("-"*100)

        # Merge data
        comparison = sector_agg[['sector', 'aum_billions', 'allocation_%']].copy()
        comparison.columns = ['sector', 'aum_2016', 'pct_2016']

        latest_agg = latest_df[['sector', 'aum_billions', 'allocation_%']].copy()
        latest_agg.columns = ['sector', 'aum_latest', 'pct_latest']

        comparison = comparison.merge(latest_agg, on='sector', how='outer').fillna(0)
        comparison = comparison.sort_values('aum_latest', ascending=False)

        for _, row in comparison.iterrows():
            if row['sector'] != 'Other':
                pct_change = row['pct_latest'] - row['pct_2016']
                change_sign = '+' if pct_change > 0 else ''
                print(f"{row['sector']:<30} ${row['aum_2016']:>11.1f}B {row['pct_2016']:>9.1f}% ${row['aum_latest']:>11.1f}B {row['pct_latest']:>9.1f}% {change_sign}{pct_change:>10.1f}pp")

        comparison.to_csv(HISTORICAL_DIR / 'comparison_2016_vs_latest.csv', index=False)
        print(f"\nSaved comparison: {HISTORICAL_DIR / 'comparison_2016_vs_latest.csv'}")

else:
    print("\nWARNING: No holdings data fetched!")

print("\n" + "="*100)
print("✓ Full Q2 2016 fetch complete!")
print("="*100)
