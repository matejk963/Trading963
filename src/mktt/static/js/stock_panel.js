var activeCharts = {};
var activeRow = null;
var _panelSymbol = null;

function toggleStockChart(symbol, clickedRow) {
    var panelId = 'stock-panel';
    // Remove previous row highlight
    if (activeRow) { activeRow.style.background = ''; activeRow = null; }

    // If clicking same symbol, close panel
    var existing = document.getElementById(panelId);
    if (existing && _panelSymbol === symbol) {
        existing.remove();
        _panelSymbol = null;
        Object.keys(activeCharts).forEach(function(k) { delete activeCharts[k]; });
        var _sp=document.getElementById('panel-spacer');if(_sp)_sp.style.height='0';
        return;
    }

    // Remove existing panel
    if (existing) existing.remove();
    Object.keys(activeCharts).forEach(function(k) { delete activeCharts[k]; });

    // Highlight clicked row
    clickedRow.style.background = 'rgba(79, 140, 247, 0.15)';
    activeRow = clickedRow;
    _panelSymbol = symbol;

    // Create tabbed panel
    var panel = document.createElement('div');
    panel.id = panelId;
    panel.style.cssText = 'position:fixed;left:0;right:0;bottom:0;height:45vh;z-index:500;background:#08080c;border-top:2px solid var(--primary,#4f8cf7);padding:0;box-shadow:0 -4px 20px rgba(0,0,0,0.8);display:flex;flex-direction:column;';
    // Add spacer at end of body so content is scrollable above the panel
    var spacer = document.getElementById('panel-spacer');
    if (!spacer) { spacer = document.createElement('div'); spacer.id = 'panel-spacer'; document.body.appendChild(spacer); }
    spacer.style.height = '45vh';

    // Header: tabs + close
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;padding:0 8px;border-bottom:1px solid #1a1a2a;flex-shrink:0;';
    var tabs = [
        {id:'chart', label:'Chart'},
        {id:'eps', label:'EPS'},
        {id:'fundamentals', label:'Fundamentals'},
        {id:'revisions', label:'Revisions'},
        {id:'rolling12m', label:'Rolling 12M'}
    ];
    tabs.forEach(function(tab, i) {
        var btn = document.createElement('span');
        btn.id = 'panel-tab-' + tab.id;
        btn.textContent = tab.label;
        btn.style.cssText = 'padding:6px 14px;font-size:12px;cursor:pointer;color:' + (i===0?'white':'#666') + ';border-bottom:2px solid ' + (i===0?'var(--primary,#4f8cf7)':'transparent') + ';';
        btn.onclick = function(e) { e.stopPropagation(); switchPanelTab(tab.id, symbol); };
        header.appendChild(btn);
    });
    var symLabel = document.createElement('span');
    symLabel.textContent = symbol;
    symLabel.style.cssText = 'margin-left:auto;font-size:14px;font-weight:700;color:var(--primary,#4f8cf7);padding-right:8px;';
    header.appendChild(symLabel);
    var closeBtn = document.createElement('span');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'padding:6px 10px;cursor:pointer;color:#ff3333;font-size:16px;font-weight:700;';
    closeBtn.onclick = function(e) { e.stopPropagation(); panel.remove(); _panelSymbol=null; if(activeRow){activeRow.style.background='';activeRow=null;} document.querySelector('.container').style.paddingBottom=''; };
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Content area
    var content = document.createElement('div');
    content.id = 'panel-content';
    content.style.cssText = 'flex:1;overflow:hidden;padding:4px;';
    panel.appendChild(content);
    document.body.appendChild(panel);

    // Load first tab
    switchPanelTab('chart', symbol);
}

function switchPanelTab(tabId, symbol) {
    // Update tab styles
    ['chart','eps','fundamentals','revisions','rolling12m'].forEach(function(t) {
        var el = document.getElementById('panel-tab-' + t);
        if (el) {
            el.style.color = t === tabId ? 'white' : '#666';
            el.style.borderBottom = '2px solid ' + (t === tabId ? 'var(--primary,#4f8cf7)' : 'transparent');
        }
    });
    var content = document.getElementById('panel-content');
    if (!content) return;
    content.innerHTML = '<span style="color:#666;font-size:13px;padding:8px;">Loading...</span>';

    console.log('switchPanelTab:', tabId, symbol);
    if (tabId === 'chart') loadPanelChart(symbol, content);
    else if (tabId === 'eps') loadPanelEPS(symbol, content);
    else if (tabId === 'fundamentals') loadPanelFundamentals(symbol, content);
    else if (tabId === 'revisions') loadPanelRevisions(symbol, content);
    else if (tabId === 'rolling12m') loadPanelRolling12M(symbol, content);
}

