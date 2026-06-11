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
