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

# Parse into a tree structure
tree = {'files': {}, 'folders': {}}

# Python files
for pyfile in sorted(SRC_DIR.rglob('*.py')):
    if '__pycache__' in str(pyfile): continue
    rel = pyfile.relative_to(SRC_DIR)
    parts = list(rel.parts)
    parsed = parse_module(pyfile)
    if not parsed or (not parsed['functions'] and not parsed['imports']): continue

    fname = parts[-1].replace('.py', '')
    if len(parts) == 1:
        tree['files'][fname] = parsed
    else:
        folder = parts[0]
        if folder not in tree['folders']:
            tree['folders'][folder] = {'files': {}}
        tree['folders'][folder]['files'][fname] = parsed

# JS files
for jsfile in sorted(SRC_DIR.rglob('*.js')):
    rel = jsfile.relative_to(SRC_DIR)
    parts = list(rel.parts)
    parsed = parse_js(jsfile)
    if not parsed: continue
    folder = '/'.join(parts[:-1]) if len(parts) > 1 else None
    fname = parts[-1].replace('.js', '')
    if folder:
        if folder not in tree['folders']:
            tree['folders'][folder] = {'files': {}}
        tree['folders'][folder]['files'][fname] = parsed
    else:
        tree['files'][fname] = parsed

# HTML templates
for htmlfile in sorted(SRC_DIR.rglob('*.html')):
    rel = htmlfile.relative_to(SRC_DIR)
    parts = list(rel.parts)
    parsed = parse_html(htmlfile)
    if not parsed: continue
    folder = '/'.join(parts[:-1]) if len(parts) > 1 else None
    fname = parts[-1].replace('.html', '')
    if folder:
        if folder not in tree['folders']:
            tree['folders'][folder] = {'files': {}}
        tree['folders'][folder]['files'][fname] = parsed
    else:
        tree['files'][fname] = parsed

# CSS files
for cssfile in sorted(SRC_DIR.rglob('*.css')):
    rel = cssfile.relative_to(SRC_DIR)
    parts = list(rel.parts)
    parsed = parse_css(cssfile)
    if not parsed: continue
    folder = '/'.join(parts[:-1]) if len(parts) > 1 else None
    fname = parts[-1].replace('.css', '')
    if folder:
        if folder not in tree['folders']:
            tree['folders'][folder] = {'files': {}}
        tree['folders'][folder]['files'][fname] = parsed
    else:
        tree['files'][fname] = parsed

# Flatten for lookups
all_modules = {}
for fname, data in tree['files'].items():
    all_modules[fname] = data
for folder, fdata in tree['folders'].items():
    for fname, data in fdata['files'].items():
        all_modules[f'{folder}/{fname}'] = data

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

js_tree = {'files': {}, 'folders': {}}
for fname, data in tree['files'].items():
    d = build_file_js(data)
    d['color'] = MOD_COLORS.get(fname, '#4f8cf7')
    js_tree['files'][fname] = d
for folder, fdata in tree['folders'].items():
    js_tree['folders'][folder] = {'color': MOD_COLORS.get(folder, '#4f8cf7'), 'files': {}}
    for fname, data in fdata['files'].items():
        js_tree['folders'][folder]['files'][fname] = build_file_js(data, folder)

nfiles = len(tree['files']) + sum(len(f['files']) for f in tree['folders'].values())
nfuncs = sum(len(d['functions']) for d in all_modules.values())
print(f"Parsed {nfiles} files, {nfuncs} functions, {len(tree['folders'])} folders")

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
<button id="callsBtn" class="hbtn" onclick="toggleCalls()">Show Calls</button>
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

var exp={};  // key -> true (folders, files, functions expanded)
var showCalls=false;
var zm=1,px=0,py=0,drag=false,dx,dy;

function at(){var e=document.getElementById('diagram');e.style.transform='scale('+zm+') translate('+px+'px,'+py+'px)';document.getElementById('zl').textContent=Math.round(zm*100)+'%';}
function zi(){zm=Math.min(zm*1.25,5);at();}
function zo(){zm=Math.max(zm*0.8,0.2);at();}
function zr(){zm=1;px=0;py=0;at();}

