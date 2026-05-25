"""
Build interactive HTML code map of MKTT app.
Auto-parses all Python files, extracts modules/classes/functions/imports/calls,
renders as interactive D3.js force-directed graph with drill-down.

Run: cd sandbox/analysis/mktt_dataflow && python build_interactive_map.py
"""
import ast
import os
import json
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent.parent.parent / 'src' / 'mktt'
OUT = Path(__file__).parent / 'output'
OUT.mkdir(parents=True, exist_ok=True)


def parse_module(filepath):
    """Parse a Python file and extract structure."""
    try:
        source = open(filepath, encoding='utf-8').read()
        tree = ast.parse(source)
    except:
        return None

    module = {
        'file': str(filepath),
        'imports': [],
        'functions': [],
        'classes': [],
        'globals': [],
    }

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module['imports'].append({'module': alias.name, 'name': alias.asname or alias.name, 'line': node.lineno})
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    module['imports'].append({'module': node.module, 'name': alias.name, 'line': node.lineno})
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            func = parse_function(node, source)
            module['functions'].append(func)
        elif isinstance(node, ast.ClassDef):
            cls = parse_class(node, source)
            module['classes'].append(cls)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module['globals'].append({'name': target.id, 'line': node.lineno})

    return module


def parse_function(node, source):
    """Extract function info: name, args, decorators, docstring, calls made."""
    args = []
    for arg in node.args.args:
        args.append(arg.arg)

    decorators = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            decorators.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            decorators.append(f'{ast.unparse(dec)}')
        elif isinstance(dec, ast.Call):
            decorators.append(ast.unparse(dec.func))

    # Extract calls made inside function
    calls = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.add(child.func.attr)

    # Docstring
    docstring = ast.get_docstring(node) or ''

    # Route decorator
    route = None
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and hasattr(dec.func, 'attr') and dec.func.attr == 'route':
            if dec.args:
                route = ast.literal_eval(dec.args[0])

    return {
        'name': node.name,
        'args': args,
        'decorators': decorators,
        'docstring': docstring[:200],
        'calls': sorted(calls),
        'route': route,
        'line': node.lineno,
        'end_line': node.end_lineno or node.lineno,
        'lines': (node.end_lineno or node.lineno) - node.lineno + 1,
    }


def parse_class(node, source):
    """Extract class info."""
    methods = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(parse_function(child, source))

    return {
        'name': node.name,
        'methods': methods,
        'docstring': ast.get_docstring(node) or '',
        'line': node.lineno,
    }


# =========================================================================
# Parse all modules
# =========================================================================
modules = {}
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile):
        continue
    rel = pyfile.relative_to(SRC_DIR)
    mod_name = str(rel).replace('.py', '').replace(os.sep, '.')
    parsed = parse_module(pyfile)
    if parsed:
        parsed['name'] = mod_name
        modules[mod_name] = parsed

print(f"Parsed {len(modules)} modules:")
for name, mod in modules.items():
    nf = len(mod['functions'])
    nc = len(mod['classes'])
    ni = len(mod['imports'])
    routes = [f['route'] for f in mod['functions'] if f.get('route')]
    print(f"  {name}: {nf} functions, {nc} classes, {ni} imports, {len(routes)} routes")

# =========================================================================
# Build graph data for D3
# =========================================================================

# Nodes: modules + functions
nodes = []
links = []
node_index = {}

# Module nodes
for mod_name, mod in modules.items():
    idx = len(nodes)
    node_index[mod_name] = idx
    total_lines = sum(f['lines'] for f in mod['functions'])
    routes = [f['route'] for f in mod['functions'] if f.get('route')]
    nodes.append({
        'id': mod_name,
        'type': 'module',
        'functions': [f['name'] for f in mod['functions']],
        'function_details': mod['functions'],
        'classes': [c['name'] for c in mod['classes']],
        'imports': mod['imports'],
        'globals': [g['name'] for g in mod['globals']],
        'routes': routes,
        'total_lines': total_lines,
        'file': mod['file'],
    })

# Function nodes (inside modules)
for mod_name, mod in modules.items():
    for func in mod['functions']:
        fid = f"{mod_name}.{func['name']}"
        idx = len(nodes)
        node_index[fid] = idx
        nodes.append({
            'id': fid,
            'type': 'function',
            'module': mod_name,
            'name': func['name'],
            'args': func['args'],
            'decorators': func['decorators'],
            'docstring': func['docstring'],
            'calls': func['calls'],
            'route': func['route'],
            'lines': func['lines'],
            'line': func['line'],
        })
        # Link function to its module
        if mod_name in node_index:
            links.append({'source': node_index[mod_name], 'target': idx, 'type': 'contains'})

