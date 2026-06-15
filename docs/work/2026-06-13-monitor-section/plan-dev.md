# plan-dev.md — Monitor section (TDD execution plan)

Tactics for the PRD (`prd.md`). One section per slice/issue. The orchestrator settles each
slice's TDD gate (public interface · prioritized behaviors · testable DoD) here before dispatch.
Locked decisions: Lightweight Charts for OHLC (`docs/adr/0003`); PE/PS = period-end (historical)
/ current (forward, TTM). Monitor **reads** MKLists, Screener **writes** — neither imports the other.

---

## Slice 1 — `/monitor` workspace spine + rail (watchlist replacement) · GitHub #8 · AFK · [x] DONE (2026-06-13)

**Tracer bullet.** Stand up the unified `/monitor` page (detail left + rail right). The rail is the
working watchlist replacement (MKLists-backed, enriched with stage/RS, sortable). Detail pane reuses
the *existing* per-symbol render (`/api/chart/<symbol>` → price/history/fundamentals) — not a blank
placeholder (free; the render already works).

### Public interface (settled)

1. **`lists.ListStore.members_detailed(list_name) -> list[(symbol, note, added_at)]`** — NEW read.
   `members_with_notes` (symbol, note) stays for the badge path. `members_detailed` adds `added_at`
   (the `recently-added` sort key). `StubLists` in the test module mirrors it (store `added_at` on add;
   in-memory monotonic counter is fine since real `Date.now` is unavailable in tests — use an
   incrementing int, ordering only).
2. **`service.rail(lists, computed, list_name=DEFAULT_LIST) -> ViewModel`** — NEW. Builds the rail VM:
   - reads `members_detailed`; side from the note (default `"long"`);
   - joins each symbol against `computed.cross_section()` for `stage` + `rs_rank` (the precomputed
     cross-section — a single live symbol can't rank; mirror `_handle_multi`'s `rank_lookup`);
   - `context.entries = [{symbol, side, stage, rs_rank, added_at}]`, default-ordered by `added_at` desc
     (recently-added first); `readouts={members:[...], count:n}`;
   - missing cross-section row → `stage=None, rs_rank=None` (rail still renders the row).
   - `watchlist_members` / `watchlist_add` / `watchlist_remove` are **unchanged** (badge + add/remove path).