document.addEventListener('DOMContentLoaded',function(){
    var w=document.getElementById('dw');
    w.addEventListener('wheel',function(e){e.preventDefault();if(e.deltaY<0)zm=Math.min(zm*1.1,5);else zm=Math.max(zm*0.9,0.2);at();},{passive:false});
    w.addEventListener('mousedown',function(e){if(e.target.closest('.node,.cbtn,#panel,#zc'))return;drag=true;dx=e.clientX-px*zm;dy=e.clientY-py*zm;});
    document.addEventListener('mousemove',function(e){if(!drag)return;px=(e.clientX-dx)/zm;py=(e.clientY-dy)/zm;at();});
    document.addEventListener('mouseup',function(){drag=false;});
});

function toggleCalls(){showCalls=!showCalls;var b=document.getElementById('callsBtn');b.classList.toggle('active',showCalls);b.textContent=showCalls?'Hide Calls':'Show Calls';rebuild();}

mermaid.initialize({startOnLoad:false,theme:'dark',
    themeVariables:{darkMode:true,background:'#0a0a0e',primaryColor:'#4f8cf7',primaryTextColor:'#ccc',lineColor:'#444',secondaryColor:'#1a1a2a',tertiaryColor:'#111'},
    flowchart:{curve:'basis',padding:12,nodeSpacing:18,rankSpacing:35},securityLevel:'loose'});

