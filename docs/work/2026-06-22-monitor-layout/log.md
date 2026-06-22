# Log — Monitor layout adjust + watchlist bulk-delete

Solo orchestrator effort (UI/layout + small server add). Append-only.

## 2026-06-22 · orchestrator · REPORT (done)
Four user-requested Monitor adjustments. User locked: move the existing indicators pane ABOVE price
(not a new strip); bulk-delete = checkbox-per-row + Remove selected.

**1. Bulk-delete from watchlist** (server + client)
- `monitor/service.py`: `watchlist_remove_bulk(lists, list_name, symbols) -> {status,list,removed,members}`
  (upper-case/strip/dedupe/skip-blank, `lists.remove` per survivor).
- `monitor/routes.py`: `POST /api/watchlist/bulk` now dispatches on `action` ("add" default,
  "remove" → bulk remove). Thin.
- `monitor.html` rail: checkbox per row (`.rail-chk`, survives sort/reload via `railSel`), an "All"
  select-all, and a "Remove selected (N)" button → POST bulk remove on the CURRENT list (MKLIST) →
  reload rail + badge. `railSel` pruned to present members on each load.
- Test: `test_watchlist_remove_bulk_deletes_selected`.

**2. Price right-side margin** — `viewmodel.js` price chart + synced indicator pane `rightOffset` 6→14
(kept equal so the logical-range sync stays bar-aligned).

**3. Fundamentals plots right below price** — moved `#monitor-fund-pane` (EPS/Sales/PE/PS 2×2) directly
under `#monitor_price`; the 12-row metrics table (`#monitor_fundamentals`) now follows it.

**4. Relative-strength line above price** — moved the synced indicators pane (`#monitor-ind-toolkit` +
`#monitor_history`, Mansfield RS default) ABOVE the price chart; relabeled "Relative Strength"; height
320→200. Sync is by element id + logical range, so DOM position above/below price is irrelevant.

**Browser-verified (:5001, /monitor/AAPL):**
- Vertical order = RS toolkit → RS pane → price → fundamentals 2×2 → metrics table (measured by offset).
- Screenshot: yellow Mansfield-RS line above price, candles+MAs with right-edge gap, EPS/Sales below.
- Bulk delete: checked 5 seeds → "Remove selected (5)" → removed exactly those, original 8 intact; rail
  re-rendered to 8; select-all → "(8)", clear → "(0)". No console errors.

**Tests:** monitor suite 64 passed; full `pytest -q` baseline unchanged (only the 6 carried
`test_parity_kernel` failures). UNCOMMITTED. No FLAGs.

## 2026-06-22 · orchestrator · REPORT (chart defaults: last-year view, 4× margin, wheel-zoom)
Three price-chart behaviour tweaks (`static/js/viewmodel.js`, price chart + synced RS pane):
- **Default last year** — replaced `fitContent()` (showed all ~6y) with
  `setVisibleLogicalRange({from: n-viewBars, to: n-1+56})`, `viewBars` timeframe-aware (D=252, W=52,
  M=12). Set BEFORE the indicators pane builds, so the pane adopts the same range (lines up on last-year).
- **Right margin 4× larger** — `rightOffset` 14→56 on both panes (kept equal for bar-aligned sync); the
  `+56` in the visible range keeps that margin shown by default.
- **Zoom with scrolling** — `handleScale.mouseWheel` false→true on both panes (wheel now zooms the time
  axis; wheel-pan stays off so it zooms rather than slides). Drag-pan + pinch + axis-drag unchanged.

**Browser-verified (/monitor/AAPL):** default visible range = 2025-06-13→2026-06-17 (~1y), logical span
307 (252 data + 56 margin), RS pane logical range identical (aligned). Wheel-up ×3 → span 307→230
(zoom in) and the RS pane followed in lockstep. Screenshot shows last-year candles with a clear right-edge
gap. No console errors. Static-only change (no app restart); bumps nothing server-side.

## 2026-06-22 · orchestrator · REPORT (multiple watchlists)
Added a multi-watchlist selector to the Monitor rail (the MKLists store was already multi-list capable;
only the UI hardcoded one active list).
- **Server**: `monitor/service.py` `watchlist_lists(lists) -> {status, lists:[...]}` ('default' always first,
  then named lists with members). `monitor/routes.py` `GET /api/watchlist/lists` (thin). StubLists gained
  `lists()`. Tests: `test_watchlist_lists_returns_default_first_plus_named`,
  `test_watchlist_lists_empty_store_still_has_default`.
