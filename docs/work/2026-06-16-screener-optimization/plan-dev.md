# plan-dev.md — Screener optimization (TDD execution plan)

Tactics for `prd.md`. Decisions locked: **hybrid** (adr/0004) + **invalidate-on-data-update**. Server
logic is TDD'd (`src/mktt/tests/`); client behavior is browser-verified by the orchestrator. Run tests
from `src/mktt/`: `python -m pytest -q`. Each slice keeps the existing screener suite green.

Dependency order: **S1 (cache + version) → S2 (selected-col + embedded JSON) → S4 (jank) → S3 (keep-alive)**
(S3 needs S1's version endpoint + S2's embedded JSON; S2/S1 share `service.py`/template → sequential).

---

## Slice 1 — Server pipeline cache + freshness version + version endpoint · DONE
**Goal:** repeated/identical screener requests (back-nav, same filters) skip the heavy recompute; never
serve staler-than-data.
### Interface
1. **`computed`/`ComputedStore`**: expose a monotonic **freshness version** that bumps on `upsert()`
   (e.g. an in-proc counter or `max(updated_at)` token) — `cross_section_version() -> str|int`.
2. **`data`/datasource**: expose the **price-parquet mtime** used by the technicals path
   (`price_panel_version() -> float`), so the cache key reflects parquet updates.
3. **`screener.service`**: wrap `_pipeline(req, data, computed)` in a bounded LRU **result cache** keyed
   on `(ScreenRequest identity, cross_section_version, price_panel_version)`. Hit → return the cached
   `_PipelineResult` (a copy / immutable). Miss → compute + store. No global mutable leak. The cache key
   MUST include the two freshness tokens so a data change invalidates instantly. Keep the existing 30s
   `cross_section` cache underneath.
4. **Route**: `GET /api/screener/version` → `{ "version": "<cross_section_version>:<price_panel_version>" }`
   (thin; for the client keep-alive token check in S3).
### Behaviors to test
1. Two identical requests → `_pipeline` heavy work runs once (cache hit second time) — assert via a
   spy/counter on the expensive call (e.g. `data.fundamentals` call count).
2. Bumping `cross_section_version` (simulate `upsert`) invalidates → recompute.
3. Bumping `price_panel_version` (simulate parquet change) invalidates → recompute.
4. Different `ScreenRequest` (filter/sort/preset/cols) → distinct cache entries (no cross-serve).
5. `GET /api/screener/version` returns the combined token; changes when either token changes.
6. Cached result is value-equal to the fresh result (no staleness, no mutation of the cache).
### DoD
Tests green; existing screener tests green. Section stays DI; cache is process-local + bounded.

---

## Slice 2 — Render only selected columns + embed result JSON · DONE (server; client browser-verify pending)
**Goal:** the DOM materializes only selected columns; the client has the full data embedded for instant
toggle/sort/keep-alive.
### Interface
1. **`ScreenRequest`**: parse `cols` (comma-separated column ids); default = the current visible set
   (the ~21 the template shows today) when absent. Validate against `RESULT_COLUMNS` (drop unknowns).
2. **`handle_page`**: pass `visible_cols` (ordered, validated) to the template; ALSO emit the **full**
   result rows × all `RESULT_COLUMNS` as a compact structure for embedding (`screener_data = {columns,
   rows}`), independent of `visible_cols`.
3. **`screener.html`**: make the flat table **data-driven** — `<thead>`/`<tbody>` loop over
   `visible_cols` only (emit just those `<td>`), preserving the existing per-column formatting/coloring.
   Embed `var SCREENER_DATA = {{ screener_data|tojson }};` once. The column picker now: (a) updates the
   selected set in the URL (`?cols=…`) + localStorage, (b) re-renders the visible columns **client-side
   from `SCREENER_DATA`** (instant; no full reload, no 100k-node scan). Sort also re-renders from
   `SCREENER_DATA` (or batched DOM — see S4).
### Behaviors to test (server)
1. `handle_page` with `cols=symbol,price,rs` → context `visible_cols == [symbol, price, rs]` (valid,
   ordered); template-facing data restricted to those for the rendered table.
