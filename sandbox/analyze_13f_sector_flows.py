"""
13F Holdings - Sector Capital Flows Analysis

Analyzes institutional capital allocation across sectors over time.
"""

import pandas as pd
import numpy as np
from datetime import datetime

print("="*90)
print("13F SECTOR CAPITAL FLOWS ANALYSIS")
print("="*90)

# Load holdings data
print("\n[1/5] Loading holdings data...")
df = pd.read_parquet('data/13f/holdings_master_20quarters.parquet')
df['filing_date'] = pd.to_datetime(df['filing_date'])

print(f"  Total records: {len(df):,}")
print(f"  Date range: {df['filing_date'].min().date()} to {df['filing_date'].max().date()}")

# ============================================================================
# SECTOR MAPPING
# ============================================================================
print("\n[2/5] Creating sector mapping...")

# Define comprehensive sector keywords for classification
sector_keywords = {
    'ETFs & Funds': [
        # Must check ETFs first to avoid misclassification
        'SPDR', 'ISHARES', 'VANGUARD', 'INVESCO', 'SCHWAB ETF', 'SELECT SECTOR',
        'SPDR GOLD', 'SPDR S&P', 'QQQ', 'SPY', 'ETF', 'TRUST', 'INDEX FUND',
        'POWERSHARES', 'PROSHARES', 'WISDOMTREE', 'FIRST TRUST', 'DIREXION',
        'VANECK', 'GLOBAL X', 'AMPLIFY', 'ARK INVEST', 'ARK INNOVATION',
        'MUTUAL FUND', 'FUND TRUST', 'EXCHANGE TRADED'
    ],
    'Technology': [
        # Mega-cap tech
        'MICROSOFT', 'APPLE', 'NVIDIA', 'ALPHABET', 'META', 'AMAZON', 'TESLA',
        # Software
        'ORACLE', 'SALESFORCE', 'ADOBE', 'SERVICENOW', 'SAP', 'INTUIT',
        'SNOWFLAKE', 'DATADOG', 'PALANTIR', 'SPLUNK', 'TWILIO', 'ZOOM',
        'WORKDAY', 'AUTODESK', 'SYNOPSYS', 'CADENCE', 'ANSYS', 'ASPEN',
        # Semiconductors
        'BROADCOM', 'QUALCOMM', 'INTEL', 'MICRON', 'ADVANCED MICRO DEVICES', 'AMD',
        'TEXAS INSTRUMENTS', 'ANALOG DEVICES', 'MARVELL', 'MICROCHIP',
        'NXP SEMICONDUCTOR', 'ON SEMICONDUCTOR', 'APPLIED MATERIALS', 'LAM RESEARCH',
        'KLA CORP', 'ASML', 'TAIWAN SEMICONDUCTOR', 'TSMC',
        # Cybersecurity
        'PALO ALTO', 'CROWDSTRIKE', 'FORTINET', 'ZSCALER', 'OKTA',
        # Cloud/IT
        'ARISTA', 'DELL', 'HPE', 'HEWLETT PACKARD', 'CISCO', 'JUNIPER',
        'F5 NETWORKS', 'AKAMAI', 'CLOUDFLARE', 'FASTLY',
        # E-commerce/Internet
        'UBER TECHNOLOGIES', 'LYFT', 'DOORDASH', 'SHOPIFY', 'ETSY', 'EBAY',
        'PAYPAL', 'BLOCK INC', 'SQUARE', 'STRIPE',
        # Generic terms
        'SOFTWARE', 'SEMICONDUCTOR', 'TECHNOLOGY', 'COMPUTING', 'INTERNET'
    ],
    'Financial Services': [
        # Major banks
        'JPMORGAN', 'BANK OF AMERICA', 'BANK AMERICA', 'WELLS FARGO', 'CITIGROUP',
        'GOLDMAN SACHS', 'MORGAN STANLEY', 'US BANCORP', 'TRUIST', 'PNC',
        'BANK OF NEW YORK', 'BNY MELLON', 'STATE STREET', 'NORTHERN TRUST',
        'CITIZENS FINANCIAL', 'FIFTH THIRD', 'HUNTINGTON', 'REGIONS', 'KEYCORP',
        # Investment firms
        'BERKSHIRE HATHAWAY', 'BLACKROCK', 'KKR', 'APOLLO', 'CARLYLE',
        'ARES MANAGEMENT', 'BROOKFIELD', 'BLUE OWL',
        # Payment processors
        'VISA', 'MASTERCARD', 'AMERICAN EXPRESS', 'DISCOVER', 'PAYPAL',
        # Brokers
        'CHARLES SCHWAB', 'INTERACTIVE BROKERS', 'ROBINHOOD', 'E TRADE',
        # Exchanges & data
        'S&P GLOBAL', 'CME GROUP', 'INTERCONTINENTAL EXCHANGE', 'ICE',
        'CBOE GLOBAL', 'NASDAQ', 'MOODY', 'MSCI',
        # Insurance
        'PROGRESSIVE', 'TRAVELERS', 'ALLSTATE', 'CHUBB', 'MARSH', 'AON',
        'METLIFE', 'PRUDENTIAL', 'AFLAC', 'PRINCIPAL', 'LINCOLN NATIONAL',
        'AMERICAN INTERNATIONAL', 'AIG', 'HARTFORD', 'LOEWS',
        # Other financial
        'CAPITAL ONE', 'ALLY FINANCIAL', 'SYNCHRONY', 'CREDIT ACCEPTANCE',
        # Generic terms
        'BANK', 'BANCORP', 'FINANCIAL', 'INSURANCE', 'LIFE INSURANCE', 'TRUST COMPANY',
        'ASSET MANAGEMENT', 'CAPITAL MANAGEMENT', 'HOLDINGS INC', 'INVESTMENT'
    ],
    'Healthcare': [
        # Health insurance
        'UNITEDHEALTH', 'ELEVANCE', 'CIGNA', 'HUMANA', 'CENTENE', 'MOLINA',
        # Pharma
        'ELI LILLY', 'LILLY', 'JOHNSON & JOHNSON', 'ABBVIE', 'MERCK', 'PFIZER',
        'BRISTOL MYERS', 'AMGEN', 'GILEAD', 'REGENERON', 'VERTEX', 'BIOGEN',
        'MODERNA', 'BIONTECH', 'NOVAVAX', 'INCYTE', 'ALNYLAM', 'SAREPTA',
        'ALEXION', 'BIOMARIN', 'SEAGEN', 'HORIZON THERAPEUTICS',
        # Medical devices
        'THERMO FISHER', 'DANAHER', 'ABBOTT', 'BOSTON SCIENTIFIC', 'MEDTRONIC',
        'INTUITIVE SURGICAL', 'STRYKER', 'BECTON DICKINSON', 'BD', 'BAXTER',
        'ZIMMER BIOMET', 'EDWARDS LIFESCIENCES', 'IDEXX', 'AGILENT', 'ILLUMINA',
        'INSULET', 'DEXCOM', 'TANDEM DIABETES', 'PENUMBRA',
        # Distributors
        'MCKESSON', 'CENCORA', 'AMERISOURCEBERGEN', 'CARDINAL HEALTH',
        # Pharmacy
        'CVS', 'WALGREENS', 'RITE AID',
        # Healthcare services
        'HCA HEALTHCARE', 'UNIVERSAL HEALTH', 'TENET', 'COMMUNITY HEALTH',
        'ENCOMPASS HEALTH', 'LABCORP', 'QUEST DIAGNOSTICS', 'DAVITA',
        # Biotech
        'GENENTECH', 'CELGENE', 'IMMUNOGEN', 'EXACT SCIENCES',
        # Generic terms
        'PHARMACEUTICAL', 'PHARMA', 'BIOTECH', 'MEDICAL', 'HEALTHCARE',
        'HEALTH CARE', 'THERAPEUTICS', 'LABORATORIES', 'HEALTH SYSTEMS'
    ],
    'Consumer Discretionary': [
        # Automotive
        'TESLA', 'FORD', 'GENERAL MOTORS', 'STELLANTIS', 'RIVIAN', 'LUCID',
        # Retail
        'AMAZON', 'WALMART', 'TARGET', 'COSTCO', 'HOME DEPOT', 'LOWE',
        'TJMAXX', 'TJX COMPANIES', 'ROSS STORES', 'DOLLAR GENERAL', 'DOLLAR TREE',
        'BEST BUY', 'MACY', 'NORDSTROM', 'KOHL', 'BURLINGTON', 'DILLARD',
        # Restaurants
        'MCDONALDS', 'STARBUCKS', 'CHIPOTLE', 'YUM BRANDS', 'DOMINO',
        'RESTAURANT BRANDS', 'WENDY', 'SHAKE SHACK', 'WINGSTOP', 'CHEESECAKE FACTORY',
        'DARDEN', 'BRINKER', 'BLOOMIN BRANDS', 'TEXAS ROADHOUSE',
        # Apparel
        'NIKE', 'LULULEMON', 'ADIDAS', 'UNDER ARMOUR', 'VF CORP', 'RALPH LAUREN',
        'PVH', 'CAPRI', 'TAPESTRY', 'GUESS', 'GAP', 'FOOT LOCKER',
        # E-commerce/Online
        'ETSY', 'EBAY', 'WAYFAIR', 'CHEWY', 'CARVANA', 'VROOM',
        # Travel & leisure
        'BOOKING', 'EXPEDIA', 'AIRBNB', 'MARRIOTT', 'HILTON', 'HYATT',
        'ROYAL CARIBBEAN', 'CARNIVAL', 'NORWEGIAN CRUISE',
        'CAESARS', 'MGM RESORTS', 'WYNN', 'LAS VEGAS SANDS', 'DRAFTKINGS', 'PENN',
        # Auto parts
        'AUTOZONE', 'O REILLY', 'ADVANCE AUTO', 'GENUINE PARTS', 'CARMAX',
        # Generic terms
        'RETAIL', 'STORES', 'RESTAURANT', 'APPAREL', 'AUTOMOTIVE', 'AUTO'
    ],
    'Communication Services': [
        # Social media / Internet
        'META', 'ALPHABET', 'GOOGLE', 'PINTEREST', 'SNAP', 'REDDIT', 'TWITTER',
        # Streaming/Entertainment
        'NETFLIX', 'DISNEY', 'WARNER BROS', 'PARAMOUNT', 'FOX CORP', 'LIVE NATION',
        # Telecom
        'COMCAST', 'VERIZON', 'AT&T', 'T-MOBILE', 'CHARTER', 'LUMEN', 'FRONTIER',
        'LIBERTY MEDIA', 'LIBERTY BROADBAND', 'DISH NETWORK',
        # Gaming
        'ACTIVISION', 'ELECTRONIC ARTS', 'EA', 'TAKE-TWO', 'ROBLOX', 'UNITY',
        # Generic terms
        'COMMUNICATIONS', 'TELECOM', 'MEDIA', 'ENTERTAINMENT', 'BROADCASTING'
    ],
    'Industrials': [
        # Aerospace & defense
        'GE AEROSPACE', 'GE VERNOVA', 'GENERAL ELECTRIC', 'BOEING', 'LOCKHEED',
        'RAYTHEON', 'RTX', 'NORTHROP GRUMMAN', 'L3HARRIS', 'GENERAL DYNAMICS',
        'TEXTRON', 'HUNTINGTON INGALLS', 'SPIRIT AEROSYSTEMS', 'HOWMET',
        # Industrial conglomerates
        'HONEYWELL', '3M', 'EMERSON', 'PARKER HANNIFIN', 'ROCKWELL', 'XYLEM',
        'DOVER', 'FORTIVE', 'ROPER', 'DANAHER', 'ITT',
        # Machinery
        'CATERPILLAR', 'DEERE', 'PACCAR', 'CUMMINS', 'EATON', 'INGERSOLL RAND',
        'STANLEY BLACK', 'SNAP-ON', 'KENNAMETAL', 'LINCOLN ELECTRIC',
        # Railroads
        'UNION PACIFIC', 'NORFOLK SOUTHERN', 'CSX', 'CANADIAN NATIONAL', 'CANADIAN PACIFIC',
        'KANSAS CITY SOUTHERN',
        # Transportation & logistics
        'UNITED PARCEL', 'UPS', 'FEDEX', 'JB HUNT', 'OLD DOMINION', 'KNIGHT-SWIFT',
        'XPO LOGISTICS', 'CH ROBINSON', 'EXPEDITORS', 'LANDSTAR',
        # Airlines
        'DELTA', 'UNITED AIRLINES', 'AMERICAN AIRLINES', 'SOUTHWEST', 'JETBLUE', 'ALASKA AIR',
        # Waste
        'WASTE MANAGEMENT', 'REPUBLIC SERVICES', 'WASTE CONNECTIONS', 'GFL ENVIRONMENTAL',
        # Construction
        'FLUOR', 'JACOBS', 'QUANTA SERVICES', 'AECOM', 'MAS TEC',
        # Rentals
        'UNITED RENTALS', 'ASHTEAD', 'HERC', 'H&E EQUIPMENT',
        # Generic terms
        'AEROSPACE', 'DEFENSE', 'INDUSTRIAL', 'MACHINERY', 'MANUFACTURING',
        'ENGINEERING', 'CONSTRUCTION', 'TRANSPORTATION', 'LOGISTICS', 'AIRLINES'
    ],
    'Energy': [
        # Oil & gas majors
        'EXXON', 'CHEVRON', 'CONOCOPHILLIPS', 'SHELL', 'BP', 'TOTALENERGIES',
        'EQUINOR', 'ENI',
        # E&P
        'PIONEER', 'EOG RESOURCES', 'DEVON', 'HESS', 'MARATHON OIL', 'OCCIDENTAL',
        'DIAMONDBACK', 'CONTINENTAL RESOURCES', 'OVINTIV', 'CHESAPEAKE', 'RANGE RESOURCES',
        'ANTERO', 'COTERRA', 'APA CORP',
        # Refining
        'MARATHON PETROLEUM', 'PHILLIPS 66', 'VALERO', 'HF SINCLAIR', 'PBF ENERGY',
        # Services
        'SCHLUMBERGER', 'SLB', 'HALLIBURTON', 'BAKER HUGHES', 'WEATHERFORD',
        'NOBLE CORP', 'TRANSOCEAN', 'HELMERICH', 'PATTERSON-UTI',
        # Pipelines/Midstream
        'WILLIAMS', 'KINDER MORGAN', 'ONEOK', 'ENTERPRISE PRODUCTS', 'ENERGY TRANSFER',
        'PLAINS ALL AMERICAN', 'MAGELLAN MIDSTREAM', 'TARGA RESOURCES', 'WESTERN MIDSTREAM',
        # Coal
        'PEABODY', 'ARCH RESOURCES', 'CONSOL',
        # Generic terms
        'ENERGY', 'OIL', 'GAS', 'PETROLEUM', 'EXPLORATION', 'PRODUCTION', 'PIPELINE'
    ],
    'Consumer Staples': [
        # Food & beverage
        'PROCTER', 'COCA-COLA', 'PEPSICO', 'MONDELEZ', 'KRAFT HEINZ', 'GENERAL MILLS',
        'KELLOGG', 'KELLANOVA', 'CONAGRA', 'CAMPBELL', 'HORMEL', 'TYSON', 'JM SMUCKER',
        'HERSHEY', 'MCCORMICK', 'LAMB WESTON',
        # Retailers
        'WALMART', 'COSTCO', 'KROGER', 'ALBERTSONS', 'TARGET', 'DOLLAR GENERAL',
        'DOLLAR TREE', 'BJ WHOLESALE', 'SPROUTS', 'CASEY GENERAL',
        # Household products
        'COLGATE', 'KIMBERLY-CLARK', 'CLOROX', 'CHURCH & DWIGHT',
        # Personal care
        'ESTEE LAUDER', 'ELF BEAUTY', 'COTY',
        # Tobacco
        'PHILIP MORRIS', 'ALTRIA', 'BRITISH AMERICAN TOBACCO',
        # Beverages
        'CONSTELLATION BRANDS', 'MOLSON COORS', 'BOSTON BEER', 'BROWN-FORMAN',
        # Distributors
        'SYSCO', 'US FOODS', 'PERFORMANCE FOOD',
        # Generic terms
        'FOODS', 'FOOD PRODUCTS', 'BEVERAGES', 'CONSUMER GOODS', 'HOUSEHOLD PRODUCTS'
    ],
    'Real Estate': [
        # REITs - Industrial/Logistics
        'PROLOGIS', 'DUKE REALTY', 'TERRENO',
        # REITs - Cell towers
        'AMERICAN TOWER', 'CROWN CASTLE', 'SBA COMMUNICATIONS',
        # REITs - Data centers
        'EQUINIX', 'DIGITAL REALTY', 'CORESITE', 'CYRUSONE',
        # REITs - Storage
        'PUBLIC STORAGE', 'EXTRA SPACE', 'CUBESMART', 'LIFE STORAGE',
        # REITs - Healthcare
        'WELLTOWER', 'VENTAS', 'HEALTHPEAK', 'SABRA', 'OMEGA HEALTHCARE', 'MEDICAL PROPERTIES',
        # REITs - Retail
        'REALTY INCOME', 'SIMON PROPERTY', 'REGENCY CENTERS', 'FEDERAL REALTY',
        'KIMCO', 'BRIXMOR', 'RETAIL OPPORTUNITY',
        # REITs - Residential
        'AVALONBAY', 'EQUITY RESIDENTIAL', 'UDR', 'ESSEX', 'MID-AMERICA', 'CAMDEN',
        'INVITATION HOMES', 'AMERICAN HOMES', 'SUN COMMUNITIES',
        # REITs - Office
        'BOSTON PROPERTIES', 'VORNADO', 'KILROY', 'SL GREEN', 'DOUGLAS EMMETT',
        # REITs - Diversified
        'VICI PROPERTIES', 'GAMING AND LEISURE', 'EPR PROPERTIES',
        # REITs - Specialty
        'ALEXANDRIA REAL ESTATE', 'VENTAS', 'OMEGA HEALTHCARE',
        # Generic terms
        'REIT', 'REALTY', 'PROPERTIES', 'REAL ESTATE'
    ],
    'Materials': [
        # Chemicals
        'LINDE', 'AIR PRODUCTS', 'DOW', 'DUPONT', 'LYONDELLBASELL', 'WESTLAKE',
        'EASTMAN', 'CELANESE', 'HUNTSMAN', 'OLIN', 'MOSAIC', 'CF INDUSTRIES',
        'CORTEVA', 'FMC', 'ALBEMARLE', 'NEWMARKET',
        # Specialty chemicals
        'ECOLAB', 'SHERWIN-WILLIAMS', 'PPG', 'RPM', 'AXALTA', 'CHEMOURS',
        # Mining
        'FREEPORT', 'NEWMONT', 'BARRICK', 'AGNICO EAGLE', 'ROYAL GOLD', 'WHEATON',
        'SOUTHERN COPPER', 'STEEL DYNAMICS', 'NUCOR', 'CLEVELAND-CLIFFS', 'COMMERCIAL METALS',
        # Construction materials
        'MARTIN MARIETTA', 'VULCAN MATERIALS', 'SUMMIT MATERIALS', 'US CONCRETE',
        'EAGLE MATERIALS',
        # Packaging
        'BALL CORP', 'AMCOR', 'SEALED AIR', 'SONOCO', 'GREIF', 'PACKAGING CORP',
        # Paper & forest products
        'INTERNATIONAL PAPER', 'WESTROCK', 'PACKAGING CORP', 'LOUISIANA-PACIFIC',
        # Generic terms
        'CHEMICAL', 'MINING', 'METALS', 'MATERIALS', 'STEEL', 'COPPER', 'GOLD'
    ],
    'Utilities': [
        # Electric utilities
        'NEXTERA', 'DUKE ENERGY', 'SOUTHERN COMPANY', 'DOMINION', 'AMERICAN ELECTRIC',
        'EXELON', 'CONSTELLATION ENERGY', 'XCEL', 'PUBLIC SERVICE', 'PG&E',
        'EDISON INTERNATIONAL', 'CONSOLIDATED EDISON', 'FIRSTENERGY', 'ENTERGY',
        'EVERGY', 'EVERSOURCE', 'AMEREN', 'CMS ENERGY', 'DTE ENERGY', 'PPL',
        'WEC ENERGY', 'ALLIANT', 'IDACORP', 'PINNACLE WEST', 'OGE ENERGY',
        'PORTLAND GENERAL', 'AVANGRID', 'NRG ENERGY', 'VISTRA',
        # Gas utilities
        'SEMPRA', 'ATMOS ENERGY', 'NATIONAL FUEL', 'SOUTHWEST GAS', 'ONE GAS',
        'SPIRE', 'NEW JERSEY RESOURCES', 'NORTHWEST NATURAL',
        # Water utilities
        'AMERICAN WATER', 'ESSENTIAL UTILITIES', 'CALIFORNIA WATER', 'SJW GROUP',
        # Generic terms
        'UTILITY', 'UTILITIES', 'ELECTRIC', 'POWER', 'GAS COMPANY', 'ENERGY COMPANY'
    ]
}

