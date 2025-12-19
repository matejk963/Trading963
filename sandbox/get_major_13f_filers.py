"""
Get 13F data for major institutional investment managers
Using known CIKs for major hedge funds and asset managers
"""
import requests
import pandas as pd
import time
import re
from datetime import datetime

# SEC requires identification in User-Agent
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com'
}

# Major institutional investors (CIK numbers)
MAJOR_INSTITUTIONS = {
    # Mega Asset Managers
    '0001364742': 'VANGUARD GROUP INC',
    '0001085146': 'BLACKROCK INC.',
    '0001364742': 'STATE STREET CORP',
    '0000352933': 'FIDELITY',
    '0001633989': 'T. ROWE PRICE',
    '0000315066': 'CAPITAL WORLD INVESTORS',

    # Hedge Funds - Famous Managers
    '0001067983': 'BERKSHIRE HATHAWAY INC (Warren Buffett)',
    '0001350694': 'BRIDGEWATER ASSOCIATES',
    '0001567619': 'CITADEL ADVISORS LLC',
    '0001336528': 'MILLENNIUM MANAGEMENT LLC',
    '0001040273': 'DE SHAW & CO',
    '0001513152': 'TWO SIGMA INVESTMENTS',
    '0001567547': 'RENAISSANCE TECHNOLOGIES LLC',
    '0001040693': 'BAUPOST GROUP LLC (Seth Klarman)',
    '0001037389': 'SOROS FUND MANAGEMENT LLC (George Soros)',
    '0001555283': 'PERSHING SQUARE CAPITAL (Bill Ackman)',
    '0001336921': 'ICAHN CARL C (Carl Icahn)',
    '0001104659': 'THIRD POINT LLC (Dan Loeb)',
    '0001079114': 'APPALOOSA LP (David Tepper)',
    '0001649339': 'ARK INVESTMENT MANAGEMENT (Cathie Wood)',
    '0001166559': 'COATUE MANAGEMENT',
    '0001061768': 'TIGER GLOBAL MANAGEMENT',

    # Major Banks / Investment Banks
    '0001029160': 'MORGAN STANLEY',
    '0000070858': 'BANK OF AMERICA CORP',
    '0000200245': 'JPMORGAN CHASE & CO',
    '0000886982': 'GOLDMAN SACHS GROUP INC',
    '0000851968': 'WELLS FARGO',
    '0000794367': 'NORTHERN TRUST CORP',

    # Pension Funds
    '0000731766': 'CALIFORNIA PUBLIC EMPLOYEES RETIREMENT SYSTEM (CalPERS)',
    '0001108743': 'CALIFORNIA STATE TEACHERS RETIREMENT SYSTEM (CalSTRS)',

    # Other Notable
    '0001061768': 'VIKING GLOBAL INVESTORS',
    '0001408198': 'POINT72 ASSET MANAGEMENT (Steve Cohen)',
    '0001182744': 'WELLINGTON MANAGEMENT',
    '0000922621': 'GEODE CAPITAL MANAGEMENT',
}

def get_latest_13f_filing(cik, company_name):
    """
    Get latest 13F filing details for a CIK using SEC submissions API
    """
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        print(f"  Fetching data for {company_name[:50]}... ", end='', flush=True)
        response = requests.get(url, headers=HEADERS, timeout=15)

        if response.status_code == 200:
            data = response.json()

            # Get recent filings
            filings = data.get('filings', {}).get('recent', {})

            if not filings:
                print("✗ No filings found")
                return None

            forms = filings.get('form', [])
            accessions = filings.get('accessionNumber', [])
            filing_dates = filings.get('filingDate', [])
            primary_docs = filings.get('primaryDocument', [])

            # Find latest 13F-HR
            for i, form in enumerate(forms):
                if form == '13F-HR' or form == '13F-HR/A':
                    accession = accessions[i]
                    filing_date = filing_dates[i]
                    primary_doc = primary_docs[i] if i < len(primary_docs) else None

                    # Try to extract AUM
                    aum_data = extract_aum_from_filing(cik, accession, filing_date)

                    if aum_data:
                        print(f"✓ ${aum_data['aum_billions']:.2f}B ({filing_date})")
                        return {
                            'cik': cik,
                            'name': company_name,
                            'filing_date': filing_date,
                            'accession': accession,
                            **aum_data
                        }
                    else:
                        print(f"✓ Filed {filing_date} (AUM not extracted)")
                        return {
                            'cik': cik,
                            'name': company_name,
                            'filing_date': filing_date,
                            'accession': accession,
                            'aum_thousands': None,
                            'aum_millions': None,
                            'aum_billions': None
                        }

            print("✗ No 13F-HR found")
            return None

        else:
            print(f"✗ HTTP {response.status_code}")
            return None

    except Exception as e:
        print(f"✗ Error: {e}")
        return None

