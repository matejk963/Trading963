/* MKTT Macro Section — Sub-tab switching + AJAX chart loading */

var PLOTLY_LAYOUT = {
    paper_bgcolor: '#0f1117',
    plot_bgcolor: '#0f1117',
    font: {color: '#e2e8f0', family: 'Inter, sans-serif', size: 12},
    margin: {l: 60, r: 40, t: 30, b: 40},
    xaxis: {gridcolor: '#1e293b', showgrid: true, zeroline: false, linecolor: '#1e293b'},
    yaxis: {gridcolor: '#1e293b', showgrid: true, zeroline: false, linecolor: '#1e293b'},
    showlegend: true,
    legend: {font: {size: 11}, bgcolor: 'rgba(15,17,23,0.8)'},
    hovermode: 'x unified',
    dragmode: 'pan',
};

var PLOTLY_CONFIG = {
    displayModeBar: true, displaylogo: false,
    modeBarButtonsToRemove: ['select2d', 'lasso2d'],
    scrollZoom: true,
};

var loadedViews = {};

var LIQUIDITY_VIEWS = ['liquidity','layer','overlay','transmission'];

function switchMacroSection(section) {
    // Update level-1 tabs
    document.querySelectorAll('.sub-tab-bar .sub-tab').forEach(function(t) { t.classList.remove('active'); });
    document.querySelector('.sub-tab[data-section="'+section+'"]').classList.add('active');

    // Show/hide level-2 sub-tabs
    var subTabs = document.getElementById('liquidity-sub-tabs');
    if (section === 'liquidity') {
        subTabs.style.display = 'flex';
        // Activate the first liquidity sub-view if none active
        var activeStab = subTabs.querySelector('.stab.active');
        var view = activeStab ? activeStab.dataset.view : 'liquidity';
        switchMacroView(view);
    } else {
        subTabs.style.display = 'none';
        switchMacroView('rrg');
    }
}

function switchMacroView(view) {
    // Update level-2 sub-tab active state (liquidity sub-tabs)
    document.querySelectorAll('.macro-sub-tabs .stab').forEach(function(t) { t.classList.remove('active'); });
    var stab = document.querySelector('.stab[data-view="'+view+'"]');
    if (stab) stab.classList.add('active');

    // Show/hide panels
    document.querySelectorAll('.macro-panel').forEach(function(p) { p.classList.remove('active'); });
    document.getElementById('macro-' + view).classList.add('active');

    // Update URL
    history.replaceState(null, '', '/macro?view=' + view);

    // Load data
    loadMacroView(view);
}

function loadMacroView(view) {
    if (loadedViews[view]) return;
    if (view === 'liquidity') loadLiquidity();
    else if (view === 'layer') loadLayerDetail();
    else if (view === 'overlay') loadOverlay();
    else if (view === 'transmission') loadTransmission();
    else if (view === 'rrg') loadRRG();
}

// =========================================================
// LIQUIDITY DASHBOARD
// =========================================================
function loadLiquidity() {
    fetch('/macro/api/liquidity').then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) { document.getElementById('liquidity-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+data.error+'</div>'; return; }

        // Update regime badge
        var badge = document.getElementById('regime-badge');
        badge.textContent = data.regime_label || 'Unknown';
        badge.className = 'regime-badge ' + (data.bias || 'neutral');

        // Update score cards
        function setScore(id, val) {
            var el = document.getElementById(id);
            if (val != null) {
                el.textContent = (val > 0 ? '+' : '') + val.toFixed(2);
                el.className = 'value ' + (val > 0 ? 'pos' : 'neg');
            }
        }
        setScore('l1-score', data.l1);
        setScore('l2a-score', data.l2a);
        setScore('l2b-score', data.l2b);
        setScore('composite-score', data.composite);

        // Render chart
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            Plotly.newPlot('liquidity-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        loadedViews['liquidity'] = true;
    }).catch(function(e) {
        document.getElementById('liquidity-chart').innerHTML = '<div style="color:#ff3333;padding:20px">Error loading liquidity data: '+e.message+'</div>';
    });
}

