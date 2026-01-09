"""
Analyze Top 10 Parameter Combinations Per Contract
"""
import pandas as pd
import numpy as np

print("Loading full optimization results...")
df = pd.read_csv('sandbox/cot_optimization_40_contracts_full.csv')

print(f"Total rows: {len(df):,}")
print(f"Contracts: {df['Contract'].nunique()}")

# Get top 10 for each contract by Sharpe ratio
print("\n" + "="*100)
print("ANALYZING TOP 10 PARAMETER COMBINATIONS PER CONTRACT")
print("="*100)

results = []

for contract in sorted(df['Contract'].unique()):
    contract_df = df[df['Contract'] == contract].copy()

    # Remove infinite Sharpe values
    contract_df = contract_df[~contract_df['Sharpe'].isin([np.inf, -np.inf])]

    # Get top 10 by Sharpe
    top10 = contract_df.nlargest(10, 'Sharpe')

    if len(top10) == 0:
        continue

    # Collect patterns
    pattern = {
        'Contract': contract,
        'Best_Sharpe': top10['Sharpe'].iloc[0],
        'Avg_Sharpe_Top10': top10['Sharpe'].mean(),
        'Best_Return': top10['Avg_Return'].iloc[0],
        'Avg_Return_Top10': top10['Avg_Return'].mean(),
        'Best_WinRate': top10['Win_Rate'].iloc[0],
        'Avg_WinRate_Top10': top10['Win_Rate'].mean(),

        # Most common parameters in top 10
        'Most_Common_Logic': top10['Signal_Logic'].mode().iloc[0] if len(top10['Signal_Logic'].mode()) > 0 else 'N/A',
        'Logic_Count': (top10['Signal_Logic'] == top10['Signal_Logic'].mode().iloc[0]).sum() if len(top10['Signal_Logic'].mode()) > 0 else 0,

        'Most_Common_Forward': top10['Forward_Period'].mode().iloc[0] if len(top10['Forward_Period'].mode()) > 0 else 'N/A',
        'Forward_Count': (top10['Forward_Period'] == top10['Forward_Period'].mode().iloc[0]).sum() if len(top10['Forward_Period'].mode()) > 0 else 0,

        'Avg_COT_Lookback': top10['COT_Lookback'].mean(),
        'Avg_Move_Period': top10['Move_Period'].mean(),
        'Avg_COT_Low': top10['COT_Low'].mean(),
        'Avg_COT_High': top10['COT_High'].mean(),
        'Avg_Move_Low': top10['Move_Low'].mean(),
        'Avg_Move_High': top10['Move_High'].mean(),

        'N_Signals_Best': top10['Total_Signals'].iloc[0],
        'Avg_N_Signals_Top10': top10['Total_Signals'].mean()
    }

    results.append(pattern)

# Create results DataFrame
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('Best_Sharpe', ascending=False)

# Save to CSV
results_df.to_csv('sandbox/top10_patterns_by_contract.csv', index=False)
print(f"\n✓ Saved detailed patterns to: sandbox/top10_patterns_by_contract.csv")

# Print summary for each contract
print("\n" + "="*100)
print("TOP 10 COMBINATIONS SUMMARY BY CONTRACT")
print("="*100)

for idx, row in results_df.iterrows():
    print(f"\n{'='*100}")
    print(f"#{results_df.index.get_loc(idx)+1} {row['Contract']}")
    print(f"{'='*100}")
    print(f"  Best Sharpe:         {row['Best_Sharpe']:.3f}")
    print(f"  Avg Sharpe (Top 10): {row['Avg_Sharpe_Top10']:.3f}")
    print(f"  Best Return:         {row['Best_Return']:.2f}%")
    print(f"  Avg Return (Top 10): {row['Avg_Return_Top10']:.2f}%")
    print(f"  Best Win Rate:       {row['Best_WinRate']:.1f}%")
    print(f"  Avg Win Rate (Top10):{row['Avg_WinRate_Top10']:.1f}%")
    print(f"\n  DOMINANT PATTERNS IN TOP 10:")
    print(f"    Signal Logic:      {row['Most_Common_Logic']} ({row['Logic_Count']}/10 configs)")
    print(f"    Forward Period:    {row['Most_Common_Forward']} ({row['Forward_Count']}/10 configs)")
    print(f"    Avg COT Lookback:  {row['Avg_COT_Lookback']:.0f} weeks")
    print(f"    Avg Move Period:   {row['Avg_Move_Period']:.0f} weeks")
    print(f"    Avg COT Thresholds:{row['Avg_COT_Low']:.0f} / {row['Avg_COT_High']:.0f}")
    print(f"    Avg Move Thresholds:{row['Avg_Move_Low']:.0f} / {row['Avg_Move_High']:.0f}")
    print(f"    Best Config Signals:{row['N_Signals_Best']:.0f}")
    print(f"    Avg Signals (Top10):{row['Avg_N_Signals_Top10']:.0f}")

# Overall pattern analysis
print("\n" + "="*100)
print("OVERALL PATTERN ANALYSIS ACROSS ALL CONTRACTS")
print("="*100)

print(f"\nSIGNAL LOGIC DISTRIBUTION (in top 10s):")
logic_counts = results_df.groupby('Most_Common_Logic')['Logic_Count'].sum()
print(logic_counts.sort_values(ascending=False))

print(f"\nFORWARD PERIOD DISTRIBUTION (in top 10s):")
forward_counts = results_df.groupby('Most_Common_Forward')['Forward_Count'].sum()
print(forward_counts.sort_values(ascending=False))

print(f"\nAVERAGE PARAMETER VALUES (across all top 10s):")
print(f"  COT Lookback:     {results_df['Avg_COT_Lookback'].mean():.1f} weeks (std: {results_df['Avg_COT_Lookback'].std():.1f})")
print(f"  Move Period:      {results_df['Avg_Move_Period'].mean():.1f} weeks (std: {results_df['Avg_Move_Period'].std():.1f})")
print(f"  COT Low Thresh:   {results_df['Avg_COT_Low'].mean():.1f} (std: {results_df['Avg_COT_Low'].std():.1f})")
print(f"  COT High Thresh:  {results_df['Avg_COT_High'].mean():.1f} (std: {results_df['Avg_COT_High'].std():.1f})")
print(f"  Move Low Thresh:  {results_df['Avg_Move_Low'].mean():.1f} (std: {results_df['Avg_Move_Low'].std():.1f})")
print(f"  Move High Thresh: {results_df['Avg_Move_High'].mean():.1f} (std: {results_df['Avg_Move_High'].std():.1f})")

print("\n" + "="*100)
print("✓ ANALYSIS COMPLETE")
print("="*100)
