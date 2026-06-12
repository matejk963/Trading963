# ADR 0002 — Frontend: revive original templates, server-render tables

Status: Accepted (2026-06-12)
Effort: docs/work/2026-06-11-mktt-refactor (Wave 4)
Refines: refactor/TARGET_ARCHITECTURE.md §4.1 (HTTP / client-render contract)
Source: /grill-me on "Option C" (the bare-frontend fix)

## Context
The backend refactor left each section with a 54-line placeholder template — the app booted and
served real data but looked bare (no nav, no styling, no filter panels, no table). The original rich
UI (`templates/base.html` 199 lines, `templates/screener.html` 1461 lines) still exists on disk but
was never wired to the new backend, and the original screener is **server-rendered Jinja** with a rich
filter form + colored table — which the spec's §4.1 **client-render-the-ViewModel** contract does not
reproduce (the generic renderer only covers output tables/charts, not the per-section filter UI).

## Decision
1. **Revive the original templates.** `base.html` (chrome: nav, freshness panel, CSS) is restored;
   every section page `{% extends "base.html" %}`. Stale `url_for` endpoint names are remapped to the
   new blueprint endpoints. The original rich section templates (filter forms) are revived per section.
2. **Server-render tables; client-render charts.** Tabular pages (screener, watchlist) are
   **server-rendered** via Jinja fed by the section `handle()`'s data — reusing the original colored/
   sortable tables. Chart figures (monitor/options/rrg/macro) are **client-rendered** with Plotly via
   the generic `renderViewModel`. This **deviates from §4.1** (which mandated client-render for pages);
   accepted because it reuses the proven original UI for far less work and higher fidelity.
3. **`handle()` stays the single data producer.** A thin adapter renders its output to the server
   template (pages) or `jsonify`s it as a ViewModel (the JSON API + charts). One source, two presentations.
4. **Watchlist on `MKLists`** (server-side) via the Monitor endpoints + a connection pool (0.2 ms reads);
   "side" stored in `note`. Replaces the original `localStorage` watchlist.
5. **Screener technicals computed live.** turnover/price/day-change/%-from-52w-high are derived in
   `screener.handle()` from `data.time_series` (matching the original); the store stays focused on the
   expensive cross-sectional classifications (stage/RS/regime/ma_screen/eps_accel).

## Consequences
- The §4.1 "client-render pages" contract now reads: **tables server-rendered, charts client-rendered.**
- No JS table-renderer or ViewModel column-format metadata is needed (the original Jinja handles coloring).
- Each section keeps its own (revived) filter UI — they were always section-specific (input side, §5.1).
- A connection pool is added to the providers (benefits screener/monitor/lists DB reads too).

## Alternatives rejected
- Client-render everything through the ViewModel (honor §4.1 strictly) — rejected: requires rebuilding
  the original rich table + filter UI in JS, re-deriving what the Jinja templates already do.
- Build a fresh minimal frontend — rejected: discards the proven terminal look + freshness/watchlist chrome.