def classify_sector(issuer_name):
    """Classify issuer into sector based on keywords"""
    if pd.isna(issuer_name):
        return 'Unknown'

    issuer_upper = str(issuer_name).upper()

    # Check each sector's keywords
    for sector, keywords in sector_keywords.items():
        for keyword in keywords:
            if keyword in issuer_upper:
                return sector

    return 'Other'

# Apply sector classification
df['sector'] = df['issuer_name'].apply(classify_sector)

# Show sector distribution
sector_counts = df['sector'].value_counts()
print(f"\n  Sector Distribution:")
for sector, count in sector_counts.items():
    pct = (count / len(df)) * 100
    print(f"    {sector:<25} {count:>10,} records ({pct:>5.1f}%)")

# ============================================================================
# SECTOR ANALYSIS BY QUARTER
# ============================================================================
print("\n[3/5] Analyzing sector capital flows over time...")

# Get major reporting periods (100+ institutions)
filings_per_date = df.groupby('filing_date')['cik'].nunique().reset_index()
filings_per_date.columns = ['filing_date', 'num_institutions']
major_dates = filings_per_date[filings_per_date['num_institutions'] >= 100].sort_values('filing_date')

print(f"  Found {len(major_dates)} major reporting periods (100+ institutions)")

# Calculate sector allocations for each major quarter
sector_flows = []

