"""
Scrape SEC EDGAR to identify all institutional investment managers filing Form 13F
and extract their AUM (Assets Under Management)
"""
import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime
import re

# SEC requires identification in User-Agent
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com',
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov'
}

def get_recent_13f_filings(max_filings=500):
    """
    Get recent 13F filings from SEC EDGAR to identify active filers
    """
    print("Fetching recent 13F filings from SEC EDGAR...")

    # SEC EDGAR search for 13F-HR filings
    # We'll use the RSS feed or search endpoint
    base_url = "https://www.sec.gov/cgi-bin/browse-edgar"

    all_filers = {}

    # Get multiple pages of 13F filings
    for start in range(0, max_filings, 100):
        params = {
            'action': 'getcompany',
            'type': '13F-HR',
            'dateb': '',
            'owner': 'exclude',
            'start': start,
            'count': 100,
            'search_text': ''
        }

        print(f"Fetching filings {start} to {start+100}...")

        try:
            response = requests.get(base_url, params=params, headers=HEADERS, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find all company links
            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                print(f"No more filings found at offset {start}")
                break

            rows = table.find_all('tr')[1:]  # Skip header

            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    # Extract CIK from the link
                    cik_link = cols[0].find('a')
                    if cik_link:
                        cik = cik_link.get('href', '').split('CIK=')[1].split('&')[0] if 'CIK=' in cik_link.get('href', '') else None
                        company_name = cik_link.text.strip()
                        filing_date = cols[3].text.strip() if len(cols) > 3 else None

                        if cik and cik not in all_filers:
                            all_filers[cik] = {
                                'cik': cik,
                                'name': company_name,
                                'last_filing_date': filing_date
                            }

            time.sleep(0.15)  # Respect SEC rate limit (10 req/sec max)

        except Exception as e:
            print(f"Error fetching page at offset {start}: {e}")
            break

    print(f"\nFound {len(all_filers)} unique 13F filers")
    return all_filers

def get_latest_13f_aum(cik, company_name):
    """
    Get the AUM from the latest 13F filing for a given CIK
    """
    # Format CIK with leading zeros (10 digits)
    cik_padded = str(cik).zfill(10)

    # First, get the latest filing
    url = f"https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        'action': 'getcompany',
        'CIK': cik,
        'type': '13F-HR',
        'dateb': '',
        'owner': 'exclude',
        'count': 1,
        'search_text': ''
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the documents link
        table = soup.find('table', {'class': 'tableFile2'})
        if not table:
            return None

        # Find the link to the filing
        doc_link = table.find('a', {'id': 'documentsbutton'})
        if not doc_link:
            return None

        filing_url = 'https://www.sec.gov' + doc_link['href']

        time.sleep(0.15)

        # Get the filing page
        filing_response = requests.get(filing_url, headers=HEADERS, timeout=10)
        filing_response.raise_for_status()

        filing_soup = BeautifulSoup(filing_response.content, 'html.parser')

        # Find the primary document (usually form13fInfoTable.xml or .html)
        doc_table = filing_soup.find('table', {'class': 'tableFile'})
        if not doc_table:
            return None

        # Look for the primary document or information table
        aum = None
        filing_date = None

        for row in doc_table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 3:
                doc_type = cols[3].text.strip() if len(cols) > 3 else ''
                doc_name = cols[2].text.strip() if len(cols) > 2 else ''

                # Look for primary document or cover page
                if '13F-HR' in doc_type or 'primary_doc' in doc_name.lower():
                    doc_href = cols[2].find('a')
                    if doc_href:
                        doc_url = 'https://www.sec.gov' + doc_href['href']

                        time.sleep(0.15)

                        # Get the document
                        doc_response = requests.get(doc_url, headers=HEADERS, timeout=10)
                        doc_response.raise_for_status()

                        # Try to parse as XML first
                        try:
                            # Look for table value total amount
                            content = doc_response.text

                            # Try XML parsing
                            if '<?xml' in content:
                                root = ET.fromstring(content)
                                # Look for tableValueTotal or similar
                                for elem in root.iter():
                                    if 'tablevaluetotal' in elem.tag.lower() or 'totalvalue' in elem.tag.lower():
                                        aum = elem.text
                                        break

                            # Try HTML parsing
                            doc_soup = BeautifulSoup(content, 'html.parser')

                            # Look for table value total in text
                            text = doc_soup.get_text()

                            # Pattern: "Table Value Total: $XXX" or similar
                            patterns = [
                                r'table\s+(?:entry\s+)?value\s+total[:\s]+\$?\s*([0-9,]+)',
                                r'total\s+value[:\s]+\$?\s*([0-9,]+)',
                                r'tableValueTotal[>\s]+([0-9,]+)'
                            ]

                            for pattern in patterns:
                                match = re.search(pattern, text, re.IGNORECASE)
                                if match:
                                    aum = match.group(1).replace(',', '')
                                    break

                            if aum:
                                break

                        except Exception as e:
                            print(f"Error parsing document for {company_name} (CIK: {cik}): {e}")
                            continue

        if aum:
            try:
                # Convert to billions
                aum_value = float(aum) / 1000  # SEC reports in thousands, convert to millions
                return {
                    'aum_millions': aum_value,
                    'aum_billions': aum_value / 1000
                }
            except:
                return None

        return None

    except Exception as e:
        print(f"Error fetching AUM for {company_name} (CIK: {cik}): {e}")
        return None

def main():
    print("=" * 80)
    print("SEC EDGAR Form 13F Filer Analysis")
    print("=" * 80)
    print()

    # Step 1: Get list of recent 13F filers
    filers = get_recent_13f_filings(max_filings=500)

    print(f"\n{'=' * 80}")
    print(f"Extracting AUM for {len(filers)} filers...")
    print(f"{'=' * 80}\n")

    # Step 2: Get AUM for each filer
    results = []

    for i, (cik, info) in enumerate(filers.items(), 1):
        print(f"[{i}/{len(filers)}] Processing {info['name'][:50]}... ", end='', flush=True)

        aum_data = get_latest_13f_aum(cik, info['name'])

        if aum_data:
            results.append({
                'CIK': cik,
                'Name': info['name'],
                'Last Filing Date': info['last_filing_date'],
                'AUM (Millions)': aum_data['aum_millions'],
                'AUM (Billions)': aum_data['aum_billions']
            })
            print(f"✓ ${aum_data['aum_billions']:.2f}B")
        else:
            results.append({
                'CIK': cik,
                'Name': info['name'],
                'Last Filing Date': info['last_filing_date'],
                'AUM (Millions)': None,
                'AUM (Billions)': None
            })
            print("✗ No AUM found")

        # Be respectful of SEC servers
        time.sleep(0.15)

        # Save intermediate results every 50 filers
        if i % 50 == 0:
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

    # Show top 20
    print(f"\n{'=' * 80}")
    print(f"TOP 20 INSTITUTIONAL MANAGERS BY AUM")
    print(f"{'=' * 80}\n")

    top_20 = df_sorted[df_sorted['AUM (Billions)'].notna()].head(20)

    print(f"{'Rank':<6} {'Name':<50} {'AUM (Billions)':<15} {'Last Filing':<15}")
    print('-' * 86)

    for idx, (i, row) in enumerate(top_20.iterrows(), 1):
        print(f"{idx:<6} {row['Name'][:50]:<50} ${row['AUM (Billions)']:>13,.2f}  {row['Last Filing Date']:<15}")

if __name__ == '__main__':
    # Create output directory
    import os
    os.makedirs('data/13f', exist_ok=True)

    main()
