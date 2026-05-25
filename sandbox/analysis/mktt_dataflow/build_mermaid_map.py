"""
Build Mermaid.js interactive code map of MKTT app.
Auto-parses source code and generates an HTML page with multiple
Mermaid diagrams: module overview, per-module detail, request flows.

Run: cd sandbox/analysis/mktt_dataflow && python build_mermaid_map.py
"""
import ast
import os
import json
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent.parent.parent / 'src' / 'mktt'
OUT = Path(__file__).parent / 'output'
OUT.mkdir(parents=True, exist_ok=True)


def parse_module(filepath):
    try:
        tree = ast.parse(open(filepath, encoding='utf-8').read())
    except:
        return None

    module = {'imports': [], 'functions': [], 'routes': []}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                module['imports'].append({'module': node.module, 'name': alias.name})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            route = None
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and hasattr(dec.func, 'attr') and dec.func.attr == 'route':
                    if dec.args:
                        try:
                            route = ast.literal_eval(dec.args[0])
                        except:
                            pass

            calls = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)

            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node) or ''
            lines = (node.end_lineno or node.lineno) - node.lineno + 1

            module['functions'].append({
                'name': node.name,
                'args': args,
                'route': route,
                'calls': sorted(calls),
                'doc': doc[:120],
                'lines': lines,
                'line': node.lineno,
            })
            if route:
                module['routes'].append({'name': node.name, 'route': route})

    return module


# Parse all modules
modules = {}
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile):
        continue
    rel = pyfile.relative_to(SRC_DIR)
    mod_name = str(rel).replace('.py', '').replace(os.sep, '/')
    parsed = parse_module(pyfile)
    if parsed and (parsed['functions'] or parsed['imports']):
        modules[mod_name] = parsed

print(f"Parsed {len(modules)} modules")

# Build a set of all local function names per module
all_funcs = {}
for mod, data in modules.items():
    for f in data['functions']:
        all_funcs[f['name']] = mod


# =========================================================================
# Generate Mermaid diagrams
# =========================================================================

def esc(s):
    """Escape for Mermaid labels."""
    return s.replace('"', "'").replace('<', '&lt;').replace('>', '&gt;').replace('/', '∕')


# 1. Module-level overview
mod_overview = ['graph LR']
mod_colors = {
    'app': '#10b981', 'data_manager': '#f59e0b', 'stage_classifier': '#a78bfa',
    'options_service': '#ef4444', 'screener': '#ec4899', 'data_freshness': '#888',
    'macro/routes': '#06b6d4', 'macro/liquidity_service': '#06b6d4',
    'macro/rrg_service': '#06b6d4', 'macro/cache': '#06b6d4',
    'update_classifications': '#84cc16',
}

for mod, data in modules.items():
    nf = len(data['functions'])
    nr = len(data['routes'])
    label = f"{mod}\\n{nf} funcs"
    if nr:
        label += f" | {nr} routes"
    safe_id = mod.replace('/', '_').replace('.', '_')
    mod_overview.append(f'    {safe_id}["{label}"]')

# Import edges
seen_edges = set()
for mod, data in modules.items():
    src = mod.replace('/', '_').replace('.', '_')
    for imp in data['imports']:
        imp_base = imp['module'].split('.')[0]
        for other_mod in modules:
            other_base = other_mod.replace('/', '_').replace('.', '_')
            if other_mod.split('/')[0] == imp_base or other_mod == imp_base:
                edge = (src, other_base)
                if edge not in seen_edges and src != other_base:
                    mod_overview.append(f'    {src} --> {other_base}')
                    seen_edges.add(edge)
                break

# Style
for mod in modules:
    safe_id = mod.replace('/', '_').replace('.', '_')
    color = mod_colors.get(mod, '#4f8cf7')
    mod_overview.append(f'    style {safe_id} fill:{color}22,stroke:{color},color:{color}')

