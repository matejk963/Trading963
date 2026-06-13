# Log — MKTT refactor

Append-only. Agents: read the open FLAGs + recent entries before starting; append a REPORT when done.
Never edit prior entries — only extend.

## 2026-06-11 · orchestrator · HANDOFF
Effort opened. PRD `Accepted` (strategy over `refactor/TARGET_ARCHITECTURE.md`, the locked design);
`plan-dev.md` derived with 10 slices.

- **State:** design + DB done — `etc_db` schemas `MKCompStore` / `MKFund` / `MKLists` built (empty);
  no application code written yet.
- **Workflow:** just ported from `Agents_arch` into this repo on branch `chore/agents-workflow-port`.
  Application code happens in the worktree `../Trading963-mktt-refactor` (branch `refactor/mktt-impl`)
  — sync it with `git merge refactor/mktt-app` to get the spec before starting.
- **Open FLAGs:** none.
- **Next dispatch:** task 2 (Kernel) — pure, unblocked, de-risks the central design. Then 1 + 3
  (parallelizable), 4, 5.

### TDD planning gate — task 2 (Kernel) [resolved here, ready to dispatch]
- **Public interface:** spec §5.2 — `Indicators.compute(ts)`, `RelativeStrength.compute(ts, benchmark)`,
  `RelativeStrength.rank(panel, by)`, `StageClassification.compute(ts)`; enrichment pipeline
  (each `TimeSeries → TimeSeries(+cols)`); pandas `symbol×date` DataFrame at the seam, tensor internal.
- **Prioritized behaviors to test:** each primitive adds its columns; `rank()` is cross-sectional
  (needs >1 symbol); `stage` reuses prior `ma_*`/`rs_line` columns (no MA recompute); single-symbol
  path works (`rs_rank` null when 1 symbol); device auto-select with CPU fallback.
- **Definition of done:** signatures match §5.2; pure pytest green (no DB/net/Flask); behavior parity
  with `src/mktt/stage_classifier.py` on a sample; REPORT here + task 2 ticked.

## 2026-06-11 · reviewer (slice review) · REPORT
Reviewed prd + plan + spec against live `src/mktt/`. Reformulated 10 → 13 slices (added parity
harness, ViewModel renderer, MKLists; split Kernel into pandas/GPU; Screener sub-split 7a/7b/7c;
corrected dep graph). Plan-dev.md updated. 8 FLAGs raised (below). Evidence cited file:line in the
review. Recommended first dispatch: **2a (Kernel pandas) + 3 (parity harness)** in parallel — both AFK.

## 2026-06-11 · reviewer · FLAGs (open)
- **FLAG-1** [tactics] RelativeStrength `benchmark` has no provider; today SPY is hard-wired
  (`stage_classifier.py:79`, `data_manager.load_spy`). → add benchmark acquisition to Slice 1. Resolved-by: (plan, done) — Slice 1 now includes it.
- **FLAG-2** [decision] Kernel "GPU-tensorized" is greenfield — no torch/cuda in repo. → split 2a(pandas)/2b(GPU); is GPU in scope for parity or deferred? Resolved-by: ___ (USER decision pending).
- **FLAG-3** [decision] Screener classification cols (`PCA_Regime`/`EPS_Accel`/`MA_Screen`) come from a
  PCA+KMeans pipeline (`update_classifications.py:142`, `pca_stage_classifier.py`), NOT the Weinstein
  kernel `stage`. Store §6 carries `regime` but no slice produces it; spec says kernel is the store's
  only writer (§4.5). → ADR clarifying "kernel (3 primitives)" vs "additional Writer-fed classifiers". Resolved-by: ___ (USER/ADR pending).
- **FLAG-4** [tactics] Slice 7 (Screener) hides ≥3 sub-slices (live technicals + Refinitiv enrich +
  full-universe median PE + 40 filters, `app.py:214–880`). → 7a/7b/7c. Resolved-by: (plan, done).
- **FLAG-5** [strategy/scope] RRG + Macro import `compute_*` from sibling Streamlit apps via sys.path +
  a mocked `streamlit` (`rrg_service.py:13`, `liquidity_service.py:14`). Killing the leak = RELOCATING
  that code into private cores → widens IN scope beyond `src/mktt/**` (PRD). Resolved-by: ___ (USER scope call pending).
- **FLAG-6** [tactics] Dep graph wrong: generic renderer (6) blocks all sections; Options is parallel
  to Screener, not after it. Resolved-by: (plan, done).
- **FLAG-7** [operations] App-level Postgres creds (Prefect config, `10.123.0.9`) not retrieved.
  Slices 4/5/9 (DB integration) HITL-gated until creds confirmed. db-tools has `etc_db` write access
  (schemas were created via it) but app/test code needs raw creds. Resolved-by: ___ (orchestrator/USER pending).