3. **Routes** (`routes.py`):
   - `GET /monitor` and `GET /monitor/<symbol>` → render the workspace shell (`monitor.html`),
     passing `symbol` (None for the bare `/monitor`).
   - `GET /api/monitor/rail?list=…` → `service.rail(lists, computed, list)` → jsonify.
   - `GET /chart/<symbol>` → **302 redirect** to `/monitor/<symbol>` (deep-link preserved).
   - `GET /watchlist` → **302 redirect** to `/monitor` (page retired; keep the route as a redirect so
     old bookmarks don't 404).
   - `/api/watchlist` (GET badge + POST add/remove), `/api/chart/<symbol>`, `/api/monitor*` unchanged.
4. **Templates**:
   - `monitor.html` rewritten into the workspace: detail pane (left) hosting the existing
     `#monitor_price` / `#monitor_history` / `#monitor_fundamentals` hosts + `vm-*` sinks, and the
     rail (right). On load, if a symbol is set, fetch `/api/chart/<symbol>`; clicking a rail row sets
     the symbol, updates the URL (`history.pushState` to `/monitor/<symbol>`), and re-renders detail.
   - Rail: renders `context.entries` as rows `▲/▼ · SYMBOL · stage · RS · ✕`; add-by-ticker input
     (long/short); per-row remove (POST `/api/watchlist` `{action:"remove"}`); sort control
     (stage / RS / symbol / recently-added) re-sorting client-side; re-fetches the rail after any
     add/remove and re-counts the badge (`updateWlBadge`).
   - `watchlist.html` no longer routed (its `/watchlist` page is retired → redirect). Leave the file
     in place but unreferenced, or delete — implementer's call; do not break `base.html`.
   - `base.html`: rename the `WATCHLIST` nav tab → `MONITOR`, point at `url_for('monitor.monitor_page')`,
     `active_section == 'monitor'`. Keep `wl-badge` + the `mklists*` helpers (still hit `/api/watchlist`).

### Prioritized behaviors to test (red → green)

Service/store unit tests (mirror `tests/test_monitor_section.py` stubs — no Flask/DB/network):
1. `members_detailed` returns `(symbol, note, added_at)` and preserves add order via `added_at`.
2. `service.rail` enriches entries with `stage` + `rs_rank` from `computed.cross_section()`.
3. `service.rail` defaults to side `"long"` when the note is absent; reads `"short"` from the note.
4. `service.rail` default-orders entries by `added_at` desc (recently-added first).
5. `service.rail` renders a row with `stage=None, rs_rank=None` for a symbol missing from the cross-section.
6. `service.rail` on an empty list → `status="empty"`, `count==0`, `entries==[]`.

Blueprint (thin-route) tests (Flask test client + monkeypatched `_PROVIDERS`, mirror existing
`test_blueprint_*`):
7. `GET /monitor` → 200, renders the workspace shell (not the old watchlist page).
8. `GET /monitor/AAA` → 200, shell carries `symbol="AAA"`.
9. `GET /chart/AAA` → 302 → `/monitor/AAA`.
10. `GET /watchlist` → 302 → `/monitor`.
11. `GET /api/monitor/rail?list=default` → 200, JSON envelope with `context.entries`.

### Testable definition of done

- All 11 behaviors above are green; the existing 314-test suite stays green (no regressions; the
  `watchlist_members`/add/remove contract is unchanged, badge path intact).
- The section stays a thin DI manager returning the ViewModel envelope — no formulas, no fetch logic,
  no Flask in `service.py`; `rail` receives `lists` + `computed` injected.
- Monitor does not import Screener (and vice versa). No new cross-section computation (rail reads the
  precomputed `cross_section`, it does not recompute ranks).
- Manual browser check (the user's flow): `/monitor` shows the rail; add a ticker long/short; rows show
  `▲/▼ · SYMBOL · stage · RS · ✕`; click a row → detail pane renders that symbol + URL updates; remove
  a row drops it + badge re-counts; sort control reorders; `/chart/<sym>` and `/watchlist` redirect.

### Out of scope for this slice (named so they're cheap later)

- The technical Lightweight-Charts pane (#9/#10) and the fundamental Plotly 2×2 (#11/#12) — the detail
  pane here is the *existing* render, replaced by those panes in their slices.
- Drag-to-reorder, multiple named lists, per-instrument notes, the as-of scrubber (all PRD-deferred).

---

## Slice 2 — Technical pane: Lightweight Charts candles + crosshair (daily) · GitHub #9 · AFK · [x] DONE (2026-06-13)

Replace the detail pane's Plotly price line with TradingView **Lightweight Charts** daily candles +
crosshair (`adr/0003`). `base.html:8` already loads `lightweight-charts@3.8.0` (global `LightweightCharts`);
`monitor.html` extends `base.html`. **FORK-1 decision: `open = prior bar's close`** (universe has no open —
`equity.py:33`); first bar `open = its own close`. Flag the synthetic open in the figure + a small UX note.

### Public interface (settled)
1. **`service.py`** — replace `_price_figure` with **`_ohlc_figure(symbol, enriched)`** emitting a
   non-Plotly figure (the `vm()` builder passes unknown keys through verbatim — `viewmodel.py:149`):
   ```
   {"id": "monitor_price", "kind": "ohlc",
    "bars":   [{"time":"YYYY-MM-DD","open":..,"high":..,"low":..,"close":..}, ...],   # open = prior close
    "volume": [{"time":"YYYY-MM-DD","value":..}, ...],
    "series": [{"name":"MA50","data":[{"time","value"}]}, {"name":"MA150",..}, {"name":"MA200",..}],
    "layout": {"title": "SYMBOL — Price"}, "notes": {"synthetic_open": true}}
   ```
   No `traces` key (so the client's Plotly path is not taken). All values JSON-safe via the existing
   `_cell` (NaN→None). Data is already in `enriched` after `_run_kernel` (close/high/low/volume + ma_50/
   ma_150/ma_200 — recon §1); `open` derived from a 1-bar close shift.
2. **`static/js/viewmodel.js`** — in `renderFigure` (line ~46), branch on `fig.kind === "ohlc"` BEFORE the
   `Plotly.newPlot` call → call a new `renderOhlcFigure(fig, node)`: guard `typeof LightweightCharts`
   (mirror the Plotly guard); `LightweightCharts.createChart(node, {...})`; `addCandlestickSeries().setData(fig.bars)`;
   one `addLineSeries().setData(s.data)` per `fig.series`; `subscribeCrosshairMove` → write O/H/L/C+date to a
   readout element. **Dispose the prior chart instance on re-render** (store the chart ref on the node, call
   `chart.remove()` before recreating) — else re-selecting symbols leaks charts.
3. **`monitor.html`** — `#monitor_price` host already exists (480px). Add a crosshair readout element
   (e.g. `#monitor-ohlc-readout`) just above it. No backend route change.

### Prioritized behaviors to test (red → green) — Python service tests
1. `handle()` emits a `monitor_price` figure with `kind == "ohlc"` and **no `traces` key**.
2. `bars` carry `time/open/high/low/close`; `bars[i].open == bars[i-1].close`; `bars[0].open == bars[0].close`.
3. `series` includes MA50/MA150/MA200 each as `{time,value}` arrays aligned to bars.
4. `volume` block present as `{time,value}`.
5. NaN values serialize to `None` (JSON-safe).
6. `notes.synthetic_open is True`.
- **Note:** the existing `test_handle_single_symbol_live_kernel_shape` asserts Plotly `traces` names on
  `monitor_price` — UPDATE it to the new ohlc shape (expected red→green, not a regression).

### Definition of done
- New service tests green; full suite green except the 6 carried kernel-parity fails (327→ updated count).
- Section stays thin/DI/envelope; no new dep (LWC already loaded). The JS renderer is **browser-verified**
  (not unit-tested): candles render for a live symbol, crosshair readout updates, MA lines overlay,
  re-selecting a different symbol disposes the old chart (no leak/stacking).

---

## Slice 3 — Technical pane: D/W/M timeframes + MA toggles + RS line · GitHub #10 · AFK · [x] DONE (2026-06-13, backend green; JS browser-verify pending)

Adds the lean toolkit on top of #9's candles. **Aggregation + MA + RS are recomputed on the displayed
timeframe, client-side** (PRD). v3.8 has no built-in aggregation (recon §4) — do it in JS.

### Public interface (settled)
1. **`service.py`** — extend `_ohlc_figure` to also carry the **benchmark close** aligned to bars (for the
   client RS recompute): add `"benchmark": [{"time","value"}]` from the SPY panel already fetched in
   `_run_kernel` (`bench = data.time_series(["SPY"], ...)`). Drop the server MA `series` reliance for W/M —
   keep daily MAs for the D view, but the client recomputes MAs per displayed timeframe (so they stay
   correct after aggregation). Keep sending daily bars only; the client aggregates.
2. **`monitor.html` / JS** — add above `#monitor_price`: a **D/W/M** segmented control, **MA toggle**
   checkboxes (50/150/200), and an **RS** toggle. JS: aggregate daily bars → W (ISO week) / M (calendar
   month) using OHLC rules (open=first, high=max, low=min, close=last, volume=sum); recompute SMA(period)
   on the displayed-timeframe closes; compute **Mansfield RS** = normalized symbol/benchmark on the
   displayed timeframe, drawn as an overlaid line series (own price scale). Toggling re-runs aggregation
   and `series.setData()` without refetching.

### Behaviors to test (Python where it has backend surface; rest browser-verified)
1. `_ohlc_figure` now includes a non-empty `benchmark` series aligned 1:1 with `bars` by `time`.
- The aggregation/MA/RS math is **client JS** — verify in the browser: switching D/W/M re-aggregates candles;
  MA checkboxes add/remove lines recomputed on the shown timeframe; RS toggle overlays a Mansfield line;
  crosshair still reads the active series across timeframes.

### Definition of done
- The `benchmark` service test green; suite green (minus the 6 carried fails).
- Browser-verified: D/W/M switch, MA toggles (recomputed per timeframe), RS overlay, crosshair — all work
  on a live symbol with no console errors.

---

## Slice 4 — Fundamental pane: EPS + Sales (actual+forecast) + `asof` plumbing · GitHub #11 · AFK · [x] DONE (2026-06-13, backend green; JS browser-verify pending)

Plotly fundamental pane — **EPS** and **Sales** panels first (top row of the eventual 2×2). Actual solid →
forecast dashed + faint high/low band; shared **Q/Y/TTM** toggle; **today-divider**. **FORK-2 decision: port
the legacy `.pkl` blend** for the full forward-quarterly fan.

### Public interface (settled)
1. **Port the blend into a reusable, DI-friendly access (NOT in a Flask route).** Extract the legacy
   computation from `legacy_routes.py` (`_rolling_12m_impl`, `_eps_ttm_forward_impl`,
   `_sales_ttm_forward_impl`, `_revisions_impl` — they read `refinitiv_fundamentals.pkl` and blend trailing
   quarterly actuals with `forward_quarterly` mean/high/low + `trend_*_fq*`) into a new module the section
   reaches via its injected `data` provider — e.g. **`data.fundamental_series(symbol, asof=None)`** returning
   a structured dict: `{quarterly:{dates,eps,revenue}, ttm:{dates,eps,revenue}, annual:{fy_dates,eps_*,rev_*},
   forward_q:{dates,eps_mean/high/low,rev_mean/high/low}}`. Keep the pkl read in the datasource layer; the
   section stays formula/fetch-free. Strip the Flask `request.args` coupling noted in recon.
2. **`service.py`** — `fundamentals_view(symbol, data, granularity="Q", asof=None) -> ViewModel` building two
   Plotly figures `fund_eps` + `fund_sales`. Each: an **actual** solid trace, a **forecast** dashed trace
   (forward_q for Q, annual FY1/FY2 for Y, forward-TTM for TTM), a high/low **band** (two traces / fill), and
   a vertical **today-divider** shape in `layout`. `granularity ∈ {Q,Y,TTM}` selects which series set.
   `asof` (default latest) threads into `data.fundamental_series(symbol, asof=...)` (filters quarterly
   `report_date <= asof`; price `end=asof` later for PE/PS). `handle()` is unchanged — this is its own view.
3. **`routes.py`** — `GET /api/monitor/fundamentals/<symbol>?granularity=&asof=` → `fundamentals_view` →
   jsonify (a focused payload so a granularity toggle re-renders ONLY the 2×2, not the candle chart).
4. **`monitor.html` / JS** — add the 2×2 host divs (`#fund_eps`, `#fund_sales`, + `#fund_pe`, `#fund_ps`
   reserved for #12), a Q/Y/TTM segmented control, and a fetch of `/api/monitor/fundamentals/<sym>` on
   symbol-select + on toggle (Plotly render via the existing `renderFigure`).

### Behaviors to test (Python) — add a `StubData.fundamental_series` + `quarterly` stub
1. `fundamentals_view` emits `fund_eps` and `fund_sales` figures.
2. Each has an actual trace + a forecast (dashed) trace + a high/low band.
3. Granularity `Q`/`Y`/`TTM` switches the series set (assert distinct shapes per granularity).
4. A today-divider shape is present in each figure's `layout`.
5. `asof` is passed through to `data.fundamental_series(asof=...)` (assert the stub receives it) and defaults
   to latest (None) when omitted.
6. Forward points render only as deep as the data holds (no fabricated points for thin names).

### Definition of done
- Service tests green; suite green (minus the 6 carried). Section thin/DI/envelope; the pkl read lives in the
  datasource layer, not `service.py`. Browser-verified: EPS+Sales render with actual→forecast + band, Q/Y/TTM
  toggle works, today-divider visible.
- **Debt flagged** (carried in log): reintroduced `.pkl` dependency; a `forward_quarterly` DB-loader is the
  proper future fix.

---

## Slice 5 — Fundamental pane: PE + PS derived panels · GitHub #12 · AFK · [x] DONE (2026-06-13, backend green; JS browser-verify pending)

Completes the 2×2 with **PE** + **PS** (bottom row), same visual language + Q/Y/TTM + today-divider.
**Basis (locked): historical = period-end price; forward & TTM = current price.**

### Public interface (settled)
1. **`service.py`** — extend `fundamentals_view` to also emit `fund_pe` + `fund_ps`. Inputs: EPS/Sales series
   from #11's `data.fundamental_series`; `shares_outstanding` + `price_close` from `data.fundamentals([symbol])`
   (recon §2 confirms both present); the price panel from `data.time_series([symbol])` for **period-end price**
   per historical `report_date` (index the close series at each period end) and **current price** (last close)
   for forward & TTM. PE = price/EPS; PS = price/(revenue/shares). Guard divide-by-zero/negatives → None.
2. **`monitor.html`** — the `#fund_pe` / `#fund_ps` hosts (reserved in #11) now receive figures; same toggle.

### Behaviors to test (Python)
1. `fundamentals_view` now also emits `fund_pe` + `fund_ps`.
2. Historical PE/PS use the **period-end** price (assert against a stub price series at report_date);
   forward & TTM use the **current** (last close) price.
3. PS uses `shares_outstanding` (PS = price/(revenue/shares)); divide-by-zero/negative EPS → None.
4. PE/PS honor the same Q/Y/TTM toggle + today-divider + `asof` as #11.

### Definition of done
- Service tests green; suite green (minus the 6 carried). Browser-verified: full 2×2 (EPS/Sales/PE/PS)
  renders, PE/PS basis correct, toggle + divider consistent across all four panels.

---

## Slice 6 (enhancement) — Indicators as a synced Lightweight-Charts pane (toggleable) · AFK · [x] DONE (backend green; JS browser-verify pending)

User request (interactive): move the RS Rank / Mansfield RS / Stage indicators OUT of the Plotly
`#monitor_history` panel and into a **second Lightweight-Charts sub-chart stacked under the price**,
**time-synced** with the price chart (pan/zoom together), each indicator **shown on toggle** (the existing
`.ind-tog` checkboxes), pane hidden when none are on. Replaces the Plotly indicators panel. Decision
captured via /grill preview — "Separate synced pane below price".

### Public interface (settled)
1. **`service.py` `_history_figure`** — emit a non-Plotly figure: `{"id":"monitor_history",
   "kind":"indicators", "series":[{"name":"RS Rank","scale":"rsrank","data":[{time,value}…]},
   {"name":"Mansfield RS","scale":"mansfield",…}, {"name":"Stage","scale":"stage",…}]}` (only series whose
   column exists; JSON-safe via `_cell`). Drop the Plotly `traces`/3-axis `layout`. Keep the names exact.
2. **`static/js/viewmodel.js`** —
   - stash the price LWC chart instance in `renderOhlcFigure` (e.g. module var `_priceChart`);
   - `renderFigure` branches `fig.kind === "indicators"` → `renderIndicatorPane(fig, node)`;
   - `renderIndicatorPane`: dispose any prior pane chart; read `.ind-tog` state — if none checked, hide
     `#monitor_history` and return; else create an LWC chart, add one `addLineSeries` per CHECKED indicator
     on its **own** `priceScaleId` (RS Rank 0-100; Mansfield with a zero baseline; Stage 0-4) so scales
     don't collide; `handleScroll/handleScale.mouseWheel:false` (match the price chart); **bidirectional
     time-sync** with `_priceChart` via `subscribeVisibleTimeRangeChange` + `setVisibleRange` (sync by
     TIME, not logical range — densities differ; reentrancy guard to avoid loops); stash the figure on the
     node for toggle re-render.
3. **`monitor.html`** — repoint the `.ind-tog` change handler from the Plotly `applyIndicatorToggles`
   (remove it + its `.then()` chain) to re-render the LWC pane from the stashed figure. Keep the checkbox
   row. `#monitor_history` host stays (now hosts the LWC pane).

### Definition of done
- `test_handle_history_figure_from_computed` updated to the `series` shape (assert series names) and green;
  full suite green except the 6 carried kernel-parity fails.
- Browser-verified (orchestrator): pane renders under the price; checked indicators show on their own
  scales; toggling adds/removes each; pane hides when all off; pan/zoom stays synced with the price;
  survives symbol switch and D/W/M timeframe changes. No console errors.
- Note for the user: the price toolbar's existing "RS (Mansfield vs SPY)" overlay (#10, client 52-window)
  is left as-is — distinct from the pane's 252-day kernel Mansfield.

### Follow-up — synchronized crosshair between the two LWC panes · JS-only · [x] DONE (backend N/A; JS browser-verify pending)
Bidirectional **vertical-guide crosshair** sync between `#monitor_price` and `#monitor_history`
(`static/js/viewmodel.js` only). v3.8 has `subscribeCrosshairMove` (read) but not `setCrosshairPosition`
(v4+), so the sync is a cached 1px guide `<div>` overlay on the partner host positioned via
`timeScale().timeToCoordinate(param.time)` — partner chart/host resolved dynamically each move (indicator pane
is rebuilt on toggle). Hides on `param.time==null`, on out-of-range time, and when the indicator pane is off.
Existing `#monitor-ohlc-readout` untouched. Suite unchanged: **354 passed, 6 failed** (carried kernel-parity).
Browser-verify: hover price → guide on indicators; hover indicators → guide on price; off-chart clears it;
stays aligned after indicator toggle / symbol switch / D-W-M; no stray guide when the pane is hidden.

### Follow-up — fix price chart pinned to right edge (LOGICAL-range sync) · JS-only · [x] DONE (backend N/A; JS browser-verify pending)
Price chart was pinned to its right edge (couldn't scroll past the last bar into whitespace): the
price↔indicator sync used TIME range, which can't represent empty space past the last bar, so a
scroll-past got clamped back. Fix (all in `static/js/viewmodel.js`): (1) switched the cross-chart sync to
**LOGICAL range** (`subscribeVisibleLogicalRangeChange` + `setVisibleLogicalRange`) with an async-safe
initiator-tracking reentrancy guard (`_syncOwner`, released on next `requestAnimationFrame`) so the
master's free-scroll isn't reverted by the partner's echo; (2) added `aggregateLine(points, tf)` and
aggregate the indicator series (RS Rank / Mansfield RS / Stage) to the SAME D/W/M timeframe as the price
(same bucket keys, last-in-bucket) so bar counts match and logical indices stay aligned at W/M — D/W/M
change now also calls `rerenderIndicators()`; (3) added `rightOffset: 6` to both charts' `timeScale`.
Preserved wheel-scroll-off, drag-pan, crosshair-guide sync, toggles, hide-when-none, dispose-on-rebuild.
`subscribeVisibleLogicalRangeChange`/`setVisibleLogicalRange` both present in v3.8 — no fallback needed.
Suite unchanged: **354 passed, 6 failed** (carried kernel-parity). Browser-verify: drag price past right
edge → whitespace + indicator pane scrolls in lockstep; alignment holds across D/W/M; crosshair sync,
toggles, hide-when-none still work; no console errors.

### Follow-up 2 — fix ~13px horizontal misalignment under logical-range sync · JS-only · [x] DONE (backend N/A; JS browser-verify pending)
Logical-range sync aligns by BAR INDEX, but the price (full daily OHLCV) and indicators (from
`classification_history`, different date coverage / count) had DIFFERENT bar grids, so the same date
landed ~13px apart (`timeToCoordinate('2024-06-03')`: price 866px vs indicator 853px). Fix (all in
`static/js/viewmodel.js`): (1) `renderOhlcFigure` stashes the displayed bar times
`node._displayedTimes = agg.bars.map(b => toYmd(b.time))` after aggregation (refreshed every render /
D-W-M); (2) added `alignLineToTimes(points, displayedTimes)` — as-of / forward-fill resample of each
indicator series onto the price's EXACT displayed grid (null before first point); `renderIndicatorPane`
now uses it, emitting the FULL grid with LWC-v3.8 **whitespace** points (`{time}` only) for null slots so
the indicator chart's time scale has the IDENTICAL count/times as price (else a leading-null gap shifts
index 0 and re-breaks the bar-index sync); `aggregateLine` kept as the fallback when `_displayedTimes` is
missing; (3) kept logical-range sync + `rightOffset: 6`, partner mirrors 1:1 (no offset) — with identical
grids dates line up; (4) confirmed D/W/M order re-aggregates price first (`rerenderOhlc` → updates
`_displayedTimes` + re-renders pane), then `rerenderIndicators`. Suite unchanged: **354 passed, 6 failed**
(carried). v3.8 quirk: null slots must be WHITESPACE points, not dropped, to preserve the shared grid.
Browser-verify: `timeToCoordinate(sameDate)` matches within ~1-2px across dates/timeframes; free-scroll +
lockstep hold; crosshair guides line up; toggles + hide-when-none work; no console errors.

### Follow-up 3 — upgrade Lightweight Charts 3.8 → 4.2.3 (native crosshair + reliable logical-range sync) · JS + base.html · [x] DONE (backend N/A; browser-verify pending)
Bumped `base.html` to `lightweight-charts@4.2.3` (standalone production; global still `LightweightCharts`,
confirmed `version()==4.2.3`). Used v4 to replace two v3.8 workarounds — all JS in
`static/js/viewmodel.js`: (1) **crosshair sync → native** — removed the vertical-guide `<div>` overlay
(`ensureGuide`/`hideGuide`/`showGuideAtTime`/`syncGuideFrom`, `_xGuide`, `GUIDE_COLOR`, the
`position:relative` hosts) and replaced with `syncCrosshairFrom` driving the partner chart's
`setCrosshairPosition(0, param.time, partnerSeries)` / `clearCrosshairPosition()`; partner chart + a
stashed stable series (`node._lwcSeries` = candles, `node._indSeries` = first indicator line) resolved
dynamically each move; hide-when-none clears the price crosshair. (2) **Range sync → reliable
logical-range** — removed dead `_syncing`/`_syncOwner` vars + stale reentrancy comments; kept the
guardless bidirectional `subscribeVisibleLogicalRangeChange`→`setVisibleLogicalRange` mirror (v4
idempotency stops the echo). (3) v4 API adaptations: `layout.background` →
`{ type: LightweightCharts.ColorType.Solid, color: 'transparent' }`; `crosshair.mode` →
`LightweightCharts.CrosshairMode.Normal`; `addCandlestickSeries`/`addLineSeries` kept (NOT the v5
`addSeries`); `handleScroll`/`handleScale`, `rightOffset:6`, `subscribeCrosshairMove`,
`priceScale().applyOptions`, `chart.remove()`, whitespace `{time}` points — all unchanged, work in v4.
Preserved: MA50/150/200, RS (Mansfield) price overlay toggle, D/W/M aggregation, indicator per-series
toggles, hide-when-none, dispose-on-rebuild, grid-resample alignment, synthetic-open caption.
`node --check` clean; suite **354 passed, 6 failed** (carried kernel-parity). Not committed.
