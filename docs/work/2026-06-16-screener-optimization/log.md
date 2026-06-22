# Log — Screener optimization

Append-only. Agents: read open FLAGs + recent entries before starting; append a REPORT when done.

## 2026-06-16 · orchestrator · REPORT (effort opened, PRD accepted)
New effort to optimize the screener (instant back, only-selected columns, smooth, zero integrity loss).
Ideation = 2 parallel explorer subagents (server data/cache flow + frontend render/glitches). Key
findings: full pipeline + ~100k-node Jinja render on every visit; only `cross_section` 30s-cached;
columns rendered-then-CSS-hidden; tab-click = full reload (no client cache); jank from no
`table-layout:fixed` / `appendChild` sort / hidden sector hierarchy. Grill resolved the architecture:
- **Hybrid** (adr/0004): server-render first load + render only selected columns + embed result JSON for
  client toggle/sort/keep-alive + client keep-alive for instant revisit + jank fixes.
- **Freshness = invalidate on data update**: server caches key on cross_section version + parquet mtime;
  client keep-alive checks `/api/screener/version`. Never staler than the data.
PRD `prd.md`, ADR `docs/adr/0004`, tactics `plan-dev.md` (slices S1 cache+version → S2 selected-col+JSON
→ S4 jank → S3 keep-alive). Next: dispatch S1.

## 2026-06-16 · developer · REPORT (S1 — pipeline cache + freshness version + version endpoint)
Task: `plan-dev.md` → Slice 1. Strict TDD, no open FLAGs hit. DONE.

Built (invalidate-on-data-update; cache key = request identity + both freshness tokens):
- `ComputedStore.cross_section_version() -> int` — monotonic in-proc counter, starts at 1, **bumps in
  `upsert()`** (alongside the existing `invalidate_cross_section_cache()`); the 30s `_xs_cache` is
  unchanged. `src/mktt/computed/store.py`.
- `EquitySubmodule.price_panel_version() -> float` — newest mtime across the present price/volume
  panels (`close.parquet`/`volume.parquet`); `0.0` sentinel when absent. Exposed on `DataSource`
  (delegates to `_equity`). `src/mktt/datasource/submodules/equity.py`, `datasource/provider.py`.
- `screener.service` pipeline cache — `_cached_pipeline(req, data, computed)` wraps `_pipeline` in a
  bounded process-local LRU (`_PIPELINE_CACHE`, max 16, evict-oldest) keyed on
  `(_request_identity(req), cross_section_version, price_panel_version)`. Hit → returns a defensive
  copy WITHOUT re-running heavy work; miss → compute + store copy. `_clear_pipeline_cache()` exposed
  for tests. `_request_identity` freezes the dataclass's dict/list fields into a hashable tuple.
  `handle`/`handle_page` now call `_cached_pipeline` (transparent; numbers unchanged). Token accessors
  `cross_section_version(computed)` / `price_panel_version(data)` are best-effort (None on bare stubs).
  `src/mktt/sections/screener/service.py`.
- Route `GET /api/screener/version` → `{"version": "<xs>:<panel>"}` (thin). `sections/screener/routes.py`.

Behaviors covered (all 6 gate behaviors + provider wiring):
- `test_identical_requests_skip_heavy_recompute` (heavy work runs once; 2nd is a hit)
- `test_cross_section_version_bump_invalidates`, `test_price_panel_version_bump_invalidates`
- `test_different_requests_are_distinct_cache_entries`, `test_cache_hit_value_equals_fresh_compute`
  (incl. mutation-isolation), `test_version_endpoint_returns_combined_token`
- provider unit tests: `test_price_panel_version_reflects_parquet_mtime` / `_missing_parquet_is_safe` /
  `test_datasource_exposes_price_panel_version`; `test_cross_section_version_starts_truthy_and_bumps_on_upsert`

Files touched: `computed/store.py`, `datasource/submodules/equity.py`, `datasource/provider.py`,
`sections/screener/service.py`, `sections/screener/routes.py`, and tests `tests/test_screener_section.py`,
`tests/test_datasource.py`, `tests/test_computed_store_unit.py`.

