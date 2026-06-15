# Log — Monitor section

Append-only. Agents: read the open FLAGs + recent entries before starting; append a REPORT when done.
Never edit prior entries — only extend.

## 2026-06-13 · orchestrator · REPORT (effort opened, PRD accepted)
New effort for the Monitor section — the per-instrument technical + fundamental workspace that
replaces the standalone watchlist. PRD `Accepted` (`prd.md`), derived from a `/grill-me` session in
the main thread. Design resolved branch-by-branch: unified `/monitor` workspace (detail left, rail
right); rail = one flat MKLists-backed watchlist (add/side/remove/sort/select, list-name threaded for
later multi-list); technical pane = TradingView Lightweight Charts (daily + W/M aggregate, MA+RS
toggles, crosshair — lean); fundamental pane = Plotly 2×2 all-lines (EPS/Sales/PE/PS, Q/Y/TTM toggle,
actual solid → forecast dashed + high/low band, today-divider); `asof` latest-now but plumbed.

- **Data verified before acceptance** (not assumed): `MKFund.quarterly` ≈ 24Q actual history for EPS &
  Revenue; `forward_quarterly` carries EPS+Revenue mean/high/low, ~8–9 forward quarters for ~78% of
  names (fewer for thin names); `fy1`/`fy2` give 2 forward annual years; `shares_outstanding` present
  for PS. Legacy `rolling_12m`/`eps_ttm_forward`/`sales_ttm_forward`/`revisions` already compute the
  TTM+forward blends → the fundamental pane is mostly assembly.
- **Open decisions for planning (not blockers):**
  - **ADR needed** — mixed charting: TradingView Lightweight Charts (MIT) for the OHLC technical pane vs
    Plotly for analytical figures. Deviates from adr/0002 ("client-render charts via Plotly"). Decide at
    plan time.
  - **PE/PS price basis** — proposed default: historical = period-end price; forward/TTM = current price.
    Confirm during planning.
- **Next:** derive tactics — break the PRD into vertical slices (the user's flow: PRD → issues →
  slices). First slice should be the workspace spine + rail (watchlist replacement) as the tracer bullet,
  then the technical pane, then the fundamental pane.

## 2026-06-13 · orchestrator · REPORT (planning-gate decisions locked)
The two open decisions from the effort-open REPORT are resolved in-session with the user, clearing the
way to slice the PRD into issues:
- **Charting (ADR) — Lightweight Charts.** OHLC technical pane uses TradingView Lightweight Charts
  (MIT); Plotly stays for the fundamental 2×2 and all other analytical figures. Recorded as
  `docs/adr/0003-mixed-charting-lightweight-charts-for-ohlc.md` (Accepted), a scoped deviation from
  adr/0002 §2 (envelope/DI/manager contracts unchanged — only the client renderer differs by figure type).
- **PE/PS price basis — period-end / current split.** Historical periods use the period-end price;
  forward & TTM use the current price (standard trailing-vs-forward convention).
- **Next:** break the PRD into vertical-slice issues (tracer bullet first: `/monitor` workspace spine +
  rail watchlist replacement), then dispatch slice 1 once its TDD gate (interface / behaviors / DoD) is set.

## 2026-06-13 · orchestrator · REPORT (PRD sliced into issues)
PRD broken into 5 AFK vertical-slice issues (charting ADR already decided → no HITL slice needed),
published to GitHub with `enhancement` + `ready-for-agent`. Dependency chain spine → technical → fundamental:
- **#8** — slice 1: `/monitor` workspace spine + rail (watchlist replacement). *tracer bullet, no blockers.*
- **#9** — slice 2: technical pane — Lightweight Charts candles + crosshair (daily). *blocked by #8.*
- **#10** — slice 3: technical pane — D/W/M timeframes + MA + RS overlays. *blocked by #9.*
- **#11** — slice 4: fundamental pane — EPS + Sales (actual+forecast) + `asof` plumbing. *blocked by #8.*
- **#12** — slice 5: fundamental pane — PE + PS derived panels (period-end/current basis). *blocked by #11.*
- **Next:** start #8 — settle its TDD gate (public interface / prioritized behaviors / testable DoD) in the
  main session, then dispatch to the `developer` agent.

## Pre-existing context (carried, not part of this effort)
- Sibling effort `docs/work/2026-06-11-mktt-refactor/` is Done/frozen except an open **data-incident
  decision** (6 red kernel-parity tests from a restored older price snapshot + a re-introduced 2026-06-09
  single-symbol glitch). Parked by the user; does not block this effort (live app paths use `min_periods`
  and are unaffected). See that effort's 2026-06-13 HANDOFF.

## 2026-06-13 · developer · REPORT (slice 1 — /monitor workspace spine + rail · #8)
Built the unified `/monitor` workspace (detail pane left + saved-instrument rail right), the rail VM,
the rail API, and the watchlist→monitor redirects. Strict red→green→refactor, vertical slices.

**Behaviors covered (test names, all green):**
- store/service (`tests/test_monitor_section.py`): `test_members_detailed_preserves_add_order`,
  `test_rail_enriches_entries_with_stage_and_rs_rank`, `test_rail_side_defaults_long_reads_short_from_note`,
  `test_rail_default_orders_recently_added_first`, `test_rail_row_for_symbol_missing_from_cross_section`,
  `test_rail_empty_list`.
- blueprint (`tests/test_monitor_section.py`): `test_blueprint_monitor_page`,
  `test_blueprint_monitor_page_with_symbol`, `test_blueprint_chart_redirects_to_monitor`,
  `test_blueprint_watchlist_redirects_to_monitor`, `test_blueprint_monitor_rail_api`.
- lists store (`tests/test_lists.py`, live-PG): `test_members_detailed_returns_symbol_note_added_at`,
  `test_members_detailed_empty_list`.