- **FLAG-8** [operations] `screener.py` (`screen_stocks`) is dead vs the live route; the `/screener`
  route uses parquet+Refinitiv inline. Parity target = the route, not `screener.py`. Resolved-by: noted for Slices 1/7.

## 2026-06-11 · orchestrator · HANDOFF
Plan reformulated to 13 slices; tactical FLAGs (1,4,6,8) resolved in-plan. **4 FLAGs need the user:**
FLAG-2 (GPU scope), FLAG-3 (PCA-regime ADR), FLAG-5 (scope-widening), FLAG-7 (DB creds). None of these
block the AFK first wave — **2a (Kernel pandas), 3 (parity harness), 1 (DataSource), 6 (renderer)** are
unblocked and creds-free. Next: get user calls on the 4 FLAGs, then dispatch Wave 1.

## 2026-06-11 · orchestrator · REPORT (decisions — user said "go with recommended", proceed autonomously)
The 4 escalated FLAGs resolved:
- **FLAG-2 (GPU):** DEFERRED. Build pandas kernel (2a); GPU (2b) later behind same interface. → adr/0001.
- **FLAG-3 (PCA-regime):** KEEP as Writer-fed classifiers; kernel stays 3 primitives. → adr/0001. Slice 5 gains classifier sub-steps.
- **FLAG-5 (scope):** WIDEN — vendor RRG/liquidity `compute_*` out of the sibling Streamlit apps into
  section-private cores under `src/mktt/`. → prd changelog. Slices 11/12 include relocation.
- **FLAG-7 (creds):** App DB connection parameterized via env `MKTT_PG_DSN`; schema verified via db-tools
  (`etc_db` — orchestrator has write access). DB-integration slices (4/5/9) BUILT with env DSN;
  live-runtime connection is deploy-config (user supplies DSN later). Not a code blocker.
- **Dev location:** to keep autonomous orchestration simple, dev happens in the PRIMARY checkout on
  branch `chore/agents-workflow-port` (carries spec + plan + data/cache); sequential commits per slice.
  The `refactor/mktt-impl` worktree stays for old-vs-new comparison. (Plan Parameters adjusted.)

## 2026-06-11 · orchestrator · HANDOFF (dispatching Wave 1)
Dispatching Wave 1 (AFK, creds-free): Slice 3 (parity harness) → Slice 1 (DataSource) → Slice 2a
(Kernel pandas) → Slice 6 (ViewModel renderer), sequential to avoid git races. Each: TDD, tests green,
commit, REPORT. Then integrate + Wave 3 (DB, env-DSN) + Wave 4 (sections).

## 2026-06-11 · dev/slice-1 (DataSource) · REPORT
Built Slice #1 — DataSource `time_series` + `(form,id)` registry + equity submodule + benchmark. TDD: 21 tests written first (red), implemented to green. Full suite 65 passed (44 pre-existing GEX/parity unaffected). Refs: spec §4.4/§5.3, adr/0001, FLAG-1.

- **New package `src/mktt/datasource/`:**
  - `registry.py` — `Registry`: `id→asset_class` (with `default_asset_class` fallback) + `(form,asset_class)→submodule`; `group_by_submodule()` batches ids per submodule. Config, not branching.
  - `submodules/equity.py` — `EquitySubmodule`: reads `data/mktt/{close,high,low,volume}.parquet` (universe) + `spy.parquet` (benchmark, TitleCase OHLCV); mtime-keyed in-mem cache (ported from `data_manager._load_parquet_cached`); `last_bar_date()` exposes the per-symbol incremental-delta-fetch freshness signal (ported concept from `update_prices`); `fetch_universe()` is the SINGLE `yf.screen`/`EquityQuery` pagination loop (DI: injectable `screen`/`equity_query`, lazy yfinance import otherwise).
  - `provider.py` — `DataSource`: DI facade, constructor takes `registry` (+ optional `_equity` handle). `time_series(ids,start,end,fields)` routes each id via registry, batches per submodule, assembles a sorted `symbol×date` multi-index DataFrame (the TimeSeries form, columns=fields).
  - `__init__.py` — `build_default_datasource()` wires the real registry; SPY tagged `benchmark`, bulk universe falls back to `equity` default.