function loadPanelChart(symbol, container) {
    setTimeout(function() {
        fetch('/api/chart/' + encodeURIComponent(symbol))
            .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
            .then(function(data) {
                if (data.error) { container.innerHTML = '<span style="color:#f33;">No data for ' + symbol + '</span>'; return; }
                container.innerHTML = '';
                var w = container.getBoundingClientRect().width;
                var h = container.getBoundingClientRect().height;
                var chart = LightweightCharts.createChart(container, {
                    width: w, height: h,
                    layout: { backgroundColor: '#0a0a0e', textColor: '#888', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
                    grid: { vertLines: { color: '#1a1a2a' }, horzLines: { color: '#1a1a2a' } },
                    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                    rightPriceScale: { borderColor: '#1a1a2a', scaleMargins: { top: 0.05, bottom: 0.05 } },
                    timeScale: { borderColor: '#1a1a2a', timeVisible: false, rightOffset: 192 },
                });
                var cs = chart.addCandlestickSeries({
                    upColor: '#10b981', downColor: '#ef4444',
                    borderUpColor: '#10b981', borderDownColor: '#ef4444',
                    wickUpColor: '#10b98188', wickDownColor: '#ef444488',
                });
                var candles = [];
                for (var i = 0; i < data.dates.length; i++) {
                    candles.push({ time: data.dates[i], open: data.open[i], high: data.high[i], low: data.low[i], close: data.close[i] });
                }
                cs.setData(candles);
                [{data:data.ma_50,color:'#f59e0b',title:'MA50'},{data:data.ma_150,color:'#06b6d4',title:'MA150'},{data:data.ma_200,color:'#ec4899',title:'MA200'}].forEach(function(l) {
                    var s = chart.addLineSeries({ color: l.color, lineWidth: 1, title: l.title });
                    var d = [];
                    for (var i = 0; i < data.dates.length; i++) { if (l.data[i] !== null) d.push({ time: data.dates[i], value: l.data[i] }); }
                    s.setData(d);
                });
                chart.timeScale().fitContent();
                activeCharts['panel'] = chart;
                window.addEventListener('resize', function() {
                    if (activeCharts['panel'] && document.getElementById('panel-content')) {
                        var c = document.getElementById('panel-content');
                        activeCharts['panel'].resize(c.getBoundingClientRect().width, c.getBoundingClientRect().height);
                    }
                });
            })
            .catch(function(e) { container.innerHTML = '<span style="color:#f33;">Error: ' + e.message + '</span>'; });
    }, 30);
}

var _epsRevCount = 3;
var _epsLastSymbol = null;

function loadPanelEPS(symbol, container) {
    _epsLastSymbol = symbol;
    Promise.all([
        fetch('/api/rolling_12m/' + encodeURIComponent(symbol)).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); }),
        fetch('/api/eps_ttm_forward/' + encodeURIComponent(symbol) + '?n=' + (_epsRevCount || 3)).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); })
    ]).then(function(results) {
        var r12m = results[0];
        var ttmFwd = results[1];
        container.innerHTML = '';
        container.style.overflow = 'hidden';

        // Revision count control
        var ctrl = document.createElement('div');
        ctrl.style.cssText = 'position:absolute;top:4px;right:12px;z-index:10;display:flex;align-items:center;gap:6px;';
        ctrl.innerHTML = '<label style="font-size:10px;color:#666;">Revisions:</label>' +
            '<input id="eps-rev-input" type="number" value="' + _epsRevCount + '" min="1" max="' + ((ttmFwd && ttmFwd.n_available) || 12) + '" style="width:40px;font-size:11px;padding:2px 4px;background:#1a1a2a;border:1px solid #333;color:#ccc;border-radius:3px;">';

        var chartDiv = document.createElement('div');
        chartDiv.id = 'eps-main-chart';
        chartDiv.style.cssText = 'width:100%;height:100%;position:relative;';
        chartDiv.appendChild(ctrl);
        container.appendChild(chartDiv);

        document.getElementById('eps-rev-input').onchange = function() {
            _epsRevCount = parseInt(this.value) || 3;
            loadPanelEPS(_epsLastSymbol, document.getElementById('panel-content'));
        };

        setTimeout(function() {
            var h = container.getBoundingClientRect().height - 8;
            var traces = [];
            var palette = ['#4f8cf7', '#10b981', '#f59e0b', '#ef4444', '#a78bfa', '#ec4899', '#06b6d4', '#84cc16'];

            // 1. Trailing TTM actual
            if (r12m.dates && r12m.eps_ttm) {
                traces.push({
                    x: r12m.dates, y: r12m.eps_ttm, name: 'TTM Actual',
                    mode: 'lines', line: { color: '#4f8cf7', width: 2.5 },
                });
            }

            // 2. Trailing TTM estimate (consensus at time of report)
            if (r12m.eps_est_ttm) {
                var hasEst = r12m.eps_est_ttm.some(function(v) { return v !== null; });
                if (hasEst) {
                    traces.push({
                        x: r12m.dates, y: r12m.eps_est_ttm, name: 'TTM Estimate',
                        mode: 'lines', line: { color: '#4f8cf7', width: 1, dash: 'dot' },
                    });
                }
            }

            // 3. Forward cone (high/low)
            if (r12m.fwd_dates && r12m.fwd_eps_mean) {
                var connDates = [r12m.dates[r12m.dates.length - 1]].concat(r12m.fwd_dates);
                var lastTTM = r12m.eps_ttm[r12m.eps_ttm.length - 1];

                if (r12m.fwd_eps_high) {
                    traces.push({
                        x: connDates, y: [lastTTM].concat(r12m.fwd_eps_high),
                        name: 'Est High', mode: 'lines', line: { width: 0 }, showlegend: false,
                    });
                    traces.push({
                        x: connDates, y: [lastTTM].concat(r12m.fwd_eps_low || r12m.fwd_eps_mean),
                        name: 'Est Range', mode: 'lines', line: { width: 0 },
                        fill: 'tonexty', fillcolor: 'rgba(16,185,129,0.12)', showlegend: false,
                    });
                }

                // Forward mean
                traces.push({
                    x: connDates, y: [lastTTM].concat(r12m.fwd_eps_mean), name: 'Forward (Mean)',
                    mode: 'lines+markers', line: { color: '#10b981', width: 2, dash: 'dash' },
                    marker: { size: 4 },
                });
            }

            // 4. Revision lines from TTM forward
            if (ttmFwd && !ttmFwd.error && ttmFwd.curves && ttmFwd.curves.length > 0) {
                ttmFwd.curves.forEach(function(curve, i) {
                    // Map quarter labels to approximate dates
                    var curveDates = ttmFwd.quarter_dates || ttmFwd.quarter_labels;
                    traces.push({
                        x: curveDates, y: curve.values, name: curve.label,
                        mode: 'lines', line: { color: palette[(i + 2) % palette.length], width: i === 0 ? 2 : 1, dash: i === 0 ? 'solid' : 'dash' },
                    });
                });

                // Actual TTM reference line
                if (ttmFwd.current_ttm) {
                    var qDates = ttmFwd.quarter_dates || ttmFwd.quarter_labels;
                    traces.push({
                        x: qDates, y: Array(qDates.length).fill(ttmFwd.current_ttm),
                        name: 'Current TTM (' + ttmFwd.current_ttm + ')',
                        mode: 'lines', line: { color: '#666', dash: 'dot', width: 1 },
                    });
                }
            }

            Plotly.newPlot('eps-main-chart', traces, Object.assign({}, PLOTLY_DARK, {
                height: h,
                title: { text: 'EPS: Trailing TTM + Forward + Revisions', font: { size: 13, color: '#aaa' } },
                yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'EPS ($)' }),
            }), { displayModeBar: false, responsive: true });
        }, 30);
    }).catch(function(e) { container.innerHTML = '<span style="color:#f33;">Error: ' + e.message + '</span>'; });
}