for filing_date in major_dates['filing_date']:
    quarter_df = df[df['filing_date'] == filing_date]

    # Aggregate by sector (value_thousands is in dollars)
    sector_aum = quarter_df.groupby('sector').agg({
        'value_thousands': 'sum',
        'cik': 'nunique',
        'cusip': 'nunique'
    }).reset_index()

    sector_aum.columns = ['sector', 'aum_dollars', 'num_institutions', 'num_stocks']
    sector_aum['aum_billions'] = sector_aum['aum_dollars'] / 1_000_000_000

    total_aum = sector_aum['aum_billions'].sum()
    sector_aum['allocation_%'] = (sector_aum['aum_billions'] / total_aum) * 100

    sector_aum['filing_date'] = filing_date
    sector_flows.append(sector_aum)

sector_flows_df = pd.concat(sector_flows, ignore_index=True)

# Save full time series
sector_flows_df.to_csv('data/13f/analysis_sector_flows_timeseries.csv', index=False)

# ============================================================================
# LATEST QUARTER SECTOR BREAKDOWN
# ============================================================================
print("\n[4/5] Latest quarter sector analysis...")

latest_date = major_dates['filing_date'].max()
latest_sector = sector_flows_df[sector_flows_df['filing_date'] == latest_date].copy()
latest_sector = latest_sector.sort_values('aum_billions', ascending=False)

