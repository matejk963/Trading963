"""
Build expandable interactive code map.
Click module → expands in-place showing functions. Click function → info panel.
Uses Mermaid.js subgraphs for stable layouts, re-rendered on expand/collapse.
"""
import ast, os, json
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
                    if isinstance(child.func, ast.Name): calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute): calls.add(child.func.attr)
            module['functions'].append({
                'name': node.name, 'args': [a.arg for a in node.args.args],
                'route': route, 'calls': sorted(calls),
                'doc': (ast.get_docstring(node) or '')[:150],
                'lines': (node.end_lineno or node.lineno) - node.lineno + 1,
                'line': node.lineno,
            })
    return module

modules = {}
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile): continue
    rel = pyfile.relative_to(SRC_DIR)
    mod_name = str(rel).replace('.py', '').replace(os.sep, '/')
    parsed = parse_module(pyfile)
    if parsed and (parsed['functions'] or parsed['imports']):
        modules[mod_name] = parsed

func_to_mod = {}
for mod, data in modules.items():
    for f in data['functions']:
        func_to_mod[f['name']] = mod

callers = {}
for mod, data in modules.items():
    for f in data['functions']:
        for call in f['calls']:
            if call in func_to_mod:
                callers.setdefault(call, []).append({'func': f['name'], 'module': mod})

js_data = {}
for mod, data in modules.items():
    js_data[mod] = {'functions': data['functions'], 'imports': data['imports'],
                    'color': MOD_COLORS.get(mod, '#4f8cf7')}

print(f"Parsed {len(modules)} modules, {sum(len(m['functions']) for m in modules.values())} functions")

def esc(s):
    return s.replace('"', "'").replace('<', '&lt;').replace('>', '&gt;').replace('/', '∕')

