"""
Plot distributions of all metrics for all contracts
Creates separate plots for each metric showing all contracts
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# Create output folder
output_dir = 'figures/cot_distributions'
os.makedirs(output_dir, exist_ok=True)

print("="*80)
print("PLOTTING METRIC DISTRIBUTIONS - ALL 42 CONTRACTS")
print("="*80)

# Load data
print("\nLoading optimization results...")
df = pd.read_csv('sandbox/cot_optimization_40_contracts_full.csv')
print(f"✓ Loaded {len(df)} parameter combinations across {df['Contract'].nunique()} contracts")

# Get contracts sorted by median Sharpe
summary = pd.read_csv('sandbox/cot_optimization_40_contracts_summary.csv')
sorted_contracts = summary.sort_values('Best_Sharpe', ascending=False)['Contract'].tolist()

print(f"✓ Sorted {len(sorted_contracts)} contracts by best Sharpe ratio")

# ============================================================================
# PLOT 1: SHARPE RATIO DISTRIBUTION
# ============================================================================
print("\n[1/5] Plotting Sharpe Ratio distributions...")

fig, ax = plt.subplots(figsize=(20, 12))

contract_data = []
labels = []
colors = []

for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]
    sharpes = contract_df['Sharpe'].replace([np.inf, -np.inf], np.nan).dropna()

    if len(sharpes) > 0:
        contract_data.append(sharpes.values)
        labels.append(contract)

        # Color by median performance
        median = np.median(sharpes)
        if median > 1.0:
            colors.append('#2ecc71')  # Green
        elif median > 0.5:
            colors.append('#95a5a6')  # Light green
        elif median > 0:
            colors.append('#f39c12')  # Orange
        else:
            colors.append('#e74c3c')  # Red

bp = ax.boxplot(contract_data, positions=range(len(contract_data)), widths=0.6,
                patch_artist=True, showfliers=False)

# Color boxes
for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

# Reference lines
ax.axhline(y=0, color='black', linestyle='--', linewidth=1.5, alpha=0.5)
ax.axhline(y=1.0, color='green', linestyle=':', linewidth=1.5, alpha=0.5, label='Excellent (>1.0)')
ax.axhline(y=0.5, color='orange', linestyle=':', linewidth=1.5, alpha=0.5, label='Good (>0.5)')

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=10)
ax.set_ylabel('Sharpe Ratio', fontsize=14, fontweight='bold')
ax.set_title('Sharpe Ratio Distribution - All Contracts (300 parameter combinations each)',
             fontsize=16, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')
ax.legend(loc='upper right', fontsize=12)

plt.tight_layout()
plt.savefig(f'{output_dir}/01_sharpe_ratio_distribution.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/01_sharpe_ratio_distribution.png")
plt.close()

# ============================================================================
# PLOT 2: AVERAGE RETURN DISTRIBUTION
# ============================================================================
print("[2/5] Plotting Average Return distributions...")

fig, ax = plt.subplots(figsize=(20, 12))

contract_data = []
labels = []
colors = []

for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]
    returns = contract_df['Avg_Return'].replace([np.inf, -np.inf], np.nan).dropna()

    if len(returns) > 0:
        contract_data.append(returns.values)
        labels.append(contract)

        median = np.median(returns)
        if median > 5.0:
            colors.append('#2ecc71')
        elif median > 2.0:
            colors.append('#95a5a6')
        elif median > 0:
            colors.append('#f39c12')
        else:
            colors.append('#e74c3c')

bp = ax.boxplot(contract_data, positions=range(len(contract_data)), widths=0.6,
                patch_artist=True, showfliers=False)

for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax.axhline(y=0, color='black', linestyle='--', linewidth=1.5, alpha=0.5)
ax.axhline(y=5.0, color='green', linestyle=':', linewidth=1.5, alpha=0.5, label='Strong (>5%)')
ax.axhline(y=2.0, color='orange', linestyle=':', linewidth=1.5, alpha=0.5, label='Good (>2%)')

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=10)
ax.set_ylabel('Average Return (%)', fontsize=14, fontweight='bold')
ax.set_title('Average Return Distribution - All Contracts (300 parameter combinations each)',
             fontsize=16, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')
ax.legend(loc='upper right', fontsize=12)

plt.tight_layout()
plt.savefig(f'{output_dir}/02_average_return_distribution.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/02_average_return_distribution.png")
plt.close()

# ============================================================================
# PLOT 3: WIN RATE DISTRIBUTION
# ============================================================================
print("[3/5] Plotting Win Rate distributions...")

fig, ax = plt.subplots(figsize=(20, 12))

contract_data = []
labels = []
colors = []

for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]
    winrates = contract_df['Win_Rate'].replace([np.inf, -np.inf], np.nan).dropna()

    if len(winrates) > 0:
        contract_data.append(winrates.values)
        labels.append(contract)

        median = np.median(winrates)
        if median > 60:
            colors.append('#2ecc71')
        elif median > 50:
            colors.append('#95a5a6')
        else:
            colors.append('#e74c3c')

bp = ax.boxplot(contract_data, positions=range(len(contract_data)), widths=0.6,
                patch_artist=True, showfliers=False)

for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax.axhline(y=50, color='black', linestyle='--', linewidth=1.5, alpha=0.5, label='Breakeven (50%)')
ax.axhline(y=60, color='green', linestyle=':', linewidth=1.5, alpha=0.5, label='Good (>60%)')

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=10)
ax.set_ylabel('Win Rate (%)', fontsize=14, fontweight='bold')
ax.set_title('Win Rate Distribution - All Contracts (300 parameter combinations each)',
             fontsize=16, fontweight='bold')
ax.set_ylim(0, 105)
ax.grid(True, alpha=0.3, axis='y')
ax.legend(loc='upper right', fontsize=12)

plt.tight_layout()
plt.savefig(f'{output_dir}/03_win_rate_distribution.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/03_win_rate_distribution.png")
plt.close()

# ============================================================================
# PLOT 4: SIGNAL COUNT DISTRIBUTION
# ============================================================================
print("[4/5] Plotting Signal Count distributions...")

fig, ax = plt.subplots(figsize=(20, 12))

contract_data = []
labels = []
colors = []

for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]
    signals = contract_df['Total_Signals'].replace([np.inf, -np.inf], np.nan).dropna()

    if len(signals) > 0:
        contract_data.append(signals.values)
        labels.append(contract)

        median = np.median(signals)
        if median > 50:
            colors.append('#3498db')
        elif median > 20:
            colors.append('#95a5a6')
        else:
            colors.append('#e74c3c')

bp = ax.boxplot(contract_data, positions=range(len(contract_data)), widths=0.6,
                patch_artist=True, showfliers=False)

for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax.axhline(y=20, color='orange', linestyle=':', linewidth=1.5, alpha=0.5, label='Min Threshold (20)')
ax.axhline(y=50, color='blue', linestyle=':', linewidth=1.5, alpha=0.5, label='Good Sample (>50)')

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=10)
ax.set_ylabel('Total Signals', fontsize=14, fontweight='bold')
ax.set_title('Signal Count Distribution - All Contracts (300 parameter combinations each)',
             fontsize=16, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')
ax.legend(loc='upper right', fontsize=12)

plt.tight_layout()
plt.savefig(f'{output_dir}/04_signal_count_distribution.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/04_signal_count_distribution.png")
plt.close()

# ============================================================================
# PLOT 5: COMBINED METRICS HEATMAP
# ============================================================================
print("[5/5] Creating combined metrics heatmap...")

# Calculate summary statistics for heatmap
heatmap_data = []

for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]

    sharpe = contract_df['Sharpe'].replace([np.inf, -np.inf], np.nan).dropna()
    returns = contract_df['Avg_Return'].replace([np.inf, -np.inf], np.nan).dropna()
    winrate = contract_df['Win_Rate'].replace([np.inf, -np.inf], np.nan).dropna()
    signals = contract_df['Total_Signals'].replace([np.inf, -np.inf], np.nan).dropna()

    heatmap_data.append({
        'Contract': contract,
        'Median_Sharpe': np.median(sharpe) if len(sharpe) > 0 else 0,
        'Median_Return': np.median(returns) if len(returns) > 0 else 0,
        'Median_WinRate': np.median(winrate) if len(winrate) > 0 else 0,
        'Median_Signals': np.median(signals) if len(signals) > 0 else 0,
        'Pct_Positive_Sharpe': (sharpe > 0).mean() * 100 if len(sharpe) > 0 else 0,
        'Pct_Positive_Return': (returns > 0).mean() * 100 if len(returns) > 0 else 0,
    })

heatmap_df = pd.DataFrame(heatmap_data)

fig, axes = plt.subplots(1, 2, figsize=(20, 14))

# Left heatmap: Median values
ax1 = axes[0]
metrics = ['Median_Sharpe', 'Median_Return', 'Median_WinRate', 'Median_Signals']
data_matrix = heatmap_df[metrics].T.values

im1 = ax1.imshow(data_matrix, cmap='RdYlGn', aspect='auto')
ax1.set_xticks(range(len(sorted_contracts)))
ax1.set_xticklabels(sorted_contracts, rotation=45, ha='right', fontsize=9)
ax1.set_yticks(range(len(metrics)))
ax1.set_yticklabels(['Median Sharpe', 'Median Return (%)', 'Median Win Rate (%)', 'Median Signals'], fontsize=11)
ax1.set_title('Median Values Across All Parameter Combinations', fontsize=14, fontweight='bold')

# Add values
for i in range(len(metrics)):
    for j in range(len(sorted_contracts)):
        val = data_matrix[i, j]
        text = ax1.text(j, i, f'{val:.1f}', ha="center", va="center",
                       color="black" if 0.3 < im1.norm(val) < 0.7 else "white",
                       fontsize=7)

plt.colorbar(im1, ax=ax1)

# Right heatmap: % Positive
ax2 = axes[1]
metrics2 = ['Pct_Positive_Sharpe', 'Pct_Positive_Return']
data_matrix2 = heatmap_df[metrics2].T.values

im2 = ax2.imshow(data_matrix2, cmap='RdYlGn', aspect='auto', vmin=0, vmax=100)
ax2.set_xticks(range(len(sorted_contracts)))
ax2.set_xticklabels(sorted_contracts, rotation=45, ha='right', fontsize=9)
ax2.set_yticks(range(len(metrics2)))
ax2.set_yticklabels(['% Positive Sharpe', '% Positive Return'], fontsize=11)
ax2.set_title('% of Parameter Combinations with Positive Results', fontsize=14, fontweight='bold')

# Add values
for i in range(len(metrics2)):
    for j in range(len(sorted_contracts)):
        val = data_matrix2[i, j]
        text = ax2.text(j, i, f'{val:.0f}%', ha="center", va="center",
                       color="black" if 0.3 < im2.norm(val) < 0.7 else "white",
                       fontsize=7)

plt.colorbar(im2, ax=ax2)

plt.suptitle('Parameter Robustness Heatmap - All 42 Contracts', fontsize=16, fontweight='bold', y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig(f'{output_dir}/05_combined_metrics_heatmap.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/05_combined_metrics_heatmap.png")
plt.close()

# ============================================================================
# BONUS: TOP 10 CONTRACTS - DETAILED HISTOGRAMS
# ============================================================================
print("\n[BONUS] Creating detailed histogram grid for top 10 contracts...")

top10_contracts = sorted_contracts[:10]

fig = plt.figure(figsize=(24, 18))

for idx, contract in enumerate(top10_contracts):
    contract_df = df[df['Contract'] == contract]

    # Get contract name
    contract_name = summary[summary['Contract'] == contract]['Name'].iloc[0]
    best_sharpe = summary[summary['Contract'] == contract]['Best_Sharpe'].iloc[0]

    # Sharpe subplot
    ax1 = plt.subplot(10, 4, idx*4 + 1)
    sharpes = contract_df['Sharpe'].replace([np.inf, -np.inf], np.nan).dropna()
    ax1.hist(sharpes, bins=30, alpha=0.7, color='#3498db', edgecolor='black', linewidth=0.5)
    ax1.axvline(np.median(sharpes), color='red', linestyle='--', linewidth=2)
    ax1.axvline(0, color='black', linestyle=':', linewidth=1)
    ax1.set_ylabel('Frequency', fontsize=8)
    if idx == 0:
        ax1.set_title('Sharpe Ratio', fontsize=10, fontweight='bold')
    ax1.text(0.02, 0.98, f'{contract}\n{contract_name[:15]}', transform=ax1.transAxes,
             fontsize=8, verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    ax1.tick_params(labelsize=7)

    # Return subplot
    ax2 = plt.subplot(10, 4, idx*4 + 2)
    returns = contract_df['Avg_Return'].replace([np.inf, -np.inf], np.nan).dropna()
    ax2.hist(returns, bins=30, alpha=0.7, color='#2ecc71', edgecolor='black', linewidth=0.5)
    ax2.axvline(np.median(returns), color='red', linestyle='--', linewidth=2)
    ax2.axvline(0, color='black', linestyle=':', linewidth=1)
    if idx == 0:
        ax2.set_title('Avg Return (%)', fontsize=10, fontweight='bold')
    ax2.tick_params(labelsize=7)

    # Win Rate subplot
    ax3 = plt.subplot(10, 4, idx*4 + 3)
    winrates = contract_df['Win_Rate'].replace([np.inf, -np.inf], np.nan).dropna()
    ax3.hist(winrates, bins=30, alpha=0.7, color='#f39c12', edgecolor='black', linewidth=0.5)
    ax3.axvline(np.median(winrates), color='red', linestyle='--', linewidth=2)
    ax3.axvline(50, color='black', linestyle=':', linewidth=1)
    if idx == 0:
        ax3.set_title('Win Rate (%)', fontsize=10, fontweight='bold')
    ax3.tick_params(labelsize=7)

    # Signals subplot
    ax4 = plt.subplot(10, 4, idx*4 + 4)
    signals = contract_df['Total_Signals'].replace([np.inf, -np.inf], np.nan).dropna()
    ax4.hist(signals, bins=30, alpha=0.7, color='#9b59b6', edgecolor='black', linewidth=0.5)
    ax4.axvline(np.median(signals), color='red', linestyle='--', linewidth=2)
    if idx == 0:
        ax4.set_title('Signal Count', fontsize=10, fontweight='bold')
    ax4.tick_params(labelsize=7)

plt.suptitle('Detailed Metric Distributions - Top 10 Contracts by Sharpe Ratio', fontsize=18, fontweight='bold')
plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig(f'{output_dir}/06_top10_detailed_histograms.png', dpi=150, bbox_inches='tight')
print(f"   ✓ Saved: {output_dir}/06_top10_detailed_histograms.png")
plt.close()

# ============================================================================
# SAVE SUMMARY STATISTICS
# ============================================================================
print("\n[FINAL] Saving robustness statistics...")

stats_data = []
for contract in sorted_contracts:
    contract_df = df[df['Contract'] == contract]

    sharpes = contract_df['Sharpe'].replace([np.inf, -np.inf], np.nan).dropna()
    returns = contract_df['Avg_Return'].replace([np.inf, -np.inf], np.nan).dropna()
    winrates = contract_df['Win_Rate'].replace([np.inf, -np.inf], np.nan).dropna()
    signals = contract_df['Total_Signals'].replace([np.inf, -np.inf], np.nan).dropna()

    stats_data.append({
        'Contract': contract,
        'Name': summary[summary['Contract'] == contract]['Name'].iloc[0],
        'Median_Sharpe': np.median(sharpes) if len(sharpes) > 0 else np.nan,
        'Mean_Sharpe': np.mean(sharpes) if len(sharpes) > 0 else np.nan,
        'Std_Sharpe': np.std(sharpes) if len(sharpes) > 0 else np.nan,
        'Median_Return': np.median(returns) if len(returns) > 0 else np.nan,
        'Mean_Return': np.mean(returns) if len(returns) > 0 else np.nan,
        'Median_WinRate': np.median(winrates) if len(winrates) > 0 else np.nan,
        'Mean_WinRate': np.mean(winrates) if len(winrates) > 0 else np.nan,
        'Median_Signals': np.median(signals) if len(signals) > 0 else np.nan,
        'Pct_Positive_Sharpe': (sharpes > 0).mean() * 100 if len(sharpes) > 0 else 0,
        'Pct_Sharpe_Above_0.5': (sharpes > 0.5).mean() * 100 if len(sharpes) > 0 else 0,
        'Pct_Sharpe_Above_1.0': (sharpes > 1.0).mean() * 100 if len(sharpes) > 0 else 0,
        'N_Configs': len(sharpes)
    })

stats_df = pd.DataFrame(stats_data)
stats_df.to_csv(f'{output_dir}/robustness_statistics_all_contracts.csv', index=False)
print(f"   ✓ Saved: {output_dir}/robustness_statistics_all_contracts.csv")

print("\n" + "="*80)
print("✓ ALL PLOTS COMPLETE")
print("="*80)
print(f"\nGenerated 6 visualization files in: {output_dir}/")
print("  1. 01_sharpe_ratio_distribution.png")
print("  2. 02_average_return_distribution.png")
print("  3. 03_win_rate_distribution.png")
print("  4. 04_signal_count_distribution.png")
print("  5. 05_combined_metrics_heatmap.png")
print("  6. 06_top10_detailed_histograms.png")
print("  + robustness_statistics_all_contracts.csv")
print("="*80)
