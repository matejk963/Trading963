# plan-dev.md — Screener saved-cols / prop-scans / send-to-Monitor

Tactics for `prd.md`. Server logic is TDD'd (`src/mktt/tests/`, run from `src/mktt/`:
`python -m pytest -q`); client behavior is browser-verified by the orchestrator. Carried baseline:
6 `test_kernel::test_parity_kernel_vs_stage_classifier[*]` failures are pre-existing — leave untouched.

## Slice A — server: bulk-add endpoint + Monitor `?list=` (developer, TDD) · DONE
**Goal:** one request can push N symbols into a named MKLists list, and the Monitor workspace can open a
non-default list.
### Interface
1. **`monitor/service.py`**: `watchlist_add_bulk(lists, list_name: str, symbols: list[str], note: str|None
   = None) -> dict`. De-dupes + upper-cases symbols, skips blanks, calls `lists.add(list_name, sym, note)`
   for each, returns `{"status":"ok","list":list_name,"added":<int>,"members":[...]}` (members = the
   list's symbols after the add, via the existing `watchlist_members` read or `lists.members`).
2. **`monitor/routes.py`**: `POST /api/watchlist/bulk` — parse JSON `{list, symbols, note}` (list defaults
   to `DEFAULT_LIST`; symbols defaults to `[]`), call `watchlist_add_bulk`, jsonify. Thin (no logic).
3. **`monitor/routes.py`**: `monitor_page` reads `request.args.get("list")` and passes
   `mklist=<that or "default">` into `render_template`. (Template/JS wiring is Slice B / orchestrator.)
### Behaviors to test (server)
1. `watchlist_add_bulk(stub, "screener", ["aapl","msft"])` → adds both upper-cased; `added==2`;
   members contains AAPL, MSFT.
2. Blank/duplicate symbols skipped (`["AAPL","","aapl",None]` → one AAPL, `added==1`).
3. Empty `symbols` → `added==0`, no store writes, status ok (never errors).
4. `POST /api/watchlist/bulk` with a stub store → 200, envelope shape `{status,list,added,members}`;
   `list` honored (defaults to `default` when omitted).
5. `monitor_page` with `?list=screener` → template context `mklist=="screener"`; absent → `"default"`.
   (Assert via the route returning the rendered context or a `render_template` spy, mirroring existing
   monitor route tests.)
### DoD
New tests green; existing monitor + screener suites green. Section stays DI/thin. No change to
`ListStore` schema (reuses `add`/`members`). Append a REPORT to `log.md`; raise a FLAG on any contract
mismatch with `prd.md` instead of diverging.

## Slice B — client: column restore + prop scans + send-to-Monitor (orchestrator, browser-verify) · DONE
Depends on Slice A's frozen contract only (not its code) — built in parallel.
1. **Column restore** (`static/js/screener.js` `initColPicker`): when NOT keep-alive-restoring and the URL
   has no `cols` param, prefer a valid `localStorage['screenerVisibleCols']` over the server default before
   building the picker; then render. (Save already happens in `applyColVisibility`.)
2. **Prop scans** (`screener.html` + `screener.js`): "Save scan" button → prompt name → store
   `{name -> filterURL}` in `localStorage['mktt_prop_scans']`. A "Saved scans" `<select>` lists names;
   choosing one navigates to its URL; a ✕ deletes it. Filter URL = current `location` with filter params.
3. **Send-to-Monitor** (`screener.html` flat table + `screener.js`): a leading checkbox column per flat
   row + a header select-all (visible rows); a toolbar with "Send N selected → Monitor" and "Send all
   <total> filtered → Monitor". Click → gather symbols (checked subset, or ALL of `SCREENER_DATA` for
   "all filtered") → `POST /api/watchlist/bulk {list:"screener", symbols}` → on ok `location =
   "/monitor?list=screener"`. `base.html`: `var MKLIST = {{ (mklist or 'default')|tojson }}` so Monitor
   honors the list.
### DoD (browser-verify)
- Pick columns → reload bare `/screener` → same columns restored. 
- Save a named scan → reload → recall from dropdown reproduces the filtered view; delete removes it.
- Check 3 rows → Send selected → Monitor opens on the `screener` list rail with exactly those 3; back to
  screener, Send-all → rail shows the full filtered set. Existing watchlist (`default`) untouched.
- No console errors; suites green.