**Files touched:**
- `lists/store.py` — added `members_detailed(list_name) -> [(symbol, note, added_at)]` (kept `members_with_notes`).
- `sections/monitor/service.py` — added `rail(lists, computed, list_name=DEFAULT_LIST) -> vm`; reads
  `members_detailed`, side from note (default long), joins precomputed `computed.cross_section()` for
  stage/rs_rank (mirrors `_handle_multi`'s `rank_lookup`, no recompute), default-orders added_at desc,
  empty→`status="empty"`. `watchlist_*` untouched. Debug logging via existing `logger`.
- `sections/monitor/__init__.py` — export `rail`.
- `sections/monitor/routes.py` — `GET /monitor` + `/monitor/<symbol>` (`monitor_page`), `GET /api/monitor/rail`;
  `/chart/<symbol>`→302 `/monitor/<symbol>`; `/watchlist`→302 `/monitor`. `/api/watchlist`, `/api/chart`,
  `/api/monitor*` unchanged. Routes stay thin.
- `sections/monitor/templates/monitor.html` — rewritten into the workspace (detail hosts + vm-* sinks fed by
  `/api/chart/<symbol>`; rail rows `▲/▼ · SYMBOL · stage · RS · ✕`, add long/short, per-row remove,
  client-side sort, click→pushState `/monitor/<symbol>`→re-render, re-fetch rail + `updateWlBadge()`).
- `templates/base.html` — `WATCHLIST` tab → `MONITOR`, points at `monitor.monitor_page`, `active_section=='monitor'`;
  `wl-badge` + `mklists*` helpers kept (still hit `/api/watchlist`).
- `tests/test_monitor_section.py` — `StubLists` gained `added_at` (monotonic int), `members_with_notes`,
  `members_detailed`; +11 behaviors. `tests/test_lists.py` — +2 `members_detailed` integration tests.

**Test command + result (`python -m pytest -q` from `src/mktt/`):**
- Before: 314 passed, 6 failed. After: **327 passed, 6 failed** (+13 new green; live PG was reachable so the
  2 lists tests ran). The 6 failures are the unchanged, out-of-scope parked kernel-parity incident
  (`tests/test_kernel.py::test_parity_kernel_vs_stage_classifier[...]`) — not touched.
- Real-app smoke (`create_app()`): `/monitor`→200 (rail), `/monitor/AAPL`→200, `/chart/AAPL`→302
  `/monitor/AAPL`, `/watchlist`→302 `/monitor`, `/api/monitor/rail`→200 JSON.

**Deviations / notes:** none from the gate. `watchlist.html` left in place but unreferenced (plan's
implementer's-call; redirect retires the page). No deps added, no cross-section recompute, Monitor↔Screener
non-import preserved. Manual browser check is the orchestrator's to run.

## 2026-06-13 · orchestrator · REPORT (slice 1 browser-verified — #8)
Ran the user's browser-verify step against the live app on :5001 (chrome-devtools). All slice-1 success
criteria confirmed live, no console errors:
- `/monitor` renders the unified workspace (detail left + rail right); nav tab is **MONITOR** (replaced
  WATCHLIST), badge live-counts MKLists members.
- Rail row format `▲/▼ · SYMBOL · stage · RS · ✕` (e.g. `▲ INTC · 0 · 98`), sort control present
  (Recently added / Stage / RS / Symbol).
- Click row → URL `→ /monitor/INTC` (pushState) + detail pane renders the existing per-symbol view
  (price+MA chart, stage/RS evolution, fundamentals table; rs_rank/sector/stage readouts).
- Add-by-ticker (added `▼ MSFT · 1 · 22` short, recently-added first, input cleared, badge → 2) and
  per-row remove (MSFT dropped, badge → 1) both persist + re-badge. **Test watchlist state restored to
  INTC-only** (added then removed the throwaway).
- `/chart/AAPL` → 302 → `/monitor/AAPL` (deep-link redirect confirmed in-browser).
- **Slice 1 (#8) done + verified. Not committed; issue not closed** (awaiting user on commit/merge).
  Next ready slices: #9 (technical pane — base.html already loads `lightweight-charts@3.8.0`) and #11
  (fundamental pane), both unblocked now that #8 is in.

## 2026-06-13 · orchestrator · REPORT (recon + two data-gap forks resolved → gates set for #9–#12)
Ran two parallel read-only recon agents before settling the remaining gates. Both surfaced that **two
PRD success criteria were verified against the legacy `.pkl`, not the `MKFund` DB the refactored section
reads** — so they don't hold on the section's actual data seam. Raised to the user; both resolved:

- **FORK-1 (technical #9) — no `open` for the universe.** `datasource/submodules/equity.py:33` stores only
  close/high/low/volume ("open is not stored for the universe"); SPY has full OHLCV but universe tickers
  don't. → **DECISION: candles use `open = prior bar's close`** (synthetic open; body/colour reflect
  up/down vs prior close). Flag as a known limitation in the figure/UX. Deviates from a *true* OHLC candle
  but keeps the candlestick view.
- **FORK-2 (fundamental #11/#12) — no forward-quarterly in the DB.** The `~8–9Q forward mean/high/low fan`
  lives only in `refinitiv_fundamentals.pkl` (`forward_quarterly` + `trend_*_fq*`), read solely by
  `legacy_routes.py` (`_rolling_12m_impl` / `_eps_ttm_forward_impl` / `_sales_ttm_forward_impl` /
  `_revisions_impl`). The `MKFund` DB has only FY1/FY2 **annual** forward (mean/high/low) + quarterly
  **actuals**. → **DECISION: port the legacy `.pkl` blend** into a reusable, DI-friendly access so the
  Monitor section gets the full forward-quarterly fan now (matches PRD fidelity; consciously reintroduces
  the `.pkl` dependency the refactor was moving away from — noted as debt for a future `forward_quarterly`
  DB-loader task).
- **Locked earlier, carried:** Lightweight Charts for OHLC (`adr/0003`); PE/PS = period-end (historical) /
  current (forward·TTM).
- **Gates for #9–#12 written to `plan-dev.md`.** Dispatch order (shared files `service.py`/`monitor.html`
  force sequencing, not parallel): technical chain #9→#10, then fundamental chain #11→#12; browser-verify
  between. Each developer agent builds on the prior's working tree.

---

## REPORT — Slice 2 / #9 technical pane: Lightweight Charts candles + crosshair (daily) [developer]

**Task:** plan-dev.md "Slice 2 — Technical pane: Lightweight Charts candles + crosshair (daily) · #9". Strict TDD.

**Built (all under `src/mktt/`):**
- `sections/monitor/service.py` — replaced `_price_figure` with `_ohlc_figure(symbol, enriched)` emitting the
  non-Plotly figure shape: `id="monitor_price"`, `kind="ohlc"`, `bars` (FORK-1 synthetic `open = prior close`;
  first bar `open == its own close`), `volume` `{time,value}`, `series` MA50/150/200 as `{time,value}` arrays,
  `layout.title`, `notes.synthetic_open=true`. No `traces` key. JSON-safe via existing `_cell` (NaN→None).
  Debug log on entry (`MKTT_LOG_LEVEL=DEBUG`). `handle()` now calls `_ohlc_figure`.
- `static/js/viewmodel.js` — `renderFigure` branches on `fig.kind === "ohlc"` BEFORE the Plotly path → new
  `renderOhlcFigure(fig, node)`: guards `typeof LightweightCharts`, disposes the prior chart stashed on
  `node._lwcChart` (`chart.remove()`) before recreating, `createChart` → `addCandlestickSeries().setData(bars)`,
  one `addLineSeries().setData()` per `series` (NaN points filtered), `subscribeCrosshairMove` → writes O/H/L/C+date
  to `#monitor-ohlc-readout`. Exposed `_renderOhlcFigure`. `node --check` clean.
- `sections/monitor/templates/monitor.html` — added `#monitor-ohlc-readout` + a small synthetic-open UX caption
  just above the existing 480px `#monitor_price` host. No route change.

**Behaviors covered (tests, `tests/test_monitor_section.py`):**
- `test_handle_single_symbol_live_kernel_shape` (UPDATED, expected red→green) — `kind=="ohlc"`, no `traces`, MA series present.
- `test_ohlc_bars_open_is_prior_close` (b2) — t/o/h/l/c; `open==prior close`; `bars[0].open==bars[0].close`.
- `test_ohlc_series_ma_aligned_to_bars` (b3) — MA50/150/200 `{time,value}` aligned 1:1 to bars.
- `test_ohlc_volume_present_as_time_value` (b4).
- `test_ohlc_nan_values_serialize_to_none` (b5) — MA200 warm-up NaN → None.
- `test_ohlc_notes_flag_synthetic_open` (b6).

**Test command + result (from `src/mktt/`):** `python -m pytest -q` → **332 passed, 6 failed**.
Before: 327 passed / 6 failed. After: 332 passed / 6 failed. The +5 are the new ohlc tests (the updated shape
test replaced its own assertions in place). The 6 fails are the unchanged, out-of-scope
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` carried baseline — not touched.

**Deviations:** none. FORK-1 honoured as locked. JS renderer is browser-verify-only (not unit-tested), per plan.

**State left:** Slice 2 service contract is green and the LWC renderer + template are in place. Unblocks the
orchestrator's browser verification (candles render, crosshair readout updates, MA overlay, chart disposed on
re-select) and Slice 3 / #10 (D/W/M + MA toggles + RS), which extends `_ohlc_figure` with `benchmark`. Not committed; issue not closed.

---

## REPORT — Slice 3 / #10 technical pane: D/W/M timeframes + MA toggles + RS line [developer]

**Task:** plan-dev.md "Slice 3 — Technical pane: D/W/M timeframes + MA toggles + RS line · #10". Strict TDD on the
backend surface (the new `benchmark` block); aggregation/MA/RS math is client JS, browser-verified.

**Built (all under `src/mktt/`):**
- `sections/monitor/service.py` — `handle()` now fetches the SPY benchmark panel and passes it to
  `_ohlc_figure(symbol, enriched, bench)`. `_ohlc_figure` carries a new **`benchmark`** key:
  `[{"time","value"}]` (SPY close) built by the new `_benchmark_series(bench, dates)` — a `date->close`
  lookup emitting one point per symbol bar, aligned 1:1 to `bars` by `time`, JSON-safe (`_cell`, NaN→None),
  missing-date/missing-panel → `value=None` (never raises). Everything #9 emits is unchanged. Debug log path intact.
- `static/js/viewmodel.js` — extended `renderOhlcFigure`: stashes the raw daily figure on `node._ohlcFig`,
  reads toolkit state from the DOM (timeframe / MA toggles / RS), and renders the **displayed timeframe**:
  - `aggregate(bars, volume, benchmark, tf)` — daily → W (ISO week) / M (calendar month) with OHLC rules
    (open=first, high=max, low=min, close=last, volume=sum, benchmark=last-in-bucket); bucket time = last day.
  - `smaSeries(bars, period)` — SMA recomputed on the displayed-timeframe closes (null in warm-up).
  - `mansfieldRs(bars, benchmark)` — RP=close/bench normalized to its trailing SMA(min(52,len)),
    `(RP/SMA-1)*100`, drawn on its **own** overlay price scale (`rs-scale`, bottom 20%).
  - New `wireTechToolkit()` (idempotent) binds D/W/M (segmented, active class), MA checkboxes and the RS
    checkbox → `rerenderOhlc()` which re-renders from the stashed figure **without refetching**. #9 chart
    disposal (`node._lwcChart.remove()`) + crosshair readout preserved. Exposed `wireTechToolkit`,
    `rerenderOhlc`, and `_aggregateOhlc`/`_smaSeries`/`_mansfieldRs`/`_isoWeekKey` for inspection. `node --check` clean.
- `sections/monitor/templates/monitor.html` — added `#monitor-tech-toolkit` above `#monitor_price`: D/W/M
  segmented control, MA50/150/200 checkboxes (checked by default), RS checkbox; calls `ViewModel.wireTechToolkit()`
  on `DOMContentLoaded`.

**Behaviors covered (test, `tests/test_monitor_section.py`):**
- `test_ohlc_benchmark_aligned_to_bars` — the ohlc figure carries a non-empty `benchmark` series aligned 1:1
  with `bars` by `time` (`{time,value}` shape; SPY[0]==400.0). The #9 ohlc tests (bars/series/volume/notes) stay green.

**Test command + result (from `src/mktt/`):** `python -m pytest -q` → **333 passed, 6 failed**.
Before: 332 passed / 6 failed. After: 333 passed / 6 failed (+1 new green: the benchmark test). The 6 fails are the
unchanged, out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` carried baseline — not touched.
Client math sanity-checked in node (weekly/monthly OHLC roll-up, SMA warm-up, RS, ISO week keys — all correct).

**Deviations:** none from the gate. RS uses its own overlay price scale (own scale, per spec).

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol with no console errors —
(1) D/W/M switch re-aggregates the candles (weekly/monthly buckets, body sits on period close);
(2) MA50/150/200 checkboxes add/remove lines **recomputed on the shown timeframe**;
(3) RS checkbox overlays a Mansfield line on its own scale and toggles off cleanly;
(4) all of the above re-render WITHOUT a network refetch (toolkit reads the stashed daily figure);
(5) the #9 crosshair readout still updates across timeframes and the chart is still disposed on re-select.
Not committed; issue not closed.

## REPORT (addendum) — Slice 3 / #10 bug fix: RS-toggle on weekly blanks the candle chart [developer]

**Task:** continuation of "Slice 3 — Technical pane · #10". Browser-verification bug, backend fine, JS-only.

**Repro:** `/monitor/INTC` → renders Daily fine → click **W** → toggle **RS** on → console throws
`Uncaught TypeError: ymd.split is not a function` and `#monitor_price` goes blank.

**Root cause:** `aggregate()`'s Daily branch (`tf==='D'`) returned `fig.bars` **by reference**;
`renderOhlcFigure` stashes that same array on `node._ohlcFig` AND passes it to `candles.setData(agg.bars)`.
TradingView Lightweight Charts **normalizes the `time` field of the supplied data objects in place** during
`setData` (string `"YYYY-MM-DD"` → internal repr), corrupting the stashed figure's `time` values. On the next
re-render, `aggregate('W')` → `isoWeekKey(bar.time)` → `ymd.split('-')` on a now-non-string time → crash.

**Fix (both, belt-and-suspenders) in `static/js/viewmodel.js`:**
1. Stop sharing mutable objects with `setData`: `candles.setData(agg.bars.map(...fresh plain object...))`,
   and `aggregate`'s `tf==='D'` early-return now **clones** bars/volume/benchmark into fresh objects rather
   than returning the stashed references. (MA/RS line series were already built fresh via map/push with
   immutable string `time`, so no extra clone needed there.)
2. Defensive coercion: new `toYmd(t)` helper normalizes a string / epoch-seconds number / LWC BusinessDay
   `{year,month,day}` → `"YYYY-MM-DD"`. `isoWeekKey` and the month `keyFn` now route their input through it,
   so aggregation is robust even if a non-string time slips through. Exported as `_toYmd`.

**Files touched:** `static/js/viewmodel.js` only.

**Verification:**
- `python -m pytest -q` (from `src/mktt/`) → **333 passed, 6 failed** — unchanged from baseline; the 6 are the
  carried `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` fails. `test_ohlc_benchmark_aligned_to_bars`
  untouched and still green. Fix is JS-only so no count change expected/observed.
- Ad-hoc node assertions (no JS test infra in repo): aggregate(D) returns no input refs and does not mutate
  input `time`; `toYmd` handles string/epoch/BusinessDay; `isoWeekKey` gives identical key for string vs
  BusinessDay; weekly aggregation of a non-string time no longer crashes. All passed.

**State left — needs BROWSER RE-VERIFICATION (orchestrator):** `/monitor/INTC` D→W→M switching, MA toggles,
RS overlay on/off, crosshair — no `ymd.split` error, chart stays rendered. Not committed.

---

## REPORT — Slice 4 / #11 fundamental pane: EPS + Sales (actual+forecast) + `asof` plumbing [developer]

**Task:** plan-dev.md "Slice 4 — Fundamental pane: EPS + Sales (actual+forecast) + `asof` plumbing · #11".
Strict TDD on the Python surface (datasource pkl-port + service `fundamentals_view` + thin route); the JS 2×2
render is browser-verified. **FORK-2 honoured: ported the legacy `.pkl` blend** into a DI-friendly datasource access.

**Built (all under `src/mktt/`):**
- `datasource/fundamental_series.py` — NEW. Ports the legacy `legacy_routes.py` blend
  (`_rolling_12m_impl` / `_eps_ttm_forward_impl` / `_sales_ttm_forward_impl`) into a **Flask-free, DI** access
  `build_fundamental_series(loader=…) -> (symbol, asof=None) -> structured dict`. The default loader mtime-caches
  the on-disk `data/mktt/refinitiv_fundamentals.pkl`; tests inject a fake dict. Returns
  `{quarterly:{dates,eps,revenue}, ttm:{dates,eps,revenue,fwd_dates,eps_/rev_ mean/high/low},
  annual:{fy_dates,eps,rev,fwd_dates,eps_/rev_ mean/high/low}, forward_q:{dates,eps_/rev_ mean/high/low}}`.
  Revenue in $m; forward fan up to 8Q; TTM = rolling 4Q sum + forward blend; annual = complete-year sum +
  FY1/FY2 forward. `asof` clips quarterly/TTM actuals to `report_date <= asof` (forward fan = current snapshot,
  unaffected). All JSON-safe (NaN/inf→None). Stripped the legacy `request.args` Flask coupling.
- `datasource/provider.py` — `DataSource.fundamental_series(symbol, asof=None)` delegates to the access
  (lazily built on first call; injectable via the new `fundamental_series=` ctor arg — DI seam).
- `sections/monitor/service.py` — `fundamentals_view(symbol, data, granularity="Q", asof=None) -> vm` building
  Plotly figures `fund_eps` + `fund_sales`, each: an **Actual** solid trace + a high/low **band** (Low + Est.range
  `fill='tonexty'`) + a **Forecast** dashed trace, and a **today-divider** line shape in `layout` at the
  actual/forecast boundary. `granularity ∈ {Q,Y,TTM}` selects the series set; `asof` threads into
  `data.fundamental_series`. Section stays thin/DI/envelope — NO Flask, NO formulas (the blend lives in the
  datasource layer). `handle()` unchanged (this is its own view). Exported from `__init__.py`.
- `sections/monitor/routes.py` — `GET /api/monitor/fundamentals/<symbol>?granularity=&asof=` →
  `fundamentals_view` → jsonify (focused payload; thin route). A separate endpoint from the full monitor
  envelope so a toggle re-renders ONLY the 2×2, never the candle chart.
- `sections/monitor/templates/monitor.html` + inline JS — added the 2×2 host divs (`#fund_eps`, `#fund_sales`,
  + `#fund_pe`/`#fund_ps` reserved for #12), a Q/Y/TTM segmented control, `loadFundamentals(sym)` (separate
  fetch, renders via `ViewModel._renderFigure` = existing Plotly path), wired into symbol-select + the toggle.
  Technical pane / toolkit untouched.

**Behaviors covered (tests):**
- `tests/test_monitor_section.py` (6 service + 1 route, all green): `test_fundamentals_view_emits_eps_and_sales_figures`,
  `test_fundamentals_view_actual_forecast_band_per_figure`, `test_fundamentals_view_granularity_switches_series_set`,
  `test_fundamentals_view_today_divider_shape`, `test_fundamentals_view_asof_passes_through_and_defaults_none`,
  `test_fundamentals_view_forecast_only_as_deep_as_data`, `test_blueprint_fundamentals_route_is_thin`.
  Added `StubData.fundamental_series` (records `(symbol, asof)`) + a deterministic structured fixture.
- `tests/test_datasource.py` (7, all green — the pkl-port blend math via an injected fake pkl):
  `test_fundamental_series_quarterly_actuals`, `test_fundamental_series_forward_quarterly_fan_depth_and_scale`,
  `test_fundamental_series_ttm_rolling_4q_sum`, `test_fundamental_series_annual_actual_plus_fy1_fy2_forward`,
  `test_fundamental_series_asof_filters_quarterly_actuals`, `test_fundamental_series_unknown_symbol_is_empty_not_error`,
  `test_datasource_fundamental_series_delegates_to_injected_access`.

**Test command + result (`python -m pytest -q` from `src/mktt/`):**
Before: 333 passed, 6 failed. After: **347 passed, 6 failed** (+14 new green). The 6 fails are the unchanged,
out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` carried baseline — not touched.
Real-data smoke (production `build_default_datasource()` against the real pkl): AAPL → 24 quarterly EPS, 8Q
forward fan, 21 TTM points, annual FY actuals + FY1/FY2 forward; `fundamentals_view` emits both figures with
Actual/Low/Est.range/Forecast + today-divider; Q/Y/TTM switch the series sets (Q 24/8, Y 5/2, TTM 21/8).

**Deviations:** none from the gate. Built the band + forecast + divider in the tracer-bullet cycle (the next
behaviors), so cycles 2/4 passed on first run — the tests still verify behavior through the public interface.

**DEBT (carried):** reintroduced the `.pkl` dependency the refactor was moving away from. It is isolated to the
single `datasource/fundamental_series.py` default loader (the one place the pkl is read); a `forward_quarterly`
DB-loader is the proper future fix (a follow-up task), at which point only the default loader swaps.

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol with no console errors —
(1) EPS + Sales panels render Actual (solid) → Forecast (dashed) + a faint high/low band;
(2) the Q/Y/TTM segmented control re-fetches + re-renders ONLY the 2×2 (the candle chart does not reload);
(3) the today-divider (dotted vertical) sits at the actual/forecast boundary;
(4) `#fund_pe`/`#fund_ps` stay empty (reserved for #12).
Not committed; issue #11 not closed.

---

## REPORT — Slice 5 / #12 fundamental pane: PE + PS derived panels (period-end / current basis) [developer]

**Task:** plan-dev.md "Slice 5 — Fundamental pane: PE + PS derived panels · #12" — the FINAL slice,
completing the 2×2. Strict red→green per behavior. Basis LOCKED: historical = period-end price;
forward & TTM = current price; PS uses `shares_outstanding`.

**Built (all under `src/mktt/`):**
- `sections/monitor/service.py` — `fundamentals_view` now ALSO emits `fund_pe` + `fund_ps` (bottom row),
  same visual language as EPS/Sales (Actual solid → Forecast dashed + Low/Est.range band + today-divider).
  New helpers: `_price_basis(data, symbol)` → `(period_end_lookup, current_price)` from
  `data.time_series([symbol], fields=("close",))` (empty/raising → `({}, None)`, ratios then None);
  `_period_end_price(period_end, report_date)` → close on the report date else nearest *prior* trading day;
  `_shares_outstanding(data, symbol)` from the fundamentals row; `_pe`/`_ps`/`_ratio` with the
  divide-by-zero / non-positive / missing-shares guards (→ None, no fabricated point). Basis: Q/Y **actuals**
  use the period-end price; forward estimates AND the whole **TTM** domain use the current (last close) price.
  Band edges propagate the EPS/revenue high/low through the ratio — for PS the high-revenue edge maps to the
  **low** PS, so the band edges swap. Section stays thin/DI/envelope — light presentation math on already-
  fetched series; the heavy blend stays in `datasource/fundamental_series.py`. `handle()` unchanged.
- `sections/monitor/templates/monitor.html` — **no change required** (verified): the `#fund_pe`/`#fund_ps`
  hosts were reserved in #11; `loadFundamentals` already iterates ALL `vm.figures` → `ViewModel._renderFigure`
  (dispatch by `fig.id`), and the Q/Y/TTM toggle already re-runs `loadFundamentals`. The two new figures
  render + re-render on toggle automatically.

**Behaviors covered (tests, `tests/test_monitor_section.py`, all green):**
- `test_fundamentals_view_emits_pe_and_ps_figures` (b1, tracer) — `fund_pe` + `fund_ps` emitted.
- `test_fundamentals_view_pe_historical_period_end_forward_current` (b2) — historical PE = period-end
  close / EPS; forecast PE = current price / forward EPS mean.
- `test_fundamentals_view_ttm_uses_current_price` (b2) — TTM actual uses the current price.
- `test_fundamentals_view_ps_uses_shares_outstanding` (b3) — PS = price*shares/revenue.
- `test_fundamentals_view_ratio_guards_nonpositive_to_none` (b3) — zero/negative EPS & zero revenue → None;
  missing `shares_outstanding` → PS None.
- `test_fundamentals_view_pe_ps_honor_toggle_divider_asof` (b4) — Q/Y/TTM select the actual-period dates,
  today-divider at the forecast boundary per granularity, `asof` threads into `data.fundamental_series`.
- Stubs extended: `_ratio_price_panel` (distinct period-end closes 200/210/220/230 + a distinct current
  close 300), `_ratio_funds` (adds `shares_outstanding`), `_ratio_data` (wires panel + funds + fund_series).
  The #11 fundamentals tests stay green (they index `traces[0]` / figure ids, unaffected by +2 figures).

**Test command + result (`python -m pytest -q` from `src/mktt/`):**
Before: 347 passed, 6 failed. After: **353 passed, 6 failed** (+6 new green). The 6 fails are the unchanged,
out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` carried baseline — not touched.

**Deviations:** none from the gate. Ratio derivation kept in the view (light presentation math on the
already-fetched #11 series + price), the heavy blend stays in the datasource layer (per the gate's "your call").

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol, no console errors —
(1) the full 2×2 renders (EPS / Sales / PE / PS); (2) PE/PS basis correct — historical points use the
period-end price, the forward fan + TTM use the current price; (3) the Q/Y/TTM toggle re-renders ALL FOUR
panels (PE/PS included) without reloading the candle chart; (4) the today-divider + high/low band are
consistent across all four. Not committed; issue #12 not closed. This was the final slice — the 2×2 is
complete pending browser-verify.

---

## REPORT addendum — Slice 5 / #12 PS unit bug fix (browser-verification follow-up)

**Task:** Browser verification of the 2×2 fundamentals pane surfaced a correctness bug in the **PS** panel
only (PE confirmed fine — INTC's PE ~300→~1500 in a weak quarter is legitimate depressed-EPS behaviour).

**Symptom:** `/monitor/INTC` `fund_ps` chart read P/S ≈ 10M–40M; a price/sales ratio should be a small
multiple (INTC ≈ 10×). PS inflated by ~1e6.

**Root cause (confirmed against the data layer, not assumed):**
- `revenue` from `data.fundamental_series` is in **$ MILLIONS** — `datasource/fundamental_series.py` divides
  the raw Refinitiv `Revenue - Actual` (verified ~14.26e9 dollars/quarter for INTC) by `1e6` in every block
  (`_quarterly_block`, `_ttm_block`, `_annual_block`, `_forward_quarterly`).
- `shares_outstanding` from `data.fundamentals` is a **RAW share count** — `mkfund_loader.py` maps
  `"Outstanding Shares"` via `_num` with no scaling (~4.3e9 for INTC).
- `_ps` computed `price * shares / revenue` mixing a raw count against revenue-in-millions → inflated by
  exactly `1e6`. Sanity check (INTC): buggy `125 × 4.3e9 / 53000 ≈ 1.0e7` ✓ matches the chart; correct
  `125 × 4.3e9 / 53e9 ≈ 10.1` ✓.

**Fix (`sections/monitor/service.py`, `_ps`):** scale revenue to dollars before dividing —
`revenue_dollars = revenue * 1e6`, `PS = price * shares / revenue_dollars`. The 1e6 factor is exact
(revenue confirmed in millions, not thousands). Named constant `_REVENUE_MILLIONS_TO_DOLLARS = 1e6` with a
unit comment. The high/low band gets the same fix automatically — it flows through the same `_ps` via
`_ratio`. **PE untouched** (`_pe` unchanged; EPS already a per-share dollar figure).

**Behaviors covered (tests, `tests/test_monitor_section.py`):**
- `test_fundamentals_view_ps_units_are_a_sane_ratio_not_inflated` (NEW regression guard) — realistic stub
  (price 125, shares 4.3e9, revenue 13 350 $m) → asserts `0 < ps < 1000` and pins `ps ≈ 40.2622`
  (`125 × 4.3e9 / (13350 × 1e6)`). Locks the unit so it can't silently regress to ~1e7.
- `test_fundamentals_view_ps_uses_shares_outstanding` (UPDATED) — expected formula now
  `price * shares / (rev * 1e6)` to reflect the unit-consistent derivation.

**Test command + result (`python -m pytest -q` from `src/mktt/`):**
**354 passed, 6 failed** (was 353 passed; +1 new guard). The 6 fails are the unchanged, out-of-scope
`test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` carried baseline — not touched.

**State left:** PS unit bug fixed + guarded. Not committed. Pending orchestrator browser re-verify — the
`fund_ps` panel should now read a single/double-digit ratio on a live symbol. PE unchanged.

---

## 2026-06-13 · orchestrator · DEBRIEF (Monitor effort — all 5 slices done + browser-verified)
All five vertical slices implemented (TDD, developer agents), each browser-verified live on :5001 by the
orchestrator (chrome-devtools). Final suite: **354 passed, 6 failed** (the 6 are the carried, out-of-scope
kernel-parity data-incident — untouched throughout). No console errors on the final pass (only a benign
`/favicon.ico` 404, pre-existing).

**Shipped:**
- **#8** workspace spine + rail — `/monitor` (detail left + rail right), MKLists-backed rail
  (`▲/▼·SYMBOL·stage·RS·✕`, add/side/remove/sort/select), nav WATCHLIST→MONITOR, `/chart` & `/watchlist`
  → 302 redirects. Verified: add/remove persists + re-badges, click→URL+detail, redirects.
- **#9** technical candles — Lightweight Charts daily candlesticks + MA50/150/200 overlay + crosshair;
  synthetic `open = prior close` (FORK-1) with an honest UX caption. Verified.
- **#10** D/W/M + MA toggles + RS — client-side aggregation (ISO week / calendar month), MAs recomputed on
  the displayed timeframe, Mansfield-RS overlay vs SPY (server adds `benchmark` to the figure). Verified
  D/W/M switching + RS overlay. **One bug found+fixed in verification:** LWC `setData` mutates the bar
  `time` in place; the stash shared those objects -> `ymd.split is not a function` on re-aggregate. Fixed by
  cloning bars before `setData` + a `toYmd` coercion guard.
- **#11** fundamental EPS + Sales — Plotly, actual solid -> forecast dashed + high/low band + today-divider,
  Q/Y/TTM toggle (own `/api/monitor/fundamentals/<sym>` endpoint), `asof` plumbed (default latest). FORK-2:
  the legacy `.pkl` forward-quarterly blend ported into `datasource/fundamental_series.py` (DI-friendly).
  Verified Q<->Y re-render.
- **#12** fundamental PE + PS — completes the 2x2; basis locked (historical=period-end price,
  forward/TTM=current). **One bug found+fixed in verification:** PS inflated x1e6 (revenue in $millions vs
  raw `shares_outstanding`); fixed by scaling revenue to dollars + a units regression guard. Verified PE
  (~300, legit spike on depressed EPS) and PS (~10-40 sane ratio).

**Methodology note (not a bug):** at Q granularity PE/PS use *quarterly* EPS/revenue, so they read ~4x the
annual ratio — internally consistent with showing quarterly series; Y/TTM give the conventional figure.

**Debt / follow-ups (carried, not done):**
- Reintroduced `.pkl` dependency (FORK-2), isolated to the default loader in
  `datasource/fundamental_series.py`. Proper fix = a `forward_quarterly` DB-loader (MKFund) — future task.
- Synthetic candle open (FORK-1) — a true daily `open` series for the universe is a future data-plumbing task.
- `watchlist.html` left on disk but unrouted (redirect retires the page).

**NOT done (await user):** nothing committed; issues #8-#12 not closed; `docs/product/mktt-architecture.md`
not yet updated; effort folder not frozen. These are the effort-closure steps pending user sign-off on
commit/merge.

## 2026-06-13 · orchestrator · REPORT (fix — candle chart hijacked page scroll)
User reported: scrolling the page "collapsed from above". Root cause: Lightweight Charts captures the
mouse wheel by default (`handleScroll.mouseWheel`/`handleScale.mouseWheel` = true), so wheel-over-chart
zoomed/panned the candles away and trapped page scrolling. Fix in `static/js/viewmodel.js`
`renderOhlcFigure` createChart options: `handleScroll.mouseWheel:false` + `handleScale.mouseWheel:false`
(drag-pan + axis-drag zoom + double-click-axis reset stay on). Verified live via `chart.options()` +
clean re-render, no console errors. JS-only; no test-count change (browser-verified).

---

## REPORT — Slice 6 (enhancement): Indicators as a synced Lightweight-Charts pane (toggleable) [developer]

**Task:** plan-dev.md "Slice 6 (enhancement) — Indicators as a synced Lightweight-Charts pane (toggleable)".
Moves RS Rank / Mansfield RS / Stage out of the Plotly `#monitor_history` panel into a second LWC sub-chart
stacked under the price, time-synced with it, each indicator shown on toggle, pane hidden when none are on.

**Built (all under `src/mktt/`):**
- `sections/monitor/service.py` — `_history_figure` now emits the **non-Plotly** shape
  `{"id":"monitor_history","kind":"indicators","series":[{name,scale,data:[{time,value}]}]}`. Dropped the
  Plotly `traces`/3-axis `layout`. Series: "RS Rank" (scale `rsrank`), "Mansfield RS" (`mansfield`), "Stage"
  (`stage`); only a series whose column exists in `hist` is included; names EXACT so `.ind-tog` `data-ind`
  matches; times `str(d)[:10]`, values JSON-safe via `_cell` (NaN→None). New module-level `_INDICATORS` map.
- `static/js/viewmodel.js` —
  - `renderOhlcFigure` stashes the price chart in module var `_priceChart` (set on build, cleared on dispose),
    and at the end re-renders the indicators pane from its stash so the pane re-syncs to the freshly-rebuilt
    price chart after a symbol switch or D/W/M change.
  - `renderFigure` branches `fig.kind === 'indicators'` (before Plotly) → `renderIndicatorPane`.
  - `renderIndicatorPane(fig, node)`: stashes `node._indFig`; disposes prior `node._indChart` (`.remove()`);
    reads `.ind-tog` state; **none checked → `node.style.display='none'` and return**; else creates an LWC
    chart (guards `typeof LightweightCharts`, `handleScroll/handleScale.mouseWheel:false`), one
    `addLineSeries({priceScaleId:<scale>})` per CHECKED series with `.setData(filter value!=null)` + per-series
    `scaleMargins` (RS Rank top band, Mansfield mid w/ room, Stage bottom band) so scales don't collide.
    **Time-sync** via `linkTimeRanges`: BOTH charts' `timeScale().subscribeVisibleTimeRangeChange(...)` mirror
    through `setVisibleRange({from,to})` with a module-level `_syncing` reentrancy guard; synced by TIME range
    (not logical — daily indicators vs W/M-aggregated price differ in density). On first build it adopts the
    price chart's current visible range if present, else `fitContent()`.
  - Exposed `ViewModel.rerenderIndicators()` (re-runs `renderIndicatorPane` from `node._indFig`; guarded if
    absent) + `_renderIndicatorPane` for inspection. `node --check` clean.
- `sections/monitor/templates/monitor.html` — removed `applyIndicatorToggles` + its `.then(applyIndicatorToggles)`
  chain in `renderDetail` (the pane now renders via the generic `renderFigure`); repointed the `.ind-tog`
  `change` handlers to `ViewModel.rerenderIndicators()`. Checkbox row + `#monitor_history` host kept.

**Behaviors covered (test, `tests/test_monitor_section.py`):**
- `test_handle_history_figure_from_computed` (UPDATED, expected red→green) — asserts `monitor_history` figure
  has `kind == "indicators"`, no `traces` key, and `series` names include "RS Rank"/"Mansfield RS"/"Stage".

**Test command + result (`python -m pytest -q` from `src/mktt/`):**
Before: 354 passed, 6 failed. After: **354 passed, 6 failed** (same count; the updated test replaced its own
assertions in place). The 6 fails are the unchanged, out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]`
carried baseline — not touched.

**Deviations:** none from the gate. Used `subscribeVisibleTimeRangeChange`/`setVisibleRange` (v3.8 supports
both) — no fallback primitive needed. The price chart re-renders the indicator pane at the end of
`renderOhlcFigure` so the sync subscription always points at the live price-chart instance (it's a new
instance on every price render).

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol, no console errors —
(1) the indicators pane renders as an LWC sub-chart under the price (not Plotly); checked indicators show on
their own scales without colliding;
(2) toggling each `.ind-tog` checkbox adds/removes the matching series with no refetch; pane HIDES when all off,
reappears when one is re-checked;
(3) pan/zoom the price chart → the indicators pane follows (and vice-versa), no ping-pong/jitter;
(4) survives a symbol switch and D/W/M timeframe changes (pane re-syncs to the rebuilt price chart).
Not committed. Note for the user: the price toolbar's existing "RS (Mansfield vs SPY)" overlay (#10, client
52-window) is left as-is — distinct from the pane's 252-day kernel Mansfield.

---

## REPORT — Slice 6 (enhancement): synchronized crosshair (vertical-guide overlay) [developer]

**Task:** plan-dev.md "Slice 6 — Indicators as a synced Lightweight-Charts pane" — the crosshair-sync
follow-up. JS-only enhancement in `static/js/viewmodel.js`. Bidirectional vertical-guide crosshair between
the price pane (`#monitor_price`) and the indicators pane (`#monitor_history`).

**Constraint honoured:** base.html loads lightweight-charts@3.8.0 — has `subscribeCrosshairMove` (read) but
NOT `setCrosshairPosition`/`clearCrosshairPosition` (v4+). So the sync is a 1px vertical guide `<div>` overlay
on the PARTNER host (positioned via `timeScale().timeToCoordinate(time)`), NOT a driven crosshair. LWC dep
unchanged.

**Built (`src/mktt/static/js/viewmodel.js` only):**
- New crosshair-sync block: `ensureGuide(host)` (lazily creates + caches ONE guide div per host —
  `pointer-events:none`, `position:absolute; top:0; bottom:0; width:1px`, `rgba(255,255,255,0.28)`, hidden by
  default; re-created if a host re-render detached it via `innerHTML=''`), `hideGuide(host)`,
  `showGuideAtTime(partnerChart, host, time)` (computes `x = partnerChart.timeScale().timeToCoordinate(time)`;
  finite number → `left:x px` + show, else hide), and `syncGuideFrom(sourceChart, resolvePartner)` — subscribes
  the source chart's crosshair and resolves the partner chart+host **dynamically each move** (the indicator
  chart is rebuilt on every toggle, so nothing stale is captured); `param.time == null` (crosshair left) → hides
  the partner guide.
- `renderOhlcFigure`: sets `node.style.position='relative'` on `#monitor_price`; after the existing OHLC readout
  subscription, wires price→indicator via `syncGuideFrom(chart, …)` — resolver looks up
  `document.getElementById('monitor_history')._indChart` each move and returns null when the pane is absent/hidden.
  Subscribed once per price render (the price chart is the single persistent source — no double-subscribe across
  indicator toggles).
- `renderIndicatorPane`: sets `node.style.position='relative'`; on "none checked" it hides BOTH its own guide and
  the price chart's guide before hiding the pane; wires indicator→price via `syncGuideFrom(chart, …)` (resolver
  reads `document.getElementById('monitor_price')._lwcChart` each move) — subscribed per indicator render (this
  chart is a fresh instance each toggle / symbol switch / D-W-M change).
- Existing `#monitor-ohlc-readout` behaviour untouched.

**Tests / DoD:** JS-only — no Python test changes. `node --check` clean; module require smoke-loads.
`python -m pytest -q` (from `src/mktt/`): before **354 passed, 6 failed** → after **354 passed, 6 failed** —
unchanged. The 6 are the carried, out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]`
kernel-parity fails — not touched.

**Note on v3.8 `timeToCoordinate` (per the gate's ask):** guides are positioned by TIME, not logical index —
`timeToCoordinate(param.time)` maps the hovered timestamp to the partner's pixel x independently on each chart,
so a daily indicator pane and a W/M-aggregated price pane still align by time (a daily time hovered on the price
chart resolves to the nearest plotted x on the indicator pane and vice-versa). When the hovered time has no
coordinate on the partner (outside its data / off-axis), `timeToCoordinate` returns null → that guide hides
rather than mispositioning. No unexpected behaviour observed at parse/require level; full visual confirmation is
the browser-verify below.

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol, no console errors —
(1) hover the price chart → a vertical guide appears on the indicators pane at the same time, and the existing
O/H/L/C readout still updates; (2) hover the indicators pane → a guide appears on the price chart at the same
time; (3) move the cursor off either chart → the partner guide clears; (4) the guide stays time-aligned after
toggling indicators (`.ind-tog`), switching symbol, and changing D/W/M; (5) when all indicators are toggled off
(pane hidden) → no stray guide on the price chart. Not committed.

---

## REPORT — Slice 6 (fix): price chart pinned to right edge — switch sync to LOGICAL range [developer]

**Task:** plan-dev.md "Slice 6 — Indicators as a synced Lightweight-Charts pane" — fix the price chart
being **pinned to its right edge** (can't scroll/pan past the last bar into empty space). Root cause
(diagnosed in the task): the price<->indicator cross-chart sync used TIME range
(`subscribeVisibleTimeRangeChange`/`setVisibleRange`), which cannot represent whitespace past the last
bar, so any scroll-past was clamped back. JS-only, all in `static/js/viewmodel.js`.

**Built (`src/mktt/static/js/viewmodel.js` only):**
1. **LOGICAL-range sync** — `linkTimeRanges` replaced with `linkLogicalRanges(a,b)` using
   `subscribeVisibleLogicalRangeChange` + `setVisibleLogicalRange` both directions. Logical range
   (fractional bar indices) runs past `[0, len-1]`, so the master free-scrolls into whitespace and the
   partner follows. **Async-safe reentrancy guard**: replaced the synchronous `_syncing=true;…;false`
   (which can clear before an async echo arrives and let the echo revert the master) with an
   initiator-tracking guard `_syncOwner` — the partner's echo (`_syncOwner !== src`) is dropped, and
   ownership is released on the next `requestAnimationFrame` (deferring past both the synchronous
   `setVisibleLogicalRange` echo and any async partner callback in the same frame). The owning chart's
   own further moves still propagate (it re-claims ownership each move).
2. **Bar-cadence match** — new `aggregateLine(points, tf)` helper mirrors `aggregate`: buckets the
   indicator series by the SAME keys the price uses (`isoWeekKey` for W, `YYYY-MM` for M) and takes the
   **last value in each bucket** (RS Rank / Mansfield RS / Stage are slow/period-end/categorical →
   last-in-bucket). `renderIndicatorPane` now reads the current timeframe via `readToolkitState().tf`
   and runs each series through `aggregateLine` before `setData`, so the pane's bar count equals the
   price's at every timeframe and the logical sync stays aligned at W/M. The D/W/M control now also
   calls `rerenderIndicators()` (alongside `rerenderOhlc()`) on a timeframe change; the price render's
   end-of-`renderOhlcFigure` re-render of the pane already covered this implicitly, the explicit call
   makes it robust when the price chart isn't present yet.
3. **`rightOffset: 6`** added to BOTH charts' `timeScale` — last bar isn't glued to the edge (breathing
   room + whitespace to scroll into). Same offset on both keeps equal logical ranges aligned.
4. **Preserved**: wheel-scroll disabled (`handleScroll/handleScale.mouseWheel:false`), drag-pan on,
   the crosshair-guide sync (`syncGuideFrom`, both directions), per-indicator `.ind-tog` toggles,
   hide-pane-when-none-checked, dispose-on-rebuild. The initial range-adoption on first pane build now
   adopts the price's `getVisibleLogicalRange()` (was `getVisibleRange()`).

**Exposed**: `ViewModel._aggregateLine` for inspection (mirrors `_aggregateOhlc`).

**Tests / DoD:** JS-only — no Python test changes. `node --check` clean; require-smoke loads and
`_aggregateLine` verified (W-bucketing: two same-week daily points collapse to last value, next week
separate). `python -m pytest -q` (from `src/mktt/`): **354 passed, 6 failed** — unchanged. The 6 are the
carried, out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` kernel-parity fails —
not touched.