2. Absent `cols` → the default visible set.
3. Unknown col ids dropped; empty → default (never an empty table).
4. `screener_data` carries ALL columns + all passed rows (full precision) regardless of `visible_cols`.
### DoD
Server tests green. Browser-verify (orchestrator): only selected columns in the DOM; toggling a column
re-renders instantly from embedded data (no reload); numbers identical; `?cols=` round-trips on reload.

---

## Slice 4 — Jank / smoothness fixes · DONE
**Goal:** smooth first paint, scroll, sort.
### Interface (CSS/JS in screener.html / style.css)
1. `table-layout: fixed` + explicit column widths on `#screener-table` (kills measure-before-render).
2. Sort re-render uses `DocumentFragment` / `replaceChildren` (one reflow, not N `appendChild`).
3. `content-visibility: auto; contain-intrinsic-size: auto 28px` on flat `<tr>` (skip offscreen
   paint/layout on scroll).
4. Remove the now-moot all-columns `applyColVisibility` 100k-node scan (S2 renders only selected).
### DoD
Browser-verify: visibly smoother scroll + faster sort, no CLS flash; no console errors; data unchanged.

---

## Slice 3 — Client keep-alive (instant back) · DONE (renderer extracted; restore-from-any-page active; browser-verify pending)
<!-- S3 quota bug fixed earlier (snapshot = data+stripped-shell, 35 MB -> 2.80 MB, persists). The
     restore-from-Monitor blocker (renderer trapped in the screener page's inline <script>) is now
     RESOLVED: the render/sort/picker/view logic was extracted to a GLOBAL static/js/screener.js loaded
     by base.html on every page (inert until #screener-table is present). keepalive.js restore no longer
     declines for "renderer absent" on the flat view — it re-seats the window globals, injects the shell,
     and calls window.initScreener()/screenerRestoreState() which now exist everywhere. Fallback to
     navigation kept for: stale token, filter-query mismatch, view != flat, or any restore throw.
     See log.md REPORT (renderer extraction). Browser-verify by the orchestrator. -->

### S3 follow-up — renderer extraction (global screener.js) · DONE (browser-verify pending)
**Goal:** the screener client renderer lives in a globally-loaded static JS file so the keep-alive can
rebuild the flat view from ANY page after an `#app-content` swap.
- `static/js/screener.js` (new): all PURE-JS render/sort/picker/view logic moved out of the screener
  template's inline `<script>`. Reads server data from `window.*`; exposes the inline-onclick +
  keep-alive surface on `window`; auto-inits ONLY when `#screener-table` is present (inert elsewhere).
- `screener.html`: inline `<script>` reduced to a tiny Jinja data-injection block
  (`window.SCREENER_DATA/FLAT_COL_SPEC/ALL_COLS/VISIBLE_COLS/SECTOR_MAP/_TICKERS = {{…|tojson}}`); no logic.
- `base.html`: loads `screener.js` on every page (after `keepalive.js`).
- `keepalive.js`: removed the "renderer absent → decline" guard for the flat view (renderer now global);
  all other fallbacks (token/filter mismatch, non-flat view, any throw) preserved; snapshot shape unchanged.
**Goal:** returning to the screener restores instantly, no reload / no heavy pipeline, state preserved.
### Interface (client; base.html nav + screener.html)
1. On leaving `/screener`, **snapshot** `{ token, html-or-data, state:{scroll,sort,view,cols,filters} }`
   to `sessionStorage` (survives navigation within the tab).
2. Intercept navigation to `/screener` (the nav tab + Monitor→Screener): fetch `GET /api/screener/version`
   (tiny); if it **matches** the snapshot token AND the requested filters match → restore the snapshot
   instantly (client render from embedded `SCREENER_DATA`/cached DOM + `history.pushState`), **no full
   navigation**. Else → normal navigation (server render).
3. Restore scroll position, sort, active view, selected columns. Browser **Back** stays bfcache-eligible
   (no unload/no-store added).
### DoD
Browser-verify: load screener → go to Monitor → return via tab → **instant**, no reload flash, table +
scroll + sort + view + columns preserved; after a (simulated) data change the token differs → it falls
back to a fresh render (integrity). No console errors.
