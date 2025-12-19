"""
Extract AUM from all 13F filers and provide comprehensive statistics
"""
import pandas as pd
import requests
import time
import re
from datetime import datetime

# SEC requires identification in User-Agent
HEADERS = {
    'User-Agent': 'Trading Research krajcovic@example.com'
}

def extract_aum_from_filing_file(cik, filename):
    """
    Extract AUM from a 13F filing using the filename path
    """
    # Build URL to the filing document
    url = f"https://www.sec.gov/Archives/{filename}"

    patterns = [
        r'<tableValueTotal>([0-9]+)</tableValueTotal>',
        r'<ns1:tableValueTotal>([0-9]+)</ns1:tableValueTotal>',
        r'tableValueTotal[^>]*>([0-9]+)',
    ]

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)

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

        # Try alternative document paths
        accession = filename.split('/')[-1].replace('.txt', '')
        base_url = url.rsplit('/', 1)[0]

        for doc_name in ['primary_doc.xml', 'form13fInfoTable.xml', 'infotable.xml']:
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

            time.sleep(0.05)

    except Exception as e:
        pass

    return None

def main():
    print("=" * 90)
    print("EXTRACTING AUM FOR ALL 13F FILERS")
    print("=" * 90)
    print()

    # Load all filers
    df = pd.read_csv('data/13f/all_13f_filers_list.csv')
    total = len(df)

    print(f"Total institutions to process: {total:,}")
    print(f"Estimated time: ~{total * 0.15 / 60:.1f} minutes")
    print()

    start_time = datetime.now()
    results = []
    success_count = 0
    fail_count = 0

    for i, row in df.iterrows():
        cik = row['cik']
        name = row['name']
        filing_file = row['last_filing_file']
        filing_date = row['last_filing_date']

        # Progress indicator
        if i % 100 == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            print(f"[{i}/{total}] {i/total*100:.1f}% | Success: {success_count} | Failed: {fail_count} | ETA: {remaining/60:.1f}min")

        # Extract AUM
        aum_data = extract_aum_from_filing_file(cik, filing_file)

        if aum_data:
            results.append({
                'cik': cik,
                'name': name,
                'filing_date': filing_date,
                'aum_thousands': aum_data['aum_thousands'],
                'aum_millions': aum_data['aum_millions'],
                'aum_billions': aum_data['aum_billions']
            })
            success_count += 1
        else:
            results.append({
                'cik': cik,
                'name': name,
                'filing_date': filing_date,
                'aum_thousands': None,
                'aum_millions': None,
                'aum_billions': None
            })
            fail_count += 1

        # SEC rate limit
        time.sleep(0.12)

        # Save intermediate results every 500 filers
        if (i + 1) % 500 == 0:
            df_temp = pd.DataFrame(results)
            df_temp.to_csv('data/13f/all_13f_filers_aum_intermediate.csv', index=False)
            print(f"  → Checkpoint saved at {i+1} filers")

    # Final save
    df_final = pd.DataFrame(results)
    df_final = df_final.sort_values('aum_billions', ascending=False, na_position='last')

    output_file = 'data/13f/all_13f_filers_aum_complete.csv'
    df_final.to_csv(output_file, index=False)

    elapsed_total = (datetime.now() - start_time).total_seconds()

    print()
    print("=" * 90)
    print("EXTRACTION COMPLETE")
    print("=" * 90)
    print()
    print(f"Total time: {elapsed_total/60:.1f} minutes")
    print(f"Results saved to: {output_file}")
    print()

    # STATISTICS
    print("=" * 90)
    print("COMPREHENSIVE STATISTICS")
    print("=" * 90)
    print()

    df_with_aum = df_final[df_final['aum_billions'].notna()]

    print(f"Total institutions processed: {len(df_final):,}")
    print(f"Institutions with AUM data: {len(df_with_aum):,} ({len(df_with_aum)/len(df_final)*100:.1f}%)")
    print(f"Institutions without AUM data: {fail_count:,} ({fail_count/len(df_final)*100:.1f}%)")
    print()

    if len(df_with_aum) > 0:
        print("AUM STATISTICS (for institutions with data):")
        print("-" * 90)
        print(f"Total AUM (all institutions): ${df_with_aum['aum_billions'].sum():,.2f} billion")
        print(f"Mean AUM: ${df_with_aum['aum_billions'].mean():,.2f} billion")
        print(f"Median AUM: ${df_with_aum['aum_billions'].median():,.2f} billion")
        print(f"Minimum AUM: ${df_with_aum['aum_billions'].min():,.2f} billion")
        print(f"Maximum AUM: ${df_with_aum['aum_billions'].max():,.2f} billion")
        print()

        # Percentiles
        print("AUM DISTRIBUTION (Percentiles):")
        print("-" * 90)
        for p in [10, 25, 50, 75, 90, 95, 99]:
            value = df_with_aum['aum_billions'].quantile(p/100)
            print(f"{p}th percentile: ${value:,.2f} billion")
        print()

        # Size categories
        print("INSTITUTIONS BY SIZE:")
        print("-" * 90)
        mega = len(df_with_aum[df_with_aum['aum_billions'] >= 1000])
        large = len(df_with_aum[(df_with_aum['aum_billions'] >= 100) & (df_with_aum['aum_billions'] < 1000)])
        medium = len(df_with_aum[(df_with_aum['aum_billions'] >= 10) & (df_with_aum['aum_billions'] < 100)])
        small = len(df_with_aum[(df_with_aum['aum_billions'] >= 1) & (df_with_aum['aum_billions'] < 10)])
        tiny = len(df_with_aum[df_with_aum['aum_billions'] < 1])

        print(f"Mega (≥$1 trillion):    {mega:>6,} ({mega/len(df_with_aum)*100:>5.1f}%)")
        print(f"Large ($100B-$1T):      {large:>6,} ({large/len(df_with_aum)*100:>5.1f}%)")
        print(f"Medium ($10B-$100B):    {medium:>6,} ({medium/len(df_with_aum)*100:>5.1f}%)")
        print(f"Small ($1B-$10B):       {small:>6,} ({small/len(df_with_aum)*100:>5.1f}%)")
        print(f"Tiny (<$1B):            {tiny:>6,} ({tiny/len(df_with_aum)*100:>5.1f}%)")
        print()

        # Top 50
        print("=" * 90)
        print("TOP 50 INSTITUTIONS BY AUM")
        print("=" * 90)
        print()

        top_50 = df_with_aum.head(50)
        print(f"{'Rank':<6} {'Institution':<60} {'AUM ($B)':<15}")
        print('-' * 91)

        for rank, (idx, row) in enumerate(top_50.iterrows(), 1):
            print(f"{rank:<6} {row['name'][:60]:<60} ${row['aum_billions']:>13,.2f}")

if __name__ == '__main__':
    import os
    os.makedirs('data/13f', exist_ok=True)

    main()