function esc(s){return s.replace(/"/g,"'").replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\//g,'∕');}

function render(code){
    var el=document.getElementById('diagram');el.innerHTML='';
    mermaid.render('m'+Date.now(),code).then(function(r){
        el.innerHTML=r.svg;
        var svg=el.querySelector('svg');if(svg){svg.style.width='100%';svg.style.maxWidth='none';}
        el.querySelectorAll('.node').forEach(function(n){
            n.style.cursor='pointer';
            n.addEventListener('click',function(e){e.stopPropagation();
                var m=(n.id||'').match(/flowchart-(.+?)-\d+$/);
                if(m)handleClick(m[1]);});
        });
        addCloseButtons(el,svg);
    }).catch(function(e){el.innerHTML='<pre style="color:#f33;">'+e+'</pre>';});
}

function addCloseButtons(container,svg){
    container.querySelectorAll('.cbtn').forEach(function(b){b.remove();});
    if(!svg)return;
    var cr=container.getBoundingClientRect();
    Object.keys(exp).forEach(function(k){
        if(!exp[k])return;
        var nodeEl=null;
        svg.querySelectorAll('.node').forEach(function(n){
            var m=(n.id||'').match(/flowchart-(.+?)-\d+$/);
            if(m&&m[1]===k)nodeEl=n;
        });
        if(!nodeEl)return;
        var nr=nodeEl.getBoundingClientRect();
        var btn=document.createElement('button');btn.className='cbtn';btn.textContent='✕';
        btn.title='Collapse '+k;
        btn.style.left=(nr.right-cr.left-2)+'px';btn.style.top=(nr.top-cr.top-2)+'px';
        btn.addEventListener('click',function(e){e.stopPropagation();
            // Collapse this and all children
            Object.keys(exp).forEach(function(ek){if(ek===k||ek.indexOf(k+'_')===0||ek.indexOf(k+'__')===0)exp[ek]=false;});
            document.getElementById('panel').style.display='none';rebuild();});
        container.appendChild(btn);
    });
}

function handleClick(nid){
    if(nid.indexOf('__fn__')>-1){
        // Function node
        var parts=nid.split('__fn__');
        var fileKey=parts[0];
        var funcName=parts[1];
        var mod=fileKey.replace(/__/g,'/');
        showPanel(mod,funcName);
    } else {
        // Folder or file: toggle
        exp[nid]=!exp[nid];
        document.getElementById('panel').style.display='none';
        rebuild();
    }
}

function goHome(){exp={};showCalls=false;
    document.getElementById('callsBtn').classList.remove('active');
    document.getElementById('callsBtn').textContent='Show Calls';
    document.getElementById('panel').style.display='none';
    document.getElementById('breadcrumb').innerHTML='<span onclick="goHome()"><b>src/mktt</b></span> — click to explore';
    rebuild();}

function rebuild(){
    var lines=['graph TD'];

    // Top-level files
    Object.keys(TREE.files).forEach(function(fname){
        var f=TREE.files[fname];
        var fid=fname;
        var c=f.color;
        if(exp[fid]){
            // File expanded: show functions below
            var lbl='📄 '+fname+'.py';
            lines.push('    '+fid+'["'+esc(lbl)+'"]');
            lines.push('    style '+fid+' fill:'+c+'33,stroke:'+c+',color:'+c);
            f.functions.forEach(function(fn){
                var fnid=fid+'__fn__'+fn.name;
                var flbl=fn.name+'()';
                if(fn.route) flbl=fn.route+'\\n'+fn.name+'()';
                lines.push('    '+fnid+'["'+esc(flbl)+'"]');
                lines.push('    '+fid+' --> '+fnid);
                if(fn.route) lines.push('    style '+fnid+' fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b');
                else lines.push('    style '+fnid+' fill:'+c+'11,stroke:'+c+'88,color:'+c);
            });
            // Internal calls
            var fnames=f.functions.map(function(x){return x.name;});
            f.functions.forEach(function(fn){fn.calls.forEach(function(call){
                if(fnames.indexOf(call)>-1&&call!==fn.name)
                    lines.push('    '+fid+'__fn__'+fn.name+' --> '+fid+'__fn__'+call);
            });});
        } else {
            var lbl=fname+'.py\\n'+f.nfuncs+' funcs';
            if(f.nroutes) lbl+=' | '+f.nroutes+' routes';
            lines.push('    '+fid+'["'+esc(lbl)+'"]');
            lines.push('    style '+fid+' fill:'+c+'22,stroke:'+c+',color:'+c);
        }
    });

    // Folders
    Object.keys(TREE.folders).forEach(function(folder){
        var fd=TREE.folders[folder];
        var foid=folder;
        var c=fd.color;
        if(exp[foid]){
            // Folder expanded: show files inside
            var nf=Object.keys(fd.files).length;
            var lbl='📁 '+folder+'/';
            lines.push('    '+foid+'["'+esc(lbl)+'"]');
            lines.push('    style '+foid+' fill:'+c+'33,stroke:'+c+',color:'+c);

            Object.keys(fd.files).forEach(function(fname){
                var file=fd.files[fname];
                var fileid=foid+'__'+fname;
                if(exp[fileid]){
                    // File inside folder expanded
                    var flbl='📄 '+fname+'.py';
                    lines.push('    '+fileid+'["'+esc(flbl)+'"]');
                    lines.push('    '+foid+' --> '+fileid);
                    lines.push('    style '+fileid+' fill:'+c+'33,stroke:'+c+',color:'+c);
                    file.functions.forEach(function(fn){
                        var fnid=fileid+'__fn__'+fn.name;
                        var fnlbl=fn.name+'()';
                        if(fn.route) fnlbl=fn.route+'\\n'+fn.name+'()';
                        lines.push('    '+fnid+'["'+esc(fnlbl)+'"]');
                        lines.push('    '+fileid+' --> '+fnid);
                        if(fn.route) lines.push('    style '+fnid+' fill:#f59e0b22,stroke:#f59e0b,color:#f59e0b');
                        else lines.push('    style '+fnid+' fill:'+c+'11,stroke:'+c+'88,color:'+c);
                    });
                    var fns=file.functions.map(function(x){return x.name;});
                    file.functions.forEach(function(fn){fn.calls.forEach(function(call){
                        if(fns.indexOf(call)>-1&&call!==fn.name)
                            lines.push('    '+fileid+'__fn__'+fn.name+' --> '+fileid+'__fn__'+call);
                    });});
                } else {
                    var flbl=fname+'.py ('+file.nfuncs+')';
                    lines.push('    '+fileid+'["'+esc(flbl)+'"]');
                    lines.push('    '+foid+' --> '+fileid);
                    lines.push('    style '+fileid+' fill:'+c+'11,stroke:'+c+'88,color:'+c);
                }
            });
        } else {
            var total=Object.values(fd.files).reduce(function(s,f){return s+f.nfuncs;},0);
            var lbl='📁 '+folder+'/\\n'+Object.keys(fd.files).length+' files | '+total+' funcs';
            lines.push('    '+foid+'["'+esc(lbl)+'"]');
            lines.push('    style '+foid+' fill:'+c+'22,stroke:'+c+',color:'+c);
        }
    });

    // Cross-module call arrows (only when Show Calls)
    if(showCalls){
        Object.keys(exp).forEach(function(k){
            if(!exp[k]||k.indexOf('__fn__')>-1) return;
            // Find the file data
            var mod,fileData;
            if(TREE.files[k]){mod=k;fileData=TREE.files[k];}
            else{
                var parts=k.split('__');
                if(parts.length===2&&TREE.folders[parts[0]]&&TREE.folders[parts[0]].files[parts[1]]){
                    mod=parts[0]+'/'+parts[1];fileData=TREE.folders[parts[0]].files[parts[1]];
                }
            }
            if(!fileData) return;
            fileData.functions.forEach(function(fn){
                fn.calls.forEach(function(call){
                    var tm=F2M[call];
                    if(!tm||tm===mod) return;
                    var srcId=k+'__fn__'+fn.name;
                    // Find target node ID
                    var tgtId;
                    if(TREE.files[tm]){
                        tgtId=exp[tm]?tm+'__fn__'+call:tm;
                    } else {
                        var tp=tm.split('/');
                        if(tp.length===2){
                            var folderId=tp[0];
                            var fileId=folderId+'__'+tp[1];
                            if(exp[fileId]) tgtId=fileId+'__fn__'+call;
                            else if(exp[folderId]) tgtId=fileId;
                            else tgtId=folderId;
                        }
                    }
                    if(tgtId) lines.push('    '+srcId+' ==> '+tgtId);
                });
            });
        });
    }

    // Breadcrumb
    var opened=Object.keys(exp).filter(function(k){return exp[k];});
    var bc='<span onclick="goHome()">src/mktt</span>';
    if(opened.length) bc+=' → '+opened.slice(0,5).map(function(k){return '<b>'+k.replace(/__/g,'/')+'</b>';}).join(', ');
    if(opened.length>5) bc+=' +' +(opened.length-5)+' more';
    document.getElementById('breadcrumb').innerHTML=bc;

    render(lines.join('\n'));
}

function showPanel(mod,funcName){
    var fileData;
    if(TREE.files[mod]) fileData=TREE.files[mod];
    else{var p=mod.split('/');if(p.length===2&&TREE.folders[p[0]])fileData=TREE.folders[p[0]].files[p[1]];}
    if(!fileData)return;
    var f=fileData.functions.find(function(x){return x.name===funcName;});
    if(!f)return;
    var p=document.getElementById('panel');p.style.display='block';
    var h='<span class="xbtn" onclick="document.getElementById(\'panel\').style.display=\'none\'">✕</span>';
    h+='<h3>'+funcName+'('+f.args.join(', ')+')</h3>';
    if(f.route) h+='<div class="route">'+f.route+'</div>';
    h+='<div style="color:#666;">'+mod+'.py | L'+f.line+' | '+f.lines+' lines</div>';
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
    p.innerHTML=h;
}

function navTo(mod,func){
    // Expand the path to this module
    if(TREE.files[mod]){exp[mod]=true;}
    else{var p=mod.split('/');if(p.length===2){exp[p[0]]=true;exp[p[0]+'__'+p[1]]=true;}}
    rebuild();
    setTimeout(function(){showPanel(mod,func);},200);
}

goHome();
</script></body></html>"""

out_path = OUT / 'mktt_expandable_map.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Saved: {out_path} ({out_path.stat().st_size // 1024} KB)")
