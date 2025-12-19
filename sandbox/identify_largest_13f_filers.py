"""
Identify largest institutional investors from the complete 13F filers list
by filtering for known major institutions, banks, and asset managers
"""
import pandas as pd
import re

# Known major institutions - name patterns to search for
MAJOR_INSTITUTION_PATTERNS = {
    # Mega Asset Managers
    'Mega Asset Managers': [
        'VANGUARD', 'BLACKROCK', 'STATE STREET', 'FIDELITY', 'INVESCO',
        'CAPITAL GROUP', 'T. ROWE PRICE', 'FRANKLIN', 'JPMORGAN',
        'MORGAN STANLEY', 'BANK OF AMERICA', 'WELLS FARGO', 'NORTHERN TRUST',
        'BNY MELLON', 'CHARLES SCHWAB', 'GOLDMAN SACHS', 'GEODE CAPITAL',
        'DIMENSIONAL FUND', 'LEGAL & GENERAL', 'AMUNDI', 'NUVEEN',
        'PRINCIPAL FINANCIAL', 'PRUDENTIAL', 'TIAA', 'PIMCO'
    ],

    # Major Hedge Funds
    'Hedge Funds': [
        'BRIDGEWATER', 'CITADEL', 'MILLENNIUM', 'RENAISSANCE TECH',
        'TWO SIGMA', 'DE SHAW', 'ELLIOT', 'BAUPOST', 'VIKING',
        'TIGER GLOBAL', 'COATUE', 'POINT72', 'APPALOOSA', 'PERSHING SQUARE',
        'THIRD POINT', 'GREENLIGHT', 'PAULSON', 'SOROS', 'ICAHN',
        'GLENVIEW', 'JANA PARTNERS', 'LONE PINE', 'MAVERICK',
        'CANYON CAPITAL', 'ANCHORAGE', 'FARALLON', 'CITADEL',
        'LANSDOWNE', 'MAVERICK', 'OAK HILL', 'JANA', 'VALUEACT'
    ],

    # Famous Investors / Family Offices
    'Famous Investors': [
        'BERKSHIRE HATHAWAY', 'BUFFETT', 'ARK INVEST', 'CATHIE WOOD',
        'BILL ACKMAN', 'CARL ICAHN', 'DAVID TEPPER', 'SETH KLARMAN',
        'DAN LOEB', 'DAVID EINHORN', 'STEVE COHEN', 'RAY DALIO',
        'BILL GROSS', 'STANLEY DRUCKENMILLER', 'GEORGE SOROS'
    ],

    # Major Banks & Investment Banks
    'Banks': [
        'JPMORGAN', 'BANK OF AMERICA', 'CITIGROUP', 'WELLS FARGO',
        'GOLDMAN SACHS', 'MORGAN STANLEY', 'UBS', 'CREDIT SUISSE',
        'DEUTSCHE BANK', 'BARCLAYS', 'HSBC', 'BNP PARIBAS',
        'NOMURA', 'RBC', 'TD BANK', 'BMO', 'SCOTIABANK'
    ],

    # Insurance Companies
    'Insurance': [
        'METLIFE', 'PRUDENTIAL', 'AIG', 'ALLIANZ', 'AXA',
        'ZURICH', 'GENERALI', 'MANULIFE', 'SUN LIFE',
        'NORTHWESTERN MUTUAL', 'NEW YORK LIFE', 'MASS MUTUAL'
    ],

    # Pension Funds
    'Pension Funds': [
        'CALPERS', 'CALSTRS', 'TEACHERS RETIREMENT', 'PUBLIC EMPLOYEES',
        'RETIREMENT SYSTEM', 'PENSION FUND', 'ONTARIO TEACHERS'
    ],

    # Sovereign Wealth Funds
    'Sovereign Wealth': [
        'NORWAY', 'TEMASEK', 'GIC', 'ADIA', 'CHINA INVESTMENT',
        'KUWAIT INVESTMENT', 'SINGAPORE'
    ],

    # Large RIAs and Multi-Family Offices
    'Large RIAs': [
        'FISHER INVESTMENTS', 'WELLINGTON', 'NEUBERGER BERMAN',
        'LAZARD', 'PARNASSUS', 'ARIEL INVESTMENTS', 'ARTISAN',
        'DIAMOND HILL', 'BROWN ADVISORY', 'HARRIS ASSOCIATES',
        'VULCAN VALUE', 'SOUTHEASTERN ASSET', 'DODGE & COX'
    ]
}

