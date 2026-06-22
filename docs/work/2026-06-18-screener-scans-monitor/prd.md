# PRD — Screener: saved columns, prop scans, send-to-Monitor

Three screener UX additions requested by the user. Decisions locked with the user (see below).

## Goals
1. **Persist selected columns.** The column picker already writes `localStorage['screenerVisibleCols']`
   + `?cols=` on every change; it is NOT restored on a bare load. Restore it so the latest column
   selection survives reload/navigation. Save immediately on selection (already happens).
2. **Save filter criteria as a named "prop scan".** A user can name + save the current filter set and
   recall it later from a dropdown; delete a saved scan.
3. **Send filtered stocks to Monitor.** From the screener, push names into the Monitor rail for analysis —
   either a checked subset (row checkboxes) OR the entire current filtered set.

## Locked decisions (user, 2026-06-18)
- **Send-to-Monitor scope:** BOTH — row checkboxes for a subset AND a "send all filtered" button.
- **Monitor list target:** a DEDICATED `screener` list (not the long/short watchlist). Monitor opens it
  via `/monitor?list=screener`, keeping the tracked watchlist clean.
- **Prop-scan storage:** localStorage (this browser only). No DB/server change for scans.

## Interface contract (frozen, so client + server slices build in parallel)
- **`POST /api/watchlist/bulk`** — body `{list: str, symbols: [str,...], note?: str}` → add all to the
  named MKLists list (one request, not N). Returns `{status:"ok", list, added:int, members:[str,...]}`.
  Generic (reuses `ListStore.add`); the screener calls it with `list:"screener"`.
- **`GET /monitor?list=<name>`** — the workspace honors a `?list=` param: the rail loads that MKLists list
  (default `"default"`). Achieved by feeding the template `mklist` var → `base.html var MKLIST`.

## Out of scope
- Server-side prop scans (deferred; localStorage chosen).
- Any change to the Monitor detail pane / charts.
- Cross-browser/machine sync of columns or scans.

## Non-negotiables
- Zero data-integrity loss; existing screener + monitor suites stay green.
- Section stays DI / thin-route (adr/0002); bulk endpoint reuses the existing `ListStore`.