var PLOTLY_DARK = {
    paper_bgcolor: '#0a0a0e', plot_bgcolor: '#0a0a0e',
    font: { color: '#888', family: 'JetBrains Mono, monospace', size: 11 },
    xaxis: { gridcolor: '#1a1a2a', linecolor: '#1a1a2a' },
    yaxis: { gridcolor: '#1a1a2a', linecolor: '#1a1a2a' },
    margin: { l: 50, r: 20, t: 30, b: 35 },
    legend: { orientation: 'h', y: 1.02, x: 0, font: { size: 10 } },
};

function loadPanelFundamentals(symbol, container) {
    fetch('/api/fundamentals/' + encodeURIComponent(symbol))
        .then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); })
        .then(function(data) {
            if (data.error) { container.innerHTML = '<span style="color:#f33;">' + data.error + '</span>'; return; }
            container.innerHTML = '';
            container.style.overflow = 'auto';

            // Two charts: Margins + EPS/Revenue
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:4px;height:100%;';

            var div1 = document.createElement('div');
            div1.style.cssText = 'flex:1;min-width:0;';
            div1.id = 'fund-margins';
            row.appendChild(div1);

            var div2 = document.createElement('div');
            div2.style.cssText = 'flex:1;min-width:0;';
            div2.id = 'fund-eps';
            row.appendChild(div2);

            container.appendChild(row);

            setTimeout(function() {
                var h = container.getBoundingClientRect().height - 8;
                // Margins chart
                var traces1 = [
                    { x: data.dates, y: data.op_margin, name: 'Op Margin %', line: { color: '#4f8cf7' } },
                    { x: data.dates, y: data.net_margin, name: 'Net Margin %', line: { color: '#10b981' } },
                ];
                Plotly.newPlot('fund-margins', traces1, Object.assign({}, PLOTLY_DARK, {
                    height: h, title: { text: 'Margins', font: { size: 12, color: '#aaa' } },
                    yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { ticksuffix: '%' })
                }), { displayModeBar: false, responsive: true });

                // EPS + FCF chart
                var traces2 = [
                    { x: data.dates, y: data.eps, name: 'EPS Actual', line: { color: '#f59e0b' } },
                    { x: data.dates, y: data.eps_est, name: 'EPS Estimate', line: { color: '#f59e0b', dash: 'dot' } },
                    { x: data.dates, y: data.fcf, name: 'FCF ($M)', yaxis: 'y2', line: { color: '#a78bfa' } },
                ];
                Plotly.newPlot('fund-eps', traces2, Object.assign({}, PLOTLY_DARK, {
                    height: h, title: { text: 'EPS & FCF', font: { size: 12, color: '#aaa' } },
                    yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'EPS ($)' }),
                    yaxis2: { overlaying: 'y', side: 'right', gridcolor: 'transparent', linecolor: '#1a1a2a', title: 'FCF ($M)', titlefont: { color: '#a78bfa', size: 10 }, tickfont: { color: '#a78bfa' } },
                }), { displayModeBar: false, responsive: true });
            }, 30);
        })
        .catch(function(e) { container.innerHTML = '<span style="color:#f33;">Error: ' + e.message + '</span>'; });
}