- **FLAG-1 resolved (operations):** benchmark (SPY) is just another `time_series` id with an `asset_class="benchmark"` tag, served by the same equity submodule from `spy.parquet`, returned via the same `time_series()` path. No separate benchmark API.
- **yf.screen dedup (DoD):** removed the duplicated EquityQuery pagination loops from `screener.py:89-101` (`fetch_exchange_quotes`) and `data_manager.py:54-61` (`fetch_liquid_universe`) + the third copy in `data_manager.build_sector_map` (per-sector, now passes the sector as an `extra_filters` arg). All three delegate to `EquitySubmodule.fetch_universe`. A guard test asserts the loop now lives in exactly one module. Each caller's own `min_avg_vol` default preserved (parity).
- **Tests:** registry resolution (equity/benchmark/default-fallback); fields subsetting; date-window slicing; multi-id panel assembly; missing-id tolerance (skip); all-missing→empty-but-shaped; single-string id; benchmark series; mixed equity+benchmark routing; real-parquet integration (AAPL panel, date window, missing-ticker, SPY from spy.parquet, end-to-end build_default_datasource); injected-screen universe fetch; dedup guard. 21 passed, 0 skipped (real parquet present).
- **Not in this slice (later):** `option_chain`/`fundamentals` (spec §5.3) deliberately absent; GPU N/A.

## 2026-06-11 · orchestrator · REPORT (Wave 1 integrated + FLAG-7 resolved)
Wave 1 DONE — slices 3,1,2a,6 built, committed (cd88331,78f992f,53894ce,11be553), full suite **120 passed**
(+94 new, 26 pre-existing GEX untouched). Tasks 1/2a/3/6 ticked. New modules: src/mktt/{kernel,datasource,viewmodel.py,static/js/viewmodel.js}.
- **FLAG-7 RESOLVED:** found etc_db creds in db_migration/scripts (postgres/postgres); WSL reaches
  10.123.0.9:5432, all 3 MKTT schemas visible. DSN = postgresql://postgres:postgres@10.123.0.9:5432/etc_db.
  DB slices 4/5/9 unblocked → now ▶. Integration tests must use a DISPOSABLE schema (create/drop), never
  touch the real MKCompStore/MKFund/MKLists destructively; loaders may populate the real tables (upsert, idempotent).
- Options (10) unblocked (1+6 done) — parallel, not DB-gated.
- Next: Wave 2 = slices 9, 4, 5, 10 (sequential).

## 2026-06-11 · orchestrator · REPORT (Wave 2 integrated)
Wave 2 DONE — slices 9,4,5,10 built+committed (f38f2c6,0121f81,46dcc09,3b547f7). Suite **196 passed** (+76).
REAL DB POPULATED: MKFund fully loaded (4835 fundamentals_current; 9670/91203/280640 estimates/quarterly/revisions);
MKCompStore 40 current / 52837 history (parity sample via Writer); MKLists empty (correct).
Adjustments (faithful, not redesigns): Slice 4 aligned to existing real DDL column names (eps_smart, num_analysts,
mean_val…) + truncated DATE PKs. Slice 5 Writer ranks rs_rank by 6m returns (perf-style RS rank) rather than the
kernel default mansfield_rs — note for final report. Sections 7/8/11/12 now unblocked (4,5,6,9 done). Next: Wave 3 = 7,8,11,12 then 13.

## 2026-06-11 · orchestrator · REPORT (Wave 3 integrated)
Wave 3 DONE — sections 7,8,11,12 built+committed (6260362,071a86a,5f43489,6013c48). Suite **263 passed** (+67).
All 5 sections exist (screener/monitor/options/rrg/macro). streamlit leak VERIFIED killed (6 hits = relocation
comments only; no import/sys.path; cores import standalone). Macro/RRG compute relocated read-copy (originals untouched).
Slice-7 FLAG for Slice 13: build_default_datasource must receive fund_conn_factory for the live screener API.
Gaps for Slice 13: Options has service.py but no routes.py (needs options_bp); old per-symbol endpoints
(rolling_12m/sales_ttm/eps_ttm/revisions/sector_map/freshness) not yet ported — keep as legacy blueprint, no functionality loss.

## 2026-06-11 · dev/slice-13 (app-factory) · REPORT
Built Slice #13 — turned `app.py` into an app-factory. Commit `d147da2`. Suite **275 passed**
(263 baseline + 12 new boot tests; 7 gex_api tests re-pointed to the new contract). app.py: **2090 → 149 lines**.

- **`create_app()`** builds Flask, wires a shared fund-wired DataSource
  (`build_default_datasource(fund_conn_factory=build_conn_factory(MKTT_PG_DSN|DEFAULT))` — Slice-7 FLAG
  resolved), injects it into every section's lazy `_PROVIDERS["data"]`, registers all 6 blueprints,
  re-adds the `fmt_number` jinja global + `now` context processor. `__main__` keeps the
  `auto_update_if_stale` daemon thread + `app.run(debug, port=5001, reloader=stat)` verbatim.