mod_overview_text = '\n'.join(mod_overview)


# 2. Per-module function diagrams
mod_details = {}
for mod, data in modules.items():
    if not data['functions']:
        continue
    lines = ['graph TD']
    safe_mod = mod.replace('/', '_').replace('.', '_')

    for f in data['functions']:
        fid = f'{safe_mod}__{f["name"]}'
        label = f['name']
        if f['route']:
            label = f'{f["route"]}\\n{f["name"]}()'
            lines.append(f'    {fid}["{esc(label)}"]:::route')
        else:
            label = f'{f["name"]}()\\n{f["lines"]}L'
            lines.append(f'    {fid}["{esc(label)}"]')

    # Internal calls (within same module)
    for f in data['functions']:
        fid = f'{safe_mod}__{f["name"]}'
        for call in f['calls']:
            # Check if call is in same module
            for other_f in data['functions']:
                if other_f['name'] == call and call != f['name']:
                    tid = f'{safe_mod}__{call}'
                    lines.append(f'    {fid} --> {tid}')
                    break

    # Cross-module calls
    for f in data['functions']:
        fid = f'{safe_mod}__{f["name"]}'
        for call in f['calls']:
            if call in all_funcs and all_funcs[call] != mod:
                target_mod = all_funcs[call].replace('/', '_').replace('.', '_')
                tid = f'{target_mod}__{call}'
                lines.append(f'    {fid} -.-> {tid}["({all_funcs[call]})\\n{call}()"]:::external')

    lines.append('    classDef route fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b')
    lines.append('    classDef external fill:#33333322,stroke:#666,color:#888')
    mod_details[mod] = '\n'.join(lines)


# 3. Request flow diagrams
request_flows = {}

# Screener flow
request_flows['Screener Page Load'] = """graph LR
    User(["🖱 User loads /screener"]) --> Route["screener_page()"]
    Route --> LP["load_prices('close')"]
    Route --> LU["load_universe()"]
    Route --> LR["load_refinitiv_snapshot()"]
    Route --> LC["load_classification_lookups()"]
    Route -->|"if preset≠all"| RS["run_stage_from_local_db()"]
    LP --> PQ[("close.parquet")]
    LU --> UQ[("universe.parquet")]
    LR --> RFV[("refinitiv_fundamentals.pkl")]
    LC --> CJ[("classification JSONs")]
    RS --> CD["compute_all_derived_vectorized()"]
    CD --> CS["classify_all_stages()"]
    Route --> HTML["Render screener.html\\nwith sector/industry tables"]
    style User fill:#4f8cf722,stroke:#4f8cf7,color:#4f8cf7
    style PQ fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style UQ fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style RFV fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style CJ fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style HTML fill:#10b98122,stroke:#10b981,color:#10b981"""

request_flows['Stock Panel (EPS Tab)'] = """graph LR
    Click(["🖱 Click stock → EPS tab"]) --> JS["stock_panel.js"]
    JS -->|"fetch()"| R12["∕api∕rolling_12m∕SYM"]
    JS -->|"fetch()"| TTM["∕api∕eps_ttm_forward∕SYM"]
    R12 --> PKL[("refinitiv_fundamentals.pkl")]
    TTM --> PKL
    R12 --> A["quarterly actuals\\n→ rolling 4Q sum"]
    R12 --> B["forward_quarterly\\n→ next 8Q estimates"]
    TTM --> C["trend_eps_fq1-4\\n→ revision curves"]
    A --> PLT["Plotly: TTM line + cone + revisions"]
    B --> PLT
    C --> PLT
    style Click fill:#4f8cf722,stroke:#4f8cf7,color:#4f8cf7
    style PKL fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style PLT fill:#10b98122,stroke:#10b981,color:#10b981"""