# Cross-module call links
for mod_name, mod in modules.items():
    for func in mod['functions']:
        fid = f"{mod_name}.{func['name']}"
        src_idx = node_index.get(fid)
        if src_idx is None:
            continue
        for call in func['calls']:
            # Find target function in any module
            for other_mod, other in modules.items():
                if other_mod == mod_name:
                    continue
                for other_func in other['functions']:
                    if other_func['name'] == call:
                        tgt_id = f"{other_mod}.{other_func['name']}"
                        tgt_idx = node_index.get(tgt_id)
                        if tgt_idx is not None:
                            links.append({'source': src_idx, 'target': tgt_idx, 'type': 'calls'})

# Import links (module → module)
for mod_name, mod in modules.items():
    src_idx = node_index.get(mod_name)
    for imp in mod['imports']:
        # Check if imported module is local
        imp_mod = imp['module'].split('.')[0]
        for other_mod in modules:
            if other_mod == imp_mod or other_mod.startswith(imp_mod + '.'):
                tgt_idx = node_index.get(other_mod)
                if tgt_idx is not None and src_idx != tgt_idx:
                    links.append({'source': src_idx, 'target': tgt_idx, 'type': 'imports'})
                break

graph_data = {'nodes': nodes, 'links': links}

# =========================================================================
# Generate HTML
# =========================================================================
html = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>MKTT Code Map — Interactive</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #0a0a0e; color: #ccc; font-family: 'JetBrains Mono', 'Consolas', monospace; overflow: hidden; }

#controls {
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    background: #111; border-bottom: 1px solid #333; padding: 8px 16px;
    display: flex; align-items: center; gap: 12px; font-size: 12px;
}
#controls button { font-size: 11px; padding: 3px 10px; background: #1a1a2a; border: 1px solid #333;
    color: #ccc; border-radius: 4px; cursor: pointer; }
#controls button:hover { background: #2a2a3a; }
#controls button.active { background: #4f8cf7; color: white; border-color: #4f8cf7; }

#graph { width: 100vw; height: calc(100vh - 36px); margin-top: 36px; }

#detail {
    position: fixed; right: 0; top: 36px; bottom: 0; width: 380px;
    background: #111; border-left: 1px solid #333; padding: 12px;
    overflow-y: auto; font-size: 11px; display: none; z-index: 50;
}
#detail h2 { color: #4f8cf7; font-size: 14px; margin-bottom: 8px; }
#detail h3 { color: #10b981; font-size: 12px; margin: 8px 0 4px; }
#detail .route { color: #f59e0b; font-weight: 700; }
#detail .func-item { padding: 4px 0; border-bottom: 1px solid #1a1a2a; cursor: pointer; }
#detail .func-item:hover { background: #1a1a2a; }
#detail .func-name { color: #10b981; font-weight: 600; }
#detail .func-args { color: #666; }
#detail .func-doc { color: #888; font-size: 10px; margin-top: 2px; }
#detail .calls-list { color: #a78bfa; font-size: 10px; }
#detail .close-btn { position: absolute; top: 8px; right: 8px; cursor: pointer; color: #f33; font-size: 16px; }

.tooltip {
    position: absolute; background: #1a1a2a; border: 1px solid #333;
    border-radius: 4px; padding: 6px 10px; font-size: 11px; pointer-events: none;
    z-index: 200; max-width: 300px;
}
</style>
</head><body>

<div id="controls">
    <span style="font-weight:700;color:#4f8cf7;">MKTT Code Map</span>
    <button class="active" onclick="setView('modules')">Modules</button>
    <button onclick="setView('functions')">Functions</button>
    <button onclick="setView('routes')">Routes</button>
    <span id="info" style="margin-left:auto;color:#666;"></span>
</div>

<svg id="graph"></svg>

<div id="detail">
    <span class="close-btn" onclick="closeDetail()">✕</span>
    <div id="detail-content"></div>
</div>

<script>
var DATA = """ + json.dumps(graph_data) + """;

var svg = d3.select('#graph');
var width, height;
var simulation;
var currentView = 'modules';
var tooltip;

function init() {
    var rect = svg.node().getBoundingClientRect();
    width = rect.width;
    height = rect.height;

    tooltip = d3.select('body').append('div').attr('class', 'tooltip').style('display', 'none');

    setView('modules');
}

function setView(view) {
    currentView = view;
    document.querySelectorAll('#controls button').forEach(function(b) {
        b.classList.toggle('active', b.textContent.toLowerCase() === view);
    });
    render();
}

