// keepalive.js — Slice 3 (adr/0004): instant return to the screener.
//
// Once the screener has loaded, returning to it (clicking the SCREENER nav tab,
// Monitor->Screener, or browser back/forward) restores INSTANTLY from a client
// snapshot — no full page navigation, no heavy pipeline round-trip — guarded by a
// tiny `/api/screener/version` freshness check. If anything is missing, stale, or
// the restore throws, it ALWAYS falls back to a normal server render (integrity +
// robustness over cleverness). Scope is the /screener path ONLY — this is NOT an
// app-wide SPA.
//
// Debug logging is off by default; enable with `localStorage.KA_DEBUG = '1'`.
(function () {
    'use strict';

    var SNAP_KEY = 'mktt_screener_snapshot';
    var APP = 'app-content';
    var SCREENER_PATHS = { '/': true, '/screener': true };

    function dbg() {
        try {
            if (localStorage.getItem('KA_DEBUG') === '1') {
                console.debug.apply(console, ['[keepalive]'].concat([].slice.call(arguments)));
            }
        } catch (e) {}
    }

    function pathOf(href) {
        try { return new URL(href, window.location.origin).pathname; }
        catch (e) { return ''; }
    }
    function searchOf(href) {
        try { return new URL(href, window.location.origin).search || ''; }
        catch (e) { return ''; }
    }
    function isScreenerPath(p) { return !!SCREENER_PATHS[p]; }
    function onScreenerNow() { return isScreenerPath(window.location.pathname); }

    // ---- snapshot persistence -------------------------------------------------
    function readSnapshot() {
        try {
            var raw = sessionStorage.getItem(SNAP_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }
    function clearSnapshot() {
        try { sessionStorage.removeItem(SNAP_KEY); } catch (e) {}
    }

    // The freshness token embedded by the screener (server SCREENER token).
    // We don't have it inline, so we read it lazily off the live /api on snapshot
    // capture — cheap, and only while ON the screener page.
    var _tokenCache = null;
    function fetchVersion() {
        return fetch('/api/screener/version', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) { return j ? j.version : null; })
            .catch(function () { return null; });
    }

    // ---- stripped shell ------------------------------------------------------
    // The full #app-content innerHTML is ~35 MB (the 4119-row flat table + the
    // ~8500-row hidden sector hierarchy) and blows the ~5 MB sessionStorage quota,
    // so we NEVER store rendered rows. Instead we store:
    //   data  = the embedded SCREENER_DATA (~1.8 MB) + the render globals, and
    //   shell = #app-content with EVERY heavy <tbody> emptied (tens of KB: the
    //           filter form, picker, view buttons, table skeleton + colgroup).
    // On restore we inject `shell`, re-seat the globals, and re-render the flat
    // table from `data` (see restoreFromSnapshot). If the render functions are not
    // available, restore declines and the caller falls back to a normal navigation.
    function buildShell(app) {
        try {
            var clone = app.cloneNode(true);
            // Empty every tbody (flat table rows AND the big sector hierarchy + any
            // nested sub-tables) — that is the bulk of the ~36 MB payload.
            var bodies = clone.querySelectorAll('tbody');
            for (var i = 0; i < bodies.length; i++) bodies[i].innerHTML = '';
            // The Map view summary is server/JS-rendered into this container — drop it.
            var mapSummary = clone.querySelector('#map-summary');
            if (mapSummary) mapSummary.innerHTML = '';
            // Drop the inline <script> blocks: they DO NOT execute when injected via
            // innerHTML (so they are dead weight), AND they embed a second ~2 MB copy
            // of SCREENER_DATA. The render globals travel in snap.data instead, and the
            // renderer is the live page's functions (we restore only where they exist).
            var scripts = clone.querySelectorAll('script');
            for (var j = 0; j < scripts.length; j++) {
                scripts[j].parentNode && scripts[j].parentNode.removeChild(scripts[j]);
            }
            return clone.innerHTML;
        } catch (e) {
            dbg('buildShell failed', e);
            return null;
        }
    }

    // The render globals the screener template embeds (Slice 2). We snapshot them so
    // the renderer (initScreener -> renderFlatTable) can rebuild the flat table after
    // the shell is injected, WITHOUT shipping 35 MB of rendered DOM.
    function captureRenderData() {
        try {
            return {
                screener_data: window.SCREENER_DATA || null,
                flat_col_spec: window.FLAT_COL_SPEC || null,
                all_cols: window.ALL_COLS || null,
                visible_cols: window.VISIBLE_COLS || null
            };
        } catch (e) { return null; }
    }

    // Capture the current screener into the snapshot. `full` controls whether we
    // rebuild the (small) shell + render data — true on init/pagehide, false for the
    // debounced state-only refresh during sort/toggle/scroll (which only needs state).
    function captureSnapshot(full) {
        if (!onScreenerNow()) return;
        var app = document.getElementById(APP);
        if (!app) return;
        var state = (typeof window.screenerGetState === 'function')
            ? window.screenerGetState()
            : { scrollY: window.scrollY || 0, sort: null, view: 'flat', cols: null, filterQuery: window.location.search || '' };

        var prev = readSnapshot();
        var snap = {
            token: (prev && prev.token) || _tokenCache || null,
            url: window.location.href,
            state: state,
            data: full ? captureRenderData() : (prev ? prev.data : captureRenderData()),
            shell: full ? buildShell(app) : (prev ? prev.shell : buildShell(app))
        };

        // Persist. If even data+shell overflows the quota, drop `shell` (it can be
        // reconstructed from the live page on the next full capture) and keep at least
        // data+state. If that still throws, we simply have no snapshot -> safe nav.
        if (!trySaveSnapshot(snap)) {
            var lite = { token: snap.token, url: snap.url, state: snap.state, data: snap.data, shell: null };
            if (!trySaveSnapshot(lite)) {
                dbg('snapshot does not fit even without shell -> no keep-alive this load');
                clearSnapshot();
            }
        }
        dbg('captureSnapshot', { full: !!full, token: snap.token, view: state.view, savedBytes: _lastSavedBytes });

        // Make sure the token is current (async; updates the stored snapshot when back).
        if (full || !snap.token) {
            fetchVersion().then(function (v) {
                if (v == null) return;
                _tokenCache = v;
                var cur = readSnapshot();
                if (cur && cur.token == null) { cur.token = v; trySaveSnapshot(cur); }
                else if (cur && cur.token !== v) { cur.token = v; trySaveSnapshot(cur); }
            });
        }
    }

    // Try to persist a snapshot; returns true on success, false on QuotaExceededError
    // (or any setItem throw). Records the serialized size for the debug/REPORT.
    var _lastSavedBytes = 0;
    function trySaveSnapshot(snap) {
        try {
            var s = JSON.stringify(snap);
            sessionStorage.setItem(SNAP_KEY, s);
            _lastSavedBytes = s.length;
            return true;
        } catch (e) {
            dbg('trySaveSnapshot threw', e && e.name, e);
            return false;
        }
    }

    // ---- restore --------------------------------------------------------------
    // Returns true if it restored from the snapshot; false => caller must fall back
    // to a normal navigation. Never leaves a broken page: we only swap #app-content
    // AFTER confirming we can actually rebuild it (renderer present, flat view, data
    // present). On any throw, restore the original DOM and return false.
    function restoreFromSnapshot(snap, targetUrl) {
        var app = document.getElementById(APP);
        if (!app || !snap || !snap.shell || !snap.data) {
            dbg('restore declined: missing shell/data -> nav');
            return false;
        }
        // Scope to the flat view only. Sectors/Map data is server-rendered (not in
        // SCREENER_DATA) so it cannot be rebuilt client-side — fall back to a real nav.
        if (snap.state && snap.state.view && snap.state.view !== 'flat') {
            dbg('restore declined: view=' + snap.state.view + ' (not flat) -> nav');
            return false;
        }
        // The renderer (initScreener / renderFlatTable / screenerRestoreState) is now
        // extracted into the global static/js/screener.js (loaded by base.html on EVERY
        // page), so it exists here even on Monitor/RRG/etc. — no "renderer absent" decline
        // needed any more. If it somehow failed to load, the call below throws and the
        // try/catch restores the original DOM and falls back to navigation.
        if (!snap.data.screener_data || !snap.data.flat_col_spec) {
            dbg('restore declined: render data incomplete -> nav');
            return false;
        }
        var saved = app.innerHTML;
        try {
            // Re-seat the render globals the screener renderer reads, THEN inject the
            // (small) stripped shell, THEN rebuild the flat table from the data.
            window.SCREENER_DATA = snap.data.screener_data;
            window.FLAT_COL_SPEC = snap.data.flat_col_spec;
            if (snap.data.all_cols) window.ALL_COLS = snap.data.all_cols;
            if (snap.data.visible_cols) window.VISIBLE_COLS = snap.data.visible_cols;
            app.innerHTML = snap.shell;
            // Flag the restore so initScreener() does NOT apply its default-to-Sectors
            // view (Change A): screenerRestoreState() drives the view authoritatively
            // (only the flat view is data-driven for restore). Cleared in finally.
            window._screenerRestoring = true;
            try {
                window.initScreener();                   // renders the flat table from data
                window.screenerRestoreState(snap.state); // sort / cols / scroll / flat view
            } finally {
                window._screenerRestoring = false;
            }
            history.pushState(null, '', targetUrl || snap.url);
            markScreenerTabActive(true);
            dbg('restoreFromSnapshot OK', targetUrl || snap.url);
            return true;
        } catch (e) {
            dbg('restoreFromSnapshot threw -> restore DOM + fall back', e);
            try { app.innerHTML = saved; } catch (e2) {}
            return false;
        }
    }

    function markScreenerTabActive(active) {
        try {
            var tabs = document.querySelectorAll('.tab-bar .tab');
            tabs.forEach(function (t) { t.classList.remove('active'); });
            var sc = document.getElementById('screener-tab');
            if (sc && active) sc.classList.add('active');
        } catch (e) {}
    }

    // Decide whether an intercepted navigation to a /screener URL can be served from
    // the snapshot. Resolves to true (restored) or false (let nav proceed).
    function tryInstantReturn(targetHref) {
        var snap = readSnapshot();
        if (!snap || !snap.shell || !snap.data) { dbg('no snapshot -> nav'); return Promise.resolve(false); }
        var targetSearch = searchOf(targetHref);
        var snapSearch = (snap.state && snap.state.filterQuery) || '';
        // Filters must match (the snapshot reflects a specific filtered result set).
        // Compare the non-`cols` query parts so a column toggle alone still restores.
        if (!queriesMatchIgnoringCols(targetSearch, snapSearch)) {
            dbg('filter mismatch -> nav', { targetSearch: targetSearch, snapSearch: snapSearch });
            return Promise.resolve(false);
        }
        return fetchVersion().then(function (v) {
            if (v == null) { dbg('version fetch failed -> nav'); return false; }
            if (snap.token == null) { dbg('snapshot token unknown -> nav'); return false; }
            if (v !== snap.token) { dbg('token moved -> fresh nav', { live: v, snap: snap.token }); return false; }
            return restoreFromSnapshot(snap, targetHref);
        }).catch(function (e) { dbg('tryInstantReturn error -> nav', e); return false; });
    }

    // Compare two query strings ignoring the `cols` param (column selection is a
    // pure client-side view concern and the snapshot can re-apply any cols).
    function queriesMatchIgnoringCols(a, b) {
        try {
            var pa = new URLSearchParams(a); pa.delete('cols');
            var pb = new URLSearchParams(b); pb.delete('cols');
            pa.sort(); pb.sort();
            return pa.toString() === pb.toString();
        } catch (e) { return a === b; }
    }

    // ---- click interception ---------------------------------------------------
    function onClick(e) {
        // Only plain left-clicks without modifier keys.
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        if (a.target && a.target !== '' && a.target !== '_self') return;
        var href = a.href;
        if (!href) return;
        if (pathOf(href) && !isScreenerPath(pathOf(href))) return;  // scope: /screener only
        if (!isScreenerPath(pathOf(href))) return;
        // If we are ALREADY on the screener, let in-page handlers / normal nav run.
        if (onScreenerNow() && pathOf(href) === window.location.pathname) return;

        // Defer the decision to the async version check, but we must decide synchronously
        // whether to preventDefault. Strategy: preventDefault now, then either restore or
        // perform the navigation ourselves on the async result.
        e.preventDefault();
        tryInstantReturn(href).then(function (restored) {
            if (!restored) { window.location.href = href; }
        });
    }

    // ---- popstate (browser back/forward) --------------------------------------
    function onPopState() {
        // If the bfcache restored the real page, document is intact and this handler
        // may not even fire. When it does and we've navigated TO a screener URL while
        // the live DOM is NOT the screener, attempt a snapshot restore; else reload.
        var p = window.location.pathname;
        if (!isScreenerPath(p)) return;  // not navigating to the screener — nothing to do
        // Is the screener already live in the DOM? (bfcache / same page)
        if (document.getElementById('screener-table') || document.querySelector('#app-content h2.page-title')) {
            // Already a screener DOM — just re-mark the tab; nothing to inject.
            markScreenerTabActive(true);
            return;
        }
        var snap = readSnapshot();
        if (!snap || !snap.shell || !snap.data) { window.location.reload(); return; }
        fetchVersion().then(function (v) {
            if (v != null && snap.token != null && v === snap.token &&
                restoreFromSnapshot(snap, window.location.href)) {
                return;
            }
            window.location.reload();
        }).catch(function () { window.location.reload(); });
    }

    // ---- wiring ---------------------------------------------------------------
    function init() {
        document.addEventListener('click', onClick, true);  // capture: beat in-page handlers
        window.addEventListener('popstate', onPopState);

        if (onScreenerNow()) {
            // Snapshot after the screener has initialized its table/state.
            var snapNow = function () { captureSnapshot(true); };
            if (document.readyState === 'complete') snapNow();
            else window.addEventListener('load', snapNow);

            // Keep the snapshot's lightweight state fresh as the user interacts.
            var t = null;
            var refresh = function () {
                if (t) clearTimeout(t);
                t = setTimeout(function () { captureSnapshot(false); }, 150);
            };
            window.addEventListener('scroll', refresh, { passive: true });
            document.addEventListener('click', refresh, true);   // sort / toggle / view
            document.addEventListener('change', refresh, true);  // column checkboxes

            // Rebuild the (small) shell + render data right before leaving so the
            // snapshot exists when we land elsewhere. pagehide keeps the page bfcache-
            // eligible (unlike unload/beforeunload). This was the load-bearing fix:
            // previously we stored the full ~35 MB innerHTML here and setItem threw
            // QuotaExceededError, so NO snapshot was ever persisted.
            window.addEventListener('pagehide', function () { captureSnapshot(true); });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
