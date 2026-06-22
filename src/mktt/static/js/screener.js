// screener.js — the screener page's client render/sort/picker/view logic.
//
// EXTRACTED from the screener template's inline <script> (effort
// 2026-06-16-screener-optimization, S3 follow-up) so it loads on EVERY page via
// base.html. That lets the keep-alive (keepalive.js) rebuild the flat view after an
// #app-content innerHTML swap from ANY page (Monitor, RRG, …) — the renderer is no
// longer trapped in the screener page's inline script.
//
// PURE JS ONLY. All server-injected data (SCREENER_DATA, FLAT_COL_SPEC, ALL_COLS,
// VISIBLE_COLS, SECTOR_MAP, the ticker list) is assigned to `window.*` by a tiny
// inline <script> the template still renders; this file READS those globals and
// contains NO Jinja. Reassignments (e.g. the visible-column set) are written back to
// `window.*` so keepalive can re-seat them and call window.initScreener() to restore.
//
// Inert on non-screener pages: the auto-init at the bottom only runs when the
// screener DOM (#screener-table) is present. Functions referenced from inline
// onclick="" handlers are exposed on `window` (inline handlers resolve in global
// scope). Debug logging off by default: localStorage.SCR_DEBUG = '1'.
(function () {
    'use strict';

    function dbg() {
        try {
            if (localStorage.getItem('SCR_DEBUG') === '1') {
                console.debug.apply(console, ['[screener]'].concat([].slice.call(arguments)));
            }
        } catch (e) {}
    }

    // ---- server-injected globals (read fresh from window) ---------------------
    // The template assigns window.SCREENER_DATA / FLAT_COL_SPEC / ALL_COLS /
    // VISIBLE_COLS / SECTOR_MAP / _TICKERS before this script's functions run.
    // We never shadow them with local vars so keepalive's re-seating is honored.
    function SD() { return window.SCREENER_DATA; }
    function SPEC() { return window.FLAT_COL_SPEC || { cols: {}, stage_labels: {}, regime_labels: {}, ma_labels: {} }; }
    function ALL() { return window.ALL_COLS || []; }
    function VIS() { return window.VISIBLE_COLS || []; }
    function setVIS(v) { window.VISIBLE_COLS = v; }
    function MAP() { return window.SECTOR_MAP || {}; }
    function TICKERS() { return window._TICKERS || []; }

    // ===== Slice 2: client-side flat-table re-render from embedded data =========
    // Format a raw (full-precision) value exactly like the server formatter `tok`.
    function _fmtCell(tok, v) {
        var spec = SPEC();
        if (tok === 'text') return (v === null || v === undefined || v === '') ? '—' : String(v);
        if (tok === 'stage_label') return spec.stage_labels[String(v)] || '—';
        if (tok === 'regime_label') return spec.regime_labels[String(v)] || '—';
        if (tok === 'ma_label') return spec.ma_labels[String(v)] || '—';
        if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
        var n = Number(v);
        if (isNaN(n)) return '—';
        switch (tok) {
            case 'f2': return n.toFixed(2);
            case 'f1': return n.toFixed(1);
            case 'f0': return n.toFixed(0);
            case 'pct1': return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
            case 's1': return (n >= 0 ? '+' : '') + n.toFixed(1);
            case 'turnover': return n ? (n / 1e6).toFixed(1) + 'M' : '—';
            case 'pctile': return 'P' + n.toFixed(0);   // universe percentile, e.g. P82
            default: return String(v);
        }
    }
    function _rawVal(rowArr, cid) {
        var i = SD().col_id_of[cid];
        return (i === undefined) ? null : rowArr[i];
    }
    function _stageColor(stageVal) {
        var s = Number(stageVal);
        if (s === 2) return 'color:var(--phosphor-bright,var(--green));';
        if (s === 4) return 'color:var(--red,#ff3333);';
        if (s === 1) return 'color:var(--amber,#ffb000);';
        if (s === 3) return 'color:var(--orange,#ff6e27);';
        return '';
    }
    // Build one <td> for column `cid` from a SCREENER_DATA row tuple — mirrors the
    // server's _flat_cell (same label/format/coloring) so a re-render looks identical.
    function _renderCell(rowArr, cid) {
        var sp = SPEC().cols[cid] || { fmt: 'text', align: 'right', colored: false };
        var raw = _rawVal(rowArr, cid);
        var td = document.createElement('td');
        td.setAttribute('data-cid', cid);
        td.textContent = _fmtCell(sp.fmt, raw);
        var style = 'padding:3px 8px;font-size:12px;';
        if (sp.align === 'left') style = 'text-align:left;' + style;
        if (cid === 'symbol') style += 'font-weight:600';
        else if (sp.align === 'left') { /* stage gets its color below; others dim */
            if (cid === 'stage') style += _stageColor(_rawVal(rowArr, 'stage'));
            else style += 'color:var(--text-dim)';
        }
        if (sp.colored) {
            var n = Number(raw);
            if (!isNaN(n) && n !== 0) td.className = n > 0 ? 'positive' : 'negative';
        }
        td.setAttribute('style', style);
        return td;
    }
    // Slice 4: fixed-layout column widths (px). Wide text cols get more room; the
    // numeric grid stays compact. Anything unlisted falls back by alignment so a
    // newly added column still gets a sane width without a code change.
    var _COL_WIDTH = {
        symbol: 64, sector: 150, industry: 180, stage: 90, regime: 120, ma: 120,
        price: 64, chg: 60, turnover: 78, rs: 48, target: 64
    };
    function _colWidth(cid) {
        if (_COL_WIDTH[cid]) return _COL_WIDTH[cid];
        var sp = SPEC().cols[cid] || {};
        return sp.align === 'left' ? 130 : 62;
    }
    // Build (or rebuild) the <colgroup> so `table-layout:fixed` has explicit widths
    // matching the current VISIBLE_COLS order. One DOM write.
    function _applyColWidths(table) {
        var cg = table.querySelector('colgroup');
        if (!cg) { cg = document.createElement('colgroup'); table.insertBefore(cg, table.firstChild); }
        var html = '<col data-cid="__chk" style="width:30px">';   // leading select column
        VIS().forEach(function (cid) {
            html += '<col data-cid="' + cid + '" style="width:' + _colWidth(cid) + 'px">';
        });
        cg.innerHTML = html;
    }
    // Re-render the flat table's <thead>/<tbody> from SCREENER_DATA over VISIBLE_COLS,
    // honoring the current sort. DocumentFragment → one tbody DOM write (no per-row reflow).
    var _flatSort = { col: null, asc: true };  // col is a cid
    function renderFlatTable() {
        var table = document.getElementById('screener-table');
        var data = SD();
        if (!table || !data || !data.rows) return;
        _applyColWidths(table);
        var spec = SPEC();
        var symIdx = data.columns.indexOf('Symbol');
        // header (leading select-all checkbox, then the visible columns)
        var htr = document.createElement('tr');
        htr.appendChild(_buildSelAllTh());
        VIS().forEach(function (cid, i) {
            var sp = spec.cols[cid] || { label: cid, align: 'right', kind: 'str' };
            var th = document.createElement('th');
            th.setAttribute('data-cid', cid);
            th.textContent = sp.label;
            var st = 'cursor:pointer';
            if (sp.align === 'left') st = 'text-align:left;' + st;
            th.setAttribute('style', st);
            if (_flatSort.col === cid) th.setAttribute('data-asc', _flatSort.asc);
            th.onclick = (function (c, kind) { return function () { sortBy(c, kind); }; })(cid, sp.kind);
            htr.appendChild(th);
        });
        var thead = table.tHead || table.createTHead();
        thead.innerHTML = ''; thead.appendChild(htr);
        // rows (apply current sort to a copy of the index order)
        var order = data.rows.map(function (_, i) { return i; });
        if (_flatSort.col) {
            var sp = spec.cols[_flatSort.col] || { kind: 'str' };
            var asc = _flatSort.asc;
            order.sort(function (ia, ib) {
                var a = _rawVal(data.rows[ia], _flatSort.col);
                var b = _rawVal(data.rows[ib], _flatSort.col);
                if (sp.kind === 'num') {
                    var na = (a === null || a === undefined || isNaN(Number(a))) ? -Infinity : Number(a);
                    var nb = (b === null || b === undefined || isNaN(Number(b))) ? -Infinity : Number(b);
                    return asc ? na - nb : nb - na;
                }
                var sa = (a === null || a === undefined) ? '' : String(a);
                var sb = (b === null || b === undefined) ? '' : String(b);
                return asc ? sa.localeCompare(sb) : sb.localeCompare(sa);
            });
        }
        var frag = document.createDocumentFragment();
        order.forEach(function (ri) {
            var rowArr = data.rows[ri];
            var sym = symIdx >= 0 ? rowArr[symIdx] : '';
            var tr = document.createElement('tr');
            tr.setAttribute('onclick', "toggleStockChart('" + sym + "', this)");
            tr.style.cssText = 'cursor:pointer;border-bottom:1px solid var(--border);';
            tr.appendChild(_buildRowChk(sym));
            VIS().forEach(function (cid) { tr.appendChild(_renderCell(rowArr, cid)); });
            frag.appendChild(tr);
        });
        var tbody = table.tBodies[0] || table.appendChild(document.createElement('tbody'));
        tbody.innerHTML = '';
        tbody.appendChild(frag);
        _syncSelectionUI();
    }
    // Sort the flat table from data by column id (toggles direction on repeat click).
    function sortBy(cid, kind) {
        if (_flatSort.col === cid) _flatSort.asc = !_flatSort.asc;
        else { _flatSort.col = cid; _flatSort.asc = (kind !== 'num'); }
        renderFlatTable();
    }
    // Legacy sortTable(index,type) shim: the server-rendered thead calls this with a
    // column index; translate to the cid at that visible position and delegate.
    function sortTable(col, type) {
        var cid = VIS()[col];
        if (cid) { sortBy(cid, type); return; }
        // fallback (should not happen): old DOM-text sort
        var table = document.getElementById('screener-table');
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.rows);
        var th = table.tHead.rows[0].cells[col];
        var asc = th.getAttribute('data-asc') !== 'true';
        Array.prototype.forEach.call(table.tHead.rows[0].cells, function (c) { c.removeAttribute('data-asc'); });
        th.setAttribute('data-asc', asc);
        rows.sort(function (a, b) {
            var x = a.cells[col].textContent.trim(), y = b.cells[col].textContent.trim();
            if (type === 'num') {
                var nx = parseFloat(x.replace(/[%,M]/g, '')), ny = parseFloat(y.replace(/[%,M]/g, ''));
                nx = isNaN(nx) ? -Infinity : nx; ny = isNaN(ny) ? -Infinity : ny;
                return asc ? nx - ny : ny - nx;
            }
            return asc ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
    }
    // Placeholder chart toggle (Monitor section owns the real chart wiring).
    function toggleStockChart(sym, row) { /* watchlist context-menu lives in base.html */ }

    // ---- view toggle: flat table <-> sector hierarchy ----
    function switchView(v) {
        var flat = document.getElementById('view-flat');
        var sectors = document.getElementById('view-sectors');
        var map = document.getElementById('view-map');
        var bf = document.getElementById('view-flat-btn');
        var bs = document.getElementById('view-sectors-btn');
        var bm = document.getElementById('view-map-btn');
        if (!flat) return;
        var off = 'var(--bg-card)', offc = 'var(--text-dim)';
        function set(btn, on) { if (btn) { btn.style.background = on ? 'var(--primary)' : off; btn.style.color = on ? 'white' : offc; } }
        flat.style.display = 'none';
        if (sectors) sectors.style.display = 'none';
        if (map) map.style.display = 'none';
        set(bf, false); set(bs, false); set(bm, false);
        if (v === 'sectors' && sectors) {
            sectors.style.display = 'block'; set(bs, true);
        } else if (v === 'map' && map) {
            map.style.display = 'block'; set(bm, true); loadSectorMap();
        } else {
            flat.style.display = 'block'; set(bf, true);
        }
    }

    // ---- column picker (Slice 2: drives the data-driven flat table) ----
    // The flat table now materializes ONLY the selected columns (no all-then-CSS-hide).
    // The picker writes the selected set to ?cols= + localStorage and re-renders the
    // flat table from SCREENER_DATA (instant). The Sectors view still CSS-hides by
    // data-cid (its richer hierarchy stays server-rendered for now — S4/later).
    var COL_GROUPS = {
        price: ['symbol', 'price', 'chg', 'turnover', 'rs', 'rschg1w', 'rschg1m', 'rschg3m', 'stage', 'regime', 'ma', 'pct50', 'pct200', 'from52h', 'from52l'],
        valuation: ['symbol', 'pe', 'fwdpe', 'pesect', 'peind', 'evebitda', 'target'],
        earnings: ['symbol', 'eps', 'fy1', 'fy2', 'pe', 'fwdpe', 'target'],
        quality: ['symbol', 'opmgn', 'netmgn', 'roic', 'fcf'],
        debt: ['symbol', 'ndebitda', 'evebitda'],
        performance: ['symbol', 'ret1w', 'ret1m', 'ret3m', 'ret6m', 'ret12m', 'ret3y', 'ret5y'],
        minimal: ['symbol', 'price', 'chg', 'rs', 'stage']
    };
    // Canonical picker vocabulary = server ALL_COLS (no DOM scan). Ordered cids.
    function _allCols() { return ALL().map(function (c) { return c.cid; }); }
    function _colLabel(cid) {
        var all = ALL();
        for (var i = 0; i < all.length; i++) if (all[i].cid === cid) return all[i].label;
        return cid;
    }
    // flat-table cid -> sector-table data-cid (the sector view uses 'sym' for Symbol).
    function _sectorCid(cid) { return cid === 'symbol' ? 'sym' : cid; }
    function applyColVisibility() {
        // Selected set = checked boxes, in ALL_COLS order (stable, server-defined order).
        var checked = {};
        document.querySelectorAll('#col-checks input[type=checkbox]').forEach(function (cb) {
            if (cb.checked) checked[cb.value] = true;
        });
        var selected = _allCols().filter(function (cid) { return checked[cid]; });
        if (!selected.length) selected = ['symbol'];   // never an empty table
        setVIS(selected);
        renderFlatTable();                              // instant: rebuild from embedded data

        // Sectors view: keep CSS-hide by data-cid across its hierarchy (incl. sub-tables).
        var hidden = {};
        _allCols().forEach(function (cid) { if (!checked[cid]) hidden[cid] = true; });
        var stable = document.getElementById('sector-table');
        if (stable) {
            _allCols().forEach(function (cid) {
                var scid = _sectorCid(cid), hide = !!hidden[cid];
                stable.querySelectorAll('[data-cid="' + scid + '"]').forEach(function (el) {
                    if (el.tagName === 'TH' || el.tagName === 'TD') el.style.display = hide ? 'none' : '';
                });
            });
        }
        var all = _allCols();
        var cc = document.getElementById('col-count');
        if (cc) cc.textContent = selected.length + '/' + all.length + ' cols';
        // Persist: ?cols= in the URL (round-trips on reload) + localStorage.
        try { localStorage.setItem('screenerVisibleCols', JSON.stringify(selected)); } catch (e) {}
        try {
            var u = new URL(window.location.href);
            u.searchParams.set('cols', selected.join(','));
            history.replaceState(null, '', u.toString());
        } catch (e) {}
    }
    function toggleColGroup(group) {
        var keep = group === 'all' ? _allCols() : (COL_GROUPS[group] || []);
        if (keep.indexOf('symbol') === -1) keep = ['symbol'].concat(keep);
        document.querySelectorAll('#col-checks input[type=checkbox]').forEach(function (cb) {
            cb.checked = keep.indexOf(cb.value) !== -1;
        });
        applyColVisibility();
    }
    // ADD the universe-percentile companion (`{id}p`) of every currently-checked value
    // column (additive, not a replace) — the "+ %ile" picker button. Each base numeric
    // metric has a `<id>p` percentile column in the server vocabulary (ALL_COLS).
    function addPctileCols() {
        var have = {};
        _allCols().forEach(function (cid) { have[cid] = true; });
        var boxes = document.querySelectorAll('#col-checks input[type=checkbox]');
        var checked = {};
        boxes.forEach(function (cb) { if (cb.checked) checked[cb.value] = true; });
        Object.keys(checked).forEach(function (cid) {
            if (cid.slice(-1) === 'p') return;          // already a percentile col
            var pid = cid + 'p';
            if (have[pid]) checked[pid] = true;          // turn on its %ile companion
        });
        boxes.forEach(function (cb) { cb.checked = !!checked[cb.value]; });
        applyColVisibility();
    }
    // Build the column-picker checkboxes from ALL_COLS and apply the current visible
    // set. Idempotent: clears #col-checks first so a keep-alive re-init (or repeat
    // call) never double-renders checkboxes or double-binds change handlers.
    // Restore the last-used column selection (saved by applyColVisibility) on a normal
    // load when the URL didn't pin an explicit ?cols= set. Skipped during a keep-alive
    // restore (which drives cols from the snapshot) and when ?cols= is present (explicit
    // wins). Keeps only ids still known to the server vocabulary.
    function _urlHasCols() {
        try { return new URL(window.location.href).searchParams.has('cols'); } catch (e) { return false; }
    }
    function _savedCols() {
        try {
            var arr = JSON.parse(localStorage.getItem('screenerVisibleCols') || 'null');
            if (!Array.isArray(arr)) return null;
            var known = {}; ALL().forEach(function (c) { known[c.cid] = true; });
            var out = arr.filter(function (cid) { return known[cid]; });
            return out.length ? out : null;
        } catch (e) { return null; }
    }
    function initColPicker() {
        var box = document.getElementById('col-checks');
        if (!box) return;
        box.innerHTML = '';   // idempotent rebuild (no stale/duplicate checkboxes)
        if (!window._screenerRestoring && !_urlHasCols()) {
            var saved = _savedCols();
            if (saved) setVIS(saved);
        }
        // Initial checked set = VISIBLE_COLS (server-resolved from ?cols=, else default).
        var visible = {};
        VIS().forEach(function (c) { visible[c] = true; });
        ALL().forEach(function (c) {
            var cid = c.cid;
            var lbl = document.createElement('label');
            lbl.style.cssText = 'font-size:11px;color:var(--text-dim);display:flex;align-items:center;gap:3px';
            var cb = document.createElement('input');
            cb.type = 'checkbox'; cb.value = cid; cb.checked = !!visible[cid];
            cb.addEventListener('change', applyColVisibility);
            lbl.appendChild(cb); lbl.appendChild(document.createTextNode(c.label));
            box.appendChild(lbl);
        });
        // Sync sector-table hide + col-count to the server-rendered initial state
        // (the flat table is already correct from the server; no re-render needed).
        applyColVisibility();
    }

    // ---- Find Ticker autocomplete (jump straight to a symbol's screener row) ----
    function tickerAutocomplete(input) {
        var q = (input.value || '').toUpperCase().trim();
        var dd = document.getElementById('ticker-dropdown');
        if (!q) { dd.style.display = 'none'; return; }
        var hits = TICKERS().filter(function (t) { return t.indexOf(q) === 0; }).slice(0, 12);
        if (!hits.length) { dd.style.display = 'none'; return; }
        dd.innerHTML = '';
        hits.forEach(function (t) {
            var d = document.createElement('div');
            d.textContent = t;
            d.style.cssText = 'padding:4px 10px;font-size:12px;cursor:pointer;color:var(--text)';
            d.onmouseover = function () { d.style.background = 'var(--bg)'; };
            d.onmouseout = function () { d.style.background = ''; };
            d.onclick = function () { input.value = t; dd.style.display = 'none'; tickerGo(); };
            dd.appendChild(d);
        });
        dd.style.display = 'block';
    }
    function tickerGo() {
        var v = (document.getElementById('ticker-search').value || '').toUpperCase().trim();
        if (!v) return;
        var rows = document.querySelectorAll('#screener-table tbody tr');
        for (var i = 0; i < rows.length; i++) {
            // Symbol column may be toggled off — read the symbol from the row's onclick
            // (toggleStockChart('SYM', this)) so the jump works regardless of columns.
            var sym = '';
            var cell = rows[i].querySelector('td[data-cid="symbol"]');
            if (cell) sym = cell.textContent.trim().toUpperCase();
            else { var oc = rows[i].getAttribute('onclick') || ''; var m = oc.match(/toggleStockChart\('([^']+)'/); if (m) sym = m[1].toUpperCase(); }
            if (sym === v) {
                rows[i].scrollIntoView({ block: 'center' });
                rows[i].style.outline = '2px solid var(--primary)';
                setTimeout(function (r) { return function () { r.style.outline = ''; }; }(rows[i]), 2000);
                return;
            }
        }
    }

    // ===== Sector stats table (revived original): expand/collapse + tabs + sort =====
    var sectorSortDir = {};
    var _subSortDir = {};

    function _parseCell(text, type) {
        var v = text.replace(/[%▶,]/g, '').replace('—', '').trim();
        if (type === 'num') {
            var f = parseFloat(v);
            return isNaN(f) ? -Infinity : f;
        }
        return v;
    }

    // expand/collapse a sector's detail row (industry/all-stocks tabs)
    function toggleSectorStocks(id) {
        var row = document.getElementById(id);
        var arrow = document.getElementById(id.replace('sector-', 'sector-arrow-'));
        if (row.style.display === 'none') {
            row.style.display = 'table-row';
            if (arrow) arrow.style.transform = 'rotate(90deg)';
        } else {
            row.style.display = 'none';
            if (arrow) arrow.style.transform = 'rotate(0deg)';
        }
    }

    // expand/collapse an industry's stock list inside a sector
    function toggleIndustry(id) {
        var row = document.getElementById(id);
        var arrow = document.getElementById('ind-arrow-' + id.replace('ind-', ''));
        if (row.style.display === 'none') {
            row.style.display = 'table-row';
            if (arrow) arrow.style.transform = 'rotate(90deg)';
        } else {
            row.style.display = 'none';
            if (arrow) arrow.style.transform = 'rotate(0deg)';
        }
    }

    // switch a sector's "By Industry" / "All Stocks" tabs
    function switchSectorTab(sectorId, tab) {
        var indPanel = document.getElementById('panel-ind-' + sectorId);
        var allPanel = document.getElementById('panel-all-' + sectorId);
        var indTab = document.getElementById('tab-ind-' + sectorId);
        var allTab = document.getElementById('tab-all-' + sectorId);
        if (tab === 'ind') {
            indPanel.style.display = 'block'; allPanel.style.display = 'none';
            indTab.classList.add('sector-tab-active'); indTab.style.color = '';
            allTab.classList.remove('sector-tab-active'); allTab.style.color = 'var(--text-dim, #555)';
        } else {
            indPanel.style.display = 'none'; allPanel.style.display = 'block';
            allTab.classList.add('sector-tab-active'); allTab.style.color = '';
            indTab.classList.remove('sector-tab-active'); indTab.style.color = 'var(--text-dim, #555)';
        }
    }

    // sort the top-level sector rows (keeping each sector's detail row paired + collapsed)
    function sortSectorTable(th, col, type) {
        var table = document.getElementById('sector-table');
        var tbody = table.querySelector('tbody');
        var key = 'sec_' + col;
        sectorSortDir[key] = !(sectorSortDir[key] || false);
        var asc = sectorSortDir[key];
        var pairs = [];
        var rows = Array.from(tbody.children);
        for (var i = 0; i < rows.length; i++) {
            if (!rows[i].id || !rows[i].id.startsWith('sector-')) {
                pairs.push({ header: rows[i], detail: rows[i + 1] || null });
                i++;
            }
        }
        pairs.forEach(function (p) {
            if (p.detail) p.detail.style.display = 'none';
            var arrow = p.header.querySelector('[id^="sector-arrow-"]');
            if (arrow) arrow.style.transform = 'rotate(0deg)';
        });
        pairs.sort(function (a, b) {
            var aVal = _parseCell(a.header.cells[col].textContent, type);
            var bVal = _parseCell(b.header.cells[col].textContent, type);
            if (type === 'num') return asc ? aVal - bVal : bVal - aVal;
            return asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        });
        pairs.forEach(function (p) {
            tbody.appendChild(p.header);
            if (p.detail) tbody.appendChild(p.detail);
        });
    }

    // sort the industry sub-table (paired rows) or a flat stock sub-table
    function sortSubTable(th, col, type, level) {
        event.stopPropagation();
        var table = th.closest('table');
        var tbody = table.querySelector('tbody');
        var key = table.id + '_' + level + '_' + col;
        _subSortDir[key] = !(_subSortDir[key] || false);
        var asc = _subSortDir[key];
        if (level === 'ind') {
            var pairs = [];
            var rows = Array.from(tbody.children);
            for (var i = 0; i < rows.length; i++) {
                var nextRow = rows[i + 1];
                if (nextRow && nextRow.id && nextRow.id.startsWith('ind-')) {
                    pairs.push({ header: rows[i], detail: nextRow }); i++;
                } else {
                    pairs.push({ header: rows[i], detail: null });
                }
            }
            pairs.sort(function (a, b) {
                var aVal = _parseCell(a.header.cells[col] ? a.header.cells[col].textContent : '', type);
                var bVal = _parseCell(b.header.cells[col] ? b.header.cells[col].textContent : '', type);
                if (type === 'num') return asc ? aVal - bVal : bVal - aVal;
                return asc ? String(aVal).localeCompare(String(bVal)) : String(bVal).localeCompare(String(aVal));
            });
            pairs.forEach(function (p) {
                tbody.appendChild(p.header);
                if (p.detail) tbody.appendChild(p.detail);
            });
        } else {
            var rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function (a, b) {
                var aVal = _parseCell(a.cells[col] ? a.cells[col].textContent : '', type);
                var bVal = _parseCell(b.cells[col] ? b.cells[col].textContent : '', type);
                if (type === 'num') return asc ? aVal - bVal : bVal - aVal;
                return asc ? String(aVal).localeCompare(String(bVal)) : String(bVal).localeCompare(String(aVal));
            });
            rows.forEach(function (r) { tbody.appendChild(r); });
        }
    }

    // ===== Map view: sector × dimension composition (revived /api/sector_map) =====
    // SECTOR_MAP is server-computed for every dimension over the passed set, embedded
    // (window.SECTOR_MAP) so the dimension selector switches client-side, no round-trip.
    var _mapMode = 'sector'; // 'sector' = % of sector, 'category' = % of category

    function setMapMode(mode) {
        _mapMode = mode;
        document.getElementById('map-mode-sector').style.background = mode === 'sector' ? 'var(--primary)' : 'var(--bg-card)';
        document.getElementById('map-mode-sector').style.color = mode === 'sector' ? 'white' : 'var(--text-dim)';
        document.getElementById('map-mode-category').style.background = mode === 'category' ? 'var(--primary)' : 'var(--bg-card)';
        document.getElementById('map-mode-category').style.color = mode === 'category' ? 'white' : 'var(--text-dim)';
        var dim = document.getElementById('map-dim').value;
        if (MAP()[dim]) renderMap(MAP()[dim]);
    }

    function loadSectorMap() {
        var sel = document.getElementById('map-dim');
        if (!sel) return;
        var data = MAP()[sel.value];
        if (!data) { document.getElementById('map-summary').innerHTML = '<span style="color:#f33;">No data</span>'; return; }
        renderMap(data);
    }

    function renderMap(data) {
        document.getElementById('map-total').textContent = data.total_stocks + ' stocks';

        var dimColors = {};
        var palette = ['#4f8cf7', '#10b981', '#f59e0b', '#ef4444', '#a78bfa', '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1', '#14b8a6', '#e11d48'];
        // Use the server-defined category order (filtered to those present).
        var dims = (data.categories || Object.keys(data.overall)).filter(function (c) { return data.overall[c] != null; });
        dims.forEach(function (d, i) { dimColors[d] = palette[i % palette.length]; });

        var sectors = {};
        data.summary.forEach(function (r) { sectors[r.sector] = (sectors[r.sector] || 0) + r.count; });

        var overallPct = {};
        dims.forEach(function (d) { overallPct[d] = data.total_stocks > 0 ? data.overall[d] / data.total_stocks * 100 : 0; });

        var matrix = {};
        data.summary.forEach(function (r) {
            if (!matrix[r.sector]) matrix[r.sector] = {};
            matrix[r.sector][r.dimension] = r.count;
        });

        function hexToRgba(hex, alpha) {
            var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
            return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
        }

        var mode = _mapMode;
        var h = '<table id="map-table" style="width:100%;border-collapse:collapse;font-size:12px;">';
        h += '<thead><tr style="border-bottom:2px solid #333;">';
        h += '<th style="text-align:left;padding:6px 8px;min-width:140px;cursor:pointer" onclick="sortMapTable(0,\'str\')">Sector</th>';
        h += '<th style="padding:6px 4px;color:var(--text-faint);font-size:11px;cursor:pointer" onclick="sortMapTable(1,\'num\')">#</th>';
        dims.forEach(function (d, i) {
            h += '<th style="padding:6px 4px;color:' + dimColors[d] + ';font-size:11px;min-width:60px;cursor:pointer" onclick="sortMapTable(' + (i + 2) + ',\'num\')">' + d + '</th>';
        });
        h += '</tr></thead>';

        h += '<tbody><tr id="map-overall-row" style="border-bottom:2px solid #444;background:#111;">';
        h += '<td style="padding:4px 8px;font-weight:700;color:var(--text-dim);">All Stocks</td>';
        h += '<td style="padding:4px;text-align:center;color:var(--text-faint);">' + data.total_stocks + '</td>';
        dims.forEach(function (d) {
            var pct = overallPct[d];
            var expectedShare = (100 / Math.max(Object.keys(sectors).length, 1)).toFixed(0);
            h += '<td style="padding:4px;text-align:center;font-weight:600;color:' + dimColors[d] + '">' + (mode === 'category' ? expectedShare + '%' : pct.toFixed(0) + '%') + '</td>';
        });
        h += '</tr>';

        var sortedSectors = Object.keys(sectors).sort(function (a, b) { return sectors[b] - sectors[a]; });

        var colSums = {};
        if (mode === 'category') {
            dims.forEach(function (d) { colSums[d] = 0; });
            sortedSectors.forEach(function (sec) {
                var secTotal = sectors[sec];
                dims.forEach(function (d) {
                    var cnt = (matrix[sec] || {})[d] || 0;
                    colSums[d] += secTotal > 0 ? cnt / secTotal * 100 : 0;
                });
            });
        }

        sortedSectors.forEach(function (sec) {
            var secTotal = sectors[sec];
            h += '<tr style="border-bottom:1px solid #1a1a2a;">';
            h += '<td style="padding:4px 8px;font-weight:600;">' + sec + '</td>';
            h += '<td style="padding:4px;text-align:center;color:var(--text-faint);font-size:11px;">' + secTotal + '</td>';
            dims.forEach(function (d) {
                var cnt = (matrix[sec] || {})[d] || 0;
                var secPct = secTotal > 0 ? cnt / secTotal * 100 : 0;
                var ovPct = overallPct[d];
                var displayPct, tooltip, diff;
                if (mode === 'sector') {
                    displayPct = secPct; diff = secPct - ovPct;
                    tooltip = cnt + ' stocks | ' + secPct.toFixed(1) + '% of sector vs ' + ovPct.toFixed(1) + '% overall';
                } else {
                    var normalized = colSums[d] > 0 ? secPct / colSums[d] * 100 : 0;
                    displayPct = normalized;
                    var expectedShare = 100 / sortedSectors.length;
                    diff = normalized - expectedShare;
                    tooltip = secPct.toFixed(1) + '% of sector / ' + colSums[d].toFixed(0) + ' total = ' + normalized.toFixed(1) + '% (even = ' + expectedShare.toFixed(0) + '%)';
                }
                var bg = 'transparent';
                if (cnt > 0 && Math.abs(diff) > 3) {
                    var intensity = Math.min(Math.abs(diff) / 20, 0.5);
                    bg = diff > 0 ? hexToRgba(dimColors[d], intensity) : 'rgba(100,100,100,' + intensity * 0.5 + ')';
                }
                var textColor = cnt > 0 ? '#ccc' : '#333';
                h += '<td style="padding:4px;text-align:center;background:' + bg + ';color:' + textColor + ';font-size:11px;" title="' + tooltip + '">';
                h += cnt > 0 ? displayPct.toFixed(0) + '%' : '';
                h += '</td>';
            });
            h += '</tr>';
        });
        h += '</tbody></table>';

        h += '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">';
        h += mode === 'sector'
            ? '<span style="font-size:10px;color:var(--text-faint);">Each row sums to 100%. Colored = deviates from overall average.</span>'
            : '<span style="font-size:10px;color:var(--text-faint);">Each column sums to 100%. Shows which sectors concentrate most in each category relative to their own size. Hover for detail.</span>';
        h += '</div><div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:6px;">';
        dims.forEach(function (d) {
            h += '<span style="font-size:10px;padding:2px 6px;border-radius:3px;background:' + dimColors[d] + ';color:white;">' + d + ': ' + data.overall[d] + '</span>';
        });
        h += '</div>';

        var cutoffs = {
            rs_momentum: [['Improving', 'RS rank change 1M > +5 percentile points'], ['Stable', 'RS rank change 1M between -5 and +5'], ['Deteriorating', 'RS rank change 1M < -5 percentile points']],
            rs_bucket: [['RS 80+', '6-month return in top 20% of universe'], ['RS 60-80', '6-month return in 60th-80th percentile'], ['RS 40-60', '6-month return in 40th-60th percentile'], ['RS 20-40', '6-month return in 20th-40th percentile'], ['RS 0-20', '6-month return in bottom 20%']],
            pe_vs_sector: [['Deep Discount', 'PE < 0.7x sector median (30%+ cheaper)'], ['Discount', 'PE 0.7x-0.9x sector median'], ['Fair', 'PE 0.9x-1.1x sector median'], ['Premium', 'PE 1.1x-1.3x sector median'], ['High Premium', 'PE > 1.3x sector median (30%+ expensive)'], ['No PE', 'Negative or missing earnings']],
            eps_growth: [['Growing', 'FY1 EPS estimate > trailing EPS'], ['Declining', 'FY1 EPS estimate < trailing EPS'], ['Flat', 'FY1 EPS estimate = trailing EPS']],
            eps_momentum: [['Accelerating', '(FY2-FY1) growth > (FY1-TTM) growth'], ['Decelerating', '(FY2-FY1) growth < (FY1-TTM) growth']],
            pca_regime: [['Strong Leader', 'High RS, strong price trend, above MAs'], ['Quiet Uptrend', 'Above MAs, moderate momentum'], ['Erupting', 'High volatility breakout, sharp RS gain'], ['Distributing', 'Rolling over, weakening internals'], ['Declining', 'Below MAs, negative RS trend']],
            stage: [['Stage 1 Basing', 'Price consolidating around flat 200MA'], ['Stage 2 Uptrend', 'Price above rising MAs, confirmed uptrend'], ['Stage 3 Topping', 'MAs flattening, price volatile around 200MA'], ['Stage 4 Declining', 'Price below falling MAs, downtrend']],
        };
        var defs = cutoffs[data.dimension];
        if (defs) {
            h += '<div style="margin-top:10px;padding:8px 10px;background:var(--bg-card,#1a1a2a);border-radius:6px;border:1px solid var(--border,#333);">';
            h += '<div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:4px;">Category Definitions</div>';
            defs.forEach(function (def) {
                var c = dimColors[def[0]] || '#666';
                h += '<div style="font-size:11px;padding:1px 0;"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + c + ';margin-right:6px;"></span>';
                h += '<strong style="color:#ccc;">' + def[0] + '</strong> <span style="color:var(--text-faint);">— ' + def[1] + '</span></div>';
            });
            h += '</div>';
        }
        document.getElementById('map-summary').innerHTML = h;
    }

    var _mapSortDir = {};
    function sortMapTable(col, type) {
        var table = document.getElementById('map-table');
        if (!table) return;
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var pinned = document.getElementById('map-overall-row');
        var sortable = rows.filter(function (r) { return r.id !== 'map-overall-row'; });
        _mapSortDir[col] = !(_mapSortDir[col] || false);
        var asc = _mapSortDir[col];
        sortable.sort(function (a, b) {
            var aVal = a.cells[col] ? a.cells[col].textContent.trim() : '';
            var bVal = b.cells[col] ? b.cells[col].textContent.trim() : '';
            if (type === 'num') {
                aVal = parseFloat(aVal.replace(/[%x]/g, '')) || -Infinity;
                bVal = parseFloat(bVal.replace(/[%x]/g, '')) || -Infinity;
                return asc ? aVal - bVal : bVal - aVal;
            }
            return asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        });
        if (pinned) tbody.appendChild(pinned);
        sortable.forEach(function (r) { tbody.appendChild(r); });
    }

    // ===== Row selection + Send-to-Monitor (effort 2026-06-18) =================
    // A leading checkbox column lets the user pick a subset of the filtered rows and
    // push them (or the entire filtered set) into a dedicated `screener` MKLists list
    // that the Monitor workspace opens via /monitor?list=screener. Selection is keyed
    // by symbol so it survives re-render (sort / column toggle).
    var _selectedSyms = {};
    function _selCount() { return Object.keys(_selectedSyms).length; }
    function _allSyms() {
        var data = SD();
        if (!data || !data.rows) return [];
        var si = data.columns.indexOf('Symbol');
        if (si < 0) return [];
        return data.rows.map(function (r) { return r[si]; }).filter(Boolean);
    }
    function _buildSelAllTh() {
        var th = document.createElement('th');
        th.setAttribute('style', 'width:30px;text-align:center;cursor:default');
        var cb = document.createElement('input');
        cb.type = 'checkbox'; cb.id = 'scr-selall'; cb.title = 'Select all filtered';
        cb.onclick = function (e) { e.stopPropagation(); };
        cb.onchange = function () { _toggleSelectAll(this.checked); };
        th.appendChild(cb);
        return th;
    }
    function _buildRowChk(sym) {
        var td = document.createElement('td');
        td.setAttribute('style', 'width:30px;text-align:center;padding:3px 0');
        var cb = document.createElement('input');
        cb.type = 'checkbox'; cb.className = 'scr-rowchk'; cb.setAttribute('data-sym', sym);
        cb.checked = !!_selectedSyms[sym];
        cb.onclick = function (e) { e.stopPropagation(); };
        cb.onchange = (function (s) { return function () {
            if (this.checked) _selectedSyms[s] = true; else delete _selectedSyms[s];
            _syncSelectionUI();
        }; })(sym);
        td.appendChild(cb);
        return td;
    }
    function _toggleSelectAll(on) {
        _allSyms().forEach(function (s) { if (on) _selectedSyms[s] = true; else delete _selectedSyms[s]; });
        document.querySelectorAll('#screener-table tbody input.scr-rowchk').forEach(function (cb) { cb.checked = on; });
        _syncSelectionUI();
    }
    function _syncSelectionUI() {
        var n = _selCount();
        var btn = document.getElementById('scr-send-selected');
        if (btn) {
            btn.textContent = 'Send selected → Monitor (' + n + ')';
            btn.disabled = n === 0;
            btn.style.opacity = n === 0 ? '0.5' : '1';
            btn.style.cursor = n === 0 ? 'default' : 'pointer';
        }
        var all = document.getElementById('scr-send-all');
        if (all) { var t = _allSyms().length; all.textContent = 'Send all ' + t + ' → Monitor'; }
        var selAll = document.getElementById('scr-selall');
        if (selAll) {
            var total = _allSyms().length;
            selAll.checked = total > 0 && n >= total;
            selAll.indeterminate = n > 0 && n < total;
        }
    }
    // Push symbols into the dedicated `screener` list and open the Monitor workspace
    // on it. mode='all' sends the whole filtered set; otherwise the checked subset.
    // Each send creates a NEW uniquely-named watchlist ("screener 1", "screener 2", …)
    // so successive sends never clobber each other. The next index = 1 + the highest N
    // among existing "screener N" lists (from /api/watchlist/lists).
    function _nextScreenerList(names) {
        var max = 0;
        (names || []).forEach(function (n) {
            var m = /^screener\s+(\d+)$/i.exec(String(n).trim());
            if (m) { var k = parseInt(m[1], 10); if (k > max) max = k; }
        });
        return 'screener ' + (max + 1);
    }
    function sendToMonitor(mode) {
        var syms = (mode === 'all') ? _allSyms() : Object.keys(_selectedSyms);
        syms = syms.filter(Boolean);
        if (!syms.length) { alert('No stocks selected.'); return; }
        var btn = document.getElementById(mode === 'all' ? 'scr-send-all' : 'scr-send-selected');
        var label = btn ? btn.textContent : '';
        var restore = function () { if (btn) { btn.disabled = false; btn.textContent = label; } };
        if (btn) { btn.disabled = true; btn.textContent = 'Sending ' + syms.length + '…'; }
        // 1) read existing lists -> pick a fresh "screener N"; 2) bulk-add into it
        // (no replace — it's brand new); 3) open Monitor on that list.
        fetch('/api/watchlist/lists')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var listName = _nextScreenerList(data && data.lists);
                return fetch('/api/watchlist/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ list: listName, symbols: syms })
                }).then(function (r) { return r.json(); }).then(function (res) {
                    if (res && res.status === 'ok') {
                        window.location = '/monitor?list=' + encodeURIComponent(listName);
                    } else { restore(); alert('Send to Monitor failed.'); }
                });
            })
            .catch(function (e) { restore(); alert('Send to Monitor failed: ' + e); });
    }

    // ===== Prop scans — named filter sets saved in localStorage (this browser) ====
    // A "prop scan" is the current filtered URL (filters + cols + sort) stored under a
    // user name; recall navigates straight back to it. localStorage per the user's
    // choice (no server/DB) — see effort prd.md.
    var _SCAN_KEY = 'mktt_prop_scans';
    function _loadScans() {
        try { var o = JSON.parse(localStorage.getItem(_SCAN_KEY) || '{}'); return (o && typeof o === 'object') ? o : {}; }
        catch (e) { return {}; }
    }
    function _saveScans(o) { try { localStorage.setItem(_SCAN_KEY, JSON.stringify(o)); } catch (e) {} }
    function savePropScan() {
        var name = (window.prompt('Save current filters as a prop scan — name:') || '').trim();
        if (!name) return;
        var scans = _loadScans();
        scans[name] = window.location.href;   // full filtered URL (filters + cols + sort)
        _saveScans(scans);
        initPropScans(name);
    }
    function loadPropScan(name) {
        if (!name) return;
        var scans = _loadScans();
        if (scans[name]) window.location.href = scans[name];
    }
    function deletePropScan() {
        var sel = document.getElementById('prop-scan-select');
        if (!sel || !sel.value) { alert('Pick a saved scan to delete.'); return; }
        var name = sel.value;
        if (!window.confirm('Delete prop scan "' + name + '"?')) return;
        var scans = _loadScans();
        delete scans[name];
        _saveScans(scans);
        initPropScans();
    }
    function initPropScans(selectName) {
        var sel = document.getElementById('prop-scan-select');
        if (!sel) return;
        var scans = _loadScans();
        var names = Object.keys(scans).sort();
        sel.innerHTML = '';
        var o0 = document.createElement('option'); o0.value = ''; o0.textContent = names.length ? 'Saved scans…' : 'No saved scans';
        sel.appendChild(o0);
        names.forEach(function (n) {
            var o = document.createElement('option'); o.value = n; o.textContent = n;
            if (n === selectName) o.selected = true;
            sel.appendChild(o);
        });
    }

    // ===== Slice 3: single idempotent init + keep-alive snapshot hooks =====
    // initScreener() (re)binds the column picker and renders the flat table from the
    // embedded SCREENER_DATA. It is called on first DOMContentLoaded AND by the
    // keep-alive (keepalive.js) after it re-injects the screener HTML into #app-content.
    // Idempotent: only DOM-touching setup runs, and it clears+rebinds as needed.
    function initScreener() {
        bindDocOnce();     // idempotent (guarded): the ticker-dropdown close listener.
        initColPicker();   // idempotent: clears #col-checks, rebinds change handlers,
                           // applies VISIBLE_COLS, and renders the flat table.
        initPropScans();   // idempotent: rebuild the saved-scan dropdown from localStorage.
        // Default view = Sectors (Change A). The keep-alive RESTORE path drives the
        // view itself via screenerRestoreState() right after this, so it sets
        // window._screenerRestoring to skip this default (and avoid a flat<->sectors
        // flicker before restore). Only apply the sectors default on a normal,
        // non-restore init, and only when the Sectors view actually exists.
        if (!window._screenerRestoring && document.getElementById('view-sectors')) {
            switchView('sectors');
        }
        if (typeof window._screenerOnInit === 'function') {
            try { window._screenerOnInit(); } catch (e) {}
        }
    }

    // State accessors for the keep-alive snapshot (read/restore scroll/sort/view/cols).
    function screenerGetState() {
        var view = 'flat';
        var sectors = document.getElementById('view-sectors');
        var map = document.getElementById('view-map');
        if (sectors && sectors.style.display !== 'none') view = 'sectors';
        else if (map && map.style.display !== 'none') view = 'map';
        return {
            scrollY: window.scrollY || window.pageYOffset || 0,
            sort: { col: _flatSort.col, asc: _flatSort.asc },
            view: view,
            cols: VIS().slice(),
            filterQuery: window.location.search || ''
        };
    }
    function screenerRestoreState(st) {
        if (!st) return;
        try {
            if (st.cols && st.cols.length) {
                setVIS(st.cols.slice());
                // reflect into the picker checkboxes
                document.querySelectorAll('#col-checks input[type=checkbox]').forEach(function (cb) {
                    cb.checked = VIS().indexOf(cb.value) !== -1;
                });
            }
            if (st.sort && st.sort.col) { _flatSort.col = st.sort.col; _flatSort.asc = !!st.sort.asc; }
            renderFlatTable();
            if (st.view && st.view !== 'flat') switchView(st.view);
            else switchView('flat');
            // scroll last (after layout settles)
            var y = st.scrollY || 0;
            window.scrollTo(0, y);
            requestAnimationFrame(function () { window.scrollTo(0, y); });
        } catch (e) {
            // any restore failure is non-fatal: the keep-alive layer falls back.
        }
    }

    // ---- document-level listeners (bound ONCE; the document survives an
    // #app-content innerHTML swap, so a keep-alive re-init must not re-add them). ----
    function bindDocOnce() {
        if (window._screenerDocBound) return;
        window._screenerDocBound = true;
        document.addEventListener('click', function (e) {
            if (!e.target.closest('#ticker-search') && !e.target.closest('#ticker-dropdown')) {
                var dd = document.getElementById('ticker-dropdown'); if (dd) dd.style.display = 'none';
            }
        });
    }

    // ---- expose the inline-onclick + keep-alive surface on window --------------
    // Inline onclick="" handlers resolve in global scope, so these MUST be global.
    window.initScreener = initScreener;
    window.renderFlatTable = renderFlatTable;
    window.sortTable = sortTable;
    window.sortBy = sortBy;
    window.switchView = switchView;
    window.toggleColGroup = toggleColGroup;
    window.addPctileCols = addPctileCols;
    window.applyColVisibility = applyColVisibility;
    window.initColPicker = initColPicker;
    window.tickerAutocomplete = tickerAutocomplete;
    window.tickerGo = tickerGo;
    window.toggleStockChart = toggleStockChart;
    window.sendToMonitor = sendToMonitor;
    window.savePropScan = savePropScan;
    window.loadPropScan = loadPropScan;
    window.deletePropScan = deletePropScan;
    window.initPropScans = initPropScans;
    window.toggleSectorStocks = toggleSectorStocks;
    window.toggleIndustry = toggleIndustry;
    window.switchSectorTab = switchSectorTab;
    window.sortSectorTable = sortSectorTable;
    window.sortSubTable = sortSubTable;
    window.loadSectorMap = loadSectorMap;
    window.setMapMode = setMapMode;
    window.renderMap = renderMap;
    window.sortMapTable = sortMapTable;
    window.screenerGetState = screenerGetState;
    window.screenerRestoreState = screenerRestoreState;

    // ---- auto-init (inert on non-screener pages) ------------------------------
    // ONLY initialize when the screener DOM is present. On Monitor/RRG/etc. the
    // #screener-table does not exist, so this is a no-op — the global functions are
    // merely DEFINED (ready for keepalive to call after it injects the screener shell).
    function maybeAutoInit() {
        if (!document.getElementById('screener-table')) {
            dbg('no #screener-table on this page -> screener.js inert (functions defined only)');
            return;
        }
        initScreener();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', maybeAutoInit);
    } else {
        maybeAutoInit();
    }
})();