function render() {
    svg.selectAll('*').remove();

    var g = svg.append('g');

    // Zoom
    var zoom = d3.zoom().scaleExtent([0.1, 5]).on('zoom', function(e) {
        g.attr('transform', e.transform);
    });
    svg.call(zoom);

    var nodes, links;

    if (currentView === 'modules') {
        nodes = DATA.nodes.filter(function(n) { return n.type === 'module'; });
        links = DATA.links.filter(function(l) { return l.type === 'imports'; });
    } else if (currentView === 'functions') {
        nodes = DATA.nodes.slice();
        links = DATA.links.filter(function(l) { return l.type === 'contains' || l.type === 'calls'; });
    } else {
        // Routes view: only functions with routes + their call targets
        var routeFuncs = new Set();
        DATA.nodes.forEach(function(n, i) {
            if (n.type === 'function' && n.route) routeFuncs.add(i);
        });
        // Add call targets
        DATA.links.forEach(function(l) {
            if (l.type === 'calls' && routeFuncs.has(l.source)) routeFuncs.add(l.target);
        });
        nodes = DATA.nodes.filter(function(n, i) { return routeFuncs.has(i) || (n.type === 'module' && n.routes && n.routes.length > 0); });
        links = DATA.links.filter(function(l) {
            return (l.type === 'calls' && routeFuncs.has(l.source)) ||
                   (l.type === 'contains' && routeFuncs.has(l.target));
        });
    }

    // Remap indices
    var indexMap = {};
    nodes.forEach(function(n, i) {
        indexMap[DATA.nodes.indexOf(n)] = i;
    });
    var mappedLinks = links.map(function(l) {
        return {source: indexMap[l.source], target: indexMap[l.target], type: l.type};
    }).filter(function(l) { return l.source !== undefined && l.target !== undefined; });

    document.getElementById('info').textContent = nodes.length + ' nodes, ' + mappedLinks.length + ' links';

    // Colors
    var moduleColors = {
        'app': '#10b981', 'data_manager': '#f59e0b', 'stage_classifier': '#a78bfa',
        'options_service': '#ef4444', 'screener': '#06b6d4', 'data_freshness': '#888',
        'update_classifications': '#ec4899', 'macro.routes': '#06b6d4',
        'macro.liquidity_service': '#06b6d4', 'macro.rrg_service': '#06b6d4',
        'macro.cache': '#06b6d4', 'macro.__init__': '#06b6d4',
    };

    function nodeColor(n) {
        if (n.type === 'module') return moduleColors[n.id] || '#4f8cf7';
        if (n.type === 'function' && n.route) return '#f59e0b';
        return moduleColors[n.module] || '#4f8cf7';
    }
    function nodeSize(n) {
        if (n.type === 'module') return Math.max(12, Math.min(30, (n.functions || []).length * 2 + 8));
        if (n.route) return 10;
        return 6;
    }

    simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(mappedLinks).distance(function(l) {
            return l.type === 'contains' ? 40 : l.type === 'imports' ? 120 : 80;
        }))
        .force('charge', d3.forceManyBody().strength(function(n) {
            return n.type === 'module' ? -300 : -80;
        }))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(function(n) { return nodeSize(n) + 5; }));

    // Links
    var link = g.selectAll('.link').data(mappedLinks).enter().append('line')
        .attr('class', 'link')
        .attr('stroke', function(l) {
            if (l.type === 'imports') return '#333';
            if (l.type === 'calls') return '#4f8cf755';
            return '#222';
        })
        .attr('stroke-width', function(l) { return l.type === 'calls' ? 1.5 : 1; })
        .attr('stroke-dasharray', function(l) { return l.type === 'imports' ? '4,4' : null; });

    // Nodes
    var node = g.selectAll('.node').data(nodes).enter().append('g')
        .attr('class', 'node')
        .call(d3.drag()
            .on('start', function(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', function(e, d) { d.fx = e.x; d.fy = e.y; })
            .on('end', function(e, d) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.append('circle')
        .attr('r', function(d) { return nodeSize(d); })
        .attr('fill', function(d) { return nodeColor(d); })
        .attr('stroke', function(d) { return d.type === 'module' ? '#fff' : 'none'; })
        .attr('stroke-width', function(d) { return d.type === 'module' ? 2 : 0; })
        .attr('opacity', 0.85);

    node.append('text')
        .text(function(d) {
            if (d.type === 'module') return d.id;
            if (d.route) return d.route;
            return d.name || '';
        })
        .attr('dx', function(d) { return nodeSize(d) + 4; })
        .attr('dy', 3)
        .attr('fill', function(d) { return d.route ? '#f59e0b' : '#aaa'; })
        .attr('font-size', function(d) { return d.type === 'module' ? '12px' : '9px'; })
        .attr('font-weight', function(d) { return d.type === 'module' ? '700' : '400'; });

    // Hover
    node.on('mouseover', function(e, d) {
        var html = '<strong>' + (d.id || d.name) + '</strong>';
        if (d.type === 'module') {
            html += '<br>' + (d.functions || []).length + ' functions';
            if (d.routes && d.routes.length) html += '<br>Routes: ' + d.routes.join(', ');
        } else {
            if (d.route) html += '<br>Route: ' + d.route;
            if (d.args && d.args.length) html += '<br>Args: ' + d.args.join(', ');
            if (d.docstring) html += '<br><em>' + d.docstring.substring(0, 100) + '</em>';
        }
        tooltip.html(html).style('display', 'block')
            .style('left', (e.pageX + 12) + 'px').style('top', (e.pageY - 10) + 'px');
    })
    .on('mouseout', function() { tooltip.style('display', 'none'); })
    .on('click', function(e, d) { showDetail(d); });

    simulation.on('tick', function() {
        link.attr('x1', function(l) { return l.source.x; })
            .attr('y1', function(l) { return l.source.y; })
            .attr('x2', function(l) { return l.target.x; })
            .attr('y2', function(l) { return l.target.y; });
        node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
    });
}

function showDetail(d) {
    var panel = document.getElementById('detail');
    var content = document.getElementById('detail-content');
    panel.style.display = 'block';

    var h = '';
    if (d.type === 'module') {
        h += '<h2>' + d.id + '</h2>';
        h += '<p style="color:#666;">' + d.file + '</p>';

        if (d.routes && d.routes.length) {
            h += '<h3>Routes</h3>';
            d.routes.forEach(function(r) { h += '<div class="route">' + r + '</div>'; });
        }

        h += '<h3>Functions (' + d.function_details.length + ')</h3>';
        d.function_details.forEach(function(f) {
            h += '<div class="func-item" onclick="focusFunction(\\'' + d.id + '.' + f.name + '\\')">';
            h += '<span class="func-name">' + f.name + '</span>';
            h += '<span class="func-args">(' + f.args.join(', ') + ')</span>';
            if (f.route) h += ' <span class="route">' + f.route + '</span>';
            h += ' <span style="color:#444;">L' + f.line + ' (' + f.lines + ' lines)</span>';
            if (f.docstring) h += '<div class="func-doc">' + f.docstring.substring(0, 120) + '</div>';
            if (f.calls.length) h += '<div class="calls-list">calls: ' + f.calls.slice(0, 8).join(', ') + (f.calls.length > 8 ? '...' : '') + '</div>';
            h += '</div>';
        });

        if (d.globals && d.globals.length) {
            h += '<h3>Globals</h3>';
            d.globals.forEach(function(g) { h += '<div style="color:#666;">' + g.name + '</div>'; });
        }

        if (d.imports && d.imports.length) {
            h += '<h3>Imports</h3>';
            d.imports.forEach(function(i) {
                h += '<div style="color:#666;">from ' + i.module + ' import ' + i.name + '</div>';
            });
        }
    } else {
        h += '<h2>' + d.name + '</h2>';
        h += '<p style="color:#666;">Module: ' + d.module + '</p>';
        if (d.route) h += '<div class="route" style="margin:4px 0;">Route: ' + d.route + '</div>';
        h += '<p>Args: <span style="color:#10b981;">' + (d.args || []).join(', ') + '</span></p>';
        h += '<p>Lines: ' + d.line + '-' + (d.line + d.lines - 1) + ' (' + d.lines + ' lines)</p>';
        if (d.decorators && d.decorators.length) h += '<p>Decorators: ' + d.decorators.join(', ') + '</p>';
        if (d.docstring) h += '<div style="margin:8px 0;padding:6px;background:#1a1a2a;border-radius:4px;color:#888;">' + d.docstring + '</div>';
        if (d.calls && d.calls.length) {
            h += '<h3>Calls</h3>';
            d.calls.forEach(function(c) {
                h += '<div class="calls-list" style="padding:2px 0;cursor:pointer;" onclick="focusFunction(\\'' + c + '\\')">' + c + '</div>';
            });
        }
    }

    content.innerHTML = h;
}

function closeDetail() {
    document.getElementById('detail').style.display = 'none';
}

function focusFunction(name) {
    // Highlight the function node
    d3.selectAll('.node circle').attr('opacity', function(d) {
        return (d.id === name || d.name === name) ? 1 : 0.3;
    });
    setTimeout(function() {
        d3.selectAll('.node circle').attr('opacity', 0.85);
    }, 2000);
}

init();
</script>
</body></html>"""

out_path = OUT / 'mktt_interactive_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Saved: {out_path}")
print(f"Size: {out_path.stat().st_size / 1e3:.0f} KB")