print(f"\n  Sector Breakdown ({latest_date.date()}):")
print(f"  {'Sector':<25} {'AUM ($B)':<15} {'Allocation %':<15} {'# Stocks':<12} {'# Institutions':<15}")
print("  " + "-"*90)

for _, row in latest_sector.iterrows():
    print(f"  {row['sector']:<25} ${row['aum_billions']:>12,.1f} {row['allocation_%']:>12.1f}% {row['num_stocks']:>10,} {row['num_institutions']:>13}")

# Save latest quarter breakdown
latest_sector.to_csv('data/13f/analysis_sector_breakdown_latest.csv', index=False)

# ============================================================================
# CAPITAL FLOWS (QoQ CHANGES)
# ============================================================================
print("\n[5/5] Calculating quarter-over-quarter capital flows...")

# Get last 8 major quarters
recent_dates = major_dates['filing_date'].tail(8).tolist()

# Calculate QoQ changes for each sector
qoq_flows = []

for i in range(1, len(recent_dates)):
    prev_date = recent_dates[i-1]
    curr_date = recent_dates[i]

    prev_data = sector_flows_df[sector_flows_df['filing_date'] == prev_date].set_index('sector')
    curr_data = sector_flows_df[sector_flows_df['filing_date'] == curr_date].set_index('sector')

    for sector in prev_data.index:
        if sector in curr_data.index:
            prev_aum = prev_data.loc[sector, 'aum_billions']
            curr_aum = curr_data.loc[sector, 'aum_billions']

            change_billions = curr_aum - prev_aum
            change_pct = ((curr_aum / prev_aum) - 1) * 100 if prev_aum > 0 else 0

            qoq_flows.append({
                'filing_date': curr_date,
                'sector': sector,
                'aum_billions': curr_aum,
                'prev_aum_billions': prev_aum,
                'change_billions': change_billions,
                'change_%': change_pct
            })

