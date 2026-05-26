"""
Expandable code map with folder/file/function drill-down.
Level 1: folders + top-level files. Click folder → shows files inside.
Click file → shows functions. Click function → info panel.
Zoom/pan, on-demand call arrows.
"""
import ast, os, json
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent.parent.parent / 'src' / 'mktt'
OUT = Path(__file__).parent / 'output'
OUT.mkdir(parents=True, exist_ok=True)

MOD_COLORS = {
    'app': '#10b981', 'data_manager': '#f59e0b', 'stage_classifier': '#a78bfa',
    'options_service': '#ef4444', 'screener': '#ec4899', 'data_freshness': '#888',
    'macro': '#06b6d4', 'update_classifications': '#84cc16',
    'templates': '#f97316', 'templates/macro': '#f97316',
    'static/js': '#22d3ee', 'static/css': '#a3a3a3',
}

def parse_module(filepath):
    try: tree = ast.parse(open(filepath, encoding='utf-8').read())
    except: return None
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

def parse_js(filepath):
    """Parse a JS file: extract function definitions and fetch() URLs."""
    import re
    try: content = open(filepath, encoding='utf-8').read()
    except: return None
    functions = []
    # Find function declarations: function name(
    for m in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)', content):
        name = m.group(1)
        args = [a.strip() for a in m.group(2).split(',') if a.strip()]
        # Find line number
        line = content[:m.start()].count('\n') + 1
        # Find end (approximate: next function or end)
        next_func = re.search(r'\nfunction\s+\w+\s*\(', content[m.end():])
        end_line = line + (content[m.start():m.start()+next_func.start()].count('\n') if next_func else 20)
        functions.append({'name': name, 'args': args[:4], 'route': None,
            'calls': [], 'doc': '', 'lines': end_line - line, 'line': line})
    # Find fetch() URLs
    fetches = re.findall(r"fetch\(['\"]([^'\"]+)['\"]", content)
    fetches += re.findall(r"fetch\(['\"]([^'\"]+?)['\"]", content)
    # Deduplicate
    fetches = sorted(set(f.split('?')[0] for f in fetches))
    return {'functions': functions, 'fetches': fetches, 'imports': [],
            'nlines': content.count('\n') + 1}

def parse_html(filepath):
    """Parse an HTML template: extract extends, blocks, fetch URLs, script includes."""
    import re
    try: content = open(filepath, encoding='utf-8').read()
    except: return None
    extends = re.findall(r"\{%\s*extends\s+['\"]([^'\"]+)['\"]", content)
    blocks = re.findall(r"\{%\s*block\s+(\w+)", content)
    fetches = re.findall(r"fetch\(['\"]([^'\"]+)['\"]", content)
    fetches = sorted(set(f.split('?')[0] for f in fetches))
    scripts = re.findall(r'src=["\']([^"\']*\.js)["\']', content)
    scripts = [s.split('/')[-1] for s in scripts if 'static' in s or 'stock_panel' in s or 'macro' in s]
    # JS functions defined inline
    functions = []
    for m in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)', content):
        functions.append({'name': m.group(1), 'args': [], 'route': None,
            'calls': [], 'doc': '', 'lines': 5, 'line': content[:m.start()].count('\n')+1})
    return {'extends': extends, 'blocks': blocks, 'fetches': fetches, 'scripts': scripts,
            'functions': functions, 'imports': [], 'nlines': content.count('\n') + 1}

def parse_css(filepath):
    """Minimal CSS parse: just line count."""
    try: content = open(filepath, encoding='utf-8').read()
    except: return None
    return {'nlines': content.count('\n') + 1, 'functions': [], 'imports': []}

# Parse into nested tree structure: {files: {}, folders: {name: {files:{}, folders:{}}}}
tree = {'files': {}, 'folders': {}}

def add_to_tree(rel_parts, parsed, ext):
    """Add a parsed file to the tree, building nested folder structure."""
    fname = rel_parts[-1].replace(ext, '')
    if len(rel_parts) == 1:
        tree['files'][fname] = parsed
    else:
        node = tree
        for folder_part in rel_parts[:-1]:
            if folder_part not in node['folders']:
                node['folders'][folder_part] = {'files': {}, 'folders': {}}
            node = node['folders'][folder_part]
        node['files'][fname] = parsed

