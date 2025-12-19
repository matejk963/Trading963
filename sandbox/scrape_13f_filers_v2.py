"""
Scrape SEC EDGAR to identify all institutional investment managers filing Form 13F
and extract their AUM (Assets Under Management) - Using SEC JSON API
"""
import requests
import pandas as pd
import time
import json
from datetime import datetime
import re

# SEC requires identification in User-Agent
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com',
    'Accept': 'application/json'
}

def get_13f_filers_from_submissions():
    """
    Alternative approach: Get 13F filers by searching through recent submissions
    using SEC's newer API
    """
    print("Fetching recent 13F-HR filings...")

    # Use SEC's full-text search API
    # This searches for recent 13F-HR filings
    base_url = "https://efts.sec.gov/LATEST/search-index"

    all_filers = {}
    start_index = 0
    page_size = 100

    for page in range(10):  # Get 10 pages = 1000 filings
        print(f"Fetching page {page + 1} (filings {start_index} to {start_index + page_size})...")

        params = {
            'q': '13F-HR',
            'dateRange': 'all',
            'category': 'form-cat2',  # Quarterly reports category
            'startdt': '2023-01-01',
            'enddt': '2024-12-31',
            'from': start_index,
            'size': page_size
        }

        try:
            response = requests.get(base_url, params=params, headers=HEADERS, timeout=15)

            if response.status_code == 200:
                try:
                    data = response.json()

                    if 'hits' in data and 'hits' in data['hits']:
                        hits = data['hits']['hits']

                        if not hits:
                            print(f"No more results at offset {start_index}")
                            break

                        for hit in hits:
                            source = hit.get('_source', {})

                            cik = source.get('ciks', [''])[0]
                            company_name = source.get('display_names', [''])[0]
                            filing_date = source.get('file_date', '')
                            form_type = source.get('form', '')

                            if cik and '13F' in form_type and cik not in all_filers:
                                all_filers[cik] = {
                                    'cik': cik,
                                    'name': company_name,
                                    'last_filing_date': filing_date
                                }

                        print(f"  Found {len(hits)} filings on this page, {len(all_filers)} unique filers total")

                    else:
                        print(f"Unexpected response structure at offset {start_index}")
                        break

                except json.JSONDecodeError:
                    print(f"Failed to parse JSON response")
                    break

            else:
                print(f"HTTP {response.status_code} error")
                break

            start_index += page_size
            time.sleep(0.15)  # SEC rate limit

        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break

    print(f"\nFound {len(all_filers)} unique 13F filers")
    return all_filers

def get_company_tickers_json():
    """
    Get SEC company tickers JSON for CIK mapping
    """
    url = "https://www.sec.gov/files/company_tickers.json"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        pass

    return None

def get_submission_history(cik):
    """
    Get submission history for a CIK using SEC's submissions API
    """
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching submission for CIK {cik}: {e}")

    return None