// =========================================================
// LAYER DETAIL
// =========================================================
function loadLayerDetail() {
    var layer = document.getElementById('layer-select').value;
    fetch('/macro/api/layer/' + layer).then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) { document.getElementById('layer-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+data.error+'</div>'; return; }
        // Indicator table
        if (data.indicators_html) document.getElementById('layer-indicators').innerHTML = data.indicators_html;
        // Chart
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            Plotly.newPlot('layer-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        loadedViews['layer'] = true;
    }).catch(function(e) {
        document.getElementById('layer-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+e.message+'</div>';
    });
}

// =========================================================
// ASSET OVERLAY
// =========================================================
function loadOverlay() {
    var asset = document.getElementById('overlay-asset').value;
    fetch('/macro/api/overlay?asset=' + asset).then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) { document.getElementById('overlay-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+data.error+'</div>'; return; }
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            Plotly.newPlot('overlay-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        loadedViews['overlay'] = false; // Allow re-fetch on asset change
    }).catch(function(e) {
        document.getElementById('overlay-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+e.message+'</div>';
    });
}

// =========================================================
// TRANSMISSION CHAIN
// =========================================================
function loadTransmission() {
    fetch('/macro/api/transmission').then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) { document.getElementById('transmission-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+data.error+'</div>'; return; }
        // Flow diagram
        if (data.flow_html) document.getElementById('transmission-flow').innerHTML = data.flow_html;
        // Chart
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            Plotly.newPlot('transmission-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        loadedViews['transmission'] = true;
    }).catch(function(e) {
        document.getElementById('transmission-chart').innerHTML = '<div style="color:#ff3333;padding:20px">'+e.message+'</div>';
    });
}

// =========================================================
// SECTOR RRG
// =========================================================
var rrg_full_data = null;
var rrg_all_dates = null;
var rrg_visible = {};  // key -> true/false
function onRRGDatasetChange() {
    var dataset = document.getElementById('rrg-dataset').value;
    var drillControls = document.getElementById('rrg-drill-controls');
    if (dataset === 'futures') {
        drillControls.style.display = 'inline';
        document.getElementById('rrg-drill-group').value = '';
    } else {
        drillControls.style.display = 'none';
    }
    loadRRG();
}

function loadRRG() {
    var dataset = document.getElementById('rrg-dataset').value;
    var period = document.getElementById('rrg-period').value;
    var wnd = document.getElementById('rrg-window').value;
    var trail = document.getElementById('rrg-trail').value;
    var url = '/macro/api/rrg?dataset='+dataset+'&period='+period+'&window='+wnd+'&trail='+trail;

    document.getElementById('rrg-loading').style.display = 'inline';
    document.getElementById('rrg-chart').innerHTML = '';
    document.getElementById('rrg-table').innerHTML = '';

    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
        document.getElementById('rrg-loading').style.display = 'none';
        if (data.error) { document.getElementById('rrg-chart').innerHTML = '<div style="color:var(--red);padding:20px">'+data.error+'</div>'; return; }
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            layout.dragmode = 'pan';
            Plotly.newPlot('rrg-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        if (data.table_html) document.getElementById('rrg-table').innerHTML = data.table_html;
        // Store full data for date slider replay
        if (data.full_data && data.all_dates) {
            rrg_full_data = data.full_data;
            rrg_all_dates = data.all_dates;
            initRRGSliderAndChecks();
        }
    }).catch(function(e) {
        document.getElementById('rrg-loading').style.display = 'none';
        document.getElementById('rrg-chart').innerHTML = '<div style="color:var(--red);padding:20px">'+e.message+'</div>';
    });
}

function loadRRGDrill() {
    var group = document.getElementById('rrg-drill-group').value;
    if (!group) { loadRRG(); return; }

    var period = document.getElementById('rrg-period').value;
    var wnd = document.getElementById('rrg-window').value;
    var trail = document.getElementById('rrg-trail').value;
    var url = '/macro/api/rrg/drill?group='+group+'&period='+period+'&window='+wnd+'&trail='+trail;

    document.getElementById('rrg-loading').style.display = 'inline';
    document.getElementById('rrg-chart').innerHTML = '';
    document.getElementById('rrg-table').innerHTML = '';

    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
        document.getElementById('rrg-loading').style.display = 'none';
        if (data.error) { document.getElementById('rrg-chart').innerHTML = '<div style="color:var(--red);padding:20px">'+data.error+'</div>'; return; }
        if (data.traces && data.layout) {
            var layout = Object.assign({}, PLOTLY_LAYOUT, data.layout);
            layout.dragmode = 'pan';
            Plotly.newPlot('rrg-chart', data.traces, layout, PLOTLY_CONFIG);
        }
        if (data.table_html) document.getElementById('rrg-table').innerHTML = data.table_html;
        if (data.full_data && data.all_dates) {
            rrg_full_data = data.full_data;
            rrg_all_dates = data.all_dates;
            initRRGSliderAndChecks();
        }
    }).catch(function(e) {
        document.getElementById('rrg-loading').style.display = 'none';
        document.getElementById('rrg-chart').innerHTML = '<div style="color:var(--red);padding:20px">'+e.message+'</div>';
    });
}

