"""
Build expandable interactive code map.
Click module → expands to show functions. Click function → expands to show calls/callers.
Uses Mermaid.js for stable layouts, re-rendered on each expand/collapse.

Run: cd sandbox/analysis/mktt_dataflow && python build_expandable_map.py
"""
import ast
import os
import json
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent.parent.parent / 'src' / 'mktt'
OUT = Path(__file__).parent / 'output'
OUT.mkdir(parents=True, exist_ok=True)

MOD_COLORS = {
    'app': '#10b981', 'data_manager': '#f59e0b', 'stage_classifier': '#a78bfa',
    'options_service': '#ef4444', 'screener': '#ec4899', 'data_freshness': '#888',
    'macro/routes': '#06b6d4', 'macro/liquidity_service': '#06b6d4',
    'macro/rrg_service': '#06b6d4', 'macro/cache': '#06b6d4',
    'macro/__init__': '#06b6d4', 'update_classifications': '#84cc16',
}

def parse_module(filepath):
    try:
        tree = ast.parse(open(filepath, encoding='utf-8').read())
    except:
        return None

    module = {'imports': [], 'functions': []}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                module['imports'].append({'module': node.module, 'name': alias.name})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            route = None
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and hasattr(dec.func, 'attr') and dec.func.attr == 'route':
                    if dec.args:
                        try: route = ast.literal_eval(dec.args[0])
                        except: pass

            calls = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)

            module['functions'].append({
                'name': node.name,
                'args': [a.arg for a in node.args.args],
                'route': route,
                'calls': sorted(calls),
                'doc': (ast.get_docstring(node) or '')[:150],
                'lines': (node.end_lineno or node.lineno) - node.lineno + 1,
                'line': node.lineno,
            })
    return module

# Parse
modules = {}
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile):
        continue
    rel = pyfile.relative_to(SRC_DIR)
    mod_name = str(rel).replace('.py', '').replace(os.sep, '/')
    parsed = parse_module(pyfile)
    if parsed and (parsed['functions'] or parsed['imports']):
        modules[mod_name] = parsed

# Build function → module lookup
func_to_mod = {}
for mod, data in modules.items():
    for f in data['functions']:
        func_to_mod[f['name']] = mod

# Build callers map (who calls this function)
callers = {}
for mod, data in modules.items():
    for f in data['functions']:
        for call in f['calls']:
            if call in func_to_mod:
                callers.setdefault(call, []).append({'func': f['name'], 'module': mod})

print(f"Parsed {len(modules)} modules, {sum(len(m['functions']) for m in modules.values())} functions")

# Serialize for JS
js_data = {}
for mod, data in modules.items():
    js_data[mod] = {
        'functions': data['functions'],
        'imports': data['imports'],
        'color': MOD_COLORS.get(mod, '#4f8cf7'),
    }

js_func_to_mod = func_to_mod
js_callers = callers

# =========================================================================
# HTML
# =========================================================================
html = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>MKTT Code Map — Expandable</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0f1117; color:#ccc; font-family:'JetBrains Mono','Consolas',monospace; }

#header { background:#111; border-bottom:1px solid #333; padding:10px 20px; display:flex; align-items:center; gap:12px; }
#header h1 { color:#4f8cf7; font-size:16px; }
#breadcrumb { font-size:12px; color:#666; }
#breadcrumb span { cursor:pointer; color:#4f8cf7; }
#breadcrumb span:hover { text-decoration:underline; }

#main { padding:20px; }

#diagram { background:#0a0a0e; border:1px solid #222; border-radius:8px; padding:20px; margin-bottom:16px;
    min-height:200px; overflow-x:auto; }
#diagram .mermaid { font-size:13px; }

#info-panel { background:#111; border:1px solid #222; border-radius:8px; padding:16px; font-size:12px;
    display:none; margin-bottom:16px; }
#info-panel h3 { color:#10b981; margin-bottom:6px; }
#info-panel .route { color:#f59e0b; font-weight:700; }
#info-panel .doc { color:#888; font-style:italic; margin:4px 0; font-size:11px; }
#info-panel .call-link { color:#a78bfa; cursor:pointer; }
#info-panel .call-link:hover { text-decoration:underline; }
#info-panel .caller-link { color:#06b6d4; cursor:pointer; }
#info-panel .caller-link:hover { text-decoration:underline; }
#info-panel .section { margin:8px 0; }
#info-panel .section-title { color:#666; font-size:10px; text-transform:uppercase; margin-bottom:3px; }
</style>
</head><body>

<div id="header">
    <h1>MKTT Code Map</h1>
    <div id="breadcrumb"><span onclick="goHome()">Modules</span></div>
</div>

<div id="main">
    <div id="info-panel"></div>
    <div id="diagram"></div>
</div>