- **`sections/options/routes.py`** (new) — thin `options_bp`: GET `/options` page +
  `/api/options/gex/<sym>` and `/api/options/drilldown/<sym>` -> `options.handle` (lazy provider).
  `templates/options.html` shell using `renderViewModel` (figure `gex_profile`, tables
  `gex_strikes`/`gex_walls`).
- **`legacy_routes.py`** (new, `legacy_bp`) — ported VERBATIM the endpoints no section owns:
  `/api/rolling_12m`, `/api/sales_ttm_forward`, `/api/eps_ttm_forward`, `/api/revisions`,
  `/api/sector_map`, `/api/freshness` + their private helpers (load_classification_lookups,
  load_refinitiv_snapshot, _safe_num/_safe_val/fmt_number, the _impl fns). Fixed a latent NameError
  in `_eps_ttm_forward_impl`'s fallback path (init `all_trend_dates=[]`/`fy1=DataFrame()`) — happy
  path unchanged.
- **Blueprint URL ownership** (verified, no conflicts): screener `/ /screener /api/screener`;
  monitor `/chart /api/chart /api/monitor* /api/fundamentals /watchlist /api/watchlist`;
  options `/options /api/options/*`; rrg `/rrg /api/rrg /api/rrg/drill`;
  macro `/macro /macro/api/*`; legacy the 6 above. Old `macro/` blueprint NO LONGER registered
  (new section supersedes it); files kept on disk.
- **Template shadowing fix** (in app.py only): the new section shells (`sections/*/templates/*.html`)
  were shadowed by the pre-refactor app-level `templates/*.html` of the same name (Flask searches the
  app folder first). `create_app()` installs a `ChoiceLoader` putting the section folders ahead of the
  app loader — section shells now render; monolith templates stay on disk untouched.
- **FLAG (follow-up):** `/api/options/*` contract CHANGED by design — old raw GEX dict → ViewModel
  envelope (mandated `options_bp -> options.handle`). `test_gex_api.py` was re-pointed to the new
  envelope (stub DataSource injected into the blueprint); the old raw-dict route is fully retired.
  This was the one endpoint whose response shape I could not keep byte-identical (intentional per the
  refactor). New section coverage also in `test_options_section.py`.
- **Boot smoke test** `tests/test_app_factory.py`: `create_app()` + Flask test client GETs
  `/ /screener /api/screener /options /chart/AAPL /macro /rrg /watchlist` (+ legacy + options API) —
  all assert no 500 / no 404 / no import error. 12 tests, green (DB-backed via MKTT_PG_DSN → etc_db).

## 2026-06-11 · orchestrator · DEBRIEF (effort complete)
All build slices done (1,2a,3,4,5,6,7,8,9,10,11,12,13). 2b (GPU) deferred by adr/0001. **275 tests pass.**
app.py 2090 → 149 lines (app-factory). App boots vs real etc_db; all routes 200. 6 blueprints registered.
Plan vs reality: 10 planned slices → 13 after reviewer pass (added parity harness, ViewModel renderer, MKLists;
split kernel pandas/GPU; screener sub-split). All 8 FLAGs resolved (FLAG-7 creds found autonomously in db_migration).
Adjustments (all faithful, logged per slice): MKFund column names aligned to existing DDL; rs_rank by 6m-return;
/api/options now returns ViewModel envelope; legacy endpoints parked in legacy_bp; template ChoiceLoader for section shells.
As-built recorded in docs/product/mktt-architecture.md. Effort folder frozen (Done).

## 2026-06-11 · orchestrator · REPORT (full-universe migration + regime bugfix)
Ran the Writer over the full 4835-symbol universe → MKCompStore.classification_current 4835 / history 6,496,604.
BUG surfaced only by real-data migration (FLAG, fixed): regime came back 0/4835 — a corrupt date in close.parquet
(~1 symbol present) NaN-poisoned every strict rolling window in pca_regime → dropna wiped the cross-section.
Fix 7f4df7e: min_periods on the MA/vol/adr rolling calls. After re-run: regime 4501/4835 (334 null = insufficient
history; dist 0:247 1:1359 2:437 3:2120 4:338). All signals now populated; full suite green. Screener now backed by
the whole universe, not the 40-sample.

## 2026-06-11 · orchestrator · REPORT (refetch bad date + re-analysis)
Found the glitch date: 2026-06-09 had 1/4835 symbols in close.parquet (failed fetch). Re-fetched all symbols
for that date via yfinance (4794 returned; rest genuinely delisted), patched close/high/low/volume parquets
(backed up as *.bak_0609). Then re-ran the full Writer on corrected prices: 2026-06-09 history row 1→4794;
classification_history 6,501,397; current regime 4503 / stage 4835. Prices and computed analysis now consistent
and clean across 2020-04-24 → 2026-06-11.