# Python files
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile): continue
    rel = pyfile.relative_to(SRC_DIR)
    parts = list(rel.parts)
    parsed = parse_module(pyfile)
    if not parsed or (not parsed['functions'] and not parsed['imports']): continue

    add_to_tree(parts, parsed, '.py')

## add_to_tree already defined above

# JS files
for jsfile in sorted(SRC_DIR.rglob('*.js')):
    rel = jsfile.relative_to(SRC_DIR)
    parsed = parse_js(jsfile)
    if parsed: add_to_tree(list(rel.parts), parsed, '.js')

# HTML templates
for htmlfile in sorted(SRC_DIR.rglob('*.html')):
    rel = htmlfile.relative_to(SRC_DIR)
    parsed = parse_html(htmlfile)
    if parsed: add_to_tree(list(rel.parts), parsed, '.html')

# CSS files
for cssfile in sorted(SRC_DIR.rglob('*.css')):
    rel = cssfile.relative_to(SRC_DIR)
    parsed = parse_css(cssfile)
    if parsed: add_to_tree(list(rel.parts), parsed, '.css')

# Flatten for lookups (recursive)
all_modules = {}
def flatten_tree(node, prefix=''):
    for fname, data in node['files'].items():
        key = f'{prefix}{fname}' if prefix else fname
        all_modules[key] = data
    for folder, fdata in node['folders'].items():
        flatten_tree(fdata, f'{prefix}{folder}/')
flatten_tree(tree)

func_to_mod = {}
for mod, data in all_modules.items():
    for f in data['functions']:
        func_to_mod[f['name']] = mod

callers = {}
for mod, data in all_modules.items():
    for f in data['functions']:
        for call in f['calls']:
            if call in func_to_mod:
                callers.setdefault(call, []).append({'func': f['name'], 'module': mod})

def file_ext(fname):
    """Guess extension from original parsing."""
    # We stripped extensions, so check for known names
    return ''

# Build JS data
def build_file_js(data, folder=None):
    funcs = data.get('functions', [])
    return {
        'functions': funcs,
        'imports': data.get('imports', []),
        'fetches': data.get('fetches', []),
        'extends': data.get('extends', []),
        'scripts': data.get('scripts', []),
        'blocks': data.get('blocks', []),
        'color': MOD_COLORS.get(folder, '#4f8cf7') if folder else '#4f8cf7',
        'nfuncs': len(funcs),
        'nroutes': len([f for f in funcs if f.get('route')]),
        'nlines': data.get('nlines', 0),
    }

def build_js_tree(node, path=''):
    result = {'files': {}, 'folders': {}}
    for fname, data in node['files'].items():
        d = build_file_js(data, path.rstrip('/') if path else None)
        key = path + fname if path else fname
        d['color'] = MOD_COLORS.get(key, MOD_COLORS.get(path.rstrip('/'), '#4f8cf7'))
        result['files'][fname] = d
    for folder, fdata in node['folders'].items():
        fpath = f'{path}{folder}/'
        sub = build_js_tree(fdata, fpath)
        sub['color'] = MOD_COLORS.get(fpath.rstrip('/'), MOD_COLORS.get(path.rstrip('/'), '#4f8cf7'))
        result['folders'][folder] = sub
    return result

js_tree = build_js_tree(tree)

def count_tree(node):
    nf = len(node['files'])
    for sub in node['folders'].values():
        nf += count_tree(sub)
    return nf
nfiles = count_tree(tree)
nfuncs = sum(len(d['functions']) for d in all_modules.values())
nfolders = len(tree['folders'])
print(f"Parsed {nfiles} files, {nfuncs} functions, {nfolders} top-level folders")

