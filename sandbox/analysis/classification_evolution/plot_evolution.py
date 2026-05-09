"""
Plot classification evolution over time.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / 'output'

# Colors
COLORS = {
    # PCA
    'Strong Leader': '#10b981', 'Quiet Uptrend': '#4f8cf7', 'Erupting': '#f59e0b',
    'Distributing': '#ef4444', 'Declining': '#6b7280',
    # Stages
    'S2 Uptrend': '#10b981', 'S1 Basing': '#f59e0b', 'S3 Topping': '#ef4444',
    'S4 Declining': '#6b7280', 'Unclassified': '#333',
    # MA
    'Above Both': '#10b981', 'Above 200 Below 50': '#4f8cf7',
    'Below 200 Above 50': '#f59e0b', 'Below Both': '#ef4444',
}

def plot_stacked_area(csv_path, title, output_name, dim_col):
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])

    # Pivot: dates × categories
    pivot = df.pivot_table(index='date', columns=dim_col, values='count', aggfunc='sum').fillna(0)

    # Convert to percentages
    totals = pivot.sum(axis=1)
    pct = pivot.div(totals, axis=0) * 100

    fig = go.Figure()
    for col in pct.columns:
        fig.add_trace(go.Scatter(
            x=pct.index, y=pct[col], name=col,
            stackgroup='one', mode='lines',
            line=dict(width=0.5, color=COLORS.get(col, '#888')),
            fillcolor=COLORS.get(col, '#888'),
        ))

    fig.update_layout(
        title=title, template='plotly_dark', height=500,
        yaxis=dict(title='% of Universe', range=[0, 100]),
        xaxis=dict(title=''), legend=dict(orientation='h', y=-0.15),
        margin=dict(l=50, r=20, t=40, b=80),
    )
    fig.write_html(str(OUTPUT_DIR / f'{output_name}.html'))
    print(f"Saved: {output_name}.html")
    return fig


def plot_sector_heatmap(csv_path, dim_col, dim_value, title, output_name):
    """Heatmap: sector × date, showing % of sector stocks in a specific category."""
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])

    # Get total per sector per date
    totals = df.groupby(['date', 'sector'])['count'].sum().reset_index(name='total')

    # Filter to specific category
    cat = df[df[dim_col] == dim_value]
    merged = cat.merge(totals, on=['date', 'sector'], how='left')
    merged['pct'] = merged['count'] / merged['total'] * 100

    pivot = merged.pivot_table(index='sector', columns='date', values='pct').fillna(0)

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values, x=[str(d)[:10] for d in pivot.columns],
        y=pivot.index.tolist(), colorscale='RdYlGn', zmid=50,
        colorbar=dict(title='%'),
    ))
    fig.update_layout(
        title=title, template='plotly_dark', height=400,
        margin=dict(l=150, r=20, t=40, b=40),
    )
    fig.write_html(str(OUTPUT_DIR / f'{output_name}.html'))
    print(f"Saved: {output_name}.html")
    return fig


def plot_sector_lines(csv_path, dim_col, sector, title, output_name):
    """Line chart: categories over time for a specific sector."""
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    sec = df[df['sector'] == sector]
    if sec.empty:
        print(f"No data for sector {sector}")
        return

    totals = sec.groupby('date')['count'].sum()
    pivot = sec.pivot_table(index='date', columns=dim_col, values='count', aggfunc='sum').fillna(0)
    pct = pivot.div(totals, axis=0) * 100

    fig = go.Figure()
    for col in pct.columns:
        fig.add_trace(go.Scatter(
            x=pct.index, y=pct[col], name=col,
            mode='lines', line=dict(color=COLORS.get(col, '#888'), width=2),
        ))
    fig.update_layout(
        title=title, template='plotly_dark', height=400,
        yaxis=dict(title='% of Sector'), legend=dict(orientation='h', y=-0.15),
        margin=dict(l=50, r=20, t=40, b=80),
    )
    fig.write_html(str(OUTPUT_DIR / f'{output_name}.html'))
    print(f"Saved: {output_name}.html")


# =========================================================================
# Generate all plots
# =========================================================================
print("Generating plots...\n")

# 1. Overall stacked area charts
plot_stacked_area(OUTPUT_DIR / 'history_pca_regime_overall.csv',
                  'PCA Regime Distribution Over Time', 'pca_evolution', 'pca_regime')
plot_stacked_area(OUTPUT_DIR / 'history_stage_overall.csv',
                  'Weinstein Stage Distribution Over Time', 'stage_evolution', 'stage')
plot_stacked_area(OUTPUT_DIR / 'history_ma_position_overall.csv',
                  'MA Position Distribution Over Time', 'ma_evolution', 'ma_position')

# 2. Sector heatmaps for key categories
plot_sector_heatmap(OUTPUT_DIR / 'history_pca_regime.csv', 'pca_regime', 'Strong Leader',
                    '% Strong Leader by Sector Over Time', 'heatmap_strong_leader')
plot_sector_heatmap(OUTPUT_DIR / 'history_pca_regime.csv', 'pca_regime', 'Declining',
                    '% Declining by Sector Over Time', 'heatmap_declining')
plot_sector_heatmap(OUTPUT_DIR / 'history_ma_position.csv', 'ma_position', 'Above Both',
                    '% Above Both MAs by Sector Over Time', 'heatmap_above_both')

# 3. Per-sector PCA evolution for top sectors
for sector in ['Information Technology', 'Health Care', 'Financials', 'Energy']:
    plot_sector_lines(OUTPUT_DIR / 'history_pca_regime.csv', 'pca_regime', sector,
                      f'PCA Regime Evolution — {sector}', f'pca_{sector.replace(" ", "_").lower()}')

print("\nAll plots saved to:", OUTPUT_DIR)