function onRRGDateSlider() {
    if (!rrg_full_data || !rrg_all_dates) return;
    var idx = parseInt(document.getElementById('rrg-date-slider').value);
    var asOfDate = rrg_all_dates[idx];
    var trail = parseInt(document.getElementById('rrg-trail').value);

    document.getElementById('rrg-date-label').textContent = asOfDate;

    var traces = [];
    var all_x = [], all_y = [];
    var tableRows = '';
    var qColors = {Leading:'#10b981', Weakening:'#f59e0b', Lagging:'#ef4444', Improving:'#4f8cf7'};

    for (var key in rrg_full_data) {
        if (rrg_visible[key] === false) continue;
        var fd = rrg_full_data[key];
        var endIdx = -1;
        for (var i = 0; i < fd.dates.length; i++) {
            if (fd.dates[i] <= asOfDate) endIdx = i;
        }
        if (endIdx < 0) continue;

        var startIdx = Math.max(0, endIdx - trail + 1);
        var trailRatio = fd.rs_ratio.slice(startIdx, endIdx + 1);
        var trailMom = fd.rs_momentum.slice(startIdx, endIdx + 1);

        all_x = all_x.concat(trailRatio);
        all_y = all_y.concat(trailMom);

        var latestR = trailRatio[trailRatio.length - 1];
        var latestM = trailMom[trailMom.length - 1];
        var quadrant = (latestR >= 100 && latestM >= 100) ? 'Leading' :
                       (latestR >= 100 && latestM < 100) ? 'Weakening' :
                       (latestR < 100 && latestM < 100) ? 'Lagging' : 'Improving';

        if (trailRatio.length > 1) {
            traces.push({type:'scatter',mode:'lines',x:trailRatio,y:trailMom,line:{color:fd.color,width:1.5},opacity:0.4,showlegend:false,hoverinfo:'skip',legendgroup:key});
        }
        traces.push({
            type:'scatter',mode:'markers+text',x:[latestR],y:[latestM],
            marker:{size:14,color:fd.color,line:{width:2,color:'white'}},
            text:[fd.name],textposition:'top center',textfont:{size:11,color:fd.color},
            name:fd.name+' ('+quadrant+')',legendgroup:key,
            hovertemplate:'<b>'+fd.name+'</b><br>'+quadrant+'<br>RS-Ratio: %{x:.2f}<br>RS-Mom: %{y:.2f}<extra></extra>'
        });

        tableRows += '<tr data-ratio="'+latestR.toFixed(4)+'" data-mom="'+latestM.toFixed(4)+'" data-quad="'+quadrant+'">'
            +'<td style="color:'+fd.color+';font-weight:600">'+fd.name+'</td>'
            +'<td style="color:'+(qColors[quadrant]||'#888')+'">'+quadrant+'</td>'
            +'<td>'+latestR.toFixed(2)+'</td><td>'+latestM.toFixed(2)+'</td></tr>';
    }

    if (all_x.length === 0) return;

    var margin = 0.3;
    var xMin = Math.min(Math.min.apply(null, all_x), 100) - margin;
    var xMax = Math.max(Math.max.apply(null, all_x), 100) + margin;
    var yMin = Math.min(Math.min.apply(null, all_y), 100) - margin;
    var yMax = Math.max(Math.max.apply(null, all_y), 100) + margin;

    var layout = Object.assign({}, PLOTLY_LAYOUT, {
        height:600,
        xaxis:{title:'RS-Ratio',zeroline:false,gridcolor:'#1e293b'},
        yaxis:{title:'RS-Momentum',zeroline:false,gridcolor:'#1e293b'},
        legend:{x:1.02,y:1,font:{size:10}}, margin:{r:200}, dragmode:'pan',
        shapes:[
            {type:'rect',x0:100,y0:100,x1:xMax+1,y1:yMax+1,fillcolor:'rgba(16,185,129,0.06)',line_width:0,layer:'below'},
            {type:'rect',x0:100,y0:yMin-1,x1:xMax+1,y1:100,fillcolor:'rgba(245,158,11,0.06)',line_width:0,layer:'below'},
            {type:'rect',x0:xMin-1,y0:yMin-1,x1:100,y1:100,fillcolor:'rgba(239,68,68,0.06)',line_width:0,layer:'below'},
            {type:'rect',x0:xMin-1,y0:100,x1:100,y1:yMax+1,fillcolor:'rgba(79,140,247,0.06)',line_width:0,layer:'below'},
            {type:'line',x0:xMin-1,x1:xMax+1,y0:100,y1:100,line:{color:'rgba(255,255,255,0.15)',width:1,dash:'dash'}},
            {type:'line',x0:100,x1:100,y0:yMin-1,y1:yMax+1,line:{color:'rgba(255,255,255,0.15)',width:1,dash:'dash'}},
        ],
        annotations:[
            {x:100+(xMax-100)*0.5,y:100+(yMax-100)*0.5,text:'<b>LEADING</b>',showarrow:false,font:{size:14,color:'rgba(16,185,129,0.4)'}},
            {x:100+(xMax-100)*0.5,y:yMin+(100-yMin)*0.5,text:'<b>WEAKENING</b>',showarrow:false,font:{size:14,color:'rgba(245,158,11,0.4)'}},
            {x:xMin+(100-xMin)*0.5,y:yMin+(100-yMin)*0.5,text:'<b>LAGGING</b>',showarrow:false,font:{size:14,color:'rgba(239,68,68,0.4)'}},
            {x:xMin+(100-xMin)*0.5,y:100+(yMax-100)*0.5,text:'<b>IMPROVING</b>',showarrow:false,font:{size:14,color:'rgba(79,140,247,0.4)'}},
        ],
    });

    Plotly.newPlot('rrg-chart', traces, layout, PLOTLY_CONFIG);
    document.getElementById('rrg-table').innerHTML =
        '<table class="data-table" id="rrg-pos-table"><thead><tr>'
        +'<th onclick="sortRRGTable(0,\'str\')">Asset</th>'
        +'<th onclick="sortRRGTable(1,\'str\')">Quadrant</th>'
        +'<th onclick="sortRRGTable(2,\'num\')">RS-Ratio</th>'
        +'<th onclick="sortRRGTable(3,\'num\')">RS-Mom</th>'
        +'</tr></thead><tbody>'+tableRows+'</tbody></table>';
}