**v3.8 note (per the gate's ask):** `setVisibleLogicalRange` / `subscribeVisibleLogicalRangeChange` are
both present in lightweight-charts@3.8.0 (base.html) — no fallback primitive needed. No unexpected
behaviour at parse/require level; full free-scroll-into-whitespace + lockstep + W/M-alignment is the
browser-verify below.

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol, no console errors —
(a) drag/scroll the price past the right edge → empty space appears and the indicator pane scrolls in
lockstep (no revert/clamp); (b) alignment holds across D/W/M (indicators now aggregate to the timeframe);
(c) crosshair-guide sync still works both ways; (d) `.ind-tog` toggles + hide-when-none still work;
(e) no console errors. Not committed.

## REPORT — Slice 6 (fix 2): ~13px horizontal misalignment under logical-range sync [developer]

**Task:** plan-dev.md Slice 6 → "Follow-up 2 — fix ~13px horizontal misalignment under
logical-range sync". Logical-range sync (prior fix) aligns by BAR INDEX, but the price
(symbol's full daily OHLCV) and the indicator series (`classification_history`, different date
coverage/count) had DIFFERENT bar grids, so the same date landed ~13px apart
(`timeToCoordinate('2024-06-03')`: price 866px vs indicator 853px; ~2px under the old time-sync).
Root cause: bar-index sync only aligns when both charts share an IDENTICAL bar grid (same times,
same count). Fix: resample the indicator series onto the price's EXACT displayed bar times.

**Changed — all in `static/js/viewmodel.js`:**
1. `renderOhlcFigure` now stashes the displayed bar times after aggregation:
   `node._displayedTimes = agg.bars.map(b => toYmd(b.time))`. Refreshed on every price render /
   D-W-M re-aggregation, and set BEFORE the end-of-function `renderIndicatorPane` call.
2. New helper `alignLineToTimes(points, displayedTimes)` — as-of / forward-fill resample: for each
   displayed bar time T, take the series' most-recent value at-or-before T (null before the first
   point). Single monotonic walk pointer (both inputs sorted ascending); `toYmd`-normalizes times.
   Output's time array EXACTLY equals `displayedTimes` (same count, same order).
