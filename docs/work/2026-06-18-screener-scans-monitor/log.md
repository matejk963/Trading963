# Log — Screener saved-cols / prop-scans / send-to-Monitor

Append-only. Agents: read open FLAGs + recent entries before starting; append a REPORT when done.

## 2026-06-18 · orchestrator · REPORT (effort opened)
New effort for three user-requested screener additions: persist selected columns, save filter criteria as
named "prop scans", and send filtered stocks to Monitor. Recon (explorer a4aa3198) mapped the Monitor rail
(reads one MKLists list via `service.rail`, list name from `?list=`, default `default`) and the watchlist
storage (`ListStore` over `MKLists.list_member`, PK `(list_name, symbol)`; symbol-keyed, so scans can't
live there — localStorage chosen). User locked: send-to-Monitor = subset checkboxes AND send-all; target =
dedicated `screener` list; prop scans = localStorage. Contract frozen in `prd.md`. Slices: A (server, TDD,
developer) + B (client, orchestrator browser-verify), built in parallel against the frozen contract.

No open FLAGs.

## 2026-06-18 · developer · REPORT (Slice A — server: bulk-add + Monitor `?list=`)
Built the server half of send-to-Monitor, TDD (red→green per behavior). Server-only; no template/JS
touched (Slice B owns those).

**Built**
- `monitor/service.py` · `watchlist_add_bulk(lists, list_name, symbols, note=None) -> dict`: upper-case +
  strip each symbol, skip blank/None, de-dupe (first-seen order preserved), call `lists.add(list_name,
  sym, note)` per survivor. `members` sourced via `lists.members(list_name)` after the adds. Debug-logged.
- `monitor/routes.py` · `POST /api/watchlist/bulk`: thin route, parses JSON `{list, symbols, note}`
  (list→`DEFAULT_LIST`, symbols→`[]`), delegates to `watchlist_add_bulk`, jsonifies. No logic.
- `monitor/routes.py` · `monitor_page(symbol=None)`: now reads `request.args.get("list")` and passes
  `mklist=(that or "default")` into `render_template`; existing `symbol`/`active_section` kept. Template
  untouched.

**Bulk-endpoint envelope (settled):** flat dict, NOT the `vm()` meta-envelope —
`{"status": "ok", "list": <list_name>, "added": <int count after dedupe/blank-skip>, "members": [<symbols
after add>]}`. This matches the PRD-frozen contract verbatim. (`watchlist_add` returns the `vm()`
envelope; the "mirror its style" note was read as "reuse `lists.members` for the member source", since
the PRD/task literal return shape is the flat dict. Slice B consumes `status`/`members` at the top level.)

**Behaviors covered (test names, in `tests/test_monitor_section.py`)**
- `test_watchlist_add_bulk_adds_multiple_uppercased` — `["aapl","msft"]` → added==2, members {AAPL,MSFT}.
- `test_watchlist_add_bulk_skips_blank_none_and_dupes` — `["AAPL","","aapl",None]` → added==1, [AAPL].
- `test_watchlist_add_bulk_empty_is_zero_added_ok` — `[]` → status ok, added==0, members [].
- `test_blueprint_watchlist_bulk_post` — POST returns 200 + `{status,list,added,members}`, list honored.
- `test_blueprint_watchlist_bulk_post_list_defaults_to_default` — omitted `list` → `"default"`.
- `test_blueprint_monitor_page_honors_list_param` — `?list=screener`→`mklist=="screener"`; bare→`"default"`
  (asserted via a `render_template` spy monkeypatched onto the routes module — the route tests render the
  real shell as a string, so a context spy is the behavior-level way to read `mklist` without a template
  change).

**Files touched:** `src/mktt/sections/monitor/service.py`, `src/mktt/sections/monitor/routes.py`,
`src/mktt/tests/test_monitor_section.py`.