var _ttmRevisions = 3;
var _lastRevSymbol = null;

function loadPanelRevisions(symbol, container) {
    _lastRevSymbol = symbol;
    // Fetch both revisions and TTM forward in parallel
    Promise.all([
        fetch('/api/revisions/' + encodeURIComponent(symbol)).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); }),
        fetch('/api/eps_ttm_forward/' + encodeURIComponent(symbol) + '?n=' + (_ttmRevisions || 3)).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); })
    ]).then(function(results) {
        var data = results[0];
        var ttmData = results[1];
        container.innerHTML = '';
        container.style.overflow = 'auto';

        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:4px;height:100%;';

        // Left: Forward TTM EPS
        var div1 = document.createElement('div');
        div1.style.cssText = 'flex:1;min-width:0;';
        div1.id = 'rev-ttm';
        row.appendChild(div1);

        // Right: EPS estimate revisions
        var div2 = document.createElement('div');
        div2.style.cssText = 'flex:1;min-width:0;';
        div2.id = 'rev-eps';
        row.appendChild(div2);

        container.appendChild(row);

        setTimeout(function() {
            var h = container.getBoundingClientRect().height - 8;

            // Forward TTM EPS chart
            if (ttmData && !ttmData.error && ttmData.curves && ttmData.curves.length) {
                // Add revision count selector
                var ctrl = document.createElement('div');
                ctrl.style.cssText = 'position:absolute;top:4px;left:8px;z-index:10;display:flex;align-items:center;gap:6px;';
                ctrl.innerHTML = '<label style="font-size:10px;color:#666;">Revisions:</label>' +
                    '<input id="ttm-n-input" type="number" value="' + _ttmRevisions + '" min="1" max="' + (ttmData.n_available || 12) + '" style="width:40px;font-size:11px;padding:2px 4px;background:#1a1a2a;border:1px solid #333;color:#ccc;border-radius:3px;">';
                div1.style.position = 'relative';
                div1.appendChild(ctrl);
                document.getElementById('ttm-n-input').onchange = function() {
                    _ttmRevisions = parseInt(this.value) || 3;
                    loadPanelRevisions(_lastRevSymbol, document.getElementById('panel-content'));
                };

                var ttmTraces = [];
                var palette = ['#4f8cf7', '#10b981', '#f59e0b', '#ef4444', '#a78bfa', '#ec4899', '#06b6d4', '#84cc16'];
                ttmData.curves.forEach(function(curve, i) {
                    ttmTraces.push({
                        x: ttmData.quarter_labels,
                        y: curve.values,
                        name: curve.label,
                        mode: 'lines+markers',
                        line: { color: palette[i % palette.length], dash: i === 0 ? 'solid' : 'dash', width: i === 0 ? 3 : 1.5 },
                        marker: { size: i === 0 ? 5 : 3 },
                    });
                });
                // Add horizontal line for current actual TTM
                if (ttmData.current_ttm) {
                    ttmTraces.push({
                        x: ttmData.quarter_labels,
                        y: Array(ttmData.quarter_labels.length).fill(ttmData.current_ttm),
                        name: 'Actual TTM (' + ttmData.current_ttm + ')',
                        mode: 'lines',
                        line: { color: '#666', dash: 'dot', width: 1 },
                    });
                }
                Plotly.newPlot('rev-ttm', ttmTraces, Object.assign({}, PLOTLY_DARK, {
                    height: h,
                    title: { text: 'Forward TTM EPS (Next 8Q)', font: { size: 12, color: '#aaa' } },
                    yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'TTM EPS ($)' }),
                    xaxis: Object.assign({}, PLOTLY_DARK.xaxis, { type: 'category' }),
                }), { displayModeBar: false, responsive: true });
            } else {
                document.getElementById('rev-ttm').innerHTML = '<span style="color:#666;padding:20px;">' + (ttmData.error || 'No TTM data') + '</span>';
            }

            // EPS estimate revisions (FY1/FY2 trend over time)
            if (!data.error) {
                var epsTraces = [];
                if (data.eps_fy1) {
                    epsTraces.push({ x: data.eps_fy1.dates, y: data.eps_fy1.mean, name: 'FY1 Mean', line: { color: '#4f8cf7', width: 2 } });
                    if (data.eps_fy1.high) epsTraces.push({ x: data.eps_fy1.dates, y: data.eps_fy1.high, name: 'FY1 High', line: { color: '#4f8cf7', dash: 'dot', width: 1 }, showlegend: false });
                    if (data.eps_fy1.low) epsTraces.push({ x: data.eps_fy1.dates, y: data.eps_fy1.low, name: 'FY1 Low', line: { color: '#4f8cf7', dash: 'dot', width: 1 }, showlegend: false });
                }
                if (data.eps_fy2) {
                    epsTraces.push({ x: data.eps_fy2.dates, y: data.eps_fy2.mean, name: 'FY2 Mean', line: { color: '#10b981', width: 2 } });
                    if (data.eps_fy2.high) epsTraces.push({ x: data.eps_fy2.dates, y: data.eps_fy2.high, name: 'FY2 High', line: { color: '#10b981', dash: 'dot', width: 1 }, showlegend: false });
                    if (data.eps_fy2.low) epsTraces.push({ x: data.eps_fy2.dates, y: data.eps_fy2.low, name: 'FY2 Low', line: { color: '#10b981', dash: 'dot', width: 1 }, showlegend: false });
                }
                if (epsTraces.length) {
                    Plotly.newPlot('rev-eps', epsTraces, Object.assign({}, PLOTLY_DARK, {
                        height: h, title: { text: 'EPS Estimate Revisions (FY1/FY2)', font: { size: 12, color: '#aaa' } },
                        yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'EPS ($)' }),
                    }), { displayModeBar: false, responsive: true });
                } else {
                    document.getElementById('rev-eps').innerHTML = '<span style="color:#666;padding:20px;">No EPS revision data</span>';
                }
            } else {
                document.getElementById('rev-eps').innerHTML = '<span style="color:#666;padding:20px;">No revision data</span>';
            }
        }, 30);
    }).catch(function(e) { container.innerHTML = '<span style="color:#f33;">Error: ' + e.message + '</span>'; });
}