3. `renderIndicatorPane` now aligns each series via `alignLineToTimes(_displayedTimes)` instead of
   independently `aggregateLine`-ing. It emits the FULL grid: null slots become LWC-v3.8
   **whitespace** points (`{time}` only, no `value`) so the indicator chart's time scale registers
   every displayed bar at the same index as price (dropping leading-null rows would shift index 0
   and re-break the bar-index sync). Reads `document.getElementById('monitor_price')._displayedTimes`.
   **Fallback** to the existing `aggregateLine` path (filter-nulls) when `_displayedTimes` is missing
   (pane renders before price) so nothing breaks. Per-series scale/band styling, toggles,
   hide-when-none all preserved.
4. Kept the logical-range sync + `rightOffset: 6` from the prior fix; with identical grids the
   partner mirrors the source's logical range 1:1 (no offset) and dates align.
5. Confirmed D/W/M ordering: `onTfChange` calls `rerenderOhlc()` (re-aggregates price → updates
   `_displayedTimes` → re-renders pane from stash) THEN `rerenderIndicators()`. Order correct,
   not reversed; explicit `rerenderIndicators()` is belt-and-braces.

**Exposed:** `ViewModel._alignLineToTimes` for inspection (mirrors `_aggregateLine`).

**Tests / DoD:** JS-only — no Python test changes. `node` require-smoke loads clean. `_alignLineToTimes`
verified in node (6/6 PASS): as-of forward-fill, output count==grid, times==grid, last-wins on duplicate
dates, leading-null before first point, empty-series → all-null, BusinessDay-object time normalization.
`python -m pytest -q` (from `src/mktt/`): **354 passed, 6 failed** — UNCHANGED. The 6 are the carried,
out-of-scope `test_kernel.py::test_parity_kernel_vs_stage_classifier[...]` kernel-parity fails — not touched.

