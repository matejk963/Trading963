"""
Visualize Top 10 Parameter Patterns
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load the patterns
df = pd.read_csv('sandbox/top10_patterns_by_contract.csv')
df = df.sort_values('Best_Sharpe', ascending=False)

print(f"Loaded {len(df)} contracts")

# Create comprehensive visualization
fig = plt.figure(figsize=(20, 14))

# ============================================================================
# 1. SIGNAL LOGIC DISTRIBUTION
# ============================================================================
ax1 = plt.subplot(3, 3, 1)
logic_counts = df.groupby('Most_Common_Logic')['Logic_Count'].sum()
colors = ['#2ecc71', '#e74c3c', '#3498db', '#f39c12']
wedges, texts, autotexts = ax1.pie(logic_counts, labels=logic_counts.index, autopct='%1.1f%%',
                                     colors=colors[:len(logic_counts)], startangle=90)
for autotext in autotexts:
    autotext.set_color('white')
    autotext.set_fontsize(12)
    autotext.set_fontweight('bold')
ax1.set_title('Signal Logic Distribution\n(Top 10 Configs per Contract)', fontsize=12, fontweight='bold')

# ============================================================================
# 2. FORWARD PERIOD DISTRIBUTION
# ============================================================================
ax2 = plt.subplot(3, 3, 2)
forward_counts = df.groupby('Most_Common_Forward')['Forward_Count'].sum()
colors_fwd = ['#e74c3c', '#f39c12', '#2ecc71']
wedges, texts, autotexts = ax2.pie(forward_counts, labels=forward_counts.index, autopct='%1.1f%%',
                                     colors=colors_fwd, startangle=90)
for autotext in autotexts:
    autotext.set_color('white')
    autotext.set_fontsize(12)
    autotext.set_fontweight('bold')
ax2.set_title('Forward Period Distribution\n(Top 10 Configs per Contract)', fontsize=12, fontweight='bold')

# ============================================================================
# 3. COT LOOKBACK DISTRIBUTION
# ============================================================================
ax3 = plt.subplot(3, 3, 3)
ax3.hist(df['Avg_COT_Lookback'], bins=20, edgecolor='black', color='#3498db', alpha=0.7)
ax3.axvline(df['Avg_COT_Lookback'].mean(), color='red', linestyle='--', linewidth=2,
            label=f'Mean: {df["Avg_COT_Lookback"].mean():.0f}w')
ax3.axvline(df['Avg_COT_Lookback'].median(), color='blue', linestyle='-', linewidth=2,
            label=f'Median: {df["Avg_COT_Lookback"].median():.0f}w')
ax3.set_xlabel('COT Lookback Period (weeks)', fontsize=10)
ax3.set_ylabel('Number of Contracts', fontsize=10)
ax3.set_title('COT Lookback Distribution\n(Avg in Top 10)', fontsize=12, fontweight='bold')
ax3.legend(fontsize=9)
ax3.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 4. MOVE PERIOD DISTRIBUTION
# ============================================================================
ax4 = plt.subplot(3, 3, 4)
ax4.hist(df['Avg_Move_Period'], bins=15, edgecolor='black', color='#9b59b6', alpha=0.7)
ax4.axvline(df['Avg_Move_Period'].mean(), color='red', linestyle='--', linewidth=2,
            label=f'Mean: {df["Avg_Move_Period"].mean():.1f}w')
ax4.axvline(df['Avg_Move_Period'].median(), color='blue', linestyle='-', linewidth=2,
            label=f'Median: {df["Avg_Move_Period"].median():.1f}w')
ax4.set_xlabel('Move Period (weeks)', fontsize=10)
ax4.set_ylabel('Number of Contracts', fontsize=10)
ax4.set_title('Move Period Distribution\n(Avg in Top 10)', fontsize=12, fontweight='bold')
ax4.legend(fontsize=9)
ax4.grid(True, alpha=0.3, axis='y')

# ============================================================================
# 5. COT THRESHOLDS SCATTER
# ============================================================================
ax5 = plt.subplot(3, 3, 5)
scatter = ax5.scatter(df['Avg_COT_Low'], df['Avg_COT_High'], c=df['Best_Sharpe'],
                      cmap='RdYlGn', s=100, alpha=0.7, edgecolor='black')
ax5.set_xlabel('COT Low Threshold', fontsize=10)
ax5.set_ylabel('COT High Threshold', fontsize=10)
ax5.set_title('COT Threshold Ranges\n(Color = Best Sharpe)', fontsize=12, fontweight='bold')
ax5.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax5, label='Sharpe Ratio')

# ============================================================================
# 6. MOVE THRESHOLDS SCATTER
# ============================================================================
ax6 = plt.subplot(3, 3, 6)
scatter = ax6.scatter(df['Avg_Move_Low'], df['Avg_Move_High'], c=df['Best_Sharpe'],
                      cmap='RdYlGn', s=100, alpha=0.7, edgecolor='black')
ax6.set_xlabel('Move Low Threshold', fontsize=10)
ax6.set_ylabel('Move High Threshold', fontsize=10)
ax6.set_title('Move Threshold Ranges\n(Color = Best Sharpe)', fontsize=12, fontweight='bold')
ax6.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax6, label='Sharpe Ratio')

# ============================================================================
# 7. PERFORMANCE COMPARISON: SHARPE VS WIN RATE
# ============================================================================
ax7 = plt.subplot(3, 3, 7)
scatter = ax7.scatter(df['Avg_Sharpe_Top10'], df['Avg_WinRate_Top10'],
                      c=df['Avg_Return_Top10'], cmap='RdYlGn', s=150, alpha=0.7, edgecolor='black')

# Label top 5
for idx, row in df.head(5).iterrows():
    ax7.annotate(row['Contract'], (row['Avg_Sharpe_Top10'], row['Avg_WinRate_Top10']),
                 fontsize=8, fontweight='bold', ha='right')

ax7.set_xlabel('Avg Sharpe Ratio (Top 10)', fontsize=10)
ax7.set_ylabel('Avg Win Rate (Top 10) %', fontsize=10)
ax7.set_title('Performance Profile\n(Color = Avg Return)', fontsize=12, fontweight='bold')
ax7.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax7, label='Avg Return %')

# ============================================================================
# 8. PARAMETER STABILITY: STD DEV OF COT LOOKBACK
# ============================================================================
ax8 = plt.subplot(3, 3, 8)
top_contracts = df.head(15)
x_pos = np.arange(len(top_contracts))
bars = ax8.barh(x_pos, top_contracts['Avg_COT_Lookback'], color='#3498db', alpha=0.7, edgecolor='black')

# Color by Sharpe
for i, (idx, row) in enumerate(top_contracts.iterrows()):
    if row['Best_Sharpe'] > 2.0:
        bars[i].set_color('#2ecc71')
    elif row['Best_Sharpe'] > 1.0:
        bars[i].set_color('#f39c12')

ax8.set_yticks(x_pos)
ax8.set_yticklabels(top_contracts['Contract'], fontsize=9)
ax8.set_xlabel('Avg COT Lookback (weeks)', fontsize=10)
ax8.set_title('Top 15 Contracts: COT Lookback\n(Green: Sharpe>2, Orange: Sharpe>1)',
              fontsize=12, fontweight='bold')
ax8.grid(True, alpha=0.3, axis='x')

# ============================================================================
# 9. SIGNAL COUNT DISTRIBUTION
# ============================================================================
ax9 = plt.subplot(3, 3, 9)
ax9.hist(df['Avg_N_Signals_Top10'], bins=20, edgecolor='black', color='#e74c3c', alpha=0.7)
ax9.axvline(df['Avg_N_Signals_Top10'].mean(), color='darkred', linestyle='--', linewidth=2,
            label=f'Mean: {df["Avg_N_Signals_Top10"].mean():.0f}')
ax9.axvline(df['Avg_N_Signals_Top10'].median(), color='blue', linestyle='-', linewidth=2,
            label=f'Median: {df["Avg_N_Signals_Top10"].median():.0f}')
ax9.set_xlabel('Average Signal Count (Top 10)', fontsize=10)
ax9.set_ylabel('Number of Contracts', fontsize=10)
ax9.set_title('Signal Frequency Distribution\n(Avg in Top 10 Configs)', fontsize=12, fontweight='bold')
ax9.legend(fontsize=9)
ax9.grid(True, alpha=0.3, axis='y')

plt.suptitle('COT Index Optimization: Top 10 Parameter Patterns Across 42 Contracts',
             fontsize=16, fontweight='bold', y=0.995)

plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig('figures/cot_distributions/top10_parameter_patterns.png', dpi=150, bbox_inches='tight')
print("✓ Saved: figures/cot_distributions/top10_parameter_patterns.png")

# ============================================================================
# CREATE DETAILED CONTRACT COMPARISON
# ============================================================================
fig2, axes = plt.subplots(2, 2, figsize=(18, 12))

# Top 20 by Sharpe
top20 = df.head(20).copy()

# 1. Sharpe Comparison
ax = axes[0, 0]
x_pos = np.arange(len(top20))
bars = ax.barh(x_pos, top20['Best_Sharpe'], color='#2ecc71', alpha=0.7, edgecolor='black', label='Best')
ax.barh(x_pos, top20['Avg_Sharpe_Top10'], color='#3498db', alpha=0.5, edgecolor='black', label='Avg (Top 10)')
ax.set_yticks(x_pos)
ax.set_yticklabels(top20['Contract'], fontsize=9)
ax.set_xlabel('Sharpe Ratio', fontsize=11, fontweight='bold')
ax.set_title('Top 20 Contracts: Sharpe Ratio', fontsize=13, fontweight='bold')
ax.legend(loc='lower right', fontsize=10)
ax.grid(True, alpha=0.3, axis='x')

# 2. Return Comparison
ax = axes[0, 1]
bars = ax.barh(x_pos, top20['Best_Return'], color='#f39c12', alpha=0.7, edgecolor='black', label='Best')
ax.barh(x_pos, top20['Avg_Return_Top10'], color='#e74c3c', alpha=0.5, edgecolor='black', label='Avg (Top 10)')
ax.set_yticks(x_pos)
ax.set_yticklabels(top20['Contract'], fontsize=9)
ax.set_xlabel('Return (%)', fontsize=11, fontweight='bold')
ax.set_title('Top 20 Contracts: Average Return', fontsize=13, fontweight='bold')
ax.legend(loc='lower right', fontsize=10)
ax.grid(True, alpha=0.3, axis='x')

# 3. Win Rate Comparison
ax = axes[1, 0]
bars = ax.barh(x_pos, top20['Best_WinRate'], color='#9b59b6', alpha=0.7, edgecolor='black', label='Best')
ax.barh(x_pos, top20['Avg_WinRate_Top10'], color='#8e44ad', alpha=0.5, edgecolor='black', label='Avg (Top 10)')
ax.set_yticks(x_pos)
ax.set_yticklabels(top20['Contract'], fontsize=9)
ax.set_xlabel('Win Rate (%)', fontsize=11, fontweight='bold')
ax.set_title('Top 20 Contracts: Win Rate', fontsize=13, fontweight='bold')
ax.axvline(50, color='black', linestyle='--', linewidth=1, alpha=0.5, label='Breakeven')
ax.legend(loc='lower right', fontsize=10)
ax.grid(True, alpha=0.3, axis='x')

# 4. Logic Distribution by Contract
ax = axes[1, 1]
logic_map = {'Both_AND': '#2ecc71', 'Move_Only': '#e74c3c', 'COT_Only': '#3498db', 'Conditional': '#f39c12'}
colors = [logic_map.get(logic, '#95a5a6') for logic in top20['Most_Common_Logic']]
bars = ax.barh(x_pos, top20['Logic_Count'], color=colors, alpha=0.7, edgecolor='black')
ax.set_yticks(x_pos)
ax.set_yticklabels(top20['Contract'], fontsize=9)
ax.set_xlabel('Count in Top 10', fontsize=11, fontweight='bold')
ax.set_title('Most Common Signal Logic', fontsize=13, fontweight='bold')

# Create legend
from matplotlib.patches import Patch
legend_elements = [Patch(facecolor='#2ecc71', label='Both_AND'),
                   Patch(facecolor='#e74c3c', label='Move_Only')]
ax.legend(handles=legend_elements, loc='lower right', fontsize=10)
ax.grid(True, alpha=0.3, axis='x')

plt.suptitle('Top 20 Contracts: Detailed Performance Comparison',
             fontsize=16, fontweight='bold')
plt.tight_layout()
plt.savefig('figures/cot_distributions/top20_detailed_comparison.png', dpi=150, bbox_inches='tight')
print("✓ Saved: figures/cot_distributions/top20_detailed_comparison.png")

print("\n" + "="*80)
print("✓ VISUALIZATION COMPLETE")
print("="*80)