def extract_aum_from_13f_xml(accession_number, cik):
    """
    Extract AUM from 13F filing XML
    """
    # Remove hyphens from accession number for URL
    accession = accession_number.replace('-', '')
    cik_padded = str(cik).zfill(10)

    # Build URL to filing directory
    base_url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession_number}"

    # Alternative: Direct XML access
    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml"

    try:
        response = requests.get(xml_url, headers=HEADERS, timeout=10)

        if response.status_code == 200:
            content = response.text

            # Look for table value total in XML
            patterns = [
                r'<tableValueTotal>([0-9]+)</tableValueTotal>',
                r'<ns1:tableValueTotal>([0-9]+)</ns1:tableValueTotal>',
                r'<tableEntryTotal>([0-9]+)</tableEntryTotal>',
                r'tableValueTotal[^>]*>([0-9]+)<'
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

        # Try form13fInfoTable.xml
        info_table_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/form13fInfoTable.xml"
        response2 = requests.get(info_table_url, headers=HEADERS, timeout=10)

        if response2.status_code == 200:
            content = response2.text

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    aum_thousands = int(match.group(1))
                    return {
                        'aum_thousands': aum_thousands,
                        'aum_millions': aum_thousands / 1000,
                        'aum_billions': aum_thousands / 1_000_000
                    }

    except Exception as e:
        pass

    return None

def main():
    print("=" * 80)
    print("SEC EDGAR Form 13F Filer Analysis (JSON API)")
    print("=" * 80)
    print()

    # Step 1: Get list of recent 13F filers
    filers = get_13f_filers_from_submissions()

    if not filers:
        print("\nNo filers found. Exiting.")
        return

    print(f"\n{'=' * 80}")
    print(f"Extracting AUM for {len(filers)} filers...")
    print(f"{'=' * 80}\n")

    # Step 2: Get detailed info and AUM for each filer
    results = []

    for i, (cik, info) in enumerate(filers.items(), 1):
        print(f"[{i}/{len(filers)}] {info['name'][:60]}... ", end='', flush=True)

        # Get submission history
        submission_data = get_submission_history(cik)

        if submission_data:
            # Find latest 13F-HR filing
            filings = submission_data.get('filings', {}).get('recent', {})

            if filings:
                forms = filings.get('form', [])
                accessions = filings.get('accessionNumber', [])
                filing_dates = filings.get('filingDate', [])

                # Find first 13F-HR
                for j, form in enumerate(forms):
                    if '13F-HR' in form:
                        accession = accessions[j]
                        filing_date = filing_dates[j]

                        # Extract AUM
                        aum_data = extract_aum_from_13f_xml(accession, cik)

                        if aum_data:
                            results.append({
                                'CIK': cik,
                                'Name': info['name'],
                                'Last Filing Date': filing_date,
                                'Accession': accession,
                                'AUM (Thousands)': aum_data['aum_thousands'],
                                'AUM (Millions)': aum_data['aum_millions'],
                                'AUM (Billions)': aum_data['aum_billions']
                            })
                            print(f"✓ ${aum_data['aum_billions']:.2f}B")
                        else:
                            results.append({
                                'CIK': cik,
                                'Name': info['name'],
                                'Last Filing Date': filing_date,
                                'Accession': accession,
                                'AUM (Thousands)': None,
                                'AUM (Millions)': None,
                                'AUM (Billions)': None
                            })
                            print("✗ No AUM found")

                        break  # Only process latest 13F
                else:
                    print("✗ No 13F-HR found")
                    results.append({
                        'CIK': cik,
                        'Name': info['name'],
                        'Last Filing Date': info.get('last_filing_date'),
                        'Accession': None,
                        'AUM (Thousands)': None,
                        'AUM (Millions)': None,
                        'AUM (Billions)': None
                    })
            else:
                print("✗ No filings data")
        else:
            print("✗ No submission data")

        time.sleep(0.12)  # SEC rate limit

        # Save intermediate results
        if i % 25 == 0:
            df = pd.DataFrame(results)
            df.to_csv('data/13f/13f_filers_intermediate.csv', index=False)
            print(f"\n→ Intermediate results saved ({i} filers processed)\n")

    # Step 3: Create final dataframe and save
    df = pd.DataFrame(results)

    # Sort by AUM
    df_sorted = df.sort_values('AUM (Billions)', ascending=False, na_position='last')

    # Save to CSV
    output_file = 'data/13f/13f_filers_aum.csv'
    df_sorted.to_csv(output_file, index=False)

    print(f"\n{'=' * 80}")
    print(f"RESULTS SUMMARY")
    print(f"{'=' * 80}\n")

    print(f"Total filers identified: {len(df)}")
    print(f"Filers with AUM data: {df['AUM (Billions)'].notna().sum()}")
    print(f"Filers without AUM data: {df['AUM (Billions)'].isna().sum()}")
    print(f"\nResults saved to: {output_file}")

    # Show top 30
    print(f"\n{'=' * 80}")
    print(f"TOP 30 INSTITUTIONAL MANAGERS BY AUM")
    print(f"{'=' * 80}\n")

    top_30 = df_sorted[df_sorted['AUM (Billions)'].notna()].head(30)

    if len(top_30) > 0:
        print(f"{'Rank':<6} {'Name':<60} {'AUM ($B)':<12} {'Filing Date':<12}")
        print('-' * 90)

        for idx, (i, row) in enumerate(top_30.iterrows(), 1):
            print(f"{idx:<6} {row['Name'][:60]:<60} ${row['AUM (Billions)']:>10,.2f}  {row['Last Filing Date']:<12}")
    else:
        print("No filers with AUM data found")

if __name__ == '__main__':
    import os
    os.makedirs('data/13f', exist_ok=True)

    main()