**v3.8 quirk (per the gate's ask):** the alignment relies on lightweight-charts@3.8.0 **whitespace data** —
a line-series point with only `time` (no `value`) occupies a time-scale slot but draws nothing. Null/gap
slots MUST be emitted as whitespace, not dropped, or the indicator chart's grid shrinks and index 0 shifts,
re-breaking the bar-index alignment. Whitespace points must stay ascending + unique in time, which they are
(the grid is the aggregated price bars). No new API beyond what v3.8 already provides.

**State left — needs BROWSER VERIFICATION (orchestrator):** on a live symbol, no console errors —
(a) `timeToCoordinate(sameDate)` on the two charts now matches within ~1-2px across several dates AND
timeframes (was ~13px); (b) free-scroll past the right edge still works and the indicator follows in
lockstep and STAYS aligned; (c) crosshair guide lines line up; (d) `.ind-tog` toggles + hide-when-none
still work; (e) no console errors. Not committed.

## 2026-06-15 · orchestrator · DECISION (upgrade Lightweight Charts 3.8 → 4.x)
The "free right-edge scroll + reliably-synced separate indicator pane" pair proved unworkable on
lightweight-charts@3.8.0: the cross-chart range-sync is flaky (load-timing race in the subscription;
scripted + observed desync), and v3.8 lacks `setCrosshairPosition` so crosshair sync had to be a manual
vertical-guide hack. Diagnosed thoroughly (free-scroll works, rest-alignment perfect via grid-resample,
but interactive sync intermittent). User chose **upgrade to v4** (keeps the separate pane; v4 has proper
multi-chart sync + native `setCrosshairPosition`/`clearCrosshairPosition`). Cost accepted: re-verify all
chart features against v4's API. adr/0003 ("Lightweight Charts for OHLC") still holds — this is a version
bump, not a charting-strategy change. Dispatching the upgrade; orchestrator to browser-verify end-to-end.

## 2026-06-15 · developer · REPORT (Slice 6 follow-up 3 — Lightweight Charts 3.8 → 4.2.3)
**Task:** plan-dev.md Slice 6 → "Follow-up 3 — upgrade Lightweight Charts 3.8 → 4.2.3". Upgrade the
charting lib and use v4 to do native crosshair sync + reliable logical-range sync, replacing two v3.8
workarounds. JS-only + base.html version bump.

**v4 API verified against the standalone production build** (`unpkg lightweight-charts@4.2.3`, loaded in
Node: `LightweightCharts.version() == '4.2.3'`): `ColorType.Solid=='solid'`, `CrosshairMode.Normal==0`,
`LineStyle` present, and `setCrosshairPosition`/`clearCrosshairPosition`/`addCandlestickSeries`/
`addLineSeries`/`subscribeVisibleLogicalRangeChange`/`setVisibleLogicalRange` all present. No v4 surprises
vs. the task brief — every documented API behaved as the task said; `addCandlestickSeries`/`addLineSeries`
(v4) used, NOT the v5 `addSeries(...)`.

**Files touched:**
- `src/mktt/templates/base.html` (~line 8): `lightweight-charts@3.8.0` → `@4.2.3`.
- `src/mktt/static/js/viewmodel.js` (JS-only):
  - Crosshair sync → native: deleted the guide-div block (`ensureGuide`/`hideGuide`/`showGuideAtTime`/
    `syncGuideFrom`, `_xGuide`, `GUIDE_COLOR`, the `position:relative` host hacks). New `syncCrosshairFrom`
    drives the partner's `setCrosshairPosition(0, param.time, partnerSeries)` on move and
    `clearCrosshairPosition()` on leave; partner chart + a stable series resolved dynamically each move
    (`node._lwcSeries` = price candles; `node._indSeries` = first indicator line). Hide-pane-when-none now
    `clearCrosshair(_priceChart)`. `#monitor-ohlc-readout` O/H/L/C update preserved.
  - Range sync → logical-range: removed dead `_syncing`/`_syncOwner` module vars + their stale reentrancy
    comments; kept the guardless bidirectional `subscribeVisibleLogicalRangeChange`→`setVisibleLogicalRange`
    mirror (v4 idempotency stops the echo). Free right-edge scroll preserved via `rightOffset:6` on both
    charts + identical bar grids (`alignLineToTimes` onto `_displayedTimes`).
  - v4 option adaptations: `layout.background` →
    `{ type: LightweightCharts.ColorType.Solid, color: 'transparent' }` (both charts);
    `crosshair.mode` → `LightweightCharts.CrosshairMode.Normal` (both charts).
  - Preserved: MA50/150/200, RS price-overlay toggle, D/W/M aggregation, per-series indicator toggles,
    hide-when-none, dispose-on-rebuild, whitespace-point grid alignment, synthetic-open path.

**Behaviors covered:** No new automated tests (the chart layer is browser-verified per slices 2/3/6 — no
JS test runner in the repo; the Python suite asserts only the envelope shape, unchanged). DoD is the
unchanged suite + clean `node --check` + the orchestrator browser-verify checklist below.

**Test command + result:** `python -m pytest -q` (from `src/mktt/`) → **354 passed, 6 failed** (the 6
carried `test_parity_kernel_vs_stage_classifier` kernel-parity fails — untouched). `node --check
static/js/viewmodel.js` → clean.

**State left behind:** JS + base.html changes complete, NOT committed. Browser-verify needed (orchestrator):
1. Candles + MA50/150/200 render for a live symbol; D/W/M re-aggregates candles + MAs.
2. RS (Mansfield) price-overlay toggle works (own scale, doesn't distort candles).
3. Crosshair O/H/L/C readout (`#monitor-ohlc-readout`) updates on hover.
4. **Free-scroll past the right edge** (drag price into whitespace) — indicator pane tracks in lockstep,
   alignment holds across D/W/M (same date lines up on both panes).
5. **Native synced crosshair across both panes** — hover price → real vertical crosshair on indicators;
   hover indicators → real crosshair on price; leaving the chart clears the partner's crosshair.
6. Indicator per-series toggles add/remove each line; pane hides when all off (and the price crosshair
   clears); pane reappears on re-toggle.
7. Symbol switch rebuilds both panes cleanly (no leaked/stacked charts); sync + crosshair still work.
8. No console errors anywhere in the above (esp. no `setCrosshairPosition is not a function`, which would
   mean the v4 script didn't load — hard-refresh to bust the unpkg cache).