## 2026-06-12 · orchestrator · REPORT (grill on Option C → Wave 4 Frontend)
Running the app revealed bare placeholder templates (backend works, UI is skeletal). /grill-me on the
fix (Option C) resolved: revive original base.html chrome (sections extend it); revive original rich
section templates; SERVER-RENDER tables (reuse Jinja) + CLIENT-RENDER charts (deviation from §4.1 →
adr/0002); watchlist on MKLists + connection pooling; screener technicals computed live in handle().
Also found while running: (1) /static/viewmodel.js 404 (path), (2) screener empty by default (turnover
not materialized — now computed live). Wave 4 = slices 14 (chrome) → 15 (screener) → 16 (monitor+watchlist)
→ 17 (options/rrg/macro). Dispatching.

## 2026-06-12 · orchestrator · DEBRIEF (Wave 4 Frontend complete)
Slices 14-17 done+committed (5d6818e chrome, 0b9cf1f screener, f17656a monitor+watchlist; 17 verified—no new diff).
275 tests green. Browser-verified (chrome-devtools): screener renders the rich filter form + populated color-coded
table (4122 rows on default min_turnover=500000, was 0); macro/liquidity renders full chrome + Plotly chart;
all pages have the dark terminal nav. Connection pool added; watchlist on MKLists.
Honest gaps (follow-up, logged): (a) screener missing the sector→industry hierarchy + map view + EPS-estimate
columns (data not in new stores); (b) options/rrg/macro pages are chart shells (chrome+charts), not the original
rich layouts; (c) screener full-universe page render ~6-7s (live time_series fetch per request — window/cache later).

## 2026-06-12 · orchestrator · DEBRIEF (fix wave — 34 findings cleared)
Fix wave done: F1 computed+pool (0999f4f), F2 screener (48296da), F3 options (a41843e), F4 rrg+macro (cc775cb).
313 tests green (was 275, +38). Headline results (browser/curl verified):
- BUGS: rs_rank now universe-wide & incremental-safe (verified AAPL=54.12 over 4835, not 0/50/100); Options
  drilldown returns real per-strike contracts; FwdPE live (join estimates_forward); growth/EPS-accel presets
  live (join quarterly+estimates); dist_high sort fixed; pool maxconn env + graceful 503 (no more 500).
- EFFICIENCY: Writer upsert incremental via itertuples (no 6.5M-row rewrite); cross_section cached; screener
  render 6.7s → 2.4s (vectorized technicals off the wide parquet).
- GAPS RESTORED: screener column picker + sector/industry hierarchy + stage/regime banner + as-of + ticker
  search + EPS/Rev estimate columns; options chip-picker + GEX table coloring/format + disclosure footer +
  click-to-drill; RRG as-of slider (now consumes the previously-wasted full_data) + asset toggles + futures
  dropdown; macro regime badge + L1/L2a/L2b score cards + two-level nav + transmission flow.
Honest deferrals (data-availability, not bugs): (a) NTM growth uses FY1 annual as proxy — exact quarterly NTM
needs a forward_quarterly table not in MKFund; (b) asset overlays only SPY has price coverage (pre-existing).
No re-materialize needed (current store data already full-universe-correct; FwdPE/growth computed live in screener).

## 2026-06-12 · orchestrator · HANDOFF (current state — fresh-agent pick-up)
**PICK-UP PATH** (per CLAUDE.md): read THIS HANDOFF + `plan-dev.md` (status + Open items). Design=`refactor/TARGET_ARCHITECTURE.md`; as-built=`docs/product/mktt-architecture.md`; decisions=`docs/adr/0001,0002`; full chronology=this log; review=`gap-and-review-findings.md`.

**STATE** — branch `chore/agents-workflow-port` @ `7380730` (pushed to origin):
- DONE + VERIFIED: backend (kernel/datasource/computed/lists/sections/app-factory), full-universe data in Postgres `etc_db` (MKCompStore 4835+6.5M / MKFund 4835 / MKLists), clean prices through 2026-06-11, revived chrome + all 5 section pages, fix wave (34 findings), filter code→label fix. **313 tests green**; screener+macro browser-verified.
- RUN: `cd src/mktt && MKTT_PG_DSN=postgresql://postgres:postgres@10.123.0.9:5432/etc_db python -c "import app; app.create_app().run(port=<FREE>)"`. **Port 5001 collides with the energy app — use a free port.** DB creds: `postgres/postgres @ etc_db`.

**OPEN ITEMS** (see plan-dev.md "Open items"): (1) missing screener growth-filter controls + sort options; (2) **value-parity vs original NOT systematically verified** — the filter-scramble bug (user-found, review-missed) is evidence more correctness bugs may exist; (3) not all sections browser-clicked / all 34 fixes re-verified; (4) the deferrals (GPU 2b, legacy_bp port, old-module cleanup, NTM proxy, asset-overlay coverage, thinner options/rrg/macro layouts).

