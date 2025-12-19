"""
Fetch historical 13F holdings for top 401 institutions - Last 20 quarters
- Fetches last 20 quarterly filings for each institution
- Downloads raw XML, parses holdings, saves CSV
- Deletes raw XML to save space
- Creates time-series master file
"""
import requests
import pandas as pd
import time
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# SEC requires identification
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com'
}

def get_file_size_mb(filepath):
    """Get file size in MB"""
    if os.path.exists(filepath):
        return os.path.getsize(filepath) / (1024 * 1024)
    return 0

def get_historical_filings(cik, max_filings=20):
    """
    Get historical 13F-HR filings for a CIK
    Returns: List of (accession, filing_date) tuples
    """
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR&dateb=&owner=exclude&count={max_filings}&output=atom"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'xml')

            filings = []
            for entry in soup.find_all('entry'):
                filing_date = entry.find('filing-date')
                accession = entry.find('accession-number')

                if filing_date and accession:
                    filings.append({
                        'accession': accession.text.strip(),
                        'filing_date': filing_date.text.strip()
                    })

            return filings[:max_filings]

        time.sleep(0.1)
    except Exception as e:
        print(f"      Error fetching historical filings: {e}")

    return []

def discover_holdings_file(cik, accession):
    """Discover the holdings XML file from the filing index page"""
    accession_clean = accession.replace('-', '')
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.htm"

    try:
        response = requests.get(index_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            xml_candidates = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.xml' in href.lower() and 'xsl' not in href.lower():
                    if href.startswith('/Archives'):
                        url = f"https://www.sec.gov{href}"
                    elif href.startswith('http'):
                        url = href
                    else:
                        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{href}"

                    if 'primary_doc.xml' not in href.lower():
                        xml_candidates.append(url)

            for url in xml_candidates:
                try:
                    test_response = requests.get(url, headers=HEADERS, timeout=10)
                    if test_response.status_code == 200:
                        content_lower = test_response.text.lower()
                        if 'infotable' in content_lower and 'cusip' in content_lower:
                            return url
                    time.sleep(0.05)
                except:
                    continue

        time.sleep(0.05)
    except Exception as e:
        pass

    return None

def fetch_13f_holdings(cik, accession, filing_date, institution_name):
    """Fetch and parse 13F holdings"""
    xml_url = discover_holdings_file(cik, accession)
    raw_xml = None

    if xml_url:
        try:
            response = requests.get(xml_url, headers=HEADERS, timeout=15)
            if response.status_code == 200 and '<' in response.text:
                raw_xml = response.text
        except Exception as e:
            pass

    if not raw_xml:
        return None, None

    holdings = []

    try:
        root = ET.fromstring(raw_xml)

        for info_table in root.iter():
            tag_lower = info_table.tag.lower()

            if 'infotable' in tag_lower and info_table.tag != root.tag:
                cusip = None
                issuer = None
                shares = None
                value = None
                put_call = None

                for child in info_table:
                    tag = child.tag.split('}')[-1].lower() if '}' in child.tag else child.tag.lower()

                    if 'cusip' in tag:
                        cusip = child.text
                    elif 'nameofissuer' in tag or 'issuer' in tag:
                        issuer = child.text
                    elif 'value' in tag and 'table' not in tag.lower():
                        try:
                            value = int(child.text) if child.text else None
                        except:
                            pass
                    elif 'shrsorprnamt' in tag or 'sharesamt' in tag:
                        for subchild in child:
                            subtag = subchild.tag.lower()
                            if 'sshprnamt' in subtag or 'shares' in subtag:
                                try:
                                    shares = int(subchild.text) if subchild.text else None
                                except:
                                    pass
                    elif 'putcall' in tag:
                        put_call = child.text

                if cusip and issuer:
                    holdings.append({
                        'cik': cik,
                        'institution_name': institution_name,
                        'filing_date': filing_date,
                        'cusip': cusip,
                        'issuer_name': issuer,
                        'shares': shares if shares else 0,
                        'value_thousands': value if value else 0,
                        'value_millions': round(value / 1000, 2) if value else 0,
                        'position_type': put_call if put_call else 'LONG'
                    })

    except Exception as e:
        return None, raw_xml

    if holdings:
        df = pd.DataFrame(holdings)
        return df, raw_xml

    return None, raw_xml

def main():
    print("=" * 90)
    print("13F HISTORICAL HOLDINGS FETCHER - LAST 20 QUARTERS")
    print("=" * 90)
    print()

    # Create directories
    raw_dir = Path('data/13f/raw_filings_temp')
    holdings_dir = Path('data/13f/holdings_historical')

    raw_dir.mkdir(parents=True, exist_ok=True)
    holdings_dir.mkdir(parents=True, exist_ok=True)

    # Load top 401 institutions
    df_institutions = pd.read_csv('data/13f/top_401_institutions_90pct_aum.csv')

    print(f"Processing {len(df_institutions)} institutions × 20 quarters = {len(df_institutions) * 20} filings")
    print(f"Estimated time: ~{len(df_institutions) * 20 * 0.5 / 60:.0f} minutes")
    print()

    # First pass: Get all historical filing info (or load if already done)
    filings_list_file = Path('data/13f/historical_filings_list.csv')

    if filings_list_file.exists():
        print("=" * 90)
        print("PHASE 1: LOADING PREVIOUSLY DISCOVERED FILINGS")
        print("=" * 90)
        print()
        filings_df = pd.read_csv(filings_list_file)
        print(f"✓ Loaded {len(filings_df):,} filings from previous discovery")
        print(f"  Date range: {filings_df['filing_date'].min()} to {filings_df['filing_date'].max()}")
        print()
    else:
        print("=" * 90)
        print("PHASE 1: DISCOVERING HISTORICAL FILINGS")
        print("=" * 90)
        print()

        all_filings = []

        for i, row in df_institutions.iterrows():
            cik = row['cik']
            name = row['name']

            print(f"[{i+1}/{len(df_institutions)}] {name[:50]}...", end=' ', flush=True)

            filings = get_historical_filings(cik, max_filings=20)

            for filing in filings:
                all_filings.append({
                    'cik': cik,
                    'institution_name': name,
                    'accession': filing['accession'],
                    'filing_date': filing['filing_date']
                })

            print(f"✓ {len(filings)} filings found")
            time.sleep(0.15)

            if (i + 1) % 50 == 0:
                print(f"\n  → Checkpoint: {i+1}/{len(df_institutions)} | Total filings: {len(all_filings)}\n")

        filings_df = pd.DataFrame(all_filings)
        filings_df.to_csv('data/13f/historical_filings_list.csv', index=False)

        print()
        print(f"✓ Discovered {len(filings_df):,} historical filings")
        print(f"  Saved to: data/13f/historical_filings_list.csv")
        print()

    # Second pass: Fetch holdings for each filing
    print("=" * 90)
    print("PHASE 2: FETCHING HOLDINGS DATA")
    print("=" * 90)
    print()

    success_count = 0
    fail_count = 0
    total_holdings = 0

    start_time = datetime.now()

    for i, row in filings_df.iterrows():
        cik = row['cik']
        name = row['institution_name']
        accession = row['accession']
        filing_date = row['filing_date']

        # Check if already downloaded (skip to save time)
        csv_file = holdings_dir / f"{cik}_{filing_date}.csv"
        if csv_file.exists():
            success_count += 1
            continue

        if (i + 1) % 100 == 0:
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            remaining = (len(filings_df) - i - 1) * (elapsed / (i + 1))
            print(f"[{i+1}/{len(filings_df)}] Progress: {(i+1)/len(filings_df)*100:.1f}% | Success: {success_count} | Failed: {fail_count} | ETA: {remaining:.0f}min")

        # Fetch holdings
        holdings_df, raw_xml = fetch_13f_holdings(cik, accession, filing_date, name)

        if holdings_df is not None and len(holdings_df) > 0:
            # Save to CSV (one file per institution-quarter)
            csv_file = holdings_dir / f"{cik}_{filing_date}.csv"
            holdings_df.to_csv(csv_file, index=False)

            success_count += 1
            total_holdings += len(holdings_df)
        else:
            fail_count += 1

        time.sleep(0.15)

    elapsed_total = (datetime.now() - start_time).total_seconds() / 60

    print()
    print("=" * 90)
    print("PHASE 2 COMPLETE - HOLDINGS FETCHED")
    print("=" * 90)
    print()
    print(f"Success: {success_count}/{len(filings_df)} ({success_count/len(filings_df)*100:.1f}%)")
    print(f"Failed: {fail_count}/{len(filings_df)}")
    print(f"Total holdings: {total_holdings:,}")
    print(f"Time: {elapsed_total:.1f} minutes")
    print()

    # Phase 3: Create master time-series file
    print("=" * 90)
    print("PHASE 3: CREATING MASTER TIME-SERIES FILE")
    print("=" * 90)
    print()

    all_holdings = []
    for csv_file in holdings_dir.glob("*.csv"):
        df = pd.read_csv(csv_file)
        all_holdings.append(df)

    master_df = pd.concat(all_holdings, ignore_index=True)

    # Ensure consistent data types
    master_df['cusip'] = master_df['cusip'].astype(str)
    master_df['cik'] = master_df['cik'].astype(int)
    master_df['shares'] = master_df['shares'].astype(int)
    master_df['value_thousands'] = master_df['value_thousands'].astype(int)

    # Save master parquet
    master_file = Path('data/13f/holdings_master_20quarters.parquet')
    master_df.to_parquet(master_file, index=False, compression='snappy')
    master_size = get_file_size_mb(master_file)

    print(f"Master time-series file created: holdings_master_20quarters.parquet")
    print(f"  Total records: {len(master_df):,}")
    print(f"  Size: {master_size:.2f} MB")
    print(f"  Date range: {master_df['filing_date'].min()} to {master_df['filing_date'].max()}")
    print()

    # Delete individual CSVs
    csv_count = 0
    for csv_file in holdings_dir.glob("*.csv"):
        os.remove(csv_file)
        csv_count += 1

    print(f"✓ Deleted {csv_count} individual CSV files")
    print()

    # Cleanup temp directory
    if raw_dir.exists():
        import shutil
        shutil.rmtree(raw_dir)

    print("✓ Historical fetch complete.")
    print(f"✓ Output file: data/13f/holdings_master_20quarters.parquet ({master_size:.2f} MB)")

if __name__ == '__main__':
    main()