def load_filers_list():
    """Load the complete 13F filers list"""
    df = pd.read_csv('data/13f/all_13f_filers_list.csv')
    print(f"Loaded {len(df)} institutional filers\n")
    return df

def find_matching_institutions(df, patterns_dict):
    """
    Find institutions matching known major institution patterns
    """
    matches = {}

    for category, patterns in patterns_dict.items():
        print(f"Searching for {category}...")
        category_matches = []

        for pattern in patterns:
            # Case-insensitive search in institution name
            mask = df['name'].str.upper().str.contains(pattern, na=False, regex=False)
            matched = df[mask]

            if len(matched) > 0:
                for _, row in matched.iterrows():
                    if row['cik'] not in [m['cik'] for m in category_matches]:
                        category_matches.append({
                            'cik': row['cik'],
                            'name': row['name'],
                            'last_filing_date': row['last_filing_date'],
                            'category': category,
                            'matched_pattern': pattern
                        })

        matches[category] = category_matches
        print(f"  Found {len(category_matches)} institutions\n")

    return matches

def main():
    print("=" * 90)
    print("IDENTIFYING LARGEST 13F FILERS")
    print("=" * 90)
    print()

    # Load complete filers list
    df = load_filers_list()

    # Find matching institutions
    matches = find_matching_institutions(df, MAJOR_INSTITUTION_PATTERNS)

    # Combine all matches
    all_matches = []
    for category, category_matches in matches.items():
        all_matches.extend(category_matches)

    # Remove duplicates (institution might match multiple patterns)
    unique_matches = {}
    for match in all_matches:
        if match['cik'] not in unique_matches:
            unique_matches[match['cik']] = match

    # Create DataFrame
    df_identified = pd.DataFrame(unique_matches.values())
    df_identified = df_identified.sort_values('name')

    # Save results
    output_file = 'data/13f/largest_13f_filers_identified.csv'
    df_identified.to_csv(output_file, index=False)

    print("=" * 90)
    print(f"RESULTS")
    print("=" * 90)
    print()
    print(f"Total major institutions identified: {len(df_identified)}")
    print(f"From total universe of: {len(df)} filers")
    print(f"Identified: {len(df_identified)/len(df)*100:.1f}% of all filers")
    print(f"\nResults saved to: {output_file}\n")

    # Show breakdown by category
    print("=" * 90)
    print("BREAKDOWN BY CATEGORY")
    print("=" * 90)
    print()

    category_counts = df_identified['category'].value_counts()
    for category, count in category_counts.items():
        print(f"{category:<25} {count:>4} institutions")

    # Show all identified institutions
    print()
    print("=" * 90)
    print(f"ALL IDENTIFIED MAJOR INSTITUTIONS ({len(df_identified)} total)")
    print("=" * 90)
    print()

    print(f"{'CIK':<12} {'Institution Name':<60} {'Category':<20}")
    print('-' * 92)

    for _, row in df_identified.iterrows():
        print(f"{row['cik']:<12} {row['name'][:60]:<60} {row['category']:<20}")

    return df_identified

if __name__ == '__main__':
    df = main()

    print()
    print("=" * 90)
    print("NEXT STEP:")
    print("=" * 90)
    print(f"\nRun AUM extraction for these {len(df)} identified major institutions")
    print(f"Estimated time: ~{len(df) * 0.15 / 60:.1f} minutes")