qoq_flows_df = pd.DataFrame(qoq_flows)

# Show latest QoQ flows
latest_qoq = qoq_flows_df[qoq_flows_df['filing_date'] == recent_dates[-1]].copy()
latest_qoq = latest_qoq.sort_values('change_billions', ascending=False)

print(f"\n  Latest QoQ Capital Flows ({recent_dates[-2].date()} → {recent_dates[-1].date()}):")
print(f"  {'Sector':<25} {'Current AUM ($B)':<18} {'Change ($B)':<15} {'Change %':<12} {'Flow':<6}")
print("  " + "-"*85)

for _, row in latest_qoq.iterrows():
    flow_symbol = "↑" if row['change_billions'] > 0 else "↓" if row['change_billions'] < 0 else "→"
    print(f"  {row['sector']:<25} ${row['aum_billions']:>15,.1f} ${row['change_billions']:>12,.1f} {row['change_%']:>9.1f}% {flow_symbol:>4}")

# Save QoQ flows
qoq_flows_df.to_csv('data/13f/analysis_sector_qoq_flows.csv', index=False)

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*90)
print("SECTOR ANALYSIS COMPLETE")
print("="*90)

print("\nKey Findings:")
print(f"  1. Total Sectors Tracked: {latest_sector['sector'].nunique()}")
print(f"  2. Latest Total AUM: ${latest_sector['aum_billions'].sum():.1f}B")
print(f"  3. Top Sector: {latest_sector.iloc[0]['sector']} (${latest_sector.iloc[0]['aum_billions']:.1f}B, {latest_sector.iloc[0]['allocation_%']:.1f}%)")
print(f"  4. Largest Inflow (QoQ): {latest_qoq.iloc[0]['sector']} (+${latest_qoq.iloc[0]['change_billions']:.1f}B)")
print(f"  5. Largest Outflow (QoQ): {latest_qoq.iloc[-1]['sector']} (${latest_qoq.iloc[-1]['change_billions']:.1f}B)")

print("\nOutput files:")
print("  1. data/13f/analysis_sector_flows_timeseries.csv - Full time series by sector")
print("  2. data/13f/analysis_sector_breakdown_latest.csv - Latest quarter breakdown")
print("  3. data/13f/analysis_sector_qoq_flows.csv - Quarter-over-quarter flows")
print("="*90)
