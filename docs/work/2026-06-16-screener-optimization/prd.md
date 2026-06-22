# PRD — Screener performance optimization (instant back, lean columns, smooth)

Status: Accepted (2026-06-16). Derived from a recon (2 parallel explorers) + a grill with the user.

## Intent
Make the screener **fast and smooth** with **zero data-integrity loss**:
1. **Instant back / revisit** — once the screener is loaded, returning to it (nav tab or browser
   Back) restores instantly with **no reload / no heavy server round-trip**.
2. **Render only selected columns** — the DOM carries only the columns the user picked, not all of
   them hidden via CSS.
3. **Smooth & fast** — no glitches/jank on first paint, scroll, sort, filter, column-toggle, view-switch.
4. **No sacrifice of precision / data integrity** — a cached view is **never staler than the underlying
   data**; all numbers stay exact.

## Current state (recon, file:line in the explorers' reports / log)
- `GET /screener` → `handle_page` → `_pipeline` runs the **full pipeline every request** (cross_section
  + fundamentals + quarterly + technicals fetch, `rs_rank_changes` SQL, `_median_pe`, sector_stats,
  sector_map) then server-renders **~4835 rows × 21 cols ≈ 100k DOM nodes** via Jinja.
- Only `ComputedStore.cross_section()` is cached (30s in-proc TTL, invalidated on `upsert`). Nothing
  else is cached; no rendered-output cache.
- Columns: server emits ALL columns; the picker `display:none`-hides via localStorage and re-scans
  ~100k nodes on toggle.
- Back-nav: the SCREENER tab is a plain navigation → full reload (bypasses bfcache); nothing
  client-cached. Sort/filter/view are client-side on the already-loaded DOM; filter dropdowns reload.
- Jank: no `table-layout:fixed`; `appendChild` sort loop (N reflows); hidden sector hierarchy
  duplicates stock rows in the DOM; no `content-visibility`.

## Decision (locked with user)
- **Hybrid** (not full client-rewrite, not server-only): keep the **server-rendered first load** but
  (a) render only selected columns, (b) embed the full result once as compact JSON so the client does
  column-toggle / sort / keep-alive without round-trips, (c) **client keep-alive** so returning to the
  screener restores instantly from the cached state (guarded by a freshness token), (d) jank fixes.
  Deviates from adr/0002 ("tables server-rendered") → recorded in **adr/0004**.
- **Freshness = invalidate on data update**: every server-side cache keys on the cross-section version
  (bumps on Writer `upsert`) + the price/fundamentals parquet mtime, so a cached pipeline/render is
  never staler than the data. Client keep-alive validates its snapshot against a lightweight version
  token before reuse.

## Success criteria
- Returning to a loaded screener (tab or Back) shows the table **with no full reload and no heavy
  pipeline round-trip** (only a tiny version check), state (scroll/sort/view/columns) preserved.
- The DOM contains **only the selected columns**; toggling a column is instant (from embedded JSON),
  no full re-render of 100k nodes.
- First paint, scroll, and sort are visibly smoother (fixed layout, batched DOM, offscreen-skipping).
- Every number identical to today; a cached view never reflects older data than the DB/parquet hold
  (version/mtime-keyed invalidation, proven by tests).
- Existing screener tests stay green; the server-side cache + selected-column + version logic is TDD'd.

## Out of scope (named so they're cheap later)
- Full SPA conversion of the whole app; row virtualization beyond `content-visibility`; server-side
  per-user column persistence (stays URL/localStorage); pagination; changing the data pipeline's math.