Test cmd (from `src/mktt/`): `python -m pytest -q` → **382 passed, 6 failed**. The 6 are the carried
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` (out of scope, untouched — baseline was
372 passed / 6 failed; +10 new Slice 1 tests all green). DoD met: new tests green, rest green; numbers
unchanged (cached path transparent — existing screener suite passes). No commit. No browser-verify in
scope for S1 (server-side TDD only; the `/api/screener/version` JSON is consumed by S3).

State: S1 unblocks S2 (selected-col + embedded JSON — shares `service.py`/template) and S3 (needs the
`/api/screener/version` endpoint). No new FLAGs.

## 2026-06-16 · developer · REPORT (S2 — render only selected columns + embed result JSON)
Task: `plan-dev.md` → Slice 2. Strict TDD on the server surface; client re-render written clean +
smoke-rendered, awaits orchestrator browser-verify. No open FLAGs hit. DONE (server).

Built (server, `src/mktt/sections/screener/service.py`):
- **Column-id vocabulary** — `COL_ID_TO_RESULT` (readable lowercase id → RESULT_COLUMNS name) is the
  single source of truth, with inverse `RESULT_TO_COL_ID` and the validation set `RESULT_COL_IDS`.
  `DEFAULT_VISIBLE_COLS` = the exact 21 ids the flat table renders today, in template order
  (`symbol,sector,industry,price,chg,turnover,rs,stage,regime,ma,pct50,pct200,from52h,from52l,pe,fwdpe,pesect,opmgn,roic,evebitda,target`).
- **`ScreenRequest.cols`** (new field) + `_parse_cols(raw)` — comma-separated ids, validated against
  `RESULT_COL_IDS`, unknowns dropped, order preserved, de-duped; absent/empty/all-unknown → the default
  (never an empty table). Wired into `from_query` (so `?cols=` is part of the request identity → its own
  cache entry, and round-trips on server reload).
- **`handle_page`** now emits `visible_cols` (resolved ordered list), `all_cols` (full picker vocab,
  id+label), `flat_col_spec` (`flat_col_spec_js()` — JSON mirror of the per-column format/coloring for
  the client), `flat_table` (server payload restricted to `visible_cols`: ordered headers + per-cell
  text/cls/align/style built by `_flat_cell`/`FLAT_COL_SPEC`), and `screener_data`
  (`{columns: ALL RESULT_COLUMNS, rows: [[full-precision …], …], col_id_of}`) — the FULL result for ALL
  passed rows, independent of `visible_cols` (reuses `_results_table`, so numbers byte-identical to the
  JSON API). All existing context (sector_stats, sector_map, stage_dist, readouts, asof) intact.

Built (client, `templates/screener.html`):
- Flat `<thead>`/`<tbody>` made **data-driven over `flat_table`** — emits only the selected columns,
  preserving each column's label / format / numeric coloring / stage color / `data-cid`.
- Embedded once: `var SCREENER_DATA`, `var FLAT_COL_SPEC`, `var ALL_COLS`, `var VISIBLE_COLS`.
- Rewrote the column picker: builds from `ALL_COLS` (no DOM scan), on change re-renders the flat table
  from `SCREENER_DATA` (instant), writes `?cols=` to the URL + localStorage (`screenerVisibleCols`), and
  still CSS-hides the **Sectors** view by `data-cid` (translating `symbol`↔`sym`). Client sort
  (`sortBy`/`renderFlatTable`) now operates from `SCREENER_DATA` via a `DocumentFragment` (S4 refines);
  legacy `sortTable(idx,type)` kept as a thin shim. Ticker-jump reads the symbol from the row onclick so
  it works even when the Symbol column is toggled off.

Behaviors covered (new tests, `tests/test_screener_section.py`):
- `test_from_query_cols_selects_validated_ordered` · `test_from_query_cols_absent_is_default_visible_set`
- `test_from_query_cols_drops_unknown_preserves_order`
- `test_handle_page_visible_cols_in_context_and_restrict_table` (visible_cols + flat_table restricted)
- `test_handle_page_screener_data_full_regardless_of_visible_cols` (all RESULT_COLUMNS + all passed rows,
  full precision: AAA PE==20.0)
- `test_flat_col_spec_js_mirrors_server_format_tokens` (client fmt tokens mirror the server formatters)

Files touched: `sections/screener/service.py`, `sections/screener/templates/screener.html`,
`tests/test_screener_section.py`. (`routes.py` unchanged — already parses `request.args` → `cols`.)

Test cmd (from `src/mktt/`): `python -m pytest -q` → **388 passed, 6 failed**. The 6 are the carried
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` (out of scope, untouched — same as the S1
baseline of 382/6; +6 new S2 tests all green). Screener suite alone: 43 passed. Standalone Jinja
smoke-render confirmed: with `cols=symbol,price,rs,stage` the flat thead/tbody emit exactly those 4
`data-cid`s, prices format `%.2f`, stage label+color preserved, embeds present; default (no `cols`)
emits the exact 21-column set in order.

DoD (server) met: new tests green, rest green; numbers/precision unchanged (`screener_data` carries raw
full-precision values; `_flat_cell`/`FLAT_COL_SPEC` and the client `_fmtCell` apply identical formatting).

ORCHESTRATOR BROWSER-VERIFY (run `src/mktt/` Flask app on :5001):
1. Default load: flat table DOM contains ONLY the 21 default columns (inspect `#screener-table thead` —
   no hidden-then-CSS columns); numbers identical to before.
2. Toggle a column in the picker → flat table re-renders **instantly** from embedded data (no reload, no
   network), column appears/disappears with identical formatting/coloring; `?cols=` updates in the URL.
3. Reload with `?cols=symbol,price,rs` → server renders only those 3 columns (round-trip).
4. Click a flat-table header → sorts from `SCREENER_DATA` (toggles direction on repeat); numbers identical.
5. Sectors view + Map view still work; the picker still hides columns in the Sectors hierarchy.

FLAG (non-blocking, noted per protocol — sector view stays CSS-hide as the plan permits): the picker's
column vocabulary is now the flat-table `FLAT_COL_SPEC` ids; the Sectors table uses a smaller, partially
different `data-cid` set (`sym` for Symbol; no price/chg/turnover/stage/regime/ma cols). The picker maps
`symbol→sym` and CSS-hides by `data-cid`, so columns the sector table doesn't have are simply no-ops
there — consistent with today's behavior, no degradation. If a future slice unifies the two tables'
column model, revisit this mapping. No conflict that degrades the existing colored formatting.

State: S2 done (server TDD complete; client awaits browser-verify). Unblocks S4 (jank — the all-columns
`applyColVisibility` 100k-node scan is already removed; `table-layout:fixed` + `content-visibility` next)
and S3 (keep-alive — `SCREENER_DATA` is now embedded for snapshot/restore). No commit. No blocking FLAGs.

## 2026-06-16 · developer · REPORT (S4 — jank / smoothness fixes)
Task: `plan-dev.md` → Slice 4. CSS/JS only, no Python route changes, no math/data/column-set/format
change. No open FLAGs hit. DONE (server suite green; client awaits orchestrator browser-verify).

Built (presentation/perf only):
- **`table-layout: fixed` + explicit column widths** on `#screener-table` (`static/css/style.css`).
  Kills the measure-before-render full-table reflow. Cells get `overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap` so fixed widths clip with an ellipsis instead of forcing the table wider. Widths
  are driven by a `<colgroup>`: the server template emits one `<col data-cid=…>` per visible header for
  first paint, and `renderFlatTable()` rebuilds the colgroup (`_applyColWidths` + `_colWidth`/`_COL_WIDTH`
  map, single source of truth, align-based fallback for any unlisted col) on every toggle/sort so widths
  stay stable. `templates/screener.html`.
- **`content-visibility: auto; contain-intrinsic-size: auto 28px`** on `#screener-table tbody tr` AND
  `#sector-table tbody tr` (the big hidden ~8500-row hierarchy — item 5 cheap win): the browser skips
  paint+layout for offscreen rows during scroll. Scoped to `tbody tr` only, so the sticky `<thead>` is
  structurally untouched; scoped by table id so the Map view and the nested sector sub-tables are
  unaffected. `static/css/style.css`.
