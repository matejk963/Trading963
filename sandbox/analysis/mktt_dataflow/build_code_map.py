"""
Build code-level architecture diagram of MKTT app.
Shows modules as clusters, functions inside, and call arrows between them.

Run: cd sandbox/analysis/mktt_dataflow && python build_code_map.py
"""
import graphviz
from pathlib import Path

OUT = Path("output")
OUT.mkdir(parents=True, exist_ok=True)

g = graphviz.Digraph('MKTT_Code_Map', format='svg',
    graph_attr={
        'rankdir': 'LR', 'bgcolor': '#0a0a0e', 'fontcolor': '#ccc',
        'fontname': 'JetBrains Mono', 'fontsize': '10', 'pad': '0.5',
        'nodesep': '0.3', 'ranksep': '1.2', 'splines': 'ortho',
    },
    node_attr={
        'shape': 'box', 'style': 'filled,rounded', 'fontname': 'JetBrains Mono',
        'fontsize': '9', 'margin': '0.15,0.08',
    },
    edge_attr={
        'color': '#444', 'arrowsize': '0.6', 'fontname': 'JetBrains Mono',
        'fontsize': '8', 'fontcolor': '#666',
    })

# =========================================================================
# Module clusters
# =========================================================================

# --- User / Browser ---
with g.subgraph(name='cluster_browser') as c:
    c.attr(label='Browser (Client)', style='dashed,rounded', color='#4f8cf7',
           fontcolor='#4f8cf7', fontsize='11')
    c.node('user_screener', 'Load Screener\n(filters, sort, as_of)', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_stock_click', 'Click Stock Row\n→ Panel opens', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_tab', 'Switch Tab\nChart|EPS|Sales|Fund|Rev|R12M', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_options', 'Load Options\n(SPX/SPY)', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_watchlist', 'Load Watchlist', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_macro', 'Load Liquidity/RRG', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('user_freshness', 'Click DATA', fillcolor='#1a2a4a', fontcolor='#4f8cf7')
    c.node('js_stock_panel', 'stock_panel.js\nfetch() → Plotly/LWC', fillcolor='#1a2a4a', fontcolor='#06b6d4')
    c.node('js_macro', 'macro.js\nfetch() → Plotly', fillcolor='#1a2a4a', fontcolor='#06b6d4')

# --- app.py (Flask routes) ---
with g.subgraph(name='cluster_app') as c:
    c.attr(label='app.py (Flask Routes)', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#10b981', fontsize='11')
    c.node('screener_page', 'screener_page()\nGET /', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('chart_api', 'chart_api()\n/api/chart/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('fundamentals_api', 'fundamentals_api()\n/api/fundamentals/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('rolling_12m_api', 'rolling_12m_api()\n/api/rolling_12m/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('eps_ttm_fwd', 'eps_ttm_forward_api()\n/api/eps_ttm_forward/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('sales_ttm_fwd', 'sales_ttm_forward_api()\n/api/sales_ttm_forward/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('revisions_api', 'revisions_api()\n/api/revisions/<sym>', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('sector_map_api', 'sector_map_api()\n/api/sector_map', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('watchlist_api', 'watchlist_api()\n/api/watchlist', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('freshness_api', 'freshness_api()\n/api/freshness', fillcolor='#1a2a2a', fontcolor='#10b981')
    c.node('load_rfv', 'load_refinitiv_snapshot()\ncached pkl loader', fillcolor='#1a2a2a', fontcolor='#f59e0b')
    c.node('load_class', 'load_classification_lookups()\ncached JSON loader', fillcolor='#1a2a2a', fontcolor='#f59e0b')

# --- options_service.py ---
with g.subgraph(name='cluster_options') as c:
    c.attr(label='options_service.py', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#ef4444', fontsize='11')
    c.node('opt_page', 'options_page()\nGET /options', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('opt_exp', 'get_expirations()', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('opt_chain', 'process_chain()\n+ BSM Greeks', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('opt_surface', 'compute_iv_surface()', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('opt_summary', 'compute_summary()\nP/C, max pain', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('opt_gex', 'compute_gex()\nγ×OI×100×S²', fillcolor='#2a1a1a', fontcolor='#ef4444')
    c.node('bs_greeks', 'bs_gamma() bs_delta()\nbs_theta() bs_vega()', fillcolor='#2a1a1a', fontcolor='#ec4899')

# --- data_manager.py ---
with g.subgraph(name='cluster_dm') as c:
    c.attr(label='data_manager.py', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#f59e0b', fontsize='11')
    c.node('load_prices', 'load_prices(field)\nparquet → cached DataFrame', fillcolor='#2a2a1a', fontcolor='#f59e0b')
    c.node('load_universe', 'load_universe()', fillcolor='#2a2a1a', fontcolor='#f59e0b')
    c.node('load_spy', 'load_spy()', fillcolor='#2a2a1a', fontcolor='#f59e0b')
    c.node('update_prices', 'update_prices()\nyf.download() incremental', fillcolor='#2a2a1a', fontcolor='#f59e0b')

# --- stage_classifier.py ---
with g.subgraph(name='cluster_stage') as c:
    c.attr(label='stage_classifier.py', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#a78bfa', fontsize='11')
    c.node('compute_derived', 'compute_all_derived_vectorized()\nMAs, RS, dist days', fillcolor='#2a1a2a', fontcolor='#a78bfa')
    c.node('classify_stages', 'classify_all_stages()\nS1/S2/S3/S4 boolean masks', fillcolor='#2a1a2a', fontcolor='#a78bfa')
    c.node('run_stage', 'run_stage_from_local_db()\ncached 5min', fillcolor='#2a1a2a', fontcolor='#a78bfa')

# --- macro/ ---
with g.subgraph(name='cluster_macro') as c:
    c.attr(label='macro/ (Blueprint)', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#06b6d4', fontsize='11')
    c.node('liq_service', 'liquidity_service.py\nbuild_dashboard_response()', fillcolor='#1a2a2a', fontcolor='#06b6d4')
    c.node('rrg_service', 'rrg_service.py\nbuild_rrg_response()', fillcolor='#1a2a2a', fontcolor='#06b6d4')
    c.node('macro_routes', 'routes.py\n/macro/api/*', fillcolor='#1a2a2a', fontcolor='#06b6d4')

# --- data_freshness.py ---
with g.subgraph(name='cluster_fresh') as c:
    c.attr(label='data_freshness.py', style='filled,rounded', color='#333',
           fillcolor='#111', fontcolor='#888', fontsize='11')
    c.node('full_report', 'full_report()\ncheck all sources', fillcolor='#1a1a1a', fontcolor='#888')

# --- Data Storage ---
with g.subgraph(name='cluster_data') as c:
    c.attr(label='Data Storage', style='dashed,rounded', color='#f59e0b',
           fontcolor='#f59e0b', fontsize='11')
    c.node('parquets', 'data/mktt/\nclose|high|low|volume|spy\n.parquet', fillcolor='#2a2a1a', fontcolor='#f59e0b', shape='cylinder')
    c.node('rfv_pkl', 'refinitiv_fundamentals.pkl\n19 DataFrames: snapshot,\nquarterly, forward, trends', fillcolor='#2a2a1a', fontcolor='#f59e0b', shape='cylinder')
    c.node('class_json', 'classification JSONs\npca20, stages, screener,\neps_growth', fillcolor='#2a2a1a', fontcolor='#f59e0b', shape='cylinder')
    c.node('yf_api', 'yfinance API\n(live, 5min cache)', fillcolor='#2a1a1a', fontcolor='#ef4444', shape='cylinder')

# =========================================================================
# Edges: User → Routes
# =========================================================================
g.edge('user_screener', 'screener_page', color='#4f8cf7')
g.edge('user_stock_click', 'js_stock_panel', color='#4f8cf7')
g.edge('user_tab', 'js_stock_panel', color='#4f8cf7')
g.edge('user_options', 'opt_page', color='#4f8cf7')
g.edge('user_watchlist', 'watchlist_api', color='#4f8cf7')
g.edge('user_macro', 'macro_routes', color='#4f8cf7')
g.edge('user_freshness', 'freshness_api', color='#4f8cf7')

# JS → API routes
g.edge('js_stock_panel', 'chart_api', label='fetch', color='#06b6d4')
g.edge('js_stock_panel', 'fundamentals_api', label='fetch', color='#06b6d4')
g.edge('js_stock_panel', 'rolling_12m_api', label='fetch', color='#06b6d4')
g.edge('js_stock_panel', 'eps_ttm_fwd', label='fetch', color='#06b6d4')
g.edge('js_stock_panel', 'sales_ttm_fwd', label='fetch', color='#06b6d4')
g.edge('js_stock_panel', 'revisions_api', label='fetch', color='#06b6d4')
g.edge('js_macro', 'macro_routes', label='fetch', color='#06b6d4')

# Options routes
g.edge('opt_page', 'opt_exp', color='#ef4444')
g.edge('opt_page', 'opt_chain', color='#ef4444')
g.edge('opt_page', 'opt_surface', color='#ef4444')
g.edge('opt_page', 'opt_summary', color='#ef4444')
g.edge('opt_page', 'opt_gex', color='#ef4444')
g.edge('opt_chain', 'bs_greeks', color='#ec4899')
g.edge('opt_gex', 'bs_greeks', color='#ec4899')

# =========================================================================
# Edges: Routes → Services
# =========================================================================
g.edge('screener_page', 'load_prices', color='#f59e0b')
g.edge('screener_page', 'load_universe', color='#f59e0b')
g.edge('screener_page', 'load_rfv', color='#f59e0b')
g.edge('screener_page', 'load_class', color='#f59e0b')
g.edge('screener_page', 'run_stage', style='dashed', label='if preset≠all', color='#a78bfa')

g.edge('chart_api', 'load_prices', color='#f59e0b')
g.edge('fundamentals_api', 'rfv_pkl', color='#f59e0b')
g.edge('rolling_12m_api', 'rfv_pkl', color='#f59e0b')
g.edge('eps_ttm_fwd', 'rfv_pkl', color='#f59e0b')
g.edge('sales_ttm_fwd', 'rfv_pkl', color='#f59e0b')
g.edge('revisions_api', 'rfv_pkl', color='#f59e0b')
g.edge('watchlist_api', 'load_prices', color='#f59e0b')
g.edge('watchlist_api', 'load_rfv', color='#f59e0b')
g.edge('sector_map_api', 'load_prices', color='#f59e0b')
g.edge('sector_map_api', 'load_rfv', color='#f59e0b')
g.edge('sector_map_api', 'load_class', color='#f59e0b')
g.edge('screener_page', 'sector_map_api', style='dashed', color='#333')

g.edge('freshness_api', 'full_report', color='#888')

# Stage classifier chain
g.edge('run_stage', 'compute_derived', color='#a78bfa')
g.edge('compute_derived', 'classify_stages', color='#a78bfa')
g.edge('run_stage', 'load_prices', color='#f59e0b')
g.edge('run_stage', 'load_spy', color='#f59e0b')

# Macro
g.edge('macro_routes', 'liq_service', color='#06b6d4')
g.edge('macro_routes', 'rrg_service', color='#06b6d4')

# =========================================================================
# Edges: Services → Data
# =========================================================================
g.edge('load_prices', 'parquets', color='#f59e0b')
g.edge('load_universe', 'parquets', color='#f59e0b')
g.edge('load_spy', 'parquets', color='#f59e0b')
g.edge('load_rfv', 'rfv_pkl', color='#f59e0b')
g.edge('load_class', 'class_json', color='#f59e0b')
g.edge('update_prices', 'yf_api', color='#f59e0b')
g.edge('update_prices', 'parquets', color='#f59e0b', style='dashed', label='write')
g.edge('opt_exp', 'yf_api', color='#ef4444')
g.edge('opt_chain', 'yf_api', color='#ef4444')
g.edge('opt_surface', 'yf_api', color='#ef4444')
g.edge('opt_gex', 'yf_api', color='#ef4444')
g.edge('full_report', 'parquets', color='#888')
g.edge('full_report', 'rfv_pkl', color='#888')
g.edge('full_report', 'class_json', color='#888')

# Render
g.render(str(OUT / 'mktt_code_map'), cleanup=True)
print(f"Saved: {OUT / 'mktt_code_map.svg'}")

# Also PNG
g2 = g.copy()
g2.format = 'png'
g2.render(str(OUT / 'mktt_code_map'), cleanup=True)
print(f"Saved: {OUT / 'mktt_code_map.png'}")