var rrg_sort_dir = {};
function sortRRGTable(colIdx, type) {
    var table = document.getElementById('rrg-pos-table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));

    var key = colIdx + '';
    rrg_sort_dir[key] = rrg_sort_dir[key] === 'asc' ? 'desc' : 'asc';
    var asc = rrg_sort_dir[key] === 'asc';

    rows.sort(function(a, b) {
        var va, vb;
        if (type === 'num') {
            va = parseFloat(a.cells[colIdx].textContent) || 0;
            vb = parseFloat(b.cells[colIdx].textContent) || 0;
        } else {
            va = a.cells[colIdx].textContent.trim();
            vb = b.cells[colIdx].textContent.trim();
        }
        var cmp = type === 'num' ? va - vb : va.localeCompare(vb);
        return asc ? cmp : -cmp;
    });

    rows.forEach(function(r) { tbody.appendChild(r); });

    // Update header indicators
    table.querySelectorAll('th').forEach(function(th, i) {
        th.textContent = th.textContent.replace(/ [▲▼]$/, '');
        if (i === colIdx) th.textContent += asc ? ' ▲' : ' ▼';
    });
}

function initRRGSliderAndChecks() {
    // Slider
    var slider = document.getElementById('rrg-date-slider');
    slider.max = rrg_all_dates.length - 1;
    slider.value = rrg_all_dates.length - 1;
    document.getElementById('rrg-date-label').textContent = rrg_all_dates[rrg_all_dates.length - 1];
    document.getElementById('rrg-date-slider-wrap').style.display = 'block';

    // Build checkboxes
    rrg_visible = {};
    var container = document.getElementById('rrg-checkboxes');
    container.innerHTML = '';
    for (var key in rrg_full_data) {
        rrg_visible[key] = true;
        var fd = rrg_full_data[key];
        var lbl = document.createElement('label');
        lbl.style.cssText = 'display:inline-flex;align-items:center;gap:3px;font-size:12px;color:'+fd.color+';cursor:pointer;padding:2px 6px;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;user-select:none';
        var cb = document.createElement('input');
        cb.type = 'checkbox'; cb.checked = true;
        cb.dataset.key = key;
        cb.style.cssText = 'accent-color:'+fd.color+';cursor:pointer';
        cb.onchange = function(){ rrgToggle(this.dataset.key, this.checked); };
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(fd.name));
        container.appendChild(lbl);
    }
}

function rrgSelectAll(checked) {
    var cbs = document.querySelectorAll('#rrg-checkboxes input[type=checkbox]');
    cbs.forEach(function(cb) {
        cb.checked = checked;
        rrg_visible[cb.dataset.key] = checked;
    });
    rrgRedraw();
}

function rrgToggle(key, checked) {
    rrg_visible[key] = checked;
    rrgRedraw();
}

function rrgRedraw() {
    // Re-render from current slider position with visibility filter
    onRRGDateSlider();
}