- **Batched render: verified already one DOM write** — `renderFlatTable()` builds rows in a
  `DocumentFragment` then a single `tbody.appendChild(frag)` (S2 already did this; left as-is, no per-row
  `appendChild`/reflow). The header is built once and assigned via `thead.appendChild(htr)`.
- **Item 4 (drop the moot 100k-node flat-table scan): already satisfied by S2** — `applyColVisibility`
  does NOT scan the flat table (it sets `VISIBLE_COLS` and re-renders only the selected columns); the
  remaining `data-cid` `display:none` scan is scoped to `#sector-table` (`stable.querySelectorAll`) only,
  as the plan permits. Confirmed no flat-table `data-cid` hide pass remains.

Files touched: `sections/screener/templates/screener.html`, `static/css/style.css`. No `.py` changes.

Test cmd (from `src/mktt/`): `python -m pytest -q` → **388 passed, 6 failed** (unchanged from the S2
baseline; the 6 are the carried `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` — out of
scope, untouched). Inline JS validated: extracted both `<script>` bodies, neutralized Jinja, `node --check`
→ OK. Jinja colgroup fragment smoke-rendered (emits one `<col data-cid>` per header).

ORCHESTRATOR BROWSER-VERIFY (run `src/mktt/` Flask app on :5001):
1. First paint: no layout-shift flash — columns settle to fixed widths immediately (no content-measured
   reflow). Long Sector/Industry names truncate with an ellipsis (hover/title not added — ellipsis only;
   widen the column via the picker if a value must be read in full).
2. Scroll the flat table: visibly smoother (offscreen rows skip paint/layout via `content-visibility`).
   Sticky header stays pinned; colored cells (chg/RS-chg/%MA, stage colors) intact; numbers identical.
3. Sort a column: fast (one DocumentFragment write); colored cells + widths preserved.
4. Toggle columns in the picker: re-renders instantly; colgroup widths track the new visible set; numbers
   unchanged; `?cols=` round-trips.
5. Switch to Sectors view + scroll: hierarchy still expands/collapses; offscreen rows skip paint. Map view
   unaffected.
   If `table-layout:fixed` or `content-visibility` visibly breaks the colored/sticky table → that is the
   STOP/FLAG condition (none observed in static review; verify in-browser).

State: S4 done. Unblocks S3 (keep-alive) — the only remaining slice. No commit. No blocking FLAGs.

## 2026-06-16 · developer · REPORT (S3 — client keep-alive / instant back)
Task: `plan-dev.md` → Slice 3. Client-side JS + a small base.html wrapper (browser-verified by the
orchestrator; Python suite kept green). No open FLAGs hit. DONE (server suite green; client browser-verify
pending). Scoped, defensive — NOT an app-wide SPA: nav-intercept is `/screener` links only, and EVERY
uncertainty (no snapshot, stale token, filter mismatch, restore throws) falls back to normal navigation.

Built:
- **Stable content wrapper** (`templates/base.html`): `{% block content %}` is now wrapped in a single
  `<main id="app-content">…</main>` inside `.container`. Plain block-level element, no margins/display
  change, no CSS rule targets direct children of `.container` (only `max-width`/`margin`/`padding`), so
  monitor/screener/rrg/macro/options layouts are structurally unchanged. Smoke-rendered base.html via
  Jinja: exactly one `#app-content`, keepalive tag present.
- **Re-runnable screener init** (`sections/screener/templates/screener.html`): the former `initColPicker`
  IIFE is now a named, **idempotent** function (clears `#col-checks` before rebuild → no duplicate
  checkboxes / double-bound change handlers on repeat). New single entry point `window.initScreener()`
  calls `initColPicker()` (which applies `VISIBLE_COLS` + renders the flat table from embedded
  `SCREENER_DATA`); bound on first `DOMContentLoaded` AND callable by the keep-alive after re-injection.
  Document-level listeners (ticker-dropdown close) guarded by `window._screenerDocBound` so a re-init
  never re-adds them (the document survives an `#app-content` innerHTML swap). Exposed
  `window.screenerGetState()` (scrollY, sort {col,asc}, view flat/sectors/map, cols, filterQuery) and
  `window.screenerRestoreState(st)` (re-applies cols→picker checkboxes, sort, `renderFlatTable()`, view,
  then scroll on the next frame). Restore is authoritative from `SCREENER_DATA` (not from possibly-stale
  serialized html), so a snapshot can never show a mis-sorted/mis-columned table.
- **Keep-alive module** (`static/js/keepalive.js`, loaded by base.html on every page):
  - *Snapshot* `mktt_screener_snapshot` in sessionStorage = `{token, url, html(#app-content innerHTML),
    state}`. Captured with full html on `load` + `pagehide`; lightweight state-only refresh (debounced
    150ms) on scroll/click(sort,toggle,view)/change(cols). Token read lazily from `/api/screener/version`.
  - *Intercept* (capture-phase click, scoped to `/screener` paths only; ignores modifier/middle clicks,
    `target=_blank`, and same-page clicks): `preventDefault()`, then `fetch('/api/screener/version')` —
    if `version === snapshot.token` AND the target query matches the snapshot's `filterQuery` (compared
    **ignoring `cols`**, since columns are a pure client view) → swap `#app-content` innerHTML with
    `snapshot.html`, `initScreener()`, `screenerRestoreState()`, `history.pushState(snapshot.url)`,
    re-mark the SCREENER tab active. Else → `window.location.href = href` (normal server render).
  - *popstate*: when navigating to a `/screener` URL whose DOM is not the screener, token-checked
    snapshot restore; otherwise `location.reload()`. No `unload`/`beforeunload`/`no-store` added →
    page stays bfcache-eligible. Already-live screener DOM → just re-mark the tab.
  - Any throw in restore → returns false → caller falls back to navigation. Never leaves a broken page.
  - Debug logging off by default; `localStorage.KA_DEBUG='1'` enables `[keepalive]` console.debug.

Files touched: `templates/base.html`, `sections/screener/templates/screener.html`,
`static/js/keepalive.js` (new). No `.py` changes.