function loadPanelRolling12M(symbol, container) {
    fetch('/api/rolling_12m/' + encodeURIComponent(symbol))
        .then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status); return d; }); })
        .then(function(data) {
            container.innerHTML = '';
            container.style.overflow = 'auto';

            var row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:4px;height:100%;';

            var div1 = document.createElement('div');
            div1.style.cssText = 'flex:1;min-width:0;';
            div1.id = 'r12m-eps';
            row.appendChild(div1);

            var div2 = document.createElement('div');
            div2.style.cssText = 'flex:1;min-width:0;';
            div2.id = 'r12m-rev';
            row.appendChild(div2);

            container.appendChild(row);

            setTimeout(function() {
                var h = container.getBoundingClientRect().height - 8;

                // EPS Rolling 12M
                var epsTraces = [];
                // Actual TTM
                epsTraces.push({
                    x: data.dates, y: data.eps_ttm, name: 'EPS TTM (Actual)',
                    mode: 'lines', line: { color: '#4f8cf7', width: 2 },
                });
                // Estimate TTM (what consensus expected at each quarter)
                if (data.eps_est_ttm) {
                    epsTraces.push({
                        x: data.dates, y: data.eps_est_ttm, name: 'EPS TTM (Estimate)',
                        mode: 'lines', line: { color: '#4f8cf7', width: 1, dash: 'dot' },
                    });
                }
                // Forward NTM with cone
                if (data.fwd_dates && data.fwd_eps_mean) {
                    var connDates = [data.dates[data.dates.length-1]].concat(data.fwd_dates);
                    var lastTTM = data.eps_ttm[data.eps_ttm.length-1];
                    // Cone: high bound
                    if (data.fwd_eps_high) {
                        epsTraces.push({
                            x: connDates, y: [lastTTM].concat(data.fwd_eps_high),
                            name: 'Est High', mode: 'lines', line: { width: 0 },
                            showlegend: false,
                        });
                        epsTraces.push({
                            x: connDates, y: [lastTTM].concat(data.fwd_eps_low || data.fwd_eps_mean),
                            name: 'Est Range', mode: 'lines', line: { width: 0 },
                            fill: 'tonexty', fillcolor: 'rgba(16,185,129,0.15)',
                            showlegend: false,
                        });
                    }
                    // Mean line
                    epsTraces.push({
                        x: connDates, y: [lastTTM].concat(data.fwd_eps_mean), name: 'Forward (Mean)',
                        mode: 'lines+markers', line: { color: '#10b981', width: 2, dash: 'dash' },
                        marker: { size: 5 },
                    });
                }

                Plotly.newPlot('r12m-eps', epsTraces, Object.assign({}, PLOTLY_DARK, {
                    height: h,
                    title: { text: 'Rolling 12M EPS', font: { size: 12, color: '#aaa' } },
                    yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'EPS ($)' }),
                }), { displayModeBar: false, responsive: true });

                // Revenue Rolling 12M
                var revTraces = [];
                revTraces.push({
                    x: data.dates, y: data.rev_ttm, name: 'Revenue TTM ($M)',
                    mode: 'lines', line: { color: '#f59e0b', width: 2 },
                });
                if (data.fwd_dates && data.fwd_rev_mean) {
                    var connDatesR = [data.dates[data.dates.length-1]].concat(data.fwd_dates);
                    var lastRev = data.rev_ttm[data.rev_ttm.length-1];
                    // Cone
                    if (data.fwd_rev_high) {
                        revTraces.push({
                            x: connDatesR, y: [lastRev].concat(data.fwd_rev_high),
                            name: 'Est High', mode: 'lines', line: { width: 0 },
                            showlegend: false,
                        });
                        revTraces.push({
                            x: connDatesR, y: [lastRev].concat(data.fwd_rev_low || data.fwd_rev_mean),
                            name: 'Est Range', mode: 'lines', line: { width: 0 },
                            fill: 'tonexty', fillcolor: 'rgba(16,185,129,0.15)',
                            showlegend: false,
                        });
                    }
                    revTraces.push({
                        x: connDatesR, y: [lastRev].concat(data.fwd_rev_mean), name: 'Forward (Mean)',
                        mode: 'lines+markers', line: { color: '#10b981', width: 2, dash: 'dash' },
                        marker: { size: 5 },
                    });
                }

                Plotly.newPlot('r12m-rev', revTraces, Object.assign({}, PLOTLY_DARK, {
                    height: h,
                    title: { text: 'Rolling 12M Revenue ($M)', font: { size: 12, color: '#aaa' } },
                    yaxis: Object.assign({}, PLOTLY_DARK.yaxis, { title: 'Revenue ($M)' }),
                }), { displayModeBar: false, responsive: true });
            }, 30);
        })
        .catch(function(e) { container.innerHTML = '<span style="color:#f33;">Error: ' + e.message + '</span>'; });
}