def extract_aum_from_filing(cik, accession_number, filing_date):
    """
    Extract AUM from 13F filing by trying multiple document locations
    """
    # Remove hyphens from accession number for URL path
    accession_path = accession_number.replace('-', '')

    # Try multiple possible file locations
    urls_to_try = [
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/primary_doc.xml",
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/form13fInfoTable.xml",
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/infotable.xml",
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{accession_number}.txt",
    ]

    patterns = [
        r'<tableValueTotal>([0-9]+)</tableValueTotal>',
        r'<ns1:tableValueTotal>([0-9]+)</ns1:tableValueTotal>',
        r'<value>([0-9]+)</value>.*?tableValueTotal',
        r'tableValueTotal[^>]*>([0-9]+)',
        r'TOTAL VALUE.*?(\d{1,3}(?:,\d{3})*)',
    ]

    for url in urls_to_try:
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)

            if response.status_code == 200:
                content = response.text

                for pattern in patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                    if match:
                        aum_str = match.group(1).replace(',', '')
                        try:
                            aum_thousands = int(aum_str)
                            # SEC reports in thousands of dollars
                            return {
                                'aum_thousands': aum_thousands,
                                'aum_millions': aum_thousands / 1000,
                                'aum_billions': aum_thousands / 1_000_000
                            }
                        except ValueError:
                            continue

            time.sleep(0.1)

        except Exception as e:
            continue

    return None

def main():
    print("=" * 90)
    print("SEC Form 13F - Major Institutional Investors Analysis")
    print("=" * 90)
    print(f"\nAnalyzing {len(MAJOR_INSTITUTIONS)} major institutional investment managers\n")

    results = []

    for cik, name in MAJOR_INSTITUTIONS.items():
        filing_data = get_latest_13f_filing(cik, name)

        if filing_data:
            results.append(filing_data)

        time.sleep(0.12)  # Respect SEC rate limit

    # Create DataFrame
    df = pd.DataFrame(results)

    if len(df) > 0:
        # Sort by AUM
        df_sorted = df.sort_values('aum_billions', ascending=False, na_position='last')

        # Save to CSV
        output_file = 'data/13f/major_13f_filers_aum.csv'
        df_sorted.to_csv(output_file, index=False)

        print(f"\n{'=' * 90}")
        print(f"RESULTS")
        print(f"={'=' * 90}\n")

        print(f"Total institutions analyzed: {len(MAJOR_INSTITUTIONS)}")
        print(f"Institutions with 13F data: {len(df)}")
        print(f"Institutions with AUM data: {df['aum_billions'].notna().sum()}")
        print(f"\nResults saved to: {output_file}\n")

        print(f"{'=' * 90}")
        print(f"MAJOR INSTITUTIONAL INVESTORS BY AUM")
        print(f"={'=' * 90}\n")

        # Show all results
        print(f"{'Rank':<6} {'Institution':<55} {'AUM ($B)':<15} {'Filing Date':<15}")
        print('-' * 91)

        for idx, (i, row) in enumerate(df_sorted.iterrows(), 1):
            aum_str = f"${row['aum_billions']:,.2f}" if pd.notna(row['aum_billions']) else 'N/A'
            print(f"{idx:<6} {row['name'][:55]:<55} {aum_str:<15} {row['filing_date']:<15}")

    else:
        print("\n✗ No data could be retrieved")

if __name__ == '__main__':
    import os
    os.makedirs('data/13f', exist_ok=True)

    main()