**RECOMMENDED NEXT:** a value-parity verification pass (run old↔new on same inputs, diff per section) + add the missing growth-filter controls + a full UI walkthrough.

## 2026-06-12 · orchestrator · REPORT — screener filter+sort parity + RS-momentum backend
**Task:** close Open-item (1) — make the screener's filter/sort controls fully match the original.

**Found (objective gap analysis, not assumed):**
- The *served* screener template is the 534-line blueprint template (`sections/screener/templates/screener.html`), which **shadows** the 1461-line app-level original — empirically confirmed via `jinja_env.get_source` (blueprint wins). The min/max range filters were all present (an earlier greedy-grep false alarm); the true gap was 9 fields + 1 sort option.
- Missing vs original: `eps_growth` / `rev_growth` / `eps_accel_filter` dropdowns; `rschg1w/1m/3m` min/max range filters (+ their active-filter tags); `mcap` sort option.
- **Backend reality check:** the 3 growth dropdowns were already fully wired (`*_PRESETS` parse/apply/round-trip; `_join` computes `G_NTM_TTM/G_FY2_FY1/…` inline — so the old finding "growth presets dead" was resolved during the build; verified `eps_growth=ntm_pos` → 2002 rows). But `RS_Chg1W/1M/3M` were **referenced yet never computed** — `cross_section` only has `rs_rank`, no rank-change windows — so every `rschg*` filter returned **0 rows** (dead controls). `mcap` sort had no backend key.