request_flows['Options (GEX)'] = """graph LR
    User(["🖱 Load ∕options → GEX tab"]) --> JS["options.html JS"]
    JS -->|"fetch()"| API["∕api∕options∕gex∕^SPX"]
    API --> GEX["compute_gex()"]
    GEX --> YF[("yfinance API\\n5min cache")]
    GEX --> BSM["bs_gamma()\\nγ = N'(d1) ∕ (S·σ·√T)"]
    BSM --> CALC["GEX = γ × OI × 100 × S²"]
    CALC --> FLIP["Find flip point\\n(net GEX crosses 0)"]
    CALC --> BAR["Plotly: GEX bar chart\\n+ flip line + key levels"]
    FLIP --> BAR
    style User fill:#4f8cf722,stroke:#4f8cf7,color:#4f8cf7
    style YF fill:#ef444422,stroke:#ef4444,color:#ef4444
    style BAR fill:#10b98122,stroke:#10b981,color:#10b981"""

request_flows['Classification Update'] = """graph TD
    Trigger(["⏰ Run update_classifications.py"]) --> Load["load_prices() + load_spy()"]
    Load --> PQ[("OHLCV parquets")]
    Load --> Feat["compute_features()\\n20 scale-invariant features"]
    Feat --> PCA["PCA + KMeans\\n→ 5 regimes"]
    Load --> Stage["classify_all_stages()\\n→ S1/S2/S3/S4"]
    Load --> MA["MA screener\\n→ Above Both / Below Both"]
    Load --> EPS["EPS acceleration\\n→ Accelerating / Decelerating"]
    PCA --> JSON[("pca20_5c_meta.json")]
    Stage --> JSON2[("stages_meta.json")]
    MA --> JSON3[("screener_meta.json")]
    EPS --> JSON4[("eps_growth_meta.json")]
    style Trigger fill:#84cc1622,stroke:#84cc16,color:#84cc16
    style PQ fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style JSON fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style JSON2 fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style JSON3 fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b
    style JSON4 fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b"""