**Test command + result** (`python -m pytest -q` from `src/mktt/`):
- Monitor suite: `tests/test_monitor_section.py` → 61 passed.
- Screener suite: `tests/test_screener_section.py` → 53 passed.
- Full suite: 404 passed, 6 failed — the 6 failures are exactly the carried baseline
  `test_kernel::test_parity_kernel_vs_stage_classifier[MA50|MA150|MA200|MA150_Slope|Mansfield_RS|Stage]`
  (pre-existing, untouched). Nothing else regressed.

**State:** Slice A contract is now implemented + frozen in code. Slice B (client) can build against
`POST /api/watchlist/bulk` and `/monitor?list=` unblocked. No `ListStore` schema change (reused
`add`/`members`); section stays DI/thin. No open FLAGs.

## 2026-06-18 · orchestrator · REPORT (Slice B — client, all 3 features browser-verified)
Built the client half + a server semantics addition (replace). Files: `static/js/screener.js`,
`sections/screener/templates/screener.html`, `templates/base.html` (client); `sections/monitor/service.py`
+ `routes.py` + `tests/test_monitor_section.py` (replace addition).

**1. Column restore** — `screener.js initColPicker` now prefers a valid
`localStorage['screenerVisibleCols']` over the server default when NOT keep-alive-restoring and the URL
has no `?cols=` (explicit URL still wins; ids validated against ALL_COLS). Save already happened in
`applyColVisibility`. Verified: set `[symbol,roic,evebitda]` → bare `/screener` restored exactly that
(rendered header cids = [checkbox, symbol, roic, evebitda]).

**2. Prop scans (localStorage)** — `screener.html` adds a Prop Scan control group (💾 Save / `<select>` /
✕) by the Scan button; `screener.js` stores `{name -> current filtered URL}` in
`localStorage['mktt_prop_scans']`, rebuilds the dropdown on init, recalls by navigating to the URL,
deletes the selected one. Verified: save → dropdown+store has it (URL exact); recall → navigates to the
saved filtered URL (`pe_max=10&rs_min=80&cols=symbol,price,rs,pe`); delete → removed, dropdown shows
"No saved scans".

**3. Send filtered → Monitor** — leading checkbox column per flat row + header select-all (rendered in
`renderFlatTable`/`_applyColWidths`, selection keyed by symbol so it survives sort/column re-render);
toolbar buttons "Send selected → Monitor (N)" + "Send all <total> → Monitor". POST
`/api/watchlist/bulk {list:"screener", symbols, replace:true}` → `location='/monitor?list=screener'`.
`base.html` `var MKLIST = {{ (mklist or 'default')|tojson }}` so Monitor honors the list.
Verified: checked 3 (MU,NVDA,SNDK) → Send selected → landed `/monitor?list=screener`, `MKLIST=screener`,
rail showed exactly those 3; the `default` watchlist (user's long/short) stayed separate/untouched.
"Send all" on a 51-row filter → button read "Send all 51", list count became 51.

**Replace semantics (added):** each send REPLACES the `screener` list (clean working set, not
accumulation) — `watchlist_add_bulk(..., replace=False)` empties the list first when true; route threads
`replace` from the body; client sends `replace:true`. Verified live: list of 51 → replace with 2 → exactly
2. (Default `replace` omitted still appends — the additive contract is preserved.) Tests added:
`test_watchlist_add_bulk_replace_empties_list_first`, `test_watchlist_add_bulk_replace_default_appends`.

**Asset version:** base.html + screener.html + screener.js all changed → `_asset_version` mtime bumps, so
any stale screener keep-alive snapshot self-heals on next `/api/screener/version` check.

**Tests:** `python -m pytest -q` from `src/mktt/` → **406 passed, 6 failed** — the 6 are exactly the
carried-baseline `test_kernel::test_parity_kernel_vs_stage_classifier[*]` (pre-existing, untouched). +2
over Slice A's 404 (the new replace tests). monitor+screener suites: 116 passed.

**State:** all three user-requested features done + browser-verified; UNCOMMITTED (awaiting user go-ahead).
No open FLAGs.
