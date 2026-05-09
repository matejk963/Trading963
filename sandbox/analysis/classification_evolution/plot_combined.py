"""
Combined classification evolution dashboard — single HTML with all plots.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / 'output'

COLORS = {
    'Strong Leader': '#10b981', 'Quiet Uptrend': '#4f8cf7', 'Erupting': '#f59e0b',
    'Distributing': '#ef4444', 'Declining': '#6b7280',
    'S2 Uptrend': '#10b981', 'S1 Basing': '#f59e0b', 'S3 Topping': '#ef4444',
    'S4 Declining': '#6b7280', 'Unclassified': '#333',
    'Above Both': '#10b981', 'Above 200 Below 50': '#4f8cf7',
    'Below 200 Above 50': '#f59e0b', 'Below Both': '#ef4444',
}

LAYOUT = dict(template='plotly_dark', margin=dict(l=50, r=20, t=35, b=30),
              legend=dict(orientation='h', y=-0.12, font=dict(size=10)),
              font=dict(family='JetBrains Mono, monospace', size=11))


def make_area_and_line(csv_path, dim_col, title):
    """Returns two figures: stacked area (%) and line chart (%)."""
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    pivot = df.pivot_table(index='date', columns=dim_col, values='count', aggfunc='sum').fillna(0)
    totals = pivot.sum(axis=1)
    pct = pivot.div(totals, axis=0) * 100

    # Stacked area (exclude Unclassified)
    fig_area = go.Figure()
    for col in pct.columns:
        if col == 'Unclassified':
            continue
        fig_area.add_trace(go.Scatter(
            x=pct.index, y=pct[col], name=col, stackgroup='one', mode='lines',
            line=dict(width=0.5, color=COLORS.get(col, '#888')),
        ))
    fig_area.update_layout(**LAYOUT, height=300, title=dict(text=title + ' — Stacked Area (excl. Unclassified)', font=dict(size=13)),
                           yaxis=dict(title='%'))

    # Line chart
    fig_line = go.Figure()
    for col in pct.columns:
        visible = True if col != 'Unclassified' else 'legendonly'
        fig_line.add_trace(go.Scatter(
            x=pct.index, y=pct[col], name=col, mode='lines',
            line=dict(color=COLORS.get(col, '#888'), width=2),
            visible=visible,
        ))
    fig_line.update_layout(**LAYOUT, height=300, title=dict(text=title + ' — Lines', font=dict(size=13)),
                           yaxis=dict(title='%'))

    # Percentile rank
    pctile = pct.copy()
    for col in pctile.columns:
        pctile[col] = pctile[col].rank(pct=True) * 100

    fig_rank = go.Figure()
    for col in pctile.columns:
        visible = True if col != 'Unclassified' else 'legendonly'
        fig_rank.add_trace(go.Scatter(
            x=pctile.index, y=pctile[col], name=col, mode='lines',
            line=dict(color=COLORS.get(col, '#888'), width=2),
            visible=visible,
        ))
    fig_rank.update_layout(**LAYOUT, height=300, title=dict(text=title + ' — Percentile Rank', font=dict(size=13)),
                           yaxis=dict(title='Percentile', range=[0, 100]))

    return fig_area, fig_line, fig_rank


def make_sector_lines(csv_path, dim_col, sector, title):
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    sec = df[df['sector'] == sector]
    if sec.empty:
        return None, None
    totals = sec.groupby('date')['count'].sum()
    pivot = sec.pivot_table(index='date', columns=dim_col, values='count', aggfunc='sum').fillna(0)
    pct = pivot.div(totals, axis=0) * 100

    # Percentile rank: for each stage, rank current value against its own history
    pctile = pct.copy()
    for col in pctile.columns:
        pctile[col] = pctile[col].rank(pct=True) * 100

    # Figure 1: % of sector
    fig_pct = go.Figure()
    for col in pct.columns:
        visible = True if col != 'Unclassified' else 'legendonly'
        fig_pct.add_trace(go.Scatter(
            x=pct.index, y=pct[col], name=col, mode='lines',
            line=dict(color=COLORS.get(col, '#888'), width=2),
            visible=visible,
        ))
    fig_pct.update_layout(**LAYOUT, height=250, title=dict(text=title + ' — % of Sector', font=dict(size=12)),
                          yaxis=dict(title='%'),
                          xaxis=dict(range=[str(pct.index.min())[:10], str(pct.index.max())[:10]]))

    # Figure 2: percentile rank
    fig_rank = go.Figure()
    for col in pctile.columns:
        visible = True if col != 'Unclassified' else 'legendonly'
        fig_rank.add_trace(go.Scatter(
            x=pctile.index, y=pctile[col], name=col, mode='lines',
            line=dict(color=COLORS.get(col, '#888'), width=2),
            visible=visible,
        ))
    fig_rank.update_layout(**LAYOUT, height=250, title=dict(text=title + ' — Percentile Rank', font=dict(size=12)),
                           yaxis=dict(title='Percentile', range=[0, 100]),
                           xaxis=dict(range=[str(pctile.index.min())[:10], str(pctile.index.max())[:10]]))

    return fig_pct, fig_rank


def make_heatmap(csv_path, dim_col, dim_value, title):
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    totals = df.groupby(['date', 'sector'])['count'].sum().reset_index(name='total')
    cat = df[df[dim_col] == dim_value]
    merged = cat.merge(totals, on=['date', 'sector'], how='left')
    merged['pct'] = merged['count'] / merged['total'] * 100
    pivot = merged.pivot_table(index='sector', columns='date', values='pct').fillna(0)

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values, x=[str(d)[:10] for d in pivot.columns],
        y=pivot.index.tolist(), colorscale='RdYlGn', zmid=50,
        colorbar=dict(title='%', len=0.8),
    ))
    hm_layout = {k: v for k, v in LAYOUT.items() if k != 'margin'}
    fig.update_layout(**hm_layout, height=300, title=dict(text=title, font=dict(size=12)),
                      margin=dict(l=150, r=20, t=35, b=30))
    return fig


# =========================================================================
# Build combined HTML
# =========================================================================
print("Generating combined dashboard...")

figures = []

# Overall evolution
for csv, dim, title in [
    ('history_pca_regime_overall.csv', 'pca_regime', 'PCA Regime'),
    ('history_stage_overall.csv', 'stage', 'Weinstein Stage'),
    ('history_ma_position_overall.csv', 'ma_position', 'MA Position'),
]:
    area, line, rank = make_area_and_line(OUTPUT_DIR / csv, dim, title)
    figures.append(('area', area))
    figures.append(('line', line))
    figures.append(('rank', rank))

# Heatmaps
for dim_val, title in [
    ('Strong Leader', '% Strong Leader by Sector'),
    ('Declining', '% Declining by Sector'),
]:
    figures.append(('heatmap', make_heatmap(OUTPUT_DIR / 'history_pca_regime.csv', 'pca_regime', dim_val, title)))

figures.append(('heatmap', make_heatmap(OUTPUT_DIR / 'history_ma_position.csv', 'ma_position', 'Above Both', '% Above Both MAs by Sector')))

# Per-sector Weinstein Stages (both % and percentile)
sector_pairs = []
for sector in ['Information Technology', 'Health Care', 'Financials', 'Energy',
               'Consumer Discretionary', 'Industrials', 'Communication Services',
               'Consumer Staples', 'Materials', 'Real Estate', 'Utilities']:
    fig_pct, fig_rank = make_sector_lines(OUTPUT_DIR / 'history_stage.csv', 'stage', sector, f'Stages — {sector}')
    if fig_pct:
        sector_pairs.append((sector, fig_pct, fig_rank))

# Write combined HTML
html_parts = ["""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><title>Classification Evolution</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
body { background: #0a0a0e; color: #ccc; font-family: 'JetBrains Mono', monospace; margin: 0; padding: 20px; }
h1 { color: #4f8cf7; font-size: 18px; margin-bottom: 4px; }
h2 { color: #888; font-size: 14px; margin: 20px 0 4px; border-bottom: 1px solid #222; padding-bottom: 4px; }
.row { display: flex; gap: 8px; margin-bottom: 8px; }
.row > div { flex: 1; min-width: 0; }
.full { margin-bottom: 8px; }
</style></head><body>
<h1>Classification Evolution — Full History</h1>
"""]

# Group: area + line + rank for each dimension, with toggle
dims = ['PCA Regime', 'Weinstein Stage', 'MA Position']
for i, dim_name in enumerate(dims):
    area_fig = figures[i * 3][1]
    line_fig = figures[i * 3 + 1][1]
    rank_fig = figures[i * 3 + 2][1]
    html_parts.append(f'''<h2>{dim_name}
    <span style="margin-left:12px;display:inline-flex;gap:0;">
    <button onclick="setOverallMode({i},'pct')" id="ov_pct_{i}" style="font-size:10px;padding:2px 8px;background:#4f8cf7;border:1px solid #333;color:white;border-radius:4px 0 0 4px;cursor:pointer;">% Lines</button>
    <button onclick="setOverallMode({i},'rank')" id="ov_rank_{i}" style="font-size:10px;padding:2px 8px;background:#1a1a2a;border:1px solid #333;color:#888;border-radius:0 4px 4px 0;cursor:pointer;">Percentile</button>
    </span></h2>''')
    html_parts.append(f'<div class="row"><div id="fig_a{i}"></div><div id="fig_l{i}"></div></div>')
    html_parts.append(f'<div id="fig_r{i}" style="display:none;"></div>')
    html_parts.append(f'<script>Plotly.newPlot("fig_a{i}",{area_fig.to_json()});</script>')
    html_parts.append(f'<script>Plotly.newPlot("fig_l{i}",{line_fig.to_json()});</script>')
    html_parts.append(f'<script>Plotly.newPlot("fig_r{i}",{rank_fig.to_json()});</script>')

html_parts.append(f'''<script>
function setOverallMode(idx, mode) {{
    var row = document.getElementById('fig_a' + idx).parentElement;
    var rank = document.getElementById('fig_r' + idx);
    row.style.display = mode === 'pct' ? 'flex' : 'none';
    rank.style.display = mode === 'rank' ? 'block' : 'none';
    if (mode === 'rank') Plotly.Plots.resize(rank);
    document.getElementById('ov_pct_' + idx).style.background = mode === 'pct' ? '#4f8cf7' : '#1a1a2a';
    document.getElementById('ov_pct_' + idx).style.color = mode === 'pct' ? 'white' : '#888';
    document.getElementById('ov_rank_' + idx).style.background = mode === 'rank' ? '#4f8cf7' : '#1a1a2a';
    document.getElementById('ov_rank_' + idx).style.color = mode === 'rank' ? 'white' : '#888';
}}
</script>''')

# Heatmaps
html_parts.append('<h2>Sector Heatmaps</h2>')
heatmaps = [f for f in figures if f[0] == 'heatmap']
for j, (_, fig) in enumerate(heatmaps):
    html_parts.append(f'<div class="full" id="hm{j}"></div>')
    html_parts.append(f'<script>Plotly.newPlot("hm{j}",{fig.to_json()});</script>')

# Per-sector
html_parts.append('''<h2>Weinstein Stages by Sector
<span style="margin-left:16px;display:inline-flex;gap:0;">
<button id="mode-pct-btn" onclick="setSectorMode('pct')" style="font-size:11px;padding:3px 10px;background:#4f8cf7;border:1px solid #333;color:white;border-radius:4px 0 0 4px;cursor:pointer;">% of Sector</button>
<button id="mode-rank-btn" onclick="setSectorMode('rank')" style="font-size:11px;padding:3px 10px;background:#1a1a2a;border:1px solid #333;color:#888;border-radius:0 4px 4px 0;cursor:pointer;">Percentile Rank</button>
</span></h2>''')

for k, (sector, fig_pct, fig_rank) in enumerate(sector_pairs):
    html_parts.append(f'<div id="sec_pct_{k}" style="margin-bottom:4px;"></div>')
    html_parts.append(f'<div id="sec_rank_{k}" style="margin-bottom:4px;display:none;"></div>')
    html_parts.append(f'<script>Plotly.newPlot("sec_pct_{k}",{fig_pct.to_json()},{{responsive:true}});</script>')
    html_parts.append(f'<script>Plotly.newPlot("sec_rank_{k}",{fig_rank.to_json()},{{responsive:true}});</script>')

html_parts.append(f'''<script>
function setSectorMode(mode) {{
    var n = {len(sector_pairs)};
    for (var i = 0; i < n; i++) {{
        document.getElementById('sec_pct_' + i).style.display = mode === 'pct' ? 'block' : 'none';
        document.getElementById('sec_rank_' + i).style.display = mode === 'rank' ? 'block' : 'none';
        if (mode === 'rank') Plotly.Plots.resize(document.getElementById('sec_rank_' + i));
    }}
    document.getElementById('mode-pct-btn').style.background = mode === 'pct' ? '#4f8cf7' : '#1a1a2a';
    document.getElementById('mode-pct-btn').style.color = mode === 'pct' ? 'white' : '#888';
    document.getElementById('mode-rank-btn').style.background = mode === 'rank' ? '#4f8cf7' : '#1a1a2a';
    document.getElementById('mode-rank-btn').style.color = mode === 'rank' ? 'white' : '#888';
}}
</script>''')

html_parts.append('</body></html>')

out_path = OUTPUT_DIR / 'classification_evolution.html'
with open(out_path, 'w') as f:
    f.write('\n'.join(html_parts))

print(f"Saved: {out_path}")
print(f"Size: {out_path.stat().st_size / 1e6:.1f} MB")