# =========================================================================
# Build HTML
# =========================================================================
html = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>MKTT Code Map — Mermaid</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
body { background: #0f1117; color: #ccc; font-family: 'JetBrains Mono', 'Consolas', monospace; margin: 0; padding: 0; }
nav { background: #111; border-bottom: 1px solid #333; padding: 8px 16px; display: flex; gap: 0; position: sticky; top: 0; z-index: 100; }
nav button { font-size: 12px; padding: 6px 16px; background: #1a1a2a; border: 1px solid #333; color: #888;
    cursor: pointer; border-bottom: 2px solid transparent; }
nav button:first-child { border-radius: 4px 0 0 4px; }
nav button:last-child { border-radius: 0 4px 4px 0; }
nav button.active { background: #4f8cf7; color: white; border-color: #4f8cf7; }
.section { display: none; padding: 20px; }
.section.active { display: block; }
.section h2 { color: #4f8cf7; font-size: 16px; margin-bottom: 12px; }
.section h3 { color: #10b981; font-size: 13px; margin: 16px 0 8px; }
.diagram-wrap { background: #0a0a0e; border: 1px solid #222; border-radius: 8px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.mod-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.mod-btn { font-size: 11px; padding: 4px 10px; background: #1a1a2a; border: 1px solid #333; color: #ccc;
    border-radius: 4px; cursor: pointer; }
.mod-btn:hover { background: #2a2a3a; }
.mod-btn.active { background: #10b981; color: white; border-color: #10b981; }
.mod-detail { display: none; }
.mod-detail.active { display: block; }
</style>
</head><body>

<nav>
    <button class="active" onclick="switchSection('overview')">Module Overview</button>
    <button onclick="switchSection('details')">Module Details</button>
    <button onclick="switchSection('flows')">Request Flows</button>
</nav>

<div id="sec-overview" class="section active">
    <h2>Module Overview</h2>
    <p style="color:#666;font-size:11px;margin-bottom:12px;">How modules import each other. Arrows = import dependencies.</p>
    <div class="diagram-wrap">
        <pre class="mermaid">
""" + mod_overview_text + """
        </pre>
    </div>
</div>

<div id="sec-details" class="section">
    <h2>Module Details</h2>
    <p style="color:#666;font-size:11px;margin-bottom:12px;">Click a module to see its functions and internal/external calls.</p>
    <div class="mod-grid">
"""

for mod in modules:
    safe = mod.replace('/', '_')
    color = mod_colors.get(mod, '#4f8cf7')
    nf = len(modules[mod]['functions'])
    html += f'        <button class="mod-btn" onclick="showMod(\'{safe}\')" style="border-left:3px solid {color};">{mod} ({nf})</button>\n'

html += '    </div>\n'

for mod, diagram in mod_details.items():
    safe = mod.replace('/', '_')
    html += f'    <div id="mod-{safe}" class="mod-detail">\n'
    html += f'        <h3>{mod}</h3>\n'

    # Function list
    html += '        <div style="margin-bottom:8px;font-size:11px;">\n'
    for f in modules[mod]['functions']:
        route_badge = f' <span style="color:#f59e0b;font-weight:700;">{f["route"]}</span>' if f['route'] else ''
        html += f'        <div style="padding:2px 0;border-bottom:1px solid #1a1a2a;">'
        html += f'<span style="color:#10b981;">{f["name"]}</span>'
        html += f'<span style="color:#666;">({", ".join(f["args"][:4])}{"..." if len(f["args"])>4 else ""})</span>'
        html += f'{route_badge}'
        html += f' <span style="color:#444;">L{f["line"]} ({f["lines"]}L)</span>'
        if f['doc']:
            html += f'<br><span style="color:#555;font-size:10px;font-style:italic;">{esc(f["doc"][:100])}</span>'
        html += '</div>\n'
    html += '        </div>\n'

    html += f'        <div class="diagram-wrap"><pre class="mermaid">\n{diagram}\n        </pre></div>\n'
    html += '    </div>\n'

html += '</div>\n'

html += '<div id="sec-flows" class="section">\n'
html += '    <h2>Request Flows</h2>\n'
html += '    <p style="color:#666;font-size:11px;margin-bottom:12px;">What happens when a user performs an action — from click to data to response.</p>\n'

for name, diagram in request_flows.items():
    html += f'    <h3>{name}</h3>\n'
    html += f'    <div class="diagram-wrap"><pre class="mermaid">\n{diagram}\n    </pre></div>\n'

html += '</div>\n'

html += """
<script>
mermaid.initialize({
    startOnLoad: true,
    theme: 'dark',
    themeVariables: {
        darkMode: true,
        background: '#0a0a0e',
        primaryColor: '#4f8cf7',
        primaryTextColor: '#ccc',
        lineColor: '#444',
        secondaryColor: '#1a1a2a',
        tertiaryColor: '#111',
    },
    flowchart: { curve: 'basis', padding: 12 },
    securityLevel: 'loose',
});

function switchSection(id) {
    document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); });
    document.getElementById('sec-' + id).classList.add('active');
    document.querySelectorAll('nav button').forEach(function(b, i) {
        b.classList.toggle('active', ['overview','details','flows'][i] === id);
    });
    // Re-render mermaid for newly visible sections
    setTimeout(function() { mermaid.run(); }, 100);
}

function showMod(id) {
    document.querySelectorAll('.mod-detail').forEach(function(d) { d.classList.remove('active'); });
    document.querySelectorAll('.mod-btn').forEach(function(b) { b.classList.remove('active'); });
    var el = document.getElementById('mod-' + id);
    if (el) {
        el.classList.add('active');
        event.target.classList.add('active');
        setTimeout(function() { mermaid.run(); }, 100);
    }
}
</script>
</body></html>"""

out_path = OUT / 'mktt_mermaid_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Saved: {out_path}")
print(f"Size: {out_path.stat().st_size / 1e3:.0f} KB")
