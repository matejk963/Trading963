"""
Comprehensive 13F Holdings Analysis

Analyzes historical 13F holdings data to identify:
1. Top holdings by aggregate value
2. Most widely held stocks
3. Ownership concentration trends
4. Position changes over time
5. Institution-level portfolio metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json

print("="*90)
print("13F HOLDINGS ANALYSIS")
print("="*90)

# Load the master holdings file
print("\n[1/6] Loading holdings data...")
df = pd.read_parquet('data/13f/holdings_master_20quarters.parquet')

print(f"  Total records: {len(df):,}")
print(f"  Institutions: {df['cik'].nunique():,}")
print(f"  Unique stocks: {df['cusip'].nunique():,}")
print(f"  Date range: {df['filing_date'].min()} to {df['filing_date'].max()}")

# Convert filing_date to datetime
df['filing_date'] = pd.to_datetime(df['filing_date'])

# ============================================================================
# 1. TOP HOLDINGS BY AGGREGATE VALUE
# ============================================================================
print("\n[2/6] Analyzing top holdings by aggregate value...")

# Get most recent major reporting period (100+ institutions)
filings_per_date = df.groupby('filing_date')['cik'].nunique().reset_index()
filings_per_date.columns = ['filing_date', 'num_institutions']
filings_per_date = filings_per_date.sort_values('filing_date', ascending=False)

# Find most recent date with 100+ institutions
major_dates = filings_per_date[filings_per_date['num_institutions'] >= 100]
if len(major_dates) == 0:
    # Fallback to date with most institutions if none have 100+
    latest_quarter = filings_per_date.iloc[0]['filing_date']
    num_insts = filings_per_date.iloc[0]['num_institutions']
else:
    latest_quarter = major_dates.iloc[0]['filing_date']
    num_insts = major_dates.iloc[0]['num_institutions']

print(f"  Using latest major reporting period: {latest_quarter.date()} ({num_insts} institutions)")

latest_df = df[df['filing_date'] == latest_quarter].copy()

# Aggregate by stock
# NOTE: 'value_thousands' column actually contains DOLLARS (not thousands)
top_stocks = latest_df.groupby(['cusip', 'issuer_name']).agg({
    'value_thousands': 'sum',  # Sum in dollars
    'shares': 'sum',
    'cik': 'nunique'  # Number of institutions holding
}).reset_index()

# Convert dollars to millions for display
top_stocks.columns = ['cusip', 'issuer_name', 'total_value_dollars', 'total_shares', 'num_institutions']
top_stocks['total_value_millions'] = top_stocks['total_value_dollars'] / 1_000_000
top_stocks = top_stocks.sort_values('total_value_millions', ascending=False)

print(f"\n  Top 50 Holdings by Aggregate Value ({latest_quarter.date()}):")
print(f"  {'Rank':<6} {'Stock':<40} {'Total Value ($M)':<20} {'Institutions':<15} {'Avg Value/Inst ($M)':<20}")
print("  " + "-"*110)

top_50_holdings = top_stocks.head(50).copy()
top_50_holdings['avg_value_per_inst'] = top_50_holdings['total_value_millions'] / top_50_holdings['num_institutions']

for idx, row in top_50_holdings.iterrows():
    if idx >= 50:
        break
    rank = top_50_holdings.index.get_loc(idx) + 1
    print(f"  {rank:<6} {row['issuer_name'][:40]:<40} ${row['total_value_millions']:>15,.0f} {row['num_institutions']:>12} ${row['avg_value_per_inst']:>18,.2f}")

# Save to CSV
top_50_holdings.to_csv('data/13f/analysis_top50_holdings.csv', index=False)

# ============================================================================
# 2. MOST WIDELY HELD STOCKS
# ============================================================================
print("\n[3/6] Analyzing most widely held stocks...")

most_held = top_stocks.sort_values('num_institutions', ascending=False).head(50)

print(f"\n  Top 50 Most Widely Held Stocks ({latest_quarter.date()}):")
print(f"  {'Rank':<6} {'Stock':<40} {'# Institutions':<17} {'Total Value ($M)':<20} {'Avg Position ($M)':<20}")
print("  " + "-"*110)

for idx, row in most_held.iterrows():
    if most_held.index.get_loc(idx) >= 50:
        break
    rank = most_held.index.get_loc(idx) + 1
    avg_position = row['total_value_millions'] / row['num_institutions']
    print(f"  {rank:<6} {row['issuer_name'][:40]:<40} {row['num_institutions']:>14} ${row['total_value_millions']:>17,.0f} ${avg_position:>18,.2f}")

# Save to CSV
most_held.to_csv('data/13f/analysis_most_widely_held.csv', index=False)

# ============================================================================
# 3. OWNERSHIP CONCENTRATION TRENDS
# ============================================================================
print("\n[4/6] Analyzing ownership concentration over time...")

# Calculate top 10 concentration for each quarter
concentration_by_quarter = []

for quarter in sorted(df['filing_date'].unique()):
    quarter_df = df[df['filing_date'] == quarter]

    # Aggregate by stock (value_thousands is actually in dollars)
    stocks = quarter_df.groupby('cusip')['value_thousands'].sum().sort_values(ascending=False)

    total_value = stocks.sum()
    top_10_value = stocks.head(10).sum()
    top_50_value = stocks.head(50).sum()
    top_100_value = stocks.head(100).sum()

    concentration_by_quarter.append({
        'filing_date': quarter,
        'total_aum_billions': total_value / 1_000_000_000,  # Convert dollars to billions
        'top_10_concentration_%': (top_10_value / total_value * 100) if total_value > 0 else 0,
        'top_50_concentration_%': (top_50_value / total_value * 100) if total_value > 0 else 0,
        'top_100_concentration_%': (top_100_value / total_value * 100) if total_value > 0 else 0,
        'num_stocks': len(stocks)
    })

concentration_df = pd.DataFrame(concentration_by_quarter)
concentration_df = concentration_df.sort_values('filing_date')

print(f"\n  Ownership Concentration Trends:")
print(f"  {'Quarter':<15} {'Total AUM ($B)':<18} {'Top 10 %':<12} {'Top 50 %':<12} {'Top 100 %':<12} {'# Stocks':<10}")
print("  " + "-"*85)

for _, row in concentration_df.tail(12).iterrows():  # Show last 3 years
    print(f"  {str(row['filing_date'].date()):<15} ${row['total_aum_billions']:>15,.1f} {row['top_10_concentration_%']:>9.2f}% {row['top_50_concentration_%']:>9.2f}% {row['top_100_concentration_%']:>9.2f}% {row['num_stocks']:>8,}")

# Save to CSV
concentration_df.to_csv('data/13f/analysis_concentration_trends.csv', index=False)

# ============================================================================
# 4. POSITION CHANGES OVER TIME (TOP 20 STOCKS)
# ============================================================================
print("\n[5/6] Analyzing position changes for top 20 stocks...")

# Get top 20 stocks by current value
top_20_cusips = top_50_holdings.head(20)['cusip'].tolist()

# Track these stocks over all quarters
position_changes = []

for cusip in top_20_cusips:
    stock_data = df[df['cusip'] == cusip].copy()
    stock_name = stock_data['issuer_name'].iloc[0] if len(stock_data) > 0 else cusip

    # Aggregate by quarter (value_thousands is actually in dollars)
    quarterly = stock_data.groupby('filing_date').agg({
        'value_thousands': 'sum',
        'shares': 'sum',
        'cik': 'nunique'
    }).reset_index()

    quarterly = quarterly.sort_values('filing_date')
    quarterly['value_millions'] = quarterly['value_thousands'] / 1_000_000  # Convert to millions

    # Calculate quarter-over-quarter changes
    quarterly['value_change_%'] = quarterly['value_millions'].pct_change() * 100
    quarterly['shares_change_%'] = quarterly['shares'].pct_change() * 100
    quarterly['institutions_change'] = quarterly['cik'].diff()

    # Get latest quarter data
    if len(quarterly) > 0:
        latest = quarterly.iloc[-1]
        position_changes.append({
            'cusip': cusip,
            'issuer_name': stock_name,
            'latest_value_millions': latest['value_millions'],
            'latest_num_institutions': latest['cik'],
            'qoq_value_change_%': latest['value_change_%'] if not pd.isna(latest['value_change_%']) else 0,
            'qoq_shares_change_%': latest['shares_change_%'] if not pd.isna(latest['shares_change_%']) else 0,
            'qoq_institutions_change': latest['institutions_change'] if not pd.isna(latest['institutions_change']) else 0
        })

position_changes_df = pd.DataFrame(position_changes)
position_changes_df = position_changes_df.sort_values('latest_value_millions', ascending=False)

print(f"\n  Top 20 Holdings - Latest QoQ Changes:")
print(f"  {'Stock':<35} {'Value ($M)':<15} {'Value Δ%':<12} {'Shares Δ%':<12} {'Inst Δ':<10}")
print("  " + "-"*90)

for _, row in position_changes_df.iterrows():
    value_symbol = "↑" if row['qoq_value_change_%'] > 0 else "↓" if row['qoq_value_change_%'] < 0 else "→"
    shares_symbol = "↑" if row['qoq_shares_change_%'] > 0 else "↓" if row['qoq_shares_change_%'] < 0 else "→"
    inst_symbol = "↑" if row['qoq_institutions_change'] > 0 else "↓" if row['qoq_institutions_change'] < 0 else "→"

    print(f"  {row['issuer_name'][:35]:<35} ${row['latest_value_millions']:>12,.0f} {value_symbol}{abs(row['qoq_value_change_%']):>8.1f}% {shares_symbol}{abs(row['qoq_shares_change_%']):>8.1f}% {inst_symbol}{abs(row['qoq_institutions_change']):>5.0f}")

# Save to CSV
position_changes_df.to_csv('data/13f/analysis_top20_position_changes.csv', index=False)

# ============================================================================
# 5. INSTITUTION-LEVEL PORTFOLIO METRICS
# ============================================================================
print("\n[6/6] Calculating institution-level portfolio metrics...")

# Latest quarter only
latest_df = df[df['filing_date'] == latest_quarter].copy()

# Calculate portfolio metrics per institution (value_thousands is actually in dollars)
inst_metrics = latest_df.groupby(['cik', 'institution_name']).agg({
    'value_thousands': ['sum', 'count'],
    'cusip': 'nunique'
}).reset_index()

inst_metrics.columns = ['cik', 'institution_name', 'total_aum_dollars', 'num_positions', 'num_unique_stocks']
inst_metrics['total_aum_billions'] = inst_metrics['total_aum_dollars'] / 1_000_000_000  # Convert to billions

# Calculate concentration (top 10 holdings as % of portfolio)
inst_concentrations = []

for cik in inst_metrics['cik'].unique():
    inst_holdings = latest_df[latest_df['cik'] == cik].copy()
    inst_holdings = inst_holdings.sort_values('value_thousands', ascending=False)  # Sort by dollars

    total_value = inst_holdings['value_thousands'].sum()
    top_10_value = inst_holdings.head(10)['value_thousands'].sum()

    inst_concentrations.append({
        'cik': cik,
        'top_10_concentration_%': (top_10_value / total_value * 100) if total_value > 0 else 0
    })

concentration_metrics = pd.DataFrame(inst_concentrations)
inst_metrics = inst_metrics.merge(concentration_metrics, on='cik')

# Sort by AUM
inst_metrics = inst_metrics.sort_values('total_aum_billions', ascending=False)

print(f"\n  Top 30 Institutions by AUM ({latest_quarter.date()}):")
print(f"  {'Rank':<6} {'Institution':<40} {'AUM ($B)':<15} {'# Positions':<13} {'Top 10 Conc %':<15}")
print("  " + "-"*95)

for idx, row in inst_metrics.head(30).iterrows():
    rank = inst_metrics.index.get_loc(idx) + 1
    print(f"  {rank:<6} {row['institution_name'][:40]:<40} ${row['total_aum_billions']:>12,.2f} {row['num_positions']:>11} {row['top_10_concentration_%']:>12.1f}%")

# Save to CSV
inst_metrics.to_csv('data/13f/analysis_institution_metrics.csv', index=False)

# ============================================================================
# SUMMARY STATISTICS
# ============================================================================
print("\n" + "="*90)
print("SUMMARY STATISTICS")
print("="*90)

summary = {
    'total_records': int(len(df)),
    'unique_institutions': int(df['cik'].nunique()),
    'unique_stocks': int(df['cusip'].nunique()),
    'date_range_start': str(df['filing_date'].min().date()),
    'date_range_end': str(df['filing_date'].max().date()),
    'total_quarters': int(df['filing_date'].nunique()),
    'latest_quarter_date': str(latest_quarter.date()),
    'latest_quarter_num_institutions': int(num_insts),
    'latest_quarter_aum_billions': float(latest_df['value_thousands'].sum() / 1_000_000_000),
    'latest_quarter_positions': int(len(latest_df)),
    'avg_aum_per_institution_billions': float(inst_metrics['total_aum_billions'].mean()),
    'median_aum_per_institution_billions': float(inst_metrics['total_aum_billions'].median()),
    'avg_positions_per_institution': float(inst_metrics['num_positions'].mean()),
    'median_positions_per_institution': float(inst_metrics['num_positions'].median()),
    'top_stock': str(top_50_holdings.iloc[0]['issuer_name']),
    'top_stock_value_billions': float(top_50_holdings.iloc[0]['total_value_millions'] / 1000),
    'most_held_stock': str(most_held.iloc[0]['issuer_name']),
    'most_held_stock_institutions': int(most_held.iloc[0]['num_institutions'])
}

print(f"\n  Dataset Overview:")
print(f"    Total Records: {summary['total_records']:,}")
print(f"    Institutions: {summary['unique_institutions']:,}")
print(f"    Unique Stocks: {summary['unique_stocks']:,}")
print(f"    Date Range: {summary['date_range_start']} to {summary['date_range_end']}")
print(f"    Quarters: {summary['total_quarters']}")

print(f"\n  Latest Quarter ({summary['latest_quarter_date']}):")
print(f"    Institutions Reporting: {summary['latest_quarter_num_institutions']}")
print(f"    Total AUM: ${summary['latest_quarter_aum_billions']:.1f}B (${summary['latest_quarter_aum_billions']/1000:.2f}T)")
print(f"    Total Positions: {summary['latest_quarter_positions']:,}")
print(f"    Avg AUM/Institution: ${summary['avg_aum_per_institution_billions']:.1f}B")
print(f"    Median AUM/Institution: ${summary['median_aum_per_institution_billions']:.1f}B")
print(f"    Avg Positions/Institution: {summary['avg_positions_per_institution']:.0f}")
print(f"    Median Positions/Institution: {summary['median_positions_per_institution']:.0f}")

print(f"\n  Top Holdings:")
print(f"    Most Valuable: {summary['top_stock']} (${summary['top_stock_value_billions']:.1f}B)")
print(f"    Most Widely Held: {summary['most_held_stock']} ({summary['most_held_stock_institutions']} institutions)")

# Save summary
with open('data/13f/analysis_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print("\n" + "="*90)
print("ANALYSIS COMPLETE")
print("="*90)
print("\nOutput files:")
print("  1. data/13f/analysis_top50_holdings.csv")
print("  2. data/13f/analysis_most_widely_held.csv")
print("  3. data/13f/analysis_concentration_trends.csv")
print("  4. data/13f/analysis_top20_position_changes.csv")
print("  5. data/13f/analysis_institution_metrics.csv")
print("  6. data/13f/analysis_summary.json")
print("="*90)
