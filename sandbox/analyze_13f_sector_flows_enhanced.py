"""
Enhanced 13F Sector Flows Analysis with yfinance Classification

Uses yfinance sector data where available, falls back to keyword-based classification.
Analyzes institutional capital flows across sectors over time.
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================================
# SECTOR CLASSIFICATION
# ============================================================================

# ETF keywords for fallback classification
ETF_KEYWORDS = [
    'SPDR', 'ISHARES', 'VANGUARD', 'INVESCO', 'SCHWAB ETF', 'SELECT SECTOR',
    'SPDR GOLD', 'SPDR S&P', 'QQQ', 'SPY', 'ETF', 'TRUST', 'INDEX FUND',
    'POWERSHARES', 'PROSHARES', 'WISDOMTREE', 'FIRST TRUST', 'DIREXION',
    'VANECK', 'GLOBAL X', 'AMPLIFY', 'ARK INVEST', 'ARK INNOVATION'
]

# Map yfinance sector names to our standard sector names
YFINANCE_SECTOR_MAP = {
    'Technology': 'Technology',
    'Financial Services': 'Financial Services',
    'Healthcare': 'Healthcare',
    'Consumer Cyclical': 'Consumer Discretionary',
    'Consumer Defensive': 'Consumer Staples',
    'Industrials': 'Industrials',
    'Energy': 'Energy',
    'Basic Materials': 'Materials',
    'Communication Services': 'Communication Services',
    'Utilities': 'Utilities',
    'Real Estate': 'Real Estate'
}

def classify_sector(row, yfinance_mapping):
    """
    Classify stock into sector using yfinance data first, then fallback to keywords

    Priority:
    1. yfinance sector data (if available)
    2. ETF detection (by name)
    3. Return 'Other' for unclassified
    """
    cusip = row['cusip']
    issuer_name = str(row['issuer_name']).upper()

    # Check yfinance mapping first
    if cusip in yfinance_mapping.index:
        try:
            yf_sector = yfinance_mapping.loc[cusip, 'sector']
            # Handle case where loc returns a Series (duplicate CUSIPs)
            if isinstance(yf_sector, pd.Series):
                yf_sector = yf_sector.iloc[0]
            if pd.notna(yf_sector):
                # Map to our standard sector names
                return YFINANCE_SECTOR_MAP.get(yf_sector, yf_sector)
        except:
            pass

    # Check if it's an ETF
    for keyword in ETF_KEYWORDS:
        if keyword in issuer_name:
            return 'ETFs & Funds'

    # Unclassified
    return 'Other'

# ============================================================================
# LOAD DATA
# ============================================================================

print("="*90)
print("ENHANCED 13F SECTOR FLOWS ANALYSIS (with yfinance)")
print("="*90)

# Load holdings data
print("\n[1/6] Loading holdings data...")
df = pd.read_parquet('data/13f/holdings_master_20quarters.parquet')
df['filing_date'] = pd.to_datetime(df['filing_date'])
print(f"  Loaded {len(df):,} holdings records")

# Load yfinance sector mapping
print("\n[2/6] Loading yfinance sector classifications...")
yf_mapping = pd.read_csv('data/13f/yfinance_sector_mapping.csv')
yf_mapping = yf_mapping.set_index('cusip')
print(f"  Loaded {len(yf_mapping):,} sector mappings")
print(f"  Classified stocks: {yf_mapping['sector'].notna().sum():,}")
print(f"  Total AUM covered: ${yf_mapping['value_billions'].sum():.1f}B")

# Apply sector classification
print("\n[3/6] Classifying all holdings...")
df['sector'] = df.apply(lambda row: classify_sector(row, yf_mapping), axis=1)

# Get classification stats
total_holdings = len(df)
classified = df[df['sector'] != 'Other'].shape[0]
print(f"  Classified: {classified:,} holdings ({classified/total_holdings*100:.1f}%)")
print(f"  Unclassified ('Other'): {total_holdings - classified:,} holdings ({(total_holdings-classified)/total_holdings*100:.1f}%)")

# ============================================================================
# SECTOR ANALYSIS BY QUARTER
# ============================================================================

print("\n[4/6] Analyzing sector allocations over time...")

# Identify major reporting periods (100+ institutions)
filings_per_date = df.groupby('filing_date')['cik'].nunique().reset_index()
filings_per_date.columns = ['filing_date', 'num_institutions']
major_dates = filings_per_date[filings_per_date['num_institutions'] >= 100].sort_values('filing_date')

print(f"  Found {len(major_dates)} major reporting periods")

# Calculate sector allocations for each quarter
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

# ============================================================================
# LATEST QUARTER BREAKDOWN
# ============================================================================

print("\n[5/6] Generating latest quarter breakdown...")

latest_date = major_dates['filing_date'].max()
latest_breakdown = sector_flows_df[sector_flows_df['filing_date'] == latest_date].copy()
latest_breakdown = latest_breakdown.sort_values('aum_billions', ascending=False)

print(f"\n  Latest Quarter: {latest_date.date()}")
print(f"  Total AUM: ${latest_breakdown['aum_billions'].sum():.1f}B")
print(f"\n  Sector Breakdown:")
for _, row in latest_breakdown.iterrows():
    print(f"    {row['sector']:<25} ${row['aum_billions']:>8.1f}B ({row['allocation_%']:>5.1f}%)")

# Save latest breakdown
latest_breakdown.to_csv('data/13f/analysis_sector_breakdown_latest_enhanced.csv', index=False)
print(f"\n  ✓ Saved: data/13f/analysis_sector_breakdown_latest_enhanced.csv")

# ============================================================================
# QUARTER-OVER-QUARTER FLOWS
# ============================================================================

print("\n[6/6] Calculating quarter-over-quarter flows...")

# Get last 4 quarters for QoQ analysis
recent_dates = major_dates['filing_date'].tail(4).tolist()
qoq_flows = []

for i in range(1, len(recent_dates)):
    prev_date = recent_dates[i-1]
    curr_date = recent_dates[i]

    prev_data = sector_flows_df[sector_flows_df['filing_date'] == prev_date].set_index('sector')
    curr_data = sector_flows_df[sector_flows_df['filing_date'] == curr_date].set_index('sector')

    # Calculate changes for all sectors
    all_sectors = set(prev_data.index) | set(curr_data.index)

    for sector in all_sectors:
        prev_aum = prev_data.loc[sector, 'aum_billions'] if sector in prev_data.index else 0
        curr_aum = curr_data.loc[sector, 'aum_billions'] if sector in curr_data.index else 0

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

print(f"\n  Latest QoQ Flows ({recent_dates[-2].date()} → {recent_dates[-1].date()}):")
print(f"\n  {'Sector':<25} {'Change ($B)':>12} {'Change %':>10}")
print("  " + "-"*50)
for _, row in latest_qoq.iterrows():
    sign = "+" if row['change_billions'] >= 0 else ""
    print(f"  {row['sector']:<25} {sign}{row['change_billions']:>11.1f}B {row['change_%']:>9.1f}%")

# ============================================================================
# SAVE OUTPUTS
# ============================================================================

# Save time series
sector_flows_df.to_csv('data/13f/analysis_sector_flows_timeseries_enhanced.csv', index=False)
print(f"\n✓ Saved: data/13f/analysis_sector_flows_timeseries_enhanced.csv")

# Save QoQ flows
qoq_flows_df.to_csv('data/13f/analysis_sector_qoq_flows_enhanced.csv', index=False)
print(f"✓ Saved: data/13f/analysis_sector_qoq_flows_enhanced.csv")

# ============================================================================
# CLASSIFICATION SUMMARY
# ============================================================================

print("\n" + "="*90)
print("CLASSIFICATION SUMMARY")
print("="*90)

# Calculate AUM coverage by classification source
latest_df = df[df['filing_date'] == latest_date].copy()

# Classify by source
def get_classification_source(row):
    cusip = row['cusip']
    issuer_name = str(row['issuer_name']).upper()

    # Check yfinance
    if cusip in yf_mapping.index:
        try:
            yf_sector = yf_mapping.loc[cusip, 'sector']
            if isinstance(yf_sector, pd.Series):
                yf_sector = yf_sector.iloc[0]
            if pd.notna(yf_sector):
                return 'yfinance'
        except:
            pass

    # Check ETF
    for keyword in ETF_KEYWORDS:
        if keyword in issuer_name:
            return 'ETF detection'

    return 'Unclassified'

latest_df['classification_source'] = latest_df.apply(get_classification_source, axis=1)

# Aggregate by source
source_aum = latest_df.groupby('classification_source').agg({
    'value_thousands': 'sum',
    'cusip': 'nunique'
}).reset_index()
source_aum.columns = ['source', 'aum_dollars', 'num_stocks']
source_aum['aum_billions'] = source_aum['aum_dollars'] / 1_000_000_000
total_aum_latest = source_aum['aum_billions'].sum()
source_aum['coverage_%'] = (source_aum['aum_billions'] / total_aum_latest) * 100

print("\nClassification Coverage:")
for _, row in source_aum.iterrows():
    print(f"  {row['source']:<20} {row['num_stocks']:>6,} stocks | ${row['aum_billions']:>8.1f}B ({row['coverage_%']:>5.1f}%)")

print(f"\nTotal: ${total_aum_latest:.1f}B across {latest_df['cusip'].nunique():,} unique stocks")
print("="*90)
