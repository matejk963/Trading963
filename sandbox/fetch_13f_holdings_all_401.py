"""
Fetch 13F holdings for ALL 401 institutions (90% AUM threshold) - PRODUCTION VERSION
- Downloads raw XML
- Parses holdings
- Saves CSV
- Deletes raw XML to save space
- Reports disk usage
"""
import requests
import pandas as pd
import time
import os
import re
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

def get_directory_size_mb(directory):
    """Get total size of directory in MB"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            total += os.path.getsize(filepath)
    return total / (1024 * 1024)

def discover_holdings_file(cik, accession):
    """
    Discover the actual holdings XML file from the filing index page
    Returns: URL of holdings XML file, or None if not found
    """
    accession_clean = accession.replace('-', '')
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.htm"

    try:
        response = requests.get(index_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # Collect all XML files (excluding HTML/XSL versions)
            xml_candidates = []
            for link in soup.find_all('a', href=True):
                href = link['href']

                # Skip HTML versions and XSL stylesheets
                if '.xml' in href.lower() and 'xsl' not in href.lower():
                    # Build full URL
                    if href.startswith('/Archives'):
                        url = f"https://www.sec.gov{href}"
                    elif href.startswith('http'):
                        url = href
                    else:
                        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{href}"

                    # Skip primary_doc.xml (cover page only)
                    if 'primary_doc.xml' not in href.lower():
                        xml_candidates.append(url)

            # Try each candidate - return first one that contains holdings data
            for url in xml_candidates:
                try:
                    test_response = requests.get(url, headers=HEADERS, timeout=10)
                    if test_response.status_code == 200:
                        # Quick check if it contains infoTable elements
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
    """
    Fetch and parse 13F holdings for an institution
    Returns: DataFrame with holdings, raw XML
    """
    # Clean accession number
    accession_clean = accession.replace('-', '')

    # Try to discover the holdings file
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

    # Parse XML
    holdings = []

    try:
        # Try to parse as XML
        root = ET.fromstring(raw_xml)

        # Find all info table entries
        # Different 13F filings use different XML namespaces
        for info_table in root.iter():
            tag_lower = info_table.tag.lower()

            if 'infotable' in tag_lower and info_table.tag != root.tag:
                # Extract fields
                cusip = None
                issuer = None
                shares = None
                value = None
                put_call = None

                for child in info_table:
                    # Extract local name from namespace (e.g. {namespace}localname -> localname)
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
                        # This is a container, look inside
                        for subchild in child:
                            subtag = subchild.tag.lower()
                            if 'sshprnamt' in subtag or 'shares' in subtag:
                                try:
                                    shares = int(subchild.text) if subchild.text else None
                                except:
                                    pass
                    elif 'putcall' in tag:
                        put_call = child.text

                # Add to holdings if we have minimum data
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
        print(f"      XML parse error: {e}")
        return None, raw_xml

    if holdings:
        df = pd.DataFrame(holdings)
        return df, raw_xml

    return None, raw_xml

def main():
    print("=" * 90)
    print("13F HOLDINGS FETCHER - ALL 401 INSTITUTIONS TEST (FIXED)")
    print("=" * 90)
    print()

    # Create directories
    raw_dir = Path('data/13f/raw_filings_temp')
    holdings_dir = Path('data/13f/holdings')
    analysis_dir = Path('data/13f/analysis')

    raw_dir.mkdir(parents=True, exist_ok=True)
    holdings_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Load top 401 institutions
    df_institutions = pd.read_csv('data/13f/top_401_institutions_90pct_aum.csv')

    # Load all filers to get accession numbers
    all_filers = pd.read_csv('data/13f/all_13f_filers_list.csv')

    # Take first 50
    all_401 = df_institutions

    print(f"Processing all 401 institutions...")
    print(f"Estimated time: ~{len(all_401) * 0.3:.1f} minutes")
    print()

    results = []
    success_count = 0
    fail_count = 0
    total_holdings = 0

    raw_sizes = []
    csv_sizes = []

    start_time = datetime.now()

    for i, row in all_401.iterrows():
        cik = row['cik']
        name = row['name']
        filing_date = row['filing_date']

        # Get accession from the all_filers data
        inst_data = all_filers[all_filers['cik'] == cik]

        if len(inst_data) == 0:
            print(f"[{i+1}/{len(all_401)}] {name[:50]} - No filing data found")
            fail_count += 1
            continue

        accession = inst_data.iloc[0]['last_filing_file'].split('/')[-1].replace('.txt', '')

        print(f"[{i+1}/{len(all_401)}] {name[:50]}...", end=' ', flush=True)

        # Fetch holdings
        holdings_df, raw_xml = fetch_13f_holdings(cik, accession, filing_date, name)

        if holdings_df is not None and len(holdings_df) > 0:
            # Save raw XML temporarily
            raw_file = raw_dir / f"{cik}_{filing_date}.xml"
            with open(raw_file, 'w', encoding='utf-8') as f:
                f.write(raw_xml if raw_xml else '')
            raw_size = get_file_size_mb(raw_file)
            raw_sizes.append(raw_size)

            # Save holdings CSV
            csv_file = holdings_dir / f"{cik}_holdings.csv"
            holdings_df.to_csv(csv_file, index=False)
            csv_size = get_file_size_mb(csv_file)
            csv_sizes.append(csv_size)

            # Delete raw XML to save space
            os.remove(raw_file)

            print(f"✓ {len(holdings_df)} holdings | Raw: {raw_size:.2f}MB → CSV: {csv_size:.2f}MB (deleted raw)")

            success_count += 1
            total_holdings += len(holdings_df)

            results.append({
                'cik': cik,
                'name': name,
                'holdings_count': len(holdings_df),
                'total_value_millions': holdings_df['value_millions'].sum()
            })
        else:
            print(f"✗ Failed to fetch")
            fail_count += 1

        time.sleep(0.15)  # SEC rate limit

        # Progress checkpoint every 10
        if (i + 1) % 10 == 0:
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            print(f"\n  → Checkpoint: {i+1}/len(all_401) | Success: {success_count} | Failed: {fail_count} | Time: {elapsed:.1f}min\n")

    elapsed_total = (datetime.now() - start_time).total_seconds() / 60

    print()
    print("=" * 90)
    print("PHASE 1 COMPLETE - DATA FETCHED")
    print("=" * 90)
    print()
    print(f"Success: {success_count}/{len(all_401)} ({success_count/50*100:.1f}%)")
    print(f"Failed: {fail_count}/{len(all_401)}")
    print(f"Total holdings: {total_holdings:,}")
    print(f"Time: {elapsed_total:.1f} minutes")
    print()

    # Disk usage statistics
    print("=" * 90)
    print("DISK USAGE - RAW VS PROCESSED")
    print("=" * 90)
    print()

    if raw_sizes and success_count > 0:
        avg_raw_size = sum(raw_sizes) / len(raw_sizes)
        total_raw_size = sum(raw_sizes)
        avg_csv_size = sum(csv_sizes) / len(csv_sizes)
        total_csv_size = sum(csv_sizes)

        print(f"Average per institution:")
        print(f"  Raw XML:      {avg_raw_size:.2f} MB")
        print(f"  Parsed CSV:   {avg_csv_size:.2f} MB")
        print(f"  Compression:  {(1 - avg_csv_size/avg_raw_size)*100:.1f}% smaller")
        print()
        print(f"Total for {success_count} institutions:")
        print(f"  Raw XML would be:  {total_raw_size:.2f} MB (deleted)")
        print(f"  CSV files:         {total_csv_size:.2f} MB (kept)")
        print()
        print(f"Projected for all 401 institutions:")
        print(f"  Raw XML:           {avg_raw_size * 401:.2f} MB = {avg_raw_size * 401 / 1024:.2f} GB")
        print(f"  CSV files:         {avg_csv_size * 401:.2f} MB = {avg_csv_size * 401 / 1024:.2f} GB")

    print()

    if success_count == 0:
        print("No data to process. Exiting.")
        return

    # PHASE 2: Create master file and aggregations
    print("=" * 90)
    print("PHASE 2 - CREATING MASTER & AGGREGATED FILES")
    print("=" * 90)
    print()

    # Load all holdings CSVs
    all_holdings = []
    for csv_file in holdings_dir.glob("*.csv"):
        df = pd.read_csv(csv_file)
        all_holdings.append(df)

    master_df = pd.concat(all_holdings, ignore_index=True)

    # Ensure consistent data types for Parquet
    master_df['cusip'] = master_df['cusip'].astype(str)
    master_df['cik'] = master_df['cik'].astype(int)
    master_df['shares'] = master_df['shares'].astype(int)
    master_df['value_thousands'] = master_df['value_thousands'].astype(int)

    # Save master parquet
    master_file = Path('data/13f/holdings_master_all401.parquet')
    master_df.to_parquet(master_file, index=False, compression='snappy')
    master_size = get_file_size_mb(master_file)

    print(f"Master file created: holdings_master_all401.parquet")
    print(f"  Records: {len(master_df):,}")
    print(f"  Size: {master_size:.2f} MB")
    print()

    # Aggregate by stock
    agg_df = master_df.groupby(['cusip', 'issuer_name']).agg({
        'institution_name': 'count',
        'shares': 'sum',
        'value_millions': 'sum'
    }).reset_index()

    agg_df.columns = ['cusip', 'issuer_name', 'num_holders', 'total_shares', 'total_value_millions']
    agg_df = agg_df.sort_values('total_value_millions', ascending=False)

    agg_file = Path('data/13f/holdings_aggregated_all401.csv')
    agg_df.to_csv(agg_file, index=False)
    agg_size = get_file_size_mb(agg_file)

    print(f"Aggregated file created: holdings_aggregated_all401.csv")
    print(f"  Unique stocks: {len(agg_df):,}")
    print(f"  Size: {agg_size:.2f} MB")
    print()

    # Delete individual CSV files - only keep master and aggregated
    print("Cleaning up individual CSV files...")
    csv_count = 0
    for csv_file in holdings_dir.glob("*.csv"):
        os.remove(csv_file)
        csv_count += 1
    print(f"  ✓ Deleted {csv_count} individual CSV files")
    print()

    # Top stocks
    print("=" * 90)
    print("TOP 20 MOST HELD STOCKS (by value)")
    print("=" * 90)
    print()
    print(f"{'Rank':<6} {'Stock':<45} {'Holders':<10} {'Total Value ($M)':<20}")
    print('-' * 90)

    for idx, row in enumerate(agg_df.head(20).iterrows(), 1):
        row_data = row[1]
        print(f"{idx:<6} {row_data['issuer_name'][:45]:<45} {row_data['num_holders']:<10} ${row_data['total_value_millions']:>18,.2f}")

    print()
    print("=" * 90)
    print("FINAL DISK USAGE SUMMARY")
    print("=" * 90)
    print()

    print(f"Master parquet:          {master_size:.2f} MB")
    print(f"Aggregated CSV:          {agg_size:.2f} MB")
    print(f"Individual CSVs:         0.00 MB (deleted)")
    print(f"Raw XMLs:                0.00 MB (deleted)")
    print(f"TOTAL:                   {master_size + agg_size:.2f} MB")
    print()

    # Cleanup temp directory
    if raw_dir.exists():
        import shutil
        shutil.rmtree(raw_dir)

    print("✓ Fetch complete. Only master parquet and aggregated CSV retained.")
    print(f"✓ Output files:")
    print(f"  - data/13f/holdings_master_all401.parquet ({master_size:.2f} MB)")
    print(f"  - data/13f/holdings_aggregated_all401.csv ({agg_size:.2f} MB)")

if __name__ == '__main__':
    main()