html = r"""<!DOCTYPE html>
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
button.reset { font-size:11px; padding:3px 10px; background:#1a1a2a; border:1px solid #333; color:#ccc; border-radius:4px; cursor:pointer; margin-left:auto; }
button.reset:hover { background:#2a2a3a; }
#main { display:flex; gap:0; }
#diagram-wrap { flex:1; padding:16px; overflow:hidden; min-height:calc(100vh - 50px); position:relative; }
#diagram { background:#0a0a0e; border:1px solid #222; border-radius:8px; min-height:300px; position:relative;
    transform-origin:0 0; cursor:grab; }
#diagram:active { cursor:grabbing; }
.close-mod { position:absolute; z-index:10; background:#ef4444cc; color:white; border:none; border-radius:50%;
    width:22px; height:22px; font-size:14px; font-weight:700; cursor:pointer; line-height:20px; text-align:center; }
.close-mod:hover { background:#ef4444; transform:scale(1.2); }
#zoom-controls { position:absolute; bottom:12px; left:12px; z-index:20; display:flex; gap:4px; }
#zoom-controls button { width:30px; height:30px; font-size:16px; background:#1a1a2a; border:1px solid #333;
    color:#ccc; border-radius:4px; cursor:pointer; }
#zoom-controls button:hover { background:#2a2a3a; }
#zoom-controls span { font-size:11px; color:#666; padding:8px 4px; }
#panel { width:360px; background:#111; border-left:1px solid #333; padding:14px; overflow-y:auto;
    max-height:calc(100vh - 50px); display:none; font-size:11px; flex-shrink:0; }
#panel h3 { color:#10b981; font-size:14px; margin-bottom:6px; }
#panel .route { color:#f59e0b; font-weight:700; margin:4px 0; }
#panel .doc { color:#888; font-style:italic; margin:4px 0; font-size:10px; }
#panel .sec { margin:10px 0 4px; color:#666; font-size:10px; text-transform:uppercase; border-bottom:1px solid #222; padding-bottom:2px; }
#panel .link { color:#a78bfa; cursor:pointer; padding:2px 0; }
#panel .link:hover { text-decoration:underline; }
#panel .clink { color:#06b6d4; cursor:pointer; padding:2px 0; }
#panel .clink:hover { text-decoration:underline; }
.close-btn { position:absolute; top:8px; right:10px; cursor:pointer; color:#f33; font-size:16px; font-weight:700; }
</style>
</head><body>
<div id="header">
    <h1>MKTT Code Map</h1>
    <div id="breadcrumb"><span onclick="goHome()"><b>Modules</b></span> — click any module to expand</div>
    <button id="callsBtn" onclick="toggleCalls()" style="font-size:11px;padding:3px 10px;background:#1a1a2a;border:1px solid #333;color:#888;border-radius:4px;cursor:pointer;">Show Calls</button>
    <button class="reset" onclick="goHome()">Collapse All</button>
</div>
<div id="main">
    <div id="diagram-wrap">
        <div id="diagram">Loading...</div>
        <div id="zoom-controls">
            <button onclick="zoomIn()">+</button>
            <button onclick="zoomOut()">−</button>
            <button onclick="zoomReset()">⟲</button>
            <span id="zoom-level">100%</span>
        </div>
    </div>
    <div id="panel" style="position:relative;"></div>
</div>
<script>
var MODULES = """ + json.dumps(js_data) + r""";
var FUNC_TO_MOD = """ + json.dumps(func_to_mod) + r""";
var CALLERS = """ + json.dumps(callers) + r""";
var expanded = {};
var showCalls = false;
var zoom = 1;
var panX = 0, panY = 0;
var isDragging = false, dragStartX, dragStartY;

// Zoom/Pan
function applyTransform() {
    var el = document.getElementById('diagram');
    el.style.transform = 'scale('+zoom+') translate('+panX+'px,'+panY+'px)';
    document.getElementById('zoom-level').textContent = Math.round(zoom*100)+'%';
}
function zoomIn() { zoom = Math.min(zoom * 1.25, 5); applyTransform(); }
function zoomOut() { zoom = Math.max(zoom * 0.8, 0.2); applyTransform(); }
function zoomReset() { zoom = 1; panX = 0; panY = 0; applyTransform(); }

document.addEventListener('DOMContentLoaded', function() {
    var wrap = document.getElementById('diagram-wrap');
    wrap.addEventListener('wheel', function(e) {
        e.preventDefault();
        if (e.deltaY < 0) zoom = Math.min(zoom * 1.1, 5);
        else zoom = Math.max(zoom * 0.9, 0.2);
        applyTransform();
    }, {passive: false});
    // Pan with mouse drag on background
    wrap.addEventListener('mousedown', function(e) {
        if (e.target.closest('.node,.close-mod,#panel,#zoom-controls')) return;
        isDragging = true; dragStartX = e.clientX - panX * zoom; dragStartY = e.clientY - panY * zoom;
    });
    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        panX = (e.clientX - dragStartX) / zoom;
        panY = (e.clientY - dragStartY) / zoom;
        applyTransform();
    });
    document.addEventListener('mouseup', function() { isDragging = false; });
});

function toggleCalls() {
    showCalls = !showCalls;
    var btn = document.getElementById('callsBtn');
    btn.style.background = showCalls ? '#a78bfa' : '#1a1a2a';
    btn.style.color = showCalls ? 'white' : '#888';
    btn.textContent = showCalls ? 'Hide Calls' : 'Show Calls';
    rebuild();
}

mermaid.initialize({ startOnLoad:false, theme:'dark',
    themeVariables:{darkMode:true,background:'#0a0a0e',primaryColor:'#4f8cf7',
        primaryTextColor:'#ccc',lineColor:'#444',secondaryColor:'#1a1a2a',tertiaryColor:'#111'},
    flowchart:{curve:'basis',padding:12,nodeSpacing:18,rankSpacing:35},
    securityLevel:'loose'});

function esc(s){return s.replace(/"/g,"'").replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\//g,'∕');}

function render(code){
    var el=document.getElementById('diagram');
    el.innerHTML='';
    var id='m'+Date.now();
    mermaid.render(id,code).then(function(r){
        el.innerHTML=r.svg;
        var svg=el.querySelector('svg');
        if(svg){svg.style.width='100%';svg.style.maxWidth='none';}
        // Clickable nodes
        el.querySelectorAll('.node,.cluster').forEach(function(n){
            n.style.cursor='pointer';
            n.addEventListener('click',function(e){
                e.stopPropagation();
                var raw=n.id||'';
                var m=raw.match(/flowchart-(.+?)-\d+$/);
                var nid=m?m[1]:raw;
                if(!nid)return;
                handleClick(nid);
            });
        });
        // Add HTML close buttons overlaid on expanded module nodes
        addCloseButtons(el,svg);
    }).catch(function(e){el.innerHTML='<pre style="color:#f33;">'+e+'</pre>';});
}

function addCloseButtons(container, svg) {
    // Remove old buttons
    container.querySelectorAll('.close-mod').forEach(function(b){b.remove();});
    if (!svg) return;
    var svgRect = svg.getBoundingClientRect();
    var containerRect = container.getBoundingClientRect();
    // For each expanded module, find its node in the SVG and place a close button
    Object.keys(expanded).forEach(function(mid) {
        if (!expanded[mid]) return;
        // Find the module node in SVG
        var nodeEl = null;
        svg.querySelectorAll('.node').forEach(function(n) {
            var raw = n.id || '';
            var m = raw.match(/flowchart-(.+?)-\d+$/);
            var nid = m ? m[1] : raw;
            if (nid === mid) nodeEl = n;
        });
        if (!nodeEl) return;
        var nodeRect = nodeEl.getBoundingClientRect();
        var btn = document.createElement('button');
        btn.className = 'close-mod';
        btn.textContent = '✕';
        btn.title = 'Collapse ' + mid.replace(/_/g, '/');
        btn.style.left = (nodeRect.right - containerRect.left - 4) + 'px';
        btn.style.top = (nodeRect.top - containerRect.top - 4) + 'px';
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            expanded[mid] = false;
            document.getElementById('panel').style.display = 'none';
            rebuild();
        });
        container.appendChild(btn);
    });
}

function handleClick(nid){
    if(nid.indexOf('__')>-1){
        // Function node
        var parts=nid.split('__');
        var fn=parts[parts.length-1];
        var mid=parts.slice(0,-1).join('_');
        var mod=mid.replace(/_/g,'/');
        showPanel(mod,fn);
    } else {
        // Module: toggle expand
        expanded[nid]=!expanded[nid];
        document.getElementById('panel').style.display='none';
        rebuild();
    }
}

function goHome(){
    expanded={};
    document.getElementById('panel').style.display='none';
    document.getElementById('breadcrumb').innerHTML='<span onclick="goHome()"><b>Modules</b></span> — click any module to expand';
    rebuild();
}

function rebuild(){
    var lines=['graph TD'];
    var mods=Object.keys(MODULES);

    mods.forEach(function(mod){
        var m=MODULES[mod];
        var mid=mod.replace(/\//g,'_');
        if(expanded[mid]){
            // Module node stays, functions branch below it
            var nf=m.functions.length;
            var nr=m.functions.filter(function(f){return f.route;}).length;
            var lbl='📂 '+mod;
            lines.push('    '+mid+'["'+esc(lbl)+'"]');
            lines.push('    style '+mid+' fill:'+m.color+'33,stroke:'+m.color+',color:'+m.color);

            // Function nodes below
            m.functions.forEach(function(f){
                var fid=mid+'__'+f.name;
                var flbl=f.name+'()';
                if(f.route) flbl=f.route+'\\n'+f.name+'()';
                // no line count in label — keep it clean
                lines.push('    '+fid+'["'+esc(flbl)+'"]');
                lines.push('    '+mid+' --> '+fid);
                if(f.route) lines.push('    style '+fid+' fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b');
                else lines.push('    style '+fid+' fill:'+m.color+'11,stroke:'+m.color+'88,color:'+m.color);
            });

            // Internal call edges between functions
            var fnames=m.functions.map(function(f){return f.name;});
            m.functions.forEach(function(f){
                f.calls.forEach(function(c){
                    if(fnames.indexOf(c)>-1 && c!==f.name)
                        lines.push('    '+mid+'__'+f.name+' --> '+mid+'__'+c);
                });
            });
        } else {
            var nf=m.functions.length;
            var nr=m.functions.filter(function(f){return f.route;}).length;
            var lbl=mod+'\\n'+nf+' funcs';
            if(nr) lbl+=' | '+nr+' routes';
            lines.push('    '+mid+'["'+esc(lbl)+'"]');
            lines.push('    style '+mid+' fill:'+m.color+'22,stroke:'+m.color+',color:'+m.color);
        }
    });

    // Import edges
    var seen={};
    mods.forEach(function(mod){
        var src=mod.replace(/\//g,'_');
        MODULES[mod].imports.forEach(function(imp){
            var base=imp.module.split('.')[0];
            mods.forEach(function(other){
                if(other.split('/')[0]===base){
                    var tgt=other.replace(/\//g,'_');
                    if(src!==tgt && !seen[src+'->'+tgt]){
                        lines.push('    '+src+' -.-> '+tgt);
                        seen[src+'->'+tgt]=true;
                    }
                }
            });
        });
    });

    // Cross-module function calls (only when Show Calls is active)
    if(showCalls){
        mods.forEach(function(mod){
            var mid=mod.replace(/\//g,'_');
            if(!expanded[mid]) return;
            MODULES[mod].functions.forEach(function(f){
                f.calls.forEach(function(c){
                    var tm=FUNC_TO_MOD[c];
                    if(tm && tm!==mod){
                        var tmid=tm.replace(/\//g,'_');
                        if(expanded[tmid])
                            lines.push('    '+mid+'__'+f.name+' ==> '+tmid+'__'+c);
                        else
                            lines.push('    '+mid+'__'+f.name+' ==> '+tmid);
                    }
                });
            });
        });
    }

    // Breadcrumb
    var exp=Object.keys(expanded).filter(function(k){return expanded[k];}).map(function(k){return k.replace(/_/g,'/');});
    var bc='<span onclick="goHome()">Modules</span>';
    if(exp.length) bc+=' → '+exp.map(function(n){return '<b style="color:'+(MODULES[n]||{}).color+';">'+n+'</b>';}).join(', ');
    document.getElementById('breadcrumb').innerHTML=bc;

    render(lines.join('\n'));
}

function showPanel(mod,funcName){
    var m=MODULES[mod];
    if(!m) return;
    var f=m.functions.find(function(x){return x.name===funcName;});
    if(!f) return;
    var p=document.getElementById('panel');
    p.style.display='block';
    var h='<span class="close-btn" onclick="document.getElementById(\'panel\').style.display=\'none\'">✕</span>';
    h+='<h3>'+funcName+'('+f.args.join(', ')+')</h3>';
    if(f.route) h+='<div class="route">'+f.route+'</div>';
    h+='<div style="color:#666;">'+mod+' | L'+f.line+' | '+f.lines+' lines</div>';
    if(f.doc) h+='<div class="doc">'+esc(f.doc)+'</div>';

    h+='<div class="sec">Calls →</div>';
    f.calls.forEach(function(c){
        var tm=FUNC_TO_MOD[c];
        if(tm) h+='<div class="link" onclick="navTo(\''+tm+'\',\''+c+'\')">'+c+'() <span style="color:#555;">← '+tm+'</span></div>';
        else h+='<div style="color:#555;">'+c+'()</div>';
    });
    if(!f.calls.length) h+='<div style="color:#555;">None</div>';

    var cl=CALLERS[funcName]||[];
    h+='<div class="sec">← Called by</div>';
    cl.forEach(function(c){
        h+='<div class="clink" onclick="navTo(\''+c.module+'\',\''+c.func+'\')">'+c.func+'() <span style="color:#555;">← '+c.module+'</span></div>';
    });
    if(!cl.length) h+='<div style="color:#555;">No callers found</div>';

    p.innerHTML=h;
}

function navTo(mod,func){
    var mid=mod.replace(/\//g,'_');
    expanded[mid]=true;
    rebuild();
    // After rebuild, show panel for the function
    setTimeout(function(){ showPanel(mod,func); },200);
}

goHome();
</script>
</body></html>"""

out_path = OUT / 'mktt_expandable_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Saved: {out_path} ({out_path.stat().st_size / 1e3:.0f} KB)")