<script>
var MODULES = """ + json.dumps(js_data) + """;
var FUNC_TO_MOD = """ + json.dumps(func_to_mod) + """;
var CALLERS = """ + json.dumps(callers) + """;

var state = { level: 'modules', module: null, func: null, expanded: {} };

mermaid.initialize({
    startOnLoad: false, theme: 'dark',
    themeVariables: { darkMode:true, background:'#0a0a0e', primaryColor:'#4f8cf7',
        primaryTextColor:'#ccc', lineColor:'#444', secondaryColor:'#1a1a2a', tertiaryColor:'#111' },
    flowchart: { curve:'basis', padding:15, nodeSpacing:30, rankSpacing:50 },
    securityLevel:'loose',
});

function esc(s) { return s.replace(/"/g, "'").replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\//g, '∕'); }

function renderDiagram(mermaidCode) {
    var el = document.getElementById('diagram');
    el.innerHTML = '';
    var pre = document.createElement('pre');
    pre.className = 'mermaid';
    pre.textContent = mermaidCode;
    el.appendChild(pre);
    mermaid.run({nodes: [pre]});
}

function goHome() {
    state = { level:'modules', module:null, func:null, expanded:{} };
    document.getElementById('info-panel').style.display = 'none';
    document.getElementById('breadcrumb').innerHTML = '<span onclick="goHome()"><b>Modules</b></span>';
    renderModules();
}

function renderModules() {
    var lines = ['graph LR'];
    var mods = Object.keys(MODULES);

    mods.forEach(function(mod) {
        var m = MODULES[mod];
        var id = mod.replace(/\\//g,'_');
        var nf = m.functions.length;
        var routes = m.functions.filter(function(f){return f.route;}).length;
        var label = mod + '\\n' + nf + ' funcs';
        if (routes) label += ' | ' + routes + ' routes';
        lines.push('    ' + id + '["' + esc(label) + '"]');
        lines.push('    click ' + id + ' callMod');
    });

    // Import edges
    var seen = {};
    mods.forEach(function(mod) {
        var src = mod.replace(/\\//g,'_');
        MODULES[mod].imports.forEach(function(imp) {
            var base = imp.module.split('.')[0];
            mods.forEach(function(other) {
                var otherBase = other.split('/')[0];
                var tgt = other.replace(/\\//g,'_');
                if (otherBase === base && src !== tgt && !seen[src+'->'+tgt]) {
                    lines.push('    ' + src + ' --> ' + tgt);
                    seen[src+'->'+tgt] = true;
                }
            });
        });
    });

    // Styles
    mods.forEach(function(mod) {
        var id = mod.replace(/\\//g,'_');
        var c = MODULES[mod].color;
        lines.push('    style ' + id + ' fill:' + c + '22,stroke:' + c + ',color:' + c);
    });

    renderDiagram(lines.join('\\n'));
}

// Called by Mermaid click handler
window.callMod = function(nodeId) {
    var mod = nodeId.replace(/_/g, '/');
    // Check if it's a double-underscore (function node)
    if (nodeId.indexOf('__') > -1) {
        var parts = nodeId.split('__');
        var funcName = parts[parts.length - 1];
        var modName = parts.slice(0, -1).join('/');
        showFunction(modName, funcName);
    } else {
        expandModule(mod);
    }
};

function expandModule(mod) {
    if (!MODULES[mod]) return;
    state.level = 'module';
    state.module = mod;

    document.getElementById('breadcrumb').innerHTML =
        '<span onclick="goHome()">Modules</span> → <span><b>' + mod + '</b></span>';

    var m = MODULES[mod];
    var mid = mod.replace(/\\//g, '_');
    var lines = ['graph TD'];

    // Module header
    lines.push('    ' + mid + '_header["📦 ' + esc(mod) + '\\n' + m.functions.length + ' functions"]');
    lines.push('    style ' + mid + '_header fill:' + m.color + '33,stroke:' + m.color + ',color:' + m.color);

    // Functions
    m.functions.forEach(function(f) {
        var fid = mid + '__' + f.name;
        var label = f.name + '()';
        if (f.route) label = f.route + '\\n' + f.name + '()';
        else label += '\\n' + f.lines + ' lines';
        lines.push('    ' + fid + '["' + esc(label) + '"]');
        lines.push('    ' + mid + '_header --> ' + fid);
        lines.push('    click ' + fid + ' callMod');

        if (f.route) {
            lines.push('    style ' + fid + ' fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b');
        }

        // Cross-module calls
        f.calls.forEach(function(call) {
            if (FUNC_TO_MOD[call] && FUNC_TO_MOD[call] !== mod) {
                var extMod = FUNC_TO_MOD[call];
                var extId = extMod.replace(/\\//g, '_') + '__ext__' + call;
                lines.push('    ' + extId + '["' + esc(extMod) + '\\n' + call + '()"]');
                lines.push('    ' + fid + ' -.-> ' + extId);
                lines.push('    click ' + extId + ' callMod');
                var ec = (MODULES[extMod] || {}).color || '#666';
                lines.push('    style ' + extId + ' fill:' + ec + '11,stroke:' + ec + ',color:' + ec);
            }
        });
    });

    // Internal calls
    var funcNames = m.functions.map(function(f){return f.name;});
    m.functions.forEach(function(f) {
        var fid = mid + '__' + f.name;
        f.calls.forEach(function(call) {
            if (funcNames.indexOf(call) > -1 && call !== f.name) {
                lines.push('    ' + fid + ' --> ' + mid + '__' + call);
            }
        });
    });

    renderDiagram(lines.join('\\n'));
    document.getElementById('info-panel').style.display = 'none';
}

function showFunction(mod, funcName) {
    var m = MODULES[mod];
    if (!m) return;
    var func = m.functions.find(function(f){return f.name === funcName;});
    if (!func) return;

    state.level = 'function';
    state.func = funcName;

    document.getElementById('breadcrumb').innerHTML =
        '<span onclick="goHome()">Modules</span> → ' +
        '<span onclick="expandModule(\\'' + mod + '\\')">' + mod + '</span> → ' +
        '<span><b>' + funcName + '()</b></span>';

    // Info panel
    var panel = document.getElementById('info-panel');
    panel.style.display = 'block';
    var h = '<h3>' + funcName + '(' + func.args.join(', ') + ')</h3>';
    if (func.route) h += '<div class="route">Route: ' + func.route + '</div>';
    h += '<div style="color:#666;">Module: ' + mod + ' | Line ' + func.line + ' | ' + func.lines + ' lines</div>';
    if (func.doc) h += '<div class="doc">' + esc(func.doc) + '</div>';

    // Calls
    h += '<div class="section"><div class="section-title">Calls →</div>';
    if (func.calls.length) {
        func.calls.forEach(function(c) {
            var targetMod = FUNC_TO_MOD[c];
            if (targetMod) {
                h += '<div class="call-link" onclick="showFunction(\\'' + targetMod + '\\',\\'' + c + '\\')">' + c + '() <span style="color:#555;">← ' + targetMod + '</span></div>';
            } else {
                h += '<div style="color:#555;">' + c + '()</div>';
            }
        });
    } else {
        h += '<div style="color:#555;">None</div>';
    }
    h += '</div>';

    // Callers
    var myCallers = CALLERS[funcName] || [];
    h += '<div class="section"><div class="section-title">← Called by</div>';
    if (myCallers.length) {
        myCallers.forEach(function(c) {
            h += '<div class="caller-link" onclick="showFunction(\\'' + c.module + '\\',\\'' + c.func + '\\')">' + c.func + '() <span style="color:#555;">← ' + c.module + '</span></div>';
        });
    } else {
        h += '<div style="color:#555;">No callers found</div>';
    }
    h += '</div>';
    panel.innerHTML = h;

    // Diagram: this function + what it calls + who calls it
    var mid = mod.replace(/\\//g, '_');
    var fid = mid + '__' + funcName;
    var lines = ['graph LR'];

    // Callers on the left
    myCallers.forEach(function(c, i) {
        var cid = 'caller_' + i;
        var cmod = c.module.replace(/\\//g, '_');
        var cc = (MODULES[c.module] || {}).color || '#666';
        lines.push('    ' + cid + '["' + esc(c.module) + '\\n' + c.func + '()"]');
        lines.push('    ' + cid + ' --> ' + fid);
        lines.push('    click ' + cid + ' callMod');
        lines.push('    style ' + cid + ' fill:' + cc + '11,stroke:' + cc + ',color:' + cc);
    });

    // This function in center
    var label = funcName + '()';
    if (func.route) label = func.route + '\\n' + funcName + '()';
    lines.push('    ' + fid + '["' + esc(label) + '"]');
    var mc = MODULES[mod].color;
    lines.push('    style ' + fid + ' fill:' + mc + '33,stroke:' + mc + ',color:white');
    lines.push('    click ' + fid + ' callMod');

    // Calls on the right
    func.calls.forEach(function(call, i) {
        var targetMod = FUNC_TO_MOD[call];
        if (targetMod) {
            var tid = 'target_' + i;
            var tc = (MODULES[targetMod] || {}).color || '#666';
            lines.push('    ' + tid + '["' + esc(targetMod) + '\\n' + call + '()"]');
            lines.push('    ' + fid + ' --> ' + tid);
            lines.push('    click ' + tid + ' callMod');
            lines.push('    style ' + tid + ' fill:' + tc + '11,stroke:' + tc + ',color:' + tc);
        }
    });

    renderDiagram(lines.join('\\n'));
}

// Start
goHome();
</script>
</body></html>"""

out_path = OUT / 'mktt_expandable_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Saved: {out_path}")
print(f"Size: {out_path.stat().st_size / 1e3:.0f} KB")