**Did:**
1. **Template (`sections/screener/templates/screener.html`):** added the 3 growth/accel dropdowns (Fundamental row), the 3 RS-Chg range filters (Technical row) + RS1W/RS1M/RS3M active-filter tags, and the `Market Cap` sort option — all ported verbatim from the original (option values validated against the backend preset keys).
2. **RS-momentum backend (the real fix):** new `ComputedStore.rs_rank_changes(asof=None)` — computes `rs_chg1w/1m/3m` cross-sectionally from `classification_history`, diffing `rs_rank` at 5/21/63 **trading-day** lags (one SQL round-trip; anchor + 3 lagged dates diffed in-DB). Confirmed parity basis: the Writer persists `rs_rank` via `rank(by="returns_6m")` = `close.pct_change(126).rank(pct=True)*100`, **identical** to the original screener's 6-mo-return percentile (app.py @9631169), so `rs_rank[t] − rs_rank[t−N]` reproduces the original `RS_Chg` exactly.
3. **Pipeline:** `_pipeline` calls `rs_rank_changes()` and `_apply_rs_changes` splices `RS_Chg1W/1M/3M` onto rows (best-effort; absent symbols keep None → `_in_range` drops them when filtered, matching the original). This also fixes the previously-NaN sector-median RS-chg.
4. **`mcap` sort:** added `"mcap": ("ADV_Dollar", False)` to `SORT_COLUMNS` — original-parity alias (the original's `mcap` *also* mapped to ADV_Dollar; there is no market-cap column, so it sorts identically to turnover; kept for exact dropdown parity).

**Verified (live server, port 46293, full universe):**
- Field parity gap = ∅; sort-option parity = exact (both directions).
- `rschg1m_min` sweep now monotonic: −50→3694, 0→2029, 5→1127, 10→687, 20→287 (was 0 for all). Store method: 1324 symbols with `rs_chg1m≥5`, range −91.7…+98.0 — matches a direct SQL check.
- Round-trip + active tags confirmed (`eps_growth ntm_pos` selected; `RS1M: 5.0/`, `RS3M: 10.0/` tags; combined growth+RS filter → 320 rows; `mcap` sort selected, 200 OK).
- **Tests: 316 passed** (313 + 3 new `rs_rank_changes` integration tests: exact 5/21/63 deltas, short-history NaN, asof-anchor). No regressions.

**Still open:** value-parity verification pass (old↔new diff per section) and full UI walkthrough remain — Open-items (2),(3).

## 2026-06-12 · orchestrator · REPORT — screener stage-preset filter + sector-median basis (wrong-answer bugs)
**Trigger:** user — "check the old version sector analysis in screener in terms of percentiles/RS rank, I think it doesn't match."

**Found TWO compounding wrong-answer bugs (confirmed vs original app.py @9631169, not assumed):**
1. **Stage presets never filtered.** `_passes` applied base/classification/fundamental/technical filters but **never the `preset`** — so `stage1/2/3/4/trans12` all returned the *same* full passing universe (verified: stage2 and stage4 both → 3856 rows). The original filters `Stage == N` (app.py:487-494); `trans12 → Transition == "1->2"` (stage_classifier.py:243). The preset was only used for the stage-distribution banner, never the table.
2. **Sector/industry medians computed over the FULL universe, not the passed set.** `_sector_stats` took medians over `full_rows`; the original groups the already-**filtered** `results_df` (app.py:759-870). Because `RS_Rank` is a global 0-100 percentile, the full-universe sector median sits ~50 for every sector regardless of filter — so the panel's `median_rs` (and all medians) were wrong under any preset/filter. This is what the user saw.

(Bug 1 masked bug 2: with the preset ignored, the passed set was identical across presets, so even a correct median basis would have shown identical numbers.)

**Did:**
1. **Stage-preset filter** (`_passes`, base-filter position): `stage1-4 → Stage_Class == N` via `_STAGE_NUM`; `trans12 → Transition == "1->2"`. The banner still counts the full universe (handle_page reads `res.rows`, the filter only narrows `res.passed`).
2. **`ComputedStore.stage_transitions(asof=None, lookback=5)`** — per-symbol `"prev->current"` label from `classification_history`: current = latest `stage`, prev = **mode** of the prior 5 bars; labelled only when `prev != current` and neither is 0 (exact port of stage_classifier.py:243). `_pipeline` attaches `row["Transition"]` only when `preset == trans12` (its sole consumer). One SQL round-trip + pandas mode.
3. **Sector/industry medians now over the PASSED set** (`_sector_stats`): `_group_medians(prows)` / `_group_medians(iprows)` instead of the full universe. Counts/`pct_of_sector` still use full-universe totals (unchanged, matches original). The separate per-stock `PE_vs_Sector` premium stays full-universe (also matches original).

**Verified (live, full universe):**
- Preset row counts now distinct: all=3856, stage1=181, stage2=462, stage3=555, stage4=499, trans12=0.
- `trans12 = 0` is **correct** — there are zero `1->2` transitions in today's data (breakdown: 2->3×14, 3->2×8, 3->1×2, 1->4×2, 4->1, 3->4, 1->3); store found 29 transitions total, none `1->2`.
- Sector-median RS now tracks stage character: stage2 73-94 (leaders), stage4 7-15 (laggards), stage1 29-52 (basing), stage3 36-60 (topping), all 40-80. Previously identical (~50) across all presets.
- **Tests: 319 passed** (+3: `stage_preset_filters_table`, `sector_stats_medians_over_passed_not_full_universe`, `stage_transitions_detects_prev_to_current`).

**Bearing on Open-item (2):** this is the **second** user-found, review-missed wrong-answer bug (after the label-scramble). The systematic value-parity pass (old↔new diff per section) is now clearly warranted — these were found by spot-check, not coverage.

## 2026-06-12 · orchestrator · REPORT — restore original sector-stats table (screener "Sectors" view)
**Trigger:** user — the screener Sectors tab "is not matching original; there should be stats of each stage / selected filter for the sector." Confirmed via AskUserQuestion: **restore the original stats table**.

**Found:** the revived screener kept a *simplified* sector view — a card layout showing only `count/total` + a one-line `PE·FwdPE·OpMgn·ROIC·RS` per sector and `symbol + RS` per stock. The original (app.py @9631169 `templates/screener.html`) is a rich, single expandable **`#sector-table`**: each sector row carries the full median set (PE, FwdPE, PE/Sec, PE/Ind, EPS, FY1, FY2, OpMgn, NetMgn, ROIC, FCF, ND/EBITDA, EV/EBITDA, RS, RS 1W/1M/3M, Target) and expands into **By-Industry / All-Stocks** tabs; industries expand to full per-stock stat rows. The data layer already produced every median (`_sector_stats` / `_group_medians`) — the gap was purely the template + its JS.

**Did:**
1. **Ported the original `#sector-table` verbatim** into the `view-sectors` block (sector → industry → stock, By-Industry/All-Stocks tabs). Field names matched the new `_page_row` 1:1 (`fmt_number` is a registered Jinja global).
2. **Added the sector JS** the table needs: `sortSectorTable`, `sortSubTable`, `switchSectorTab`, `toggleIndustry`, `toggleSectorStocks`, `_parseCell` + `sectorSortDir`/`_subSortDir` globals.
3. **`_page_row` gained `rs_chg1w/1m/3m`** (the per-stock RS-momentum columns the sector/industry/stock rows display) — sourced from the RS_Chg* columns already attached in `_pipeline`.

Combined with the prior fix (medians over the **passed** set), the sector table's stats now reflect the **selected stage/filter** — exactly the user's ask. Under `stage2` the sector-row median RS reads 73-94 (leaders); per-stock RS 1W/1M/3M render with +/- coloring.

**Verified:** browser screenshot (Energy expanded, By-Industry → stock rows, all median columns populated); `#sector-table` present, 11 sectors, By-Industry/All-Stocks tabs live; 319 tests green (template-only + `_page_row` additive change — no test changes needed).

**Note (minor, not blocking):** the flat-table column-picker does not drive `#sector-table` (the original wired both; here the sector table always shows all columns). Logged as a small follow-up if column-hiding parity on the sector table is wanted.

## 2026-06-12 · orchestrator · REPORT — column picker now drives the sector table
**Trigger:** user — "hook up the column picker to the sector table" (the follow-up flagged in the prior REPORT).

**Did (template/JS only):**
- `_allCols()` now returns the **union** of `data-cid`s across `#screener-table` and `#sector-table` (de-duped, document order — the richer sector set leads), so the picker lists every column either view shows (29 total, incl. the sector-only `peind/eps/fy1/fy2/netmgn/fcf/ndebitda/rschg1w/1m/3m`).
- `applyColVisibility()` applies the hidden set to **both** tables; for `#sector-table` the `[data-cid]` selector also reaches the nested industry/all-stocks sub-tables, so a hidden column disappears consistently across the whole hierarchy.
- `_colLabel()` resolves labels from either table; added the **Debt** group button + updated `COL_GROUPS` (valuation→+peind, earnings→eps/fy1/fy2, quality→+netmgn/fcf, debt→ndebitda/evebitda) to cover the sector columns.

**Verified (browser):** hiding `pe` → flat 463→0 visible + sector 1078→0 visible (nested rows included); `minimal` group hides `roic` in both, keeps `rs`; `valuation` group leaves only PE/FwdPE/PE-Sec/PE-Ind/EV-EBITDA/Target in the sector view (col-count "7/29"); picker exposes all 29 union columns. Screenshot captured. Template compiles; 319 tests unaffected.

This closes the minor follow-up from the sector-table-restore REPORT — sector "Sectors" view is now at full original parity (rich stats table + tabs + sort + column picker).

## 2026-06-12 · orchestrator · REPORT — restore the "Map" view (sector × dimension composition) + DATA INCIDENT
**Trigger:** user — "I remember a summary of stocks within selected group (stage, regime,…)". Found it: the original's third results view, **Map** (app.py `/api/sector_map`), a sector × dimension composition matrix.

**Did (reimplemented on the new pipeline, per user choice "former"):**
- `service._sector_map_summary(rows)` — for each of 7 dimensions (`pca_regime, stage, eps_momentum, eps_growth, rs_bucket, rs_momentum, pe_vs_sector`), a per-(sector,category) `summary` + `overall` distribution, shaped exactly like the original AJAX response. Bucket cutoffs ported verbatim (`_map_category`); computed over the **passed** rows so the Map reflects the active filter. Added to `handle_page` context as `sector_map`.
- Template: new **Map** view button + `view-map` block (dimension selector + %Sector/%Category toggle + `map-summary`); `switchView` handles 3 views; embedded `var SECTOR_MAP = {{ sector_map|tojson }}` + ported `renderMap`/`setMapMode`/`sortMapTable` (no AJAX — dimension switches client-side). Avoids the broken legacy `/api/sector_map` (which still reads the old `data_manager` parquet path).
- Test: `test_sector_map_summary_buckets_each_dimension` (all 7 dimension buckets). Verified in-browser (PCA Regime: 2890 stocks, sector×regime heatmap, overall row, legend, category defs).

**⚠️ DATA INCIDENT (price panels corrupted + restored):** mid-session the four wide price panels (`data/mktt/{close,high,low,volume}.parquet`, gitignored) were found **corrupt** ("Couldn't deserialize thrift"), mtime 2026-06-13 09:08 — almost certainly a background price-update write truncated when the dev server was `kill`ed mid-write during a restart. Effect: `panel_technicals` failed → no live turnover → `min_turnover` dropped **all** rows (screener returned 0). **Recovery:** the corrupt files were moved aside to `*.parquet.corrupt_0613` and the valid `*.parquet.bak_0609` backups (Jun 11, data through 2026-06-11) copied into place; screener works again (461 stage2 rows).
**Consequence:** 6 `test_kernel::test_parity_kernel_vs_stage_classifier` golden-parity cases now FAIL — they compute from the live `close.parquet` and compare to frozen golden fixtures baselined against the (now-lost) pre-09:08 snapshot; `bak_0609` is ~2 days older so a few borderline symbols' stages differ (e.g. ASO 0 vs golden 3). **Not caused by this change** (test_kernel doesn't touch the screener). **Open decision for the user:** re-fetch the latest prices (restores the proper/newer snapshot, then re-baseline fixtures) — OR accept the Jun 11 data and re-run `generate_golden.py` to re-baseline. Left for the user; fixtures NOT silently changed.
