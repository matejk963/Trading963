"""
Visualize Universal Parameters Results
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load results
df = pd.read_csv('sandbox/universal_parameters_results.csv')

print(f"Loaded {len(df)} results")
print(f"Contracts: {df['Contract'].nunique()}")
print(f"Forward periods: {df['Forward_Period'].unique()}")

# Separate by forward period
df_4w = df[df['Forward_Period'] == '4w'].copy()
df_26w = df[df['Forward_Period'] == '26w'].copy()

# Sort by Sharpe
df_4w = df_4w.sort_values('Sharpe', ascending=False).reset_index(drop=True)
df_26w = df_26w.sort_values('Sharpe', ascending=False).reset_index(drop=True)

# Create comprehensive visualization
fig = plt.figure(figsize=(22, 14))

# ============================================================================
# 1. SHARPE COMPARISON: 4w vs 26w
# ============================================================================
ax1 = plt.subplot(3, 3, 1)
df_comp = pd.merge(df_4w[['Contract', 'Sharpe']], df_26w[['Contract', 'Sharpe']],
                   on='Contract', suffixes=('_4w', '_26w'))
x = np.arange(len(df_comp))
width = 0.35

bars1 = ax1.bar(x - width/2, df_comp['Sharpe_4w'], width, label='4w', alpha=0.8, color='#3498db')
bars2 = ax1.bar(x + width/2, df_comp['Sharpe_26w'], width, label='26w', alpha=0.8, color='#e74c3c')

ax1.axhline(y=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax1.set_ylabel('Sharpe Ratio', fontsize=11, fontweight='bold')
ax1.set_title('Sharpe Ratio: 4w vs 26w Forward Period', fontsize=13, fontweight='bold')
ax1.set_xticks(x[::2])  # Every other contract
ax1.set_xticklabels(df_comp['Contract'][::2], fontsize=8, rotation=45)
ax1.legend(fontsize=10)
ax1.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 2. RETURN COMPARISON: 4w vs 26w
# ============================================================================
ax2 = plt.subplot(3, 3, 2)
df_comp = pd.merge(df_4w[['Contract', 'Avg_Return']], df_26w[['Contract', 'Avg_Return']],
                   on='Contract', suffixes=('_4w', '_26w'))

bars1 = ax2.bar(x - width/2, df_comp['Avg_Return_4w'], width, label='4w', alpha=0.8, color='#3498db')
bars2 = ax2.bar(x + width/2, df_comp['Avg_Return_26w'], width, label='26w', alpha=0.8, color='#e74c3c')

ax2.axhline(y=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax2.set_ylabel('Avg Return (%)', fontsize=11, fontweight='bold')
ax2.set_title('Average Return: 4w vs 26w Forward Period', fontsize=13, fontweight='bold')
ax2.set_xticks(x[::2])
ax2.set_xticklabels(df_comp['Contract'][::2], fontsize=8, rotation=45)
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 3. WIN RATE COMPARISON: 4w vs 26w
# ============================================================================
ax3 = plt.subplot(3, 3, 3)
df_comp = pd.merge(df_4w[['Contract', 'Win_Rate']], df_26w[['Contract', 'Win_Rate']],
                   on='Contract', suffixes=('_4w', '_26w'))

bars1 = ax3.bar(x - width/2, df_comp['Win_Rate_4w'], width, label='4w', alpha=0.8, color='#3498db')
bars2 = ax3.bar(x + width/2, df_comp['Win_Rate_26w'], width, label='26w', alpha=0.8, color='#e74c3c')

ax3.axhline(y=50, color='black', linestyle='--', linewidth=1, alpha=0.5, label='Breakeven')
ax3.set_ylabel('Win Rate (%)', fontsize=11, fontweight='bold')
ax3.set_title('Win Rate: 4w vs 26w Forward Period', fontsize=13, fontweight='bold')
ax3.set_xticks(x[::2])
ax3.set_xticklabels(df_comp['Contract'][::2], fontsize=8, rotation=45)
ax3.legend(fontsize=10)
ax3.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 4. TOP 15 CONTRACTS - 4W FORWARD
# ============================================================================
ax4 = plt.subplot(3, 3, 4)
top15_4w = df_4w.head(15)
colors_4w = ['#2ecc71' if s > 0.5 else '#f39c12' if s > 0 else '#e74c3c' for s in top15_4w['Sharpe']]

y_pos = np.arange(len(top15_4w))
bars = ax4.barh(y_pos, top15_4w['Sharpe'], color=colors_4w, alpha=0.7, edgecolor='black')

ax4.set_yticks(y_pos)
ax4.set_yticklabels(top15_4w['Contract'], fontsize=9)
ax4.set_xlabel('Sharpe Ratio', fontsize=11, fontweight='bold')
ax4.set_title('Top 15 Contracts - 4w Forward Period', fontsize=13, fontweight='bold')
ax4.axvline(x=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax4.grid(True, alpha=0.3, axis='x')

# ============================================================================
# 5. TOP 15 CONTRACTS - 26W FORWARD
# ============================================================================
ax5 = plt.subplot(3, 3, 5)
top15_26w = df_26w.head(15)
colors_26w = ['#2ecc71' if s > 0.5 else '#f39c12' if s > 0 else '#e74c3c' for s in top15_26w['Sharpe']]

y_pos = np.arange(len(top15_26w))
bars = ax5.barh(y_pos, top15_26w['Sharpe'], color=colors_26w, alpha=0.7, edgecolor='black')

ax5.set_yticks(y_pos)
ax5.set_yticklabels(top15_26w['Contract'], fontsize=9)
ax5.set_xlabel('Sharpe Ratio', fontsize=11, fontweight='bold')
ax5.set_title('Top 15 Contracts - 26w Forward Period', fontsize=13, fontweight='bold')
ax5.axvline(x=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax5.grid(True, alpha=0.3, axis='x')

# ============================================================================
# 6. SHARPE DISTRIBUTION - 4W
# ============================================================================
ax6 = plt.subplot(3, 3, 6)
ax6.hist(df_4w['Sharpe'], bins=20, edgecolor='black', color='#3498db', alpha=0.7)
ax6.axvline(df_4w['Sharpe'].mean(), color='red', linestyle='--', linewidth=2,
            label=f'Mean: {df_4w["Sharpe"].mean():.3f}')
ax6.axvline(df_4w['Sharpe'].median(), color='blue', linestyle='-', linewidth=2,
            label=f'Median: {df_4w["Sharpe"].median():.3f}')
ax6.axvline(0, color='black', linestyle=':', linewidth=1.5, alpha=0.7)
ax6.set_xlabel('Sharpe Ratio', fontsize=11)
ax6.set_ylabel('Number of Contracts', fontsize=11)
ax6.set_title('Sharpe Distribution - 4w Forward', fontsize=13, fontweight='bold')
ax6.legend(fontsize=9)
ax6.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 7. SHARPE DISTRIBUTION - 26W
# ============================================================================
ax7 = plt.subplot(3, 3, 7)
ax7.hist(df_26w['Sharpe'], bins=20, edgecolor='black', color='#e74c3c', alpha=0.7)
ax7.axvline(df_26w['Sharpe'].mean(), color='darkred', linestyle='--', linewidth=2,
            label=f'Mean: {df_26w["Sharpe"].mean():.3f}')
ax7.axvline(df_26w['Sharpe'].median(), color='blue', linestyle='-', linewidth=2,
            label=f'Median: {df_26w["Sharpe"].median():.3f}')
ax7.axvline(0, color='black', linestyle=':', linewidth=1.5, alpha=0.7)
ax7.set_xlabel('Sharpe Ratio', fontsize=11)
ax7.set_ylabel('Number of Contracts', fontsize=11)
ax7.set_title('Sharpe Distribution - 26w Forward', fontsize=13, fontweight='bold')
ax7.legend(fontsize=9)
ax7.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 8. SCATTER: 4W SHARPE VS 26W SHARPE
# ============================================================================
ax8 = plt.subplot(3, 3, 8)
df_comp = pd.merge(df_4w[['Contract', 'Sharpe', 'Win_Rate']],
                   df_26w[['Contract', 'Sharpe']],
                   on='Contract', suffixes=('_4w', '_26w'))

scatter = ax8.scatter(df_comp['Sharpe_4w'], df_comp['Sharpe_26w'],
                      c=df_comp['Win_Rate'], cmap='RdYlGn', s=100, alpha=0.7, edgecolor='black')

# Add diagonal line (perfect correlation)
min_val = min(df_comp['Sharpe_4w'].min(), df_comp['Sharpe_26w'].min())
max_val = max(df_comp['Sharpe_4w'].max(), df_comp['Sharpe_26w'].max())
ax8.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.3, label='Perfect Correlation')

# Label top performers
for idx, row in df_comp.iterrows():
    if row['Sharpe_4w'] > 0.5 or row['Sharpe_26w'] > 0.5:
        ax8.annotate(row['Contract'], (row['Sharpe_4w'], row['Sharpe_26w']),
                     fontsize=7, ha='right')

ax8.set_xlabel('4w Forward Sharpe', fontsize=11, fontweight='bold')
ax8.set_ylabel('26w Forward Sharpe', fontsize=11, fontweight='bold')
ax8.set_title('Sharpe Correlation: 4w vs 26w', fontsize=13, fontweight='bold')
ax8.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax8, label='Win Rate (4w)')
ax8.legend(fontsize=9)

# ============================================================================
# 9. SIGNAL COUNT COMPARISON
# ============================================================================
ax9 = plt.subplot(3, 3, 9)
df_comp = pd.merge(df_4w[['Contract', 'Total_Signals']],
                   df_26w[['Contract', 'Total_Signals']],
                   on='Contract', suffixes=('_4w', '_26w'))

x = np.arange(len(df_comp))
bars1 = ax9.bar(x - width/2, df_comp['Total_Signals_4w'], width, label='4w', alpha=0.8, color='#3498db')
bars2 = ax9.bar(x + width/2, df_comp['Total_Signals_26w'], width, label='26w', alpha=0.8, color='#e74c3c')

ax9.set_ylabel('Total Signals', fontsize=11, fontweight='bold')
ax9.set_title('Signal Count: 4w vs 26w', fontsize=13, fontweight='bold')
ax9.set_xticks(x[::2])
ax9.set_xticklabels(df_comp['Contract'][::2], fontsize=8, rotation=45)
ax9.legend(fontsize=10)
ax9.grid(True, alpha=0.3, axis='y')

plt.suptitle('Universal Parameters Test: 4w vs 26w Forward Periods\\n(Both_AND, 150w COT, 8w Move, 10/90 & ±45 Thresholds)',
             fontsize=16, fontweight='bold', y=0.995)

plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig('figures/cot_distributions/universal_parameters_comparison.png', dpi=150, bbox_inches='tight')
print("✓ Saved: figures/cot_distributions/universal_parameters_comparison.png")

# ============================================================================
# CREATE SUMMARY TABLE
# ============================================================================
print("\n" + "="*100)
print("UNIVERSAL PARAMETERS RESULTS SUMMARY")
print("="*100)

print("\n4W FORWARD PERIOD:")
print(f"  Mean Sharpe:   {df_4w['Sharpe'].mean():.3f}")
print(f"  Median Sharpe: {df_4w['Sharpe'].median():.3f}")
print(f"  Positive:      {(df_4w['Sharpe'] > 0).sum()}/{len(df_4w)} ({(df_4w['Sharpe'] > 0).mean()*100:.1f}%)")
print(f"  Sharpe > 0.5:  {(df_4w['Sharpe'] > 0.5).sum()}/{len(df_4w)} ({(df_4w['Sharpe'] > 0.5).mean()*100:.1f}%)")

print("\n26W FORWARD PERIOD:")
print(f"  Mean Sharpe:   {df_26w['Sharpe'].mean():.3f}")
print(f"  Median Sharpe: {df_26w['Sharpe'].median():.3f}")
print(f"  Positive:      {(df_26w['Sharpe'] > 0).sum()}/{len(df_26w)} ({(df_26w['Sharpe'] > 0).mean()*100:.1f}%)")
print(f"  Sharpe > 0.5:  {(df_26w['Sharpe'] > 0.5).sum()}/{len(df_26w)} ({(df_26w['Sharpe'] > 0.5).mean()*100:.1f}%)")

print("\n" + "="*100)
print("TOP 10 CONTRACTS - 4W FORWARD")
print("="*100)
for idx, row in df_4w.head(10).iterrows():
    print(f"{idx+1:2d}. {row['Contract']:6s} - Sharpe: {row['Sharpe']:6.3f}, Return: {row['Avg_Return']:7.2f}%, "
          f"WinRate: {row['Win_Rate']:5.1f}%, Signals: {int(row['Total_Signals']):3d}")

print("\n" + "="*100)
print("TOP 10 CONTRACTS - 26W FORWARD")
print("="*100)
for idx, row in df_26w.head(10).iterrows():
    print(f"{idx+1:2d}. {row['Contract']:6s} - Sharpe: {row['Sharpe']:6.3f}, Return: {row['Avg_Return']:7.2f}%, "
          f"WinRate: {row['Win_Rate']:5.1f}%, Signals: {int(row['Total_Signals']):3d}")

# Comparison analysis
print("\n" + "="*100)
print("WHICH FORWARD PERIOD IS BETTER?")
print("="*100)

df_comp = pd.merge(df_4w[['Contract', 'Sharpe']], df_26w[['Contract', 'Sharpe']],
                   on='Contract', suffixes=('_4w', '_26w'))
df_comp['Better_Period'] = df_comp.apply(lambda x: '4w' if x['Sharpe_4w'] > x['Sharpe_26w'] else '26w', axis=1)
df_comp['Sharpe_Diff'] = df_comp['Sharpe_26w'] - df_comp['Sharpe_4w']

better_4w = (df_comp['Better_Period'] == '4w').sum()
better_26w = (df_comp['Better_Period'] == '26w').sum()

print(f"\nBetter with 4w:  {better_4w}/{len(df_comp)} contracts ({better_4w/len(df_comp)*100:.1f}%)")
print(f"Better with 26w: {better_26w}/{len(df_comp)} contracts ({better_26w/len(df_comp)*100:.1f}%)")

print("\nContracts MUCH BETTER with 26w (Sharpe difference > 0.3):")
much_better_26w = df_comp[df_comp['Sharpe_Diff'] > 0.3].sort_values('Sharpe_Diff', ascending=False)
for idx, row in much_better_26w.iterrows():
    print(f"  {row['Contract']:6s}: 4w={row['Sharpe_4w']:6.3f}, 26w={row['Sharpe_26w']:6.3f}, Diff={row['Sharpe_Diff']:+.3f}")

print("\nContracts MUCH BETTER with 4w (Sharpe difference < -0.3):")
much_better_4w = df_comp[df_comp['Sharpe_Diff'] < -0.3].sort_values('Sharpe_Diff')
for idx, row in much_better_4w.iterrows():
    print(f"  {row['Contract']:6s}: 4w={row['Sharpe_4w']:6.3f}, 26w={row['Sharpe_26w']:6.3f}, Diff={row['Sharpe_Diff']:+.3f}")

# Save summary
summary_df = df_comp[['Contract', 'Sharpe_4w', 'Sharpe_26w', 'Sharpe_Diff', 'Better_Period']]
summary_df = summary_df.sort_values('Sharpe_Diff', ascending=False)
summary_df.to_csv('sandbox/universal_parameters_summary.csv', index=False)
print("\n✓ Saved: sandbox/universal_parameters_summary.csv")

print("\n" + "="*100)
print("✓ ANALYSIS COMPLETE")
print("="*100)
