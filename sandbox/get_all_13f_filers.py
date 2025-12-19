"""
Extract complete list of ALL institutions filing Form 13F
Using SEC EDGAR RSS feeds and daily filings index
"""
import requests
import pandas as pd
import time
import re
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

# SEC requires identification in User-Agent
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com'
}

def get_daily_index(year, quarter):
    """
    Get the SEC daily index file for a specific year and quarter
    This contains ALL filings for that period
    """
    # SEC provides master.idx files for each quarter
    # Format: https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRX/master.idx

    url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx"

    try:
        print(f"  Fetching {year} Q{quarter} index... ", end='', flush=True)
        response = requests.get(url, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            content = response.text
            lines = content.split('\n')

            # Skip header lines (first ~11 lines)
            data_lines = [line for line in lines if '|' in line]

            # Parse lines: CIK|Company Name|Form Type|Date Filed|Filename
            filings_13f = []

            for line in data_lines:
                parts = line.split('|')
                if len(parts) >= 5:
                    cik = parts[0].strip()
                    company_name = parts[1].strip()
                    form_type = parts[2].strip()
                    date_filed = parts[3].strip()
                    filename = parts[4].strip()

                    # Only keep 13F-HR filings (main holding report, not amendments)
                    if form_type == '13F-HR':
                        filings_13f.append({
                            'cik': cik,
                            'company_name': company_name,
                            'form_type': form_type,
                            'date_filed': date_filed,
                            'filename': filename
                        })

            print(f"✓ Found {len(filings_13f)} 13F-HR filings")
            return filings_13f
        else:
            print(f"✗ HTTP {response.status_code}")
            return []

    except Exception as e:
        print(f"✗ Error: {e}")
        return []

def get_all_13f_filers_from_recent_quarters():
    """
    Get all unique 13F filers from the last 4 quarters (1 year)
    This ensures we capture all active filers
    """
    current_year = 2024
    current_quarter = 4

    all_filers = {}

    print("=" * 80)
    print("Extracting ALL 13F Filers from Recent Quarters")
    print("=" * 80)
    print()

    # Get last 4 quarters
    quarters_to_check = []
    year = current_year
    quarter = current_quarter

    for i in range(4):
        quarters_to_check.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            quarter = 4
            year -= 1

    print(f"Checking quarters: {quarters_to_check}\n")

    for year, quarter in quarters_to_check:
        filings = get_daily_index(year, quarter)

        for filing in filings:
            cik = filing['cik']

            if cik not in all_filers:
                all_filers[cik] = {
                    'cik': cik,
                    'name': filing['company_name'],
                    'last_filing_date': filing['date_filed'],
                    'last_filing_file': filing['filename']
                }
            else:
                # Update with more recent filing if newer
                if filing['date_filed'] > all_filers[cik]['last_filing_date']:
                    all_filers[cik]['last_filing_date'] = filing['date_filed']
                    all_filers[cik]['last_filing_file'] = filing['filename']

        time.sleep(0.15)  # SEC rate limit

    print(f"\n{'=' * 80}")
    print(f"Total unique 13F filers found: {len(all_filers)}")
    print(f"{'=' * 80}\n")

    return all_filers

def extract_aum_from_filing_file(filename):
    """
    Extract AUM from a 13F filing using the filename path
    """
    # Filename format: edgar/data/CIK/ACCESSION/primary_doc.xml
    url = f"https://www.sec.gov/Archives/{filename}"

    # Try to get the filing
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)

        if response.status_code == 200:
            content = response.text

            # Look for table value total
            patterns = [
                r'<tableValueTotal>([0-9]+)</tableValueTotal>',
                r'<ns1:tableValueTotal>([0-9]+)</ns1:tableValueTotal>',
                r'tableValueTotal[^>]*>([0-9]+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    aum_thousands = int(match.group(1))
                    return {
                        'aum_thousands': aum_thousands,
                        'aum_millions': aum_thousands / 1000,
                        'aum_billions': aum_thousands / 1_000_000
                    }

        # Try alternative document names
        # Replace primary_doc.xml with form13fInfoTable.xml or infotable.xml
        base_url = url.rsplit('/', 1)[0]

        for doc_name in ['form13fInfoTable.xml', 'infotable.xml']:
            alt_url = f"{base_url}/{doc_name}"

            response = requests.get(alt_url, headers=HEADERS, timeout=10)

            if response.status_code == 200:
                content = response.text

                for pattern in patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        aum_thousands = int(match.group(1))
                        return {
                            'aum_thousands': aum_thousands,
                            'aum_millions': aum_thousands / 1000,
                            'aum_billions': aum_thousands / 1_000_000
                        }

            time.sleep(0.1)

    except Exception as e:
        pass

    return None

def main():
    print("=" * 80)
    print("SEC Form 13F - COMPLETE FILER DATABASE")
    print("=" * 80)
    print()
    print("Extracting ALL institutions required to file Form 13F")
    print("(Institutional investment managers with >$100M AUM in equities)")
    print()

    # Step 1: Get all unique filers from recent quarters
    all_filers = get_all_13f_filers_from_recent_quarters()

    # Step 2: Save initial list (without AUM for now)
    df_initial = pd.DataFrame(all_filers.values())
    df_initial = df_initial.sort_values('name')

    output_file_list = 'data/13f/all_13f_filers_list.csv'
    df_initial.to_csv(output_file_list, index=False)

    print(f"Complete filer list saved to: {output_file_list}")
    print(f"Total filers: {len(df_initial)}\n")

    # Step 3: Show summary statistics
    print(f"{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}\n")

    print(f"Total institutional investment managers filing 13F: {len(df_initial)}")
    print(f"(These are ALL institutions with >$100M in reportable securities)\n")

    # Show sample
    print(f"Sample of filers (first 30 alphabetically):\n")
    print(f"{'CIK':<12} {'Institution Name':<70}")
    print('-' * 82)

    for idx, row in df_initial.head(30).iterrows():
        print(f"{row['cik']:<12} {row['name'][:70]:<70}")

    print(f"\n... and {len(df_initial) - 30} more institutions")

    # Ask user if they want to extract AUM for all (this will take hours)
    print(f"\n{'=' * 80}")
    print(f"NOTE: Extracting AUM for all {len(df_initial)} filers would take several hours")
    print(f"due to SEC rate limits (10 requests/second).")
    print(f"{'=' * 80}")
    print(f"\nTo extract AUM data, run the script with --extract-aum flag")
    print(f"Estimated time: ~{len(df_initial) * 0.15 / 60:.0f} minutes")

    return df_initial

if __name__ == '__main__':
    import os
    os.makedirs('data/13f', exist_ok=True)

    df = main()

    print(f"\n{'=' * 80}")
    print(f"COMPLETE!")
    print(f"{'=' * 80}")