html = r"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><title>MKTT Code Map</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f1117;color:#ccc;font-family:'JetBrains Mono','Consolas',monospace}
#header{background:#111;border-bottom:1px solid #333;padding:8px 16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#header h1{color:#4f8cf7;font-size:15px}
#breadcrumb{font-size:11px;color:#666}
#breadcrumb span{cursor:pointer;color:#4f8cf7}
#breadcrumb span:hover{text-decoration:underline}
.hbtn{font-size:11px;padding:3px 10px;background:#1a1a2a;border:1px solid #333;color:#888;border-radius:4px;cursor:pointer}
.hbtn:hover{background:#2a2a3a}
.hbtn.active{background:#a78bfa;color:white;border-color:#a78bfa}
#main{display:flex;gap:0}
#dw{flex:1;overflow:hidden;position:relative;min-height:calc(100vh - 44px)}
#diagram{background:#0a0a0e;border:1px solid #222;border-radius:8px;min-height:300px;position:relative;
    transform-origin:0 0;cursor:grab;margin:12px}
#diagram:active{cursor:grabbing}
.cbtn{position:absolute;z-index:10;background:#ef4444cc;color:white;border:none;border-radius:50%;
    width:20px;height:20px;font-size:12px;font-weight:700;cursor:pointer;line-height:18px;text-align:center}
.cbtn:hover{background:#ef4444;transform:scale(1.2)}
#zc{position:absolute;bottom:10px;left:10px;z-index:20;display:flex;gap:3px}
#zc button{width:28px;height:28px;font-size:14px;background:#1a1a2a;border:1px solid #333;color:#ccc;border-radius:4px;cursor:pointer}
#zc button:hover{background:#2a2a3a}
#zc span{font-size:10px;color:#666;padding:7px 3px}
#panel{width:350px;background:#111;border-left:1px solid #333;padding:12px;overflow-y:auto;
    max-height:calc(100vh - 44px);display:none;font-size:11px;flex-shrink:0}
#panel h3{color:#10b981;font-size:13px;margin-bottom:6px}
#panel .route{color:#f59e0b;font-weight:700;margin:3px 0}
#panel .doc{color:#888;font-style:italic;margin:3px 0;font-size:10px}
#panel .sec{margin:8px 0 3px;color:#666;font-size:10px;text-transform:uppercase;border-bottom:1px solid #222;padding-bottom:2px}
#panel .lnk{color:#a78bfa;cursor:pointer;padding:1px 0}
#panel .lnk:hover{text-decoration:underline}
#panel .clnk{color:#06b6d4;cursor:pointer;padding:1px 0}
#panel .clnk:hover{text-decoration:underline}
.xbtn{position:absolute;top:6px;right:8px;cursor:pointer;color:#f33;font-size:16px;font-weight:700}
</style></head><body>
<div id="header">
<h1>MKTT Code Map</h1>
<div id="breadcrumb"><span onclick="goHome()"><b>src/mktt</b></span></div>
<span id="legend" style="display:none;font-size:10px;color:#666;margin-left:6px">
<span style="color:#333">──</span> contains &nbsp;
<span style="color:#06b6d4">- -</span> calls &nbsp;
<span style="color:#f59e0b">- -</span> fetch
</span>
<button class="hbtn" onclick="goHome()" style="margin-left:auto">Collapse All</button>
</div>
<div id="main">
<div id="dw">
<div id="diagram">Loading...</div>
<div id="zc"><button onclick="zi()">+</button><button onclick="zo()">−</button><button onclick="zr()">⟲</button><span id="zl">100%</span></div>
</div>
<div id="panel" style="position:relative"></div>
</div>
<script>
var TREE=""" + json.dumps(js_tree) + r""";
var F2M=""" + json.dumps(func_to_mod) + r""";
var CALLERS=""" + json.dumps(callers) + r""";

var exp={};
var selNid=null,selMod=null,selFunc=null;
var pendingEdges=[];
var connectedNids={};  // nids that are call/fetch connected to selected
var zm=1,px=0,py=0,drag=false,dx,dy;

function at(){var e=document.getElementById('diagram');e.style.transform='scale('+zm+') translate('+px+'px,'+py+'px)';document.getElementById('zl').textContent=Math.round(zm*100)+'%';drawCallOverlays();}
function zi(){zm=Math.min(zm*1.25,5);at();}
function zo(){zm=Math.max(zm*0.8,0.2);at();}
function zr(){zm=1;px=0;py=0;at();}

document.addEventListener('DOMContentLoaded',function(){
    var w=document.getElementById('dw');
    w.addEventListener('wheel',function(e){e.preventDefault();if(e.deltaY<0)zm=Math.min(zm*1.1,5);else zm=Math.max(zm*0.9,0.2);at();},{passive:false});
    w.addEventListener('mousedown',function(e){if(e.target.closest('.node,.cbtn,#panel,#zc'))return;drag=true;dx=e.clientX-px*zm;dy=e.clientY-py*zm;});
    document.addEventListener('mousemove',function(e){if(!drag)return;px=(e.clientX-dx)/zm;py=(e.clientY-dy)/zm;at();});
    document.addEventListener('mouseup',function(){if(drag){drag=false;drawCallOverlays();}else{drag=false;}});
});

function resolveFile(mod){
    if(TREE.files[mod]) return TREE.files[mod];
    var parts=mod.split('/');var node=TREE;
    for(var i=0;i<parts.length-1;i++){if(!node.folders||!node.folders[parts[i]])return null;node=node.folders[parts[i]];}
    return (node.files||{})[parts[parts.length-1]]||null;
}
function findTargetId(mod,func){
    var parts=mod.split('/');var nid='';
    if(parts.length===1){return exp[parts[0]]?parts[0]+'__fn__'+func:parts[0];}
    for(var i=0;i<parts.length-1;i++){nid=nid?(nid+'__'+parts[i]):parts[i];if(!exp[nid])return nid;}
    var fileId=nid+'__'+parts[parts.length-1];
    return exp[fileId]?fileId+'__fn__'+func:fileId;
}
function countAll(n){var t=Object.keys(n.files||{}).length;Object.values(n.folders||{}).forEach(function(s){t+=countAll(s);});return t;}
function countFuncs(n){var t=Object.values(n.files||{}).reduce(function(s,f){return s+(f.nfuncs||0);},0);Object.values(n.folders||{}).forEach(function(s){t+=countFuncs(s);});return t;}

// Build route map once
var ROUTE_MAP={};
(function buildRouteMap(node,prefix){
    Object.keys(node.files||{}).forEach(function(fname){
        (node.files[fname].functions||[]).forEach(function(fn){
            if(fn.route) ROUTE_MAP[fn.route]={mod:(prefix?prefix+fname:fname),func:fn.name};
        });
    });
    Object.keys(node.folders||{}).forEach(function(folder){
        buildRouteMap(node.folders[folder],(prefix||'')+folder+'/');
    });
})(TREE,'');

function matchRoute(url){
    if(ROUTE_MAP[url]) return ROUTE_MAP[url];
    var base=url.replace(/\/$/,''),target=null;
    Object.keys(ROUTE_MAP).forEach(function(r){
        if(!target&&r.replace(/<[^>]+>/g,'').replace(/\/$/,'')===base) target=ROUTE_MAP[r];
    });
    return target;
}

mermaid.initialize({startOnLoad:false,theme:'dark',
    themeVariables:{darkMode:true,background:'#0a0a0e',primaryColor:'#4f8cf7',primaryTextColor:'#ccc',lineColor:'#222',secondaryColor:'#1a1a2a',tertiaryColor:'#111'},
    flowchart:{curve:'basis',padding:12,nodeSpacing:18,rankSpacing:35},securityLevel:'loose'});

function esc(s){return s.replace(/"/g,"'").replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\//g,'∕');}

function render(code){
    var el=document.getElementById('diagram');el.innerHTML='';
    mermaid.render('m'+Date.now(),code).then(function(r){
        el.innerHTML=r.svg;
        var svg=el.querySelector('svg');
        if(svg){svg.style.width='100%';svg.style.maxWidth='none';}
        el.querySelectorAll('.node').forEach(function(n){
            n.style.cursor='pointer';
            n.addEventListener('click',function(e){e.stopPropagation();
                var m=(n.id||'').match(/flowchart-(.+)-\d+$/);
                if(m)handleClick(m[1]);});
        });
        // Draw call overlays using screen coordinates on a separate HTML SVG
        setTimeout(function(){drawCallOverlays();},80);
    }).catch(function(e){el.innerHTML='<pre style="color:#f33;">'+e+'</pre>';});
}

function getNodeRect(nid){
    // Find the Mermaid node element and return its bounding rect
    var el=document.getElementById('diagram');
    var svg=el.querySelector('svg');
    if(!svg) return null;
    var found=null;
    svg.querySelectorAll('.node').forEach(function(n){
        var m=(n.id||'').match(/flowchart-(.+)-\d+$/);
        if(m&&m[1]===nid) found=n;
    });
    if(!found) return null;
    return found.getBoundingClientRect();
}

function drawCallOverlays(){
    // Remove existing overlay
    var old=document.getElementById('callOverlay');
    if(old) old.remove();
    if(!pendingEdges.length) return;

    var dw=document.getElementById('dw');
    var dwRect=dw.getBoundingClientRect();

    // Create an absolutely positioned SVG that covers the whole diagram area
    var oSvg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    oSvg.id='callOverlay';
    oSvg.style.cssText='position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:5;';
    dw.appendChild(oSvg);

    var drawn=0;
    pendingEdges.forEach(function(edge){
        var sr=getNodeRect(edge.src), tr=getNodeRect(edge.tgt);
        if(!sr||!tr) return;

        // Convert to dw-relative coords
        var sx=sr.left+sr.width/2-dwRect.left, sy=sr.top+sr.height/2-dwRect.top;
        var tx=tr.left+tr.width/2-dwRect.left, ty=tr.top+tr.height/2-dwRect.top;
        var dx=tx-sx, dy=ty-sy;

        // Pick connection edge points
        if(Math.abs(dx)>Math.abs(dy)){
            if(dx>0){sx=sr.right-dwRect.left;tx=tr.left-dwRect.left;}
            else{sx=sr.left-dwRect.left;tx=tr.right-dwRect.left;}
            sy=sr.top+sr.height/2-dwRect.top;ty=tr.top+tr.height/2-dwRect.top;
        }else{
            if(dy>0){sy=sr.bottom-dwRect.top;ty=tr.top-dwRect.top;}
            else{sy=sr.top-dwRect.top;ty=tr.bottom-dwRect.top;}
            sx=sr.left+sr.width/2-dwRect.left;tx=tr.left+tr.width/2-dwRect.left;
        }

        var col=edge.lbl==='fetch'?'#f59e0b':'#06b6d4';
        var mx=(sx+tx)/2, my=(sy+ty)/2;

        // Cubic bezier curve
        var cx1,cy1,cx2,cy2;
        if(Math.abs(dx)>Math.abs(dy)){cx1=mx;cy1=sy;cx2=mx;cy2=ty;}
        else{cx1=sx;cy1=my;cx2=tx;cy2=my;}

        // Glow behind path for contrast
        var glow=document.createElementNS('http://www.w3.org/2000/svg','path');
        glow.setAttribute('d','M'+sx+','+sy+' C'+cx1+','+cy1+' '+cx2+','+cy2+' '+tx+','+ty);
        glow.setAttribute('stroke','#000');glow.setAttribute('stroke-width','6');
        glow.setAttribute('fill','none');glow.setAttribute('opacity','0.5');
        oSvg.appendChild(glow);

        var path=document.createElementNS('http://www.w3.org/2000/svg','path');
        path.setAttribute('d','M'+sx+','+sy+' C'+cx1+','+cy1+' '+cx2+','+cy2+' '+tx+','+ty);
        path.setAttribute('stroke',col);path.setAttribute('stroke-width','3');
        path.setAttribute('fill','none');path.setAttribute('stroke-dasharray','10,5');
        oSvg.appendChild(path);

        // Arrowhead
        var angle=Math.atan2(ty-cy2,tx-cx2);
        var a1x=tx-10*Math.cos(angle-0.4), a1y=ty-10*Math.sin(angle-0.4);
        var a2x=tx-10*Math.cos(angle+0.4), a2y=ty-10*Math.sin(angle+0.4);
        var arrow=document.createElementNS('http://www.w3.org/2000/svg','polygon');
        arrow.setAttribute('points',tx+','+ty+' '+a1x+','+a1y+' '+a2x+','+a2y);
        arrow.setAttribute('fill',col);
        oSvg.appendChild(arrow);

        // Label with dark background
        var lbl=document.createElementNS('http://www.w3.org/2000/svg','text');
        lbl.setAttribute('x',mx);lbl.setAttribute('y',my-6);
        lbl.setAttribute('text-anchor','middle');lbl.setAttribute('font-size','12');
        lbl.setAttribute('fill',col);lbl.setAttribute('font-weight','bold');
        lbl.setAttribute('font-family','monospace');
        lbl.textContent=edge.lbl;
        // Measure text for background
        oSvg.appendChild(lbl);
        var bb=lbl.getBBox();
        var bg=document.createElementNS('http://www.w3.org/2000/svg','rect');
        bg.setAttribute('x',bb.x-3);bg.setAttribute('y',bb.y-1);
        bg.setAttribute('width',bb.width+6);bg.setAttribute('height',bb.height+2);
        bg.setAttribute('fill','#0a0a0e');bg.setAttribute('rx','3');
        oSvg.insertBefore(bg,lbl);
        drawn++;
    });
}

function handleClick(nid){
    if(nid.indexOf('__fn__')>-1){
        // Function node — select and show connections
        var parts=nid.split('__fn__');
        var fileKey=parts[0];
        var funcName=parts[1];
        var mod=fileKey.replace(/__/g,'/');
        selNid=nid;selMod=mod;selFunc=funcName;
        showPanel(mod,funcName);
        buildEdgesForSelection();
        rebuild();
    } else {
        // Folder or file node
        var mod=nid.replace(/__/g,'/');
        var fileData=resolveFile(mod);
        if(fileData){
            // It's a file — first click: select & show calls. Second click: expand.
            if(selNid===nid){
                // Already selected — expand it
                exp[nid]=!exp[nid];
                if(exp[nid]){selNid=null;selMod=null;selFunc=null;pendingEdges=[];connectedNids={};}
            } else {
                // Select it — show file-level calls
                selNid=nid;selMod=mod;selFunc=null;
                buildEdgesForSelection();
            }
            document.getElementById('panel').style.display='none';
        } else {
            // It's a folder — just expand/collapse
            exp[nid]=!exp[nid];
            if(!exp[nid]&&selNid&&selNid.indexOf(nid)===0){selNid=null;selMod=null;selFunc=null;pendingEdges=[];connectedNids={};}
            document.getElementById('panel').style.display='none';
        }
        rebuild();
    }
}

function buildEdgesForSelection(){
    pendingEdges=[];connectedNids={};
    if(!selNid) return;
    var fileData=resolveFile(selMod);
    if(!fileData) return;
    var fnNid=selMod.replace(/\//g,'__');

    if(selFunc){
        // FUNCTION selected: show its specific calls
        var fn=(fileData.functions||[]).find(function(f){return f.name===selFunc;});
        if(!fn) return;
        // Outgoing Python calls
        (fn.calls||[]).forEach(function(call){
            var tm=F2M[call];if(!tm||tm===selMod) return;
            var tgtId=findTargetId(tm,call);
            if(tgtId){pendingEdges.push({src:fnNid+'__fn__'+selFunc,tgt:tgtId,lbl:'calls'});connectedNids[tgtId]='calls';}
        });
        // Incoming Python callers
        (CALLERS[selFunc]||[]).forEach(function(c){
            var srcId=findTargetId(c.module,c.func);
            if(srcId){pendingEdges.push({src:srcId,tgt:fnNid+'__fn__'+selFunc,lbl:'calls'});connectedNids[srcId]='calls';}
        });
        // Outgoing fetches from file (if JS/HTML)
        (fileData.fetches||[]).forEach(function(url){
            var target=matchRoute(url);if(!target) return;
            var tgtId=findTargetId(target.mod,target.func);
            if(tgtId){pendingEdges.push({src:fnNid+'__fn__'+selFunc,tgt:tgtId,lbl:'fetch'});connectedNids[tgtId]='fetch';}
        });
        // Incoming: who fetches this route
        if(fn.route){
            (function walkFC(node,prefix){
                Object.keys(node.files||{}).forEach(function(fname){
                    var f=node.files[fname];var fmod=prefix?prefix+fname:fname;
                    (f.fetches||[]).forEach(function(url){
                        var base=url.replace(/\/$/,'');
                        var rb=fn.route.replace(/<[^>]+>/g,'').replace(/\/$/,'');
                        if(url===fn.route||base===rb){
                            var srcId=findTargetId(fmod,fname);
                            if(srcId){pendingEdges.push({src:srcId,tgt:fnNid+'__fn__'+selFunc,lbl:'fetch'});connectedNids[srcId]='fetch';}
                        }
                    });
                });
                Object.keys(node.folders||{}).forEach(function(folder){walkFC(node.folders[folder],(prefix||'')+folder+'/');});
            })(TREE,'');
        }
    } else {
        // FILE selected (not expanded): show aggregate calls from all its functions
        (fileData.functions||[]).forEach(function(fn){
            (fn.calls||[]).forEach(function(call){
                var tm=F2M[call];if(!tm||tm===selMod) return;
                var tgtId=findTargetId(tm,call);
                if(tgtId){pendingEdges.push({src:fnNid,tgt:tgtId,lbl:'calls'});connectedNids[tgtId]='calls';}
            });
            // Incoming callers
            (CALLERS[fn.name]||[]).forEach(function(c){
                var srcId=findTargetId(c.module,c.func);
                if(srcId&&srcId!==fnNid){pendingEdges.push({src:srcId,tgt:fnNid,lbl:'calls'});connectedNids[srcId]='calls';}
            });
        });
        // Fetches
        (fileData.fetches||[]).forEach(function(url){
            var target=matchRoute(url);if(!target) return;
            var tgtId=findTargetId(target.mod,target.func);
            if(tgtId){pendingEdges.push({src:fnNid,tgt:tgtId,lbl:'fetch'});connectedNids[tgtId]='fetch';}
        });
        // Incoming fetches to any route in this file
        (fileData.functions||[]).forEach(function(fn){
            if(!fn.route) return;
            (function walkFC(node,prefix){
                Object.keys(node.files||{}).forEach(function(fname){
                    var f=node.files[fname];var fmod=prefix?prefix+fname:fname;
                    (f.fetches||[]).forEach(function(url){
                        var base=url.replace(/\/$/,'');
                        var rb=fn.route.replace(/<[^>]+>/g,'').replace(/\/$/,'');
                        if(url===fn.route||base===rb){
                            var srcId=findTargetId(fmod,fname);
                            if(srcId&&srcId!==fnNid){pendingEdges.push({src:srcId,tgt:fnNid,lbl:'fetch'});connectedNids[srcId]='fetch';}
                        }
                    });
                });
                Object.keys(node.folders||{}).forEach(function(folder){walkFC(node.folders[folder],(prefix||'')+folder+'/');});
            })(TREE,'');
        });
    }
    // Deduplicate
    var seen={},unique=[];
    pendingEdges.forEach(function(e){var k=e.src+'>>'+e.tgt;if(!seen[k]){seen[k]=true;unique.push(e);}});
    pendingEdges=unique;
    document.getElementById('legend').style.display=pendingEdges.length?'inline':'none';
}

function goHome(){exp={};selNid=null;selMod=null;selFunc=null;pendingEdges=[];connectedNids={};
    document.getElementById('legend').style.display='none';
    document.getElementById('panel').style.display='none';
    document.getElementById('breadcrumb').innerHTML='<span onclick="goHome()"><b>src/mktt</b></span> — click to explore';
    rebuild();}

function rebuild(){
    var lines=['graph TD'];

    function renderFolder(node, parentId, prefix, depth){
        Object.keys(node.folders||{}).forEach(function(folder){
            var fd=node.folders[folder];
            var foid=prefix?prefix+'__'+folder:folder;
            var c=fd.color;
            if(exp[foid]){
                lines.push('    '+foid+'["'+esc('📁 '+folder+'/')+'"]');
                if(parentId) lines.push('    '+parentId+' ~~~ '+foid);
                lines.push('    style '+foid+' fill:'+c+'33,stroke:'+c+',color:'+c);
                renderFolder(fd, foid, foid, depth+1);
            } else {
                var nf=countAll(fd), nfn=countFuncs(fd);
                var nsub=Object.keys(fd.folders||{}).length;
                var lbl='📁 '+folder+'/\\n';
                if(nsub) lbl+=nsub+' dirs | ';
                lbl+=nf+' files | '+nfn+' funcs';
                lines.push('    '+foid+'["'+esc(lbl)+'"]');
                if(parentId) lines.push('    '+parentId+' ~~~ '+foid);
                lines.push('    style '+foid+' fill:'+c+'22,stroke:'+c+',color:'+c);
            }
        });
        Object.keys(node.files||{}).forEach(function(fname){
            var file=node.files[fname];
            var fileid=prefix?prefix+'__'+fname:fname;
            var c=file.color||(node.color||'#4f8cf7');
            if(exp[fileid]){
                lines.push('    '+fileid+'["'+esc('📄 '+fname)+'"]');
                if(parentId) lines.push('    '+parentId+' ~~~ '+fileid);
                lines.push('    style '+fileid+' fill:'+c+'33,stroke:'+c+',color:'+c);
                (file.functions||[]).forEach(function(fn){
                    var fnid=fileid+'__fn__'+fn.name;
                    var fnlbl=fn.name+'()';
                    if(fn.route) fnlbl=fn.route+'\\n'+fn.name+'()';
                    lines.push('    '+fnid+'["'+esc(fnlbl)+'"]');
                    lines.push('    '+fileid+' ~~~ '+fnid);
                    if(fn.route) lines.push('    style '+fnid+' fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b');
                    else lines.push('    style '+fnid+' fill:'+c+'11,stroke:'+c+'88,color:'+c);
                });
            } else {
                var flbl=fname+' ('+(file.nfuncs||0)+')';
                lines.push('    '+fileid+'["'+esc(flbl)+'"]');
                if(parentId) lines.push('    '+parentId+' ~~~ '+fileid);
                lines.push('    style '+fileid+' fill:'+c+'11,stroke:'+c+'88,color:'+c);
            }
        });
    }
    renderFolder(TREE, null, '', 0);

    // Highlights via Mermaid style (selected node = white border, connected = colored border)
    if(selNid){
        lines.push('    style '+selNid+' stroke:#fff,stroke-width:3px');
        Object.keys(connectedNids).forEach(function(nid){
            var col=connectedNids[nid]==='fetch'?'#f59e0b':'#06b6d4';
            lines.push('    style '+nid+' stroke:'+col+',stroke-width:2.5px');
        });
    }

    // Breadcrumb
    var opened=Object.keys(exp).filter(function(k){return exp[k];});
    var bc='<span onclick="goHome()">src/mktt</span>';
    if(opened.length) bc+=' → '+opened.slice(0,5).map(function(k){return '<b>'+k.replace(/__/g,'/')+'</b>';}).join(', ');
    if(opened.length>5) bc+=' +'+(opened.length-5)+' more';
    if(selFunc) bc+=' &nbsp;<span style="color:#06b6d4">⚡ '+selFunc+'()</span>';
    document.getElementById('breadcrumb').innerHTML=bc;

    render(lines.join('\n'));
}

function showPanel(mod,funcName){
    var fileData=resolveFile(mod);if(!fileData)return;
    var f=fileData.functions.find(function(x){return x.name===funcName;});if(!f)return;
    var p=document.getElementById('panel');p.style.display='block';
    var h='<span class="xbtn" onclick="document.getElementById(\'panel\').style.display=\'none\'">✕</span>';
    h+='<h3>'+funcName+'('+f.args.join(', ')+')</h3>';
    if(f.route) h+='<div class="route">'+f.route+'</div>';
    h+='<div style="color:#666;">'+mod+' | L'+f.line+' | '+f.lines+' lines</div>';
    if(f.doc) h+='<div class="doc">'+esc(f.doc)+'</div>';
    h+='<div class="sec">Calls →</div>';
    f.calls.forEach(function(c){var tm=F2M[c];
        if(tm) h+='<div class="lnk" onclick="navTo(\''+tm+'\',\''+c+'\')">'+c+'() <span style="color:#555;">← '+tm+'</span></div>';
        else h+='<div style="color:#555;">'+c+'()</div>';});
    if(!f.calls.length) h+='<div style="color:#555;">None</div>';
    var cl=CALLERS[funcName]||[];
    h+='<div class="sec">← Called by</div>';
    cl.forEach(function(c){h+='<div class="clnk" onclick="navTo(\''+c.module+'\',\''+c.func+'\')">'+c.func+'() <span style="color:#555;">← '+c.module+'</span></div>';});
    if(!cl.length) h+='<div style="color:#555;">No callers found</div>';
    // Fetches section
    if(fileData.fetches&&fileData.fetches.length){
        h+='<div class="sec">HTTP Fetches →</div>';
        fileData.fetches.forEach(function(url){
            var t=matchRoute(url);
            if(t) h+='<div class="lnk" onclick="navTo(\''+t.mod+'\',\''+t.func+'\')" style="color:#f59e0b;">'+url+' <span style="color:#555;">→ '+t.func+'()</span></div>';
            else h+='<div style="color:#555;">'+url+'</div>';
        });
    }
    p.innerHTML=h;
}

function navTo(mod,func){
    var parts=mod.split('/');
    if(parts.length===1){exp[parts[0]]=true;}
    else{var nid='';for(var i=0;i<parts.length;i++){nid=nid?(nid+'__'+parts[i]):parts[i];exp[nid]=true;}}
    selMod=mod;selFunc=func;selNid=mod.replace(/\//g,'__')+'__fn__'+func;
    buildEdgesForSelection();
    rebuild();
    setTimeout(function(){showPanel(mod,func);},200);
}

goHome();
</script></body></html>"""

out_path = OUT / 'mktt_expandable_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Saved: {out_path} ({out_path.stat().st_size // 1024} KB)")