Test cmd (from `src/mktt/`): `python -m pytest -q` → **388 passed, 6 failed** (unchanged carried
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` — out of scope, untouched). JS validated:
`node --check static/js/keepalive.js` OK; both screener inline `<script>` bodies extracted + Jinja-
neutralized + `node --check` OK. base.html Jinja smoke-render OK (single `#app-content`, keepalive tag).

ORCHESTRATOR BROWSER-VERIFY (run `src/mktt/` Flask app on :5001):
1. Load `/screener`, scroll down, sort a column, switch to Sectors view (or toggle columns). Click the
   MONITOR tab. Click the SCREENER tab → screener appears **instantly, no reload flash**; Network shows
   ONLY `GET /api/screener/version` (no `/screener` document, no `/api/screener` heavy call); scroll
   position + sort + active view + selected columns are preserved. URL is restored via pushState.
2. Also via Monitor→Screener nav tab specifically (same as step 1; the tab is the only Monitor→Screener
   link). Confirm instant restore.
3. Simulate a data change so the token differs: e.g. in DevTools run
   `JSON.parse(sessionStorage.mktt_screener_snapshot).token` to read the stored token, then mutate it:
   `var s=JSON.parse(sessionStorage.mktt_screener_snapshot); s.token='stale'; sessionStorage.mktt_screener_snapshot=JSON.stringify(s);`
   Return to the screener → it does a NORMAL fresh server render (full document load), NOT a stale
   snapshot. (A real Writer `upsert`/parquet change bumps `/api/screener/version`, same effect.)
4. Browser **Back** from Monitor → Screener still works (bfcache restores the real page, or popstate
   snapshot-restores). No blank page.
5. No console errors on any of the above. Visit `/monitor`, `/rrg`, `/macro`, `/options` → layout/CSS
   unaffected by the `#app-content` wrapper; clicking THEIR nav tabs still does normal navigation (the
   intercept is `/screener`-only).
6. Enable `localStorage.KA_DEBUG='1'` to watch `[keepalive]` decisions (captureSnapshot / restore / token
   mismatch → nav) if a step does not behave as expected.

Caveats (non-blocking):
- The snapshot `html` is re-serialized on `pagehide`; if `pagehide` is skipped by the browser the restore
  still rebuilds the flat table from embedded `SCREENER_DATA` + saved state, so the table is always
  correct — only an unsaved *expanded sector row* in the Sectors hierarchy (server-rendered, not data-
  driven) would revert to collapsed. Flat-table view (the default) restores fully.
- Filter-query match ignores `cols`, so returning with a different column selection still restores
  instantly and re-applies the snapshot's columns (a pure client view concern). A different *filter*
  (preset/sector/etc.) correctly falls back to a fresh server render.

State: S3 done — all four slices (S1, S2, S4, S3) implemented; only orchestrator browser-verify remains.
No commit. No blocking FLAGs.

## 2026-06-16 · developer · REPORT (S3 keep-alive — quota bug FIXED; restore-from-Monitor BLOCKED, FLAG)
Task: fix the S3 keep-alive that never restores. Two bugs found; one fixed in scope, one is an
architecture blocker that the data+shell plan alone cannot solve. JS/template only; Python suite green.

MEASURED LIVE (rendered `/screener` via `app.test_client()`, real universe):
- Old snapshot stored full `#app-content` innerHTML = **39.1 MB** (87 `<tbody>` = **36.3 MB**: 4119-row
  flat table + ~8500-row sector hierarchy + nested sub-tables). `sessionStorage.setItem` → QuotaExceeded
  (~5 MB cap). Confirms the diagnosis: NO snapshot ever persisted → every return fell back to full nav.
- `SCREENER_DATA` embed = **2.14 MB**.

FIX 1 (quota — DONE, in scope, `static/js/keepalive.js`): snapshot reshaped to
`{token, url, state, data, shell}` (no rendered rows):
- `data` = the embedded render globals `{screener_data, flat_col_spec, all_cols, visible_cols}`.
- `shell` = `#app-content` clone with **every `<tbody>` emptied AND every inline `<script>` removed**
  (the scripts don't execute via innerHTML anyway and embed a 2nd 2.14 MB copy of SCREENER_DATA) and
  `#map-summary` emptied → **631 KB**.
- **Measured final snapshot JSON = 2.80 MB** (shell 631 KB + data 2.13 MB) → **fits, setItem does NOT
  throw**. Layered save: data+shell → if it throws, data-only → else clear (never a stale broken snapshot).
- Restore re-seats `window.SCREENER_DATA/FLAT_COL_SPEC/ALL_COLS/VISIBLE_COLS`, injects `shell`, then
  re-renders from data. Scoped to `state.view==='flat'` (sectors/map data is server-rendered, not in
  SCREENER_DATA → fall back). All guards kept (token match, filter-query match ignoring `cols`, restore
  restores original DOM + returns false on ANY throw → never a broken page). Saves on `pagehide` + debounced.
- Exposed `window.renderFlatTable` + the data globals in `sections/screener/templates/screener.html` so
  keepalive can both feed and detect the renderer.

FLAG (BLOCKING for the "instant back from Monitor" DoD — STOP per the task's explicit clause):
data+shell now FITS and PERSISTS, but it cannot RESTORE ROBUSTLY from another page. Root cause: the
screener's render functions (`initScreener`, `renderFlatTable`, `_renderCell`, `_fmtCell`, `initColPicker`,
`screenerRestoreState`, …) and the `var` globals live ONLY in the screener page's **inline `<script>`**.
On the Monitor page (the DoD scenario) that script never ran, so those functions DO NOT EXIST; and HTML
injected via `innerHTML` does NOT execute its `<script>` (HTML5 spec). keepalive.js is the only screener-
aware script loaded globally. Therefore restore-from-Monitor correctly DECLINES (renderer absent) and
falls back to a normal navigation — so the browser-verify ("click SCREENER on Monitor → instant restore,
window marker survives, NO full navigation") will NOT pass. This is independent of the quota fix.
The complete fix needs the screener client renderer EXTRACTED into a globally-loaded static JS file
(`static/js/screener.js`, loaded by base.html on every page), with the template's inline `<script>`
reduced to the per-page data injection (`window.SCREENER_DATA = {{...}}` etc.). That is a ~700-line
move touching the template + base.html + a new static file — beyond this task's keepalive.js-only scope,
and an architecture decision for the main session. Note S1 already makes the fallback navigation fast
(cached pipeline + version check), so "back" is not slow today — just not zero-network/instant.
Options for the orchestrator: (a) dispatch a follow-up slice to extract the renderer to a global JS file
(enables true instant-back from any page); or (b) accept the S1-cached fast navigation as "back" and drop
the cross-page snapshot restore. I did NOT pick for you.

Files touched: `static/js/keepalive.js`, `sections/screener/templates/screener.html` (window exports only).
Test cmd (from `src/mktt/`): `python -m pytest -q` → **388 passed, 6 failed** (unchanged carried
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]`; JS-only change). `node --check keepalive.js`
OK; screener inline `<script>` extracted + Jinja-neutralized + `node --check` OK.

State: quota bug fixed + snapshot now persists at 2.80 MB (verified). S3 stays open on the
restore-from-Monitor blocker above (FLAG) — needs the orchestrator's call on renderer extraction. No commit.

## 2026-06-16 · developer · REPORT (S3 follow-up — screener renderer EXTRACTED to global static JS; restore-from-any-page now active)
Task: the orchestrator-approved follow-up that RESOLVES the S3 FLAG ("screener render fns live only in the
inline script → can't restore from Monitor"). Mechanical-but-delicate inline→global move; JS/template
only; Python suite kept green; browser-verify by the orchestrator. DONE (client; browser-verify pending).

What moved (the PURE-JS screener client logic, ~640 lines, out of the screener template's inline
`<script>` into a new GLOBAL `static/js/screener.js` loaded by base.html on every page):
- `initScreener`, `renderFlatTable`, cell render/format helpers (`_renderCell`/`_fmtCell`/`_rawVal`/
  `_stageColor`/`_colWidth`/`_applyColWidths`/`_COL_WIDTH`/colgroup rebuild), `sortBy`/`sortTable` (the
  legacy index shim), `switchView`, the column picker (`initColPicker`/`applyColVisibility`/
  `toggleColGroup`/`COL_GROUPS`/`_allCols`/`_colLabel`/`_sectorCid`), sector hierarchy
  (`toggleSectorStocks`/`toggleIndustry`/`switchSectorTab`/`sortSectorTable`/`sortSubTable`/`_parseCell`),
  Map view (`loadSectorMap`/`renderMap`/`setMapMode`/`sortMapTable`), Find-Ticker
  (`tickerAutocomplete`/`tickerGo`), and the keep-alive surface (`screenerGetState`/`screenerRestoreState`).
- CRITICAL split preserved: ONLY pure JS moved. Everything with Jinja stayed in the template as a tiny
  inline data-injection `<script>` that assigns `window.SCREENER_DATA / FLAT_COL_SPEC / ALL_COLS /
  VISIBLE_COLS / SECTOR_MAP / _TICKERS = {{ …|tojson }}`. screener.js reads those `window.*` globals (via
  small accessors `SD()/SPEC()/ALL()/VIS()/setVIS()/MAP()/TICKERS()`) so keepalive's re-seating of the
  globals + a re-init rebuild the table correctly. screener.js contains NO Jinja. The exact cell
  formatting/coloring/widths/labels are byte-for-byte the same code as before (verbatim move).
- The advanced-filters dropdown helper (`cbUpdate` + its outside-click closer) STAYS as its own small
  inline `<script>` in the filter panel — it is filter-form logic, not render/sort/picker, and out of
  this move's scope.

base.html: loads `static/js/screener.js` after `keepalive.js` on every page. INERT on non-screener pages
— screener.js auto-init runs ONLY when `#screener-table` is present; on Monitor/RRG/etc. it merely DEFINES
the global `window.initScreener`/`renderFlatTable`/… (no DOM side effects), which is exactly what lets the
keep-alive rebuild the flat view from any page. No global-name collision: the only same-named function in
another section is rrg.html's `sortTable`, which is IIFE/closure-scoped (not on `window`) and resolved
lexically by rrg's own `wireSort` — unaffected.

keepalive.js: removed the "renderer absent on this page → decline" guard from `restoreFromSnapshot`
(the renderer is now global). Restore now: re-seats `window.SCREENER_DATA/FLAT_COL_SPEC/ALL_COLS/
VISIBLE_COLS` from the snapshot, injects the stripped `shell`, calls `window.initScreener()` +
`window.screenerRestoreState()`, `pushState`, re-marks the SCREENER tab. KEPT fallbacks: stale token,
filter-query mismatch (ignoring `cols`), `state.view !== 'flat'`, missing shell/data, or ANY restore
throw (try/catch restores the original DOM → caller navigates). Snapshot shape UNCHANGED (data+shell,
~2.8 MB, the quota fix).

Files touched: `static/js/screener.js` (new, ~640 lines), `sections/screener/templates/screener.html`
(inline logic `<script>` 703–1420 → tiny Jinja data-injection block; `{% endblock %}` restored),
`templates/base.html` (load screener.js after keepalive.js), `static/js/keepalive.js` (drop renderer-
absent decline; comment update). No `.py` changes.

Verification done here:
- `node --check static/js/screener.js` OK; `node --check static/js/keepalive.js` OK.
- Inline data-injection block Jinja-neutralized + `node --check` OK (valid JS).
- Jinja parse of `screener.html` + `base.html` OK (no template syntax errors).
- FULL Jinja render of the screener page (stub context) asserts: `window.SCREENER_DATA` present,
  `window._TICKERS` present, exactly one `#app-content`, keepalive.js THEN screener.js script tags both
  emitted by base.html, and NO inline render logic (`var SCREENER_DATA`/`function renderFlatTable`) left
  in the template.
- `python -m pytest -q` (from `src/mktt/`) → **388 passed, 6 failed** (the carried
  `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]`, out of scope/untouched — unchanged).

ORCHESTRATOR BROWSER-VERIFY (run `src/mktt/` Flask app on :5001):
1. Screener page IDENTICAL to before: first paint, instant column toggle (only selected cols), header
   sort, All-Stocks/Sectors/Map views, filters, colored cells (chg/RS-chg/stage colors), fixed widths.
   No regressions; numbers identical.
2. /screener (scroll + sort the flat view) → /monitor → set a `window.__keep='X'` marker on Monitor in
   DevTools → click the SCREENER tab → INSTANT restore, NO full navigation (the `window.__keep` marker
   SURVIVES — proves no document load), flat table + sort + scroll + columns intact; Network shows ONLY
   `GET /api/screener/version` (no `/screener` document, no `/api/screener` heavy call). URL restored via
   pushState.
3. Token change (mutate `sessionStorage.mktt_screener_snapshot.token` to 'stale', or a real data update)
   → returning does a fresh full server render. Filter-query change → fresh nav. Leave the screener with
   the SECTORS or MAP view active → returning falls back to navigation (only the flat view is data-driven).
4. Visit /monitor, /rrg, /macro, /options with screener.js now global → layout/CSS unaffected, no console
   errors, their nav tabs still do normal navigation (intercept is /screener-only); rrg table sort still
   works (closure-scoped, not shadowed).
5. Enable `localStorage.SCR_DEBUG='1'` ([screener]) and `localStorage.KA_DEBUG='1'` ([keepalive]) to trace
   init/restore decisions if a step misbehaves.

Caveat (non-blocking, within the frozen snapshot shape): after a CROSS-PAGE restore the Find-Ticker
autocomplete dropdown has no suggestions until a real reload — `_TICKERS` is injected by the template's
inline script (stripped from the snapshot shell) and is NOT part of the data+shell snapshot (kept at
~2.8 MB per the quota fix). Enter-to-jump (`tickerGo`) still works (it reads symbols from the rendered
rows, not `_TICKERS`). On-page (same-tab, no cross-page) screener use is fully unaffected.

State: S3 + the renderer-extraction follow-up DONE — restore-from-any-page is now wired and active;
only orchestrator browser-verify remains. The earlier S3 FLAG (renderer trapped inline) is RESOLVED.
No commit. No blocking FLAGs.

## 2026-06-16 · orchestrator · DEBRIEF (effort complete — all slices browser-verified)
All slices done + verified live on :5001 (chrome-devtools). Final suite: **388 passed, 6 failed** (the 6
carried kernel-parity fails, untouched throughout). No console errors.
- **S1** pipeline cache + freshness version (cross_section_version bumps on upsert; price_panel_version =
  parquet mtime) + `/api/screener/version`. Invalidate-on-data-update. Screener response ~200 ms (was the
  full pipeline every request).
- **S2** flat table renders ONLY selected columns (verified: 21 cols in DOM; toggle "industry" → 20 cols
  instantly, 4119 rows preserved, `?cols=` round-trips) + embedded `SCREENER_DATA` (1.85 MB).
- **S4** `table-layout:fixed` + `<colgroup>` widths + `content-visibility:auto` on rows + batched render;
  colors/sticky header intact, ellipsis truncation, smooth.
- **S3 + renderer extraction** — moved the screener render/sort/picker logic to global
  `static/js/screener.js` (loaded by base.html, inert off-screener); template inline `<script>` reduced to
  Jinja data-injection. Keep-alive snapshot reshaped to data+shell (1.85 MB, fits sessionStorage; the old
  35 MB full-HTML snapshot threw QuotaExceeded). **VERIFIED cross-page instant restore**: /screener →
  /monitor → click SCREENER → a `window` marker set on Monitor SURVIVED the click (no reload), screener
  flat table rebuilt from data (4119×21, 30k colored cells), `pushState` to /screener, token-matched.
  Falls back to normal navigation on token/filter mismatch or non-flat view.
- **Caveat (non-blocking):** after a cross-page restore the Find-Ticker autocomplete has no suggestions
  until a real reload (`_TICKERS` not in the snapshot); Enter-to-jump still works.
- adr/0004 records the hybrid deviation from adr/0002. **NOT committed; await user.**

## 2026-06-17 · developer · REPORT (follow-up feature: Fwd PE vs Sector/Industry filters)
Follow-up to the (Done) screener-optimization effort. Added two new screener filter criteria —
**Fwd PE vs Sector** and **Fwd PE vs Industry** — mirroring the existing trailing PE/Sector & PE/Industry.
Strict TDD on the server (5 cycles); template filter inputs left for orchestrator browser-verify.

**Behaviors covered (test names, all in `tests/test_screener_section.py`):**
- `test_median_pe_returns_forward_medians` — `_median_pe` now returns `(sector_med, industry_med,
  sector_fwd_med, industry_fwd_med)`; trailing medians byte-identical, forward medians collected
  independently of PE (a row with FwdPE but no PE still contributes to the forward median).
- `test_handle_derives_fwd_pe_median_premium` — `FwdPE_vs_Sector`/`FwdPE_vs_Industry` = FwdPE / group
  median FwdPE via the reused `_pe_premium` (round 2dp).
- `test_handle_fwd_pe_premium_none_when_missing` — None when FwdPE missing (mirrors trailing None branch).
- `test_from_query_parses_fwd_pe_premium_ranges` — `fwdpe_sect_min/max` + `fwdpe_ind_min/max` auto-parse
  into `fund_ranges` under the new stems.
- `test_handle_filters_fwd_pe_vs_sector_range` / `test_handle_filters_fwd_pe_vs_industry_range` — full
  `handle` drops rows outside the range, keeps those inside.
- `test_fwd_pe_premium_registered_as_columns_and_in_screener_data` — fields in `RESULT_COLUMNS`, column
  vocab (`fwdpesect`/`fwdpeind` both directions), `FLAT_COL_SPEC` (2dp), and full-precision per-row
  `screener_data`.

**Files touched:**
- `src/mktt/sections/screener/service.py` — `_median_pe` (forward medians + arity 2→4); caller (~454)
  derives `FwdPE_vs_Sector`/`FwdPE_vs_Industry`; `FUND_RANGE_COLUMNS` (`fwdpe_sect`/`fwdpe_ind`);
  `RESULT_COLUMNS`; `COL_ID_TO_RESULT` (`fwdpesect`/`fwdpeind`); per-row JSON (`fwdpe_vs_sector`/
  `fwdpe_vs_industry`); `FLAT_COL_SPEC` (`fwdpesect`/`fwdpeind`, label FwdPE/Sec & FwdPE/Ind, `%.2f`,
  right, colored False). NOT added to `DEFAULT_VISIBLE_COLS` (opt-in via picker, per ask).
- `src/mktt/sections/screener/templates/screener.html` — two new advanced-filter groups (Fwd PE/Sector,
  Fwd PE/Industry) with `fwdpe_sect_min/max` + `fwdpe_ind_min/max`, mirroring the PE/Sector markup.
- `src/mktt/tests/test_screener_section.py` — 7 new tests above.

**Test command + result (from `src/mktt/`):** `python -m pytest -q`
→ **395 passed, 6 failed** (the 6 failures are the carried `test_kernel::test_parity_kernel_vs_stage_classifier[*]`
parity fails — untouched; baseline was 388 passed / 6 failed, +7 new screener tests). Screener suite alone: 50 passed.

**Browser-verify (orchestrator):** run app on :5001 → open the screener advanced filters →
(1) the two new inputs "Fwd PE/Sector" and "Fwd PE/Industry" (min/max) appear next to PE/Sector & PE/Industry;
(2) setting e.g. `fwdpe_sect_max=1.2` filters the result set and the value round-trips in the URL;
(3) the columns "FwdPE/Sec" and "FwdPE/Ind" are pickable in the column picker and show correct %.2f values.

**State:** feature complete on the server; not committed (per ask). Default column view unchanged.

---

## REPORT — sector/industry summary medians → full-universe baseline (2026-06-18)

**Task (follow-up):** Change the screener Sectors-view sector/industry summary medians
to be computed over the FULL universe per sector/industry (a stable baseline),
not the passed/filtered set — so they don't move when the user tightens the filter.
File: `src/mktt/sections/screener/service.py`, `_sector_stats(passed_rows, full_rows)`.
Strict TDD.

**Behaviors covered (test names, `tests/test_screener_section.py`):**
- `test_sector_stats_medians_over_full_universe_not_passed` — UPDATED from the old
  `test_sector_stats_medians_over_passed_not_full_universe` (flipped to the full-universe
  contract; docstring rewritten). Sector + industry `median_rs`/`median_pe` now = full-universe
  median; `count`/`total`/`pct_of_sector` and `stocks` remain the passed selection.
- `test_sector_median_pe_is_full_universe_median_when_subset_passed` — NEW. Full PE
  [10,20,30,40,50], only [10,20] passed → `median_pe == 30` (not 15).
- `test_industry_median_pe_is_full_universe_median_when_subset_passed` — NEW. Same at
  industry level; `count`==passed, `stocks` are the passed rows only.
- `test_sector_medians_stable_when_filter_tightens` — NEW. Tightening the filter (4→2
  passed) changes `count`/`stocks` but leaves sector AND industry medians identical (30).

**Files touched:**
- `src/mktt/sections/screener/service.py` — `_sector_stats`: added `full_by_industry`
  grouping; sector medians now `_group_medians(full_by_sector[sec])`; industry medians
  `_group_medians(full_by_industry[ind])`; `pe_vs_sector` = full-industry-median-pe /
  full-sector-median-pe. `count`/`total`/`pct_of_sector`/`pct_of_results`/`stocks` and which
  sectors/industries are shown all UNCHANGED (still passed-driven). Docstring rewritten.
- `src/mktt/tests/test_screener_section.py` — 1 updated + 3 new tests above.

**Template:** no change needed. `screener.html` renders whatever `sector_stats` carries
(`median_pe`, `median_rs`, `pct_of_sector`, counts); the per-stock `st.pe_vs_sector` cells
come from `_page_row` (a separate full-universe figure, untouched). No FLAG.

**Test command + result (from `src/mktt/`):** `python -m pytest -q`
→ **398 passed, 6 failed** (the 6 failures are the carried
`test_kernel::test_parity_kernel_vs_stage_classifier[*]` parity fails — untouched;
baseline 395 passed / 6 failed, +3 net new screener tests). Screener suite alone: 53 passed.

**Browser-verify (orchestrator):** run app on :5001 → open the screener → Sectors view.
Apply a filter (e.g. tighten RS min or a preset): the Sectors-view summary medians
(median PE, median RS, median FwdPE, PE-vs-Sector ratios) should STAY PUT = full-universe
baseline, while each sector/industry `count`, `% of sector`, and the listed (expandable)
stocks reflect the active filter. Loosen/tighten again → medians don't move; counts do.

**State:** done; not committed (per ask).

---

## REPORT — sectors-default view + cross-load filter persistence (2026-06-18)

**Task (follow-up, pure client/template):** two screener UX changes; no Python/server
change (suite stays 398 passed / 6 failed). Files: `static/js/screener.js`,
`sections/screener/templates/screener.html`, `templates/base.html`,
plus a small assist in `static/js/keepalive.js` (restore-guard flag).

**Change A — Sectors is now the DEFAULT view.**
- `static/js/screener.js` `initScreener()`: on the normal (non-restore) path it now calls
  `switchView('sectors')` when a `#view-sectors` element exists. Guarded by
  `window._screenerRestoring` so the keep-alive RESTORE path is unchanged (restore drives
  the view authoritatively via `screenerRestoreState()`, which only data-restores the flat
  view; sectors/map still fall back to navigation). When there is no `sector_stats` (no
  Sectors view / no toggle buttons), the guard skips the switch and the flat table stays
  visible.
- `static/js/keepalive.js` `restoreFromSnapshot()`: sets `window._screenerRestoring = true`
  around `initScreener()` + `screenerRestoreState()` (cleared in `finally`) so the default-
  to-Sectors does not flicker/override a flat-view snapshot restore.
- `sections/screener/templates/screener.html`: swapped the active button styling onto
  `#view-sectors-btn` (`background:var(--primary);color:white`) and made `#view-flat-btn`
  inactive; `#view-sectors` shows by default (removed `display:none`); `#view-flat` is
  `display:none` ONLY when `sector_stats` exists (`{% if sector_stats %}display:none;{% endif %}`),
  so the no-sector-stats case still shows the flat table.

**Change B — persist filter DROPDOWN selections across loads/sessions (localStorage).**
- `templates/base.html` (the screener-URL persistence IIFE, ~line 108): extended the old
  sessionStorage-only block. New `localStorage['mktt_screener_filters']` layer:
  - `hasFilterParams(search)` strips `cols` then checks for any remaining query key →
    distinguishes a "filtered" URL from a "bare" one (cols ignored for this decision,
    preserved through redirects).
  - On `/screener` (or `/`) load WITH filter params → save full URL to both
    `localStorage['mktt_screener_filters']` and sessionStorage; point the SCREENER tab href
    at it. No redirect (avoids loops).
  - On a BARE load (query empty after removing `cols`): if a saved filtered URL exists and
    differs → `location.replace(target)` so the server re-applies filters + renders the form
    with dropdowns selected. `_mergeCols()` carries any current `?cols=` into the redirect so
    the column view round-trips. If no usable saved filters → `removeItem` (stays bare).
  - Off-screener pages: just re-point the SCREENER tab href (session URL, else saved filtered
    URL). All storage access wrapped in try/catch → any quota/parse/security error is a no-op.
- `sections/screener/templates/screener.html` "Clear All" button: now clears
  `localStorage['mktt_screener_filters']` + `sessionStorage['mktt_screener_url']` and navigates
  to a BARE `/screener` (was `?preset=all&min_turnover=…`). Bare `/screener` == `preset=all`
  server-side (`preset` defaults to "all", `from_query` line 309), so the result set is the
  same; min_turnover resets to its 500000 default (a full clear). Because the key is cleared
  first, the load-time logic does not redirect → opens unfiltered.

**Reconcile with keep-alive:** the redirect-on-bare is a load-time concern; the keep-alive
intercepts nav-link CLICKS (token+filter match wins for a click). They do not fight: a genuine
bare server load with a saved filter redirects; a click restores from snapshot. `cols` keeps
its own `?cols=`/localStorage handling and is preserved through the redirect (not double-managed).

**Files touched:** `static/js/screener.js`, `static/js/keepalive.js`,
`sections/screener/templates/screener.html`, `templates/base.html`. No `.py` changes.

**Verification done here:**
- `node --check static/js/screener.js` OK; `node --check static/js/keepalive.js` OK.
- Extracted the base.html filter-persist IIFE (no Jinja in it) → `node --check` OK.
- Jinja parse of `base.html` + `screener.html` OK. Static assertions: Sectors button =
  active (primary), All Stocks = inactive; `#view-sectors` shown, `#view-flat` hidden when
  `sector_stats`; Clear All clears `mktt_screener_filters`.
- `python -m pytest -q` (from `src/mktt/`) → **398 passed, 6 failed** (the carried
  `test_kernel::test_parity_kernel_vs_stage_classifier[*]` parity fails — untouched; no server
  change).

**Browser-verify (orchestrator, run app on :5001):**
1. Open `/screener` → opens on the **Sectors** view (Sectors button active/primary, sector
   table shown, flat table hidden). Click "All Stocks" → flat table shows; click "Map" → map
   loads; back to Sectors works. Column picker + header sort still work in the flat view.
2. Set filters (e.g. preset=Stage 2, a sector, min turnover, an advanced range) + Scan →
   reload `/screener` (bare, no query) → the SAME filters are restored (dropdowns selected,
   results match) via the localStorage `location.replace`. Open a FRESH tab to `/screener` →
   filters restored too. URL bar shows the saved filtered URL after the redirect.
3. Click **Clear All** → opens unfiltered; reload `/screener` (bare) → stays unfiltered
   (saved state cleared; no redirect).
4. Pick some columns (`?cols=`) on a filtered view → reload bare → filters restored AND the
   `cols` selection round-trips through the redirect. Flat-view keep-alive instant-restore
   (`/screener` → Monitor → SCREENER tab) still works (token+filter match). No console errors.
5. `python -m pytest -q` stays 398 passed / 6 failed.

**State:** done; not committed (per ask). No FLAGs — Sectors-default does not break the
keep-alive flat-restore (guarded) nor the no-sector-stats flat fallback.

## 2026-06-18 · orchestrator · REPORT (browser-verify: sectors-default + filter persistence)
Verified both changes from "cache the screener dropdown state + make sectors the default tab"
live on :5001 (chrome-devtools), resolving the earlier `sectorsDefault:false` red herring
(that was a stale per-tab keep-alive state on an old page, NOT a regression):
- **Sectors default** — FRESH tab `/screener` → `#view-flat` display:none, `#view-sectors`
  display:block, Sectors button = `background: var(--primary)`, flat button = bg-card.
  `sectorsIsDefault: true`. The stale `false` was a pre-change page still showing flat.
- **Filter persistence** — load `/screener?...&pe_max=15&cols=symbol,price,pe,sector` →
  `localStorage['mktt_screener_filters']` captured the full URL. Then bare `/screener` →
  `location.replace` redirected to the saved URL: 1097 rows, `pe_max=15` applied, `cols`
  round-tripped. Cleared the test filter afterward so the user starts clean.
**State:** both verified; whole screener-optimization batch + follow-ups still UNCOMMITTED
(awaiting user go-ahead).

## 2026-06-18 · orchestrator · REPORT (fix: watchlist context-menu broken in All Stocks/flat view)
Regression from the S3 renderer extraction: the flat table rendered by `static/js/screener.js`
tags the symbol cell `data-cid="symbol"`, but the base.html right-click context menu read
`td[data-cid="sym"]` (the SECTOR table's id) and bailed (`if (!symCell) return`) — so right-click
→ Add to watchlist did nothing in "All Stocks".
Fix (`templates/base.html`): resolve the symbol from the row's `onclick`
(`toggleStockChart('SYM', this)`) first — robust even when the Symbol column is toggled off —
with `td[data-cid="sym"]` / `td[data-cid="symbol"]` as fallbacks. Bumps `_asset_version` so any
stale keep-alive snapshot self-heals.
Browser-verified on :5001 flat view: right-click MU row → menu "▲ Add MU LONG / ▼ Add MU SHORT";
clicked Add LONG → `/api/watchlist` shows MU; removed MU afterward (left the user's existing 5
entries untouched). No `.py` change.