- **Client** (`monitor.html`): rail-top `<select id="rail-watchlist">` + "+ New" + delete(🗑). `loadWatchlists`
  populates from the endpoint (always includes the active list, even a brand-new empty one) + a
  "+ New watchlist…" sentinel. `setActiveWatchlist` sets `window.MKLIST` (base.html global), persists
  `localStorage['mktt_active_watchlist']`, reloads selector+rail+badge. New = prompt→switch (created
  server-side on first add). Delete = bulk-remove all members (reuses `/api/watchlist/bulk action:remove`)
  → revert to default. Add/remove also refresh the selector (a list can appear/vanish).
- **Active-list resolution**: explicit `?list=` wins (send-to-Monitor) and becomes remembered; else restore
  from localStorage; else base.html's route default. MUST run on DOMContentLoaded, NOT at parse time —
  base.html assigns `var MKLIST` in a script that runs AFTER `{% block scripts %}`, so an earlier
  assignment gets clobbered (this was a real bug, fixed by deferring to the init).

**Browser-verified (:5001):** selector lists default/screener/+New; created "tech-leaders", added NVDA →
landed in tech-leaders only (default's 8 untouched, isolated); switch updates the rail; delete removes the
list (reverts to default); persistence across reload (screener restored); `?list=default` override wins.
No console errors. Full suite 429 passed / 6 carried baseline.

**Two gotchas hit (for future template work):**
1. App runs `debug=False` → Jinja caches templates; template edits need either an app restart OR
   `TEMPLATES_AUTO_RELOAD=True` (now set on the running instance) — static JS does not.
2. A literal `{% block scripts %}` inside a JS COMMENT was parsed by Jinja as a real (unclosed) block →
   500. Never put `{% %}` sequences in inline-script comments.

## 2026-06-22 · orchestrator · REPORT (send-to-Monitor mints a fresh watchlist each time)
User: each screener→Monitor send must create a NEW uniquely-named watchlist (screener 1, screener 2, …)
instead of overwriting one 'screener' list. Client-only change (`static/js/screener.js sendToMonitor`):
- `_nextScreenerList(names)` = `"screener " + (1 + max N among existing /^screener (\d+)$/ lists)`.
- `sendToMonitor` now: GET `/api/watchlist/lists` → pick the fresh name → bulk-add into it (no `replace`,
  it's brand new) → `location='/monitor?list=<name>'`. Builds on the multi-watchlist feature (the Monitor
  selector + `?list=` already handle arbitrary names). No server change, no tests changed.

**Browser-verified (:5001):** 1st send → `screener 1` [BABA,PDD], Monitor opened on it (selector+rail).
2nd send → `screener 2` [PDD], `screener 1` untouched. Lists endpoint showed default/screener 1/screener 2.
Cleaned up test lists afterward (back to just `default`). No console errors. (Static JS — no app restart.)

## 2026-06-22 · orchestrator · REPORT (rename watchlist)
Added rename to the Monitor watchlist controls.
- **Server**: `monitor/service.py` `watchlist_rename(lists, old, new) -> {status, old, new, members}` —
  note-preserving (re-adds each member via `members_with_notes` under the new name, then drops the old);
  refuses to merge into an EXISTING list (`status:"exists"`). `monitor/routes.py` `POST /api/watchlist/rename`
  (thin). Tests: `test_watchlist_rename_moves_members_preserving_notes`,
  `test_watchlist_rename_refuses_existing_target`.
- **Client** (`monitor.html`): a ✎ "Rename" button between New and Delete → `renameActiveWatchlist`
  prompts (prefilled with current name) → POST rename → `setActiveWatchlist(new)`; on `exists` it alerts.
**Browser-verified (:5001):** renamed `winners`→`top picks` (selector+active updated, members [NVDA,AMD]
and their long notes preserved, old name gone); collision (rename→`default`) rejected with alert, stayed
put. Cleaned up. Full suite 431 passed / 6 baseline. No console errors.
