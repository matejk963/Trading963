# Plan: MKTT refactor — dev
Status: Active (Wave 4 — Frontend, 2026-06-12) — backend done (12/13); reviving UI per adr/0002
Derived from: prd.md   Respects: `refactor/TARGET_ARCHITECTURE.md` (locked contracts §5, §8)
Reformulated: 2026-06-11 after reviewer pass (see log.md REPORT + FLAGs 1–8). 10 → 13 slices.

## Parameters
- **Where code lands:** worktree `../Trading963-mktt-refactor` (branch `refactor/mktt-impl`).
  One slice = one branch off it = one PR. Sync first (`git merge` the consolidated design branch) so the spec is present.
- **Definition of done (per task):** matches the spec's locked interface; tests green (kernel = pure
  unit; sections = stubbed providers; stores = integration vs disposable Postgres schema); **behavior
  parity** vs the frozen golden fixtures (Slice 3); dependency-injected; REPORT in `log.md` + task ticked.
- **Parity baseline:** Slice 3 captures golden fixtures from the CURRENT code. Every parity DoD asserts against it.
- **DB:** `etc_db` schemas `MKCompStore`/`MKFund`/`MKLists` exist, empty. **App-level connection creds
  not yet retrieved (Prefect config) → Slices 4, 5, 9 are HITL-gated until creds confirmed (FLAG-7).**
- **GPU:** no torch/cuda anywhere today — kernel GPU is greenfield, not a port (FLAG-2). Kernel split into 2a (pandas) / 2b (GPU).

## Tasks  (▶ = ready/AFK now · ⛔ = creds-gated · ⏸ = blocked)

**Wave 1 — unblocked, AFK, parallelizable:**
- [x] ▶ **1. DataSource** — `time_series(ids,start,end,fields)` + `(form,id)` registry + equity submodule; dedupe the two `yf.screen` loops; **+ benchmark series acquisition** (FLAG-1). Blocked-by: none. **DONE** (21 tests green; log REPORT 2026-06-11 dev/slice-1).
- [x] ▶ **2a. Kernel (pandas)** — enrichment pipeline `Indicators→RelativeStrength(.compute/.rank)→StageClassification`, pure pandas, unit-tested + parity vs `stage_classifier`. Blocked-by: 3 (for parity). **← FIRST DISPATCH**
- [x] ▶ **3. Parity harness + golden fixtures** — capture current kernel/screener/GEX/RRG outputs (~50 sym# sample) as JSON + `assert_parity`. Blocked-by: none.
- [x] ▶ **6. Generic ViewModel renderer** — `renderViewModel(vm)` (figures/tables/readouts/status) + shell + thin-blueprint pattern + the `_n`/`_safe_num` shaping helper. Blocked-by: none.

**Wave 2 — after 2a/3/GPU-decision:**
- [ ] ⏸ **2b. Kernel GPU backend** — tensor/device-auto behind the same interface, equivalence-tested vs 2a. Blocked-by: 2a + GPU-scope decision (FLAG-2).

**Wave 3 — DB integration (creds-gated, FLAG-7):**
- [x] ▶ **4. MKFund loader** — pkl → `MKFund` tables + `data.fundamentals`; collapse the 7 raw pkl reads. Blocked-by: creds.
- [x] ▶ **5. ComputedStore + Writer** — `time_series`→kernel→upsert `classification_*`; `cross_section`/`history`/`ensure_fresh`. **+ PCA-regime/EPS-accel/MA-screen producers** as Writer-fed classifiers (FLAG-3, pending ADR). Blocked-by: 1, 2a, creds.
- [x] ▶ **9. MKLists access layer** — `lists.add/remove/members` over `MKLists.list_member`. Blocked-by: creds.

**Wave 4 — sections (each needs renderer #6):**
- [x] ▶ **7. Screener** — sub-split: **7a** `ScreenRequest.from_query` + filter→column map · **7b** `screener.handle` (cross_section + fundamentals + sector-median PE) · **7c** thin blueprint + landing page. The tracer bullet. Blocked-by: 4, 5, 6 (FLAG-4).
- [x] ▶ **8. Monitor** — live kernel + `classification_history` + Lists read. Blocked-by: 5, 6, 9.
- [x] ▶ **10. Options** — port `gex_engine` as private core + `data.option_chain`; keep existing GEX tests green. Blocked-by: 1, 6 (**parallel to Screener** — FLAG-6).
- [x] ▶ **11. RRG** — section + **relocate** `compute_*` out of `streamlit_app` into a private core + etf/futures submodules (FLAG-5). Blocked-by: 1, 6.
- [x] ▶ **12. Macro** — private layer-scoring core + macro `TimeSeries` submodule; **relocate** liquidity compute (FLAG-5); `macro/` dissolves. Blocked-by: 1, 6.

**Wave 5 — cleanup:**
- [x] ▶ **13. app.py → app-factory + blueprint registration** (`<~80 lines`). Blocked-by: 7–12.

## Wave 4 — Frontend (adr/0002: revive originals, server-render tables, client-render charts)
- [ ] ▶ **14. Chrome & plumbing** — revive `templates/base.html` (remap stale `url_for` → new blueprint endpoints); section pages `{% extends base %}`; add a **connection pool** in the app-factory injected into ListStore/ComputedStore/DataSource; fix the `/static/viewmodel.js` 404. Verify all pages 200 + show nav/chrome. Blocked-by: none.
- [ ] ▶ **15. Screener page** (tracer) — revive the rich `screener.html` filter form (extends base); `screener.handle` = `cross_section ⨝ MKFund ⨝ live time_series` (turnover/price/change/%-from-high) → filter → **server-render** the table; `/api/screener` still returns ViewModel. Browser-verify a populated, styled table on default filters. Blocked-by: 14.
- [ ] ▶ **16. Monitor + Watchlist pages** — revive chart/fundamentals + watchlist pages (extends base); **client-render** charts (Plotly via renderViewModel); watchlist read/write on **MKLists** via Monitor endpoints (side→note). Browser-verify. Blocked-by: 14.
- [ ] ▶ **17. Options + RRG + Macro pages** — revive their pages (extends base); client-render their charts (GEX profile / RRG scatter / liquidity lines). Browser-verify. Blocked-by: 14.

## Change log (cont.)

## Change log
- 2026-06-11 — Plan derived from prd.md + spec §11 (10 slices, first = Kernel).
- 2026-06-11 — Reformulated to 13 slices after reviewer pass. Added: #3 parity harness, #6 ViewModel
  renderer, #9 MKLists (all spec-implied, plan-omitted). Split #2 → 2a(pandas)/2b(GPU) per FLAG-2.
  Corrected deps (renderer blocks all sections; Options parallel to Screener — FLAG-6). Screener
  sub-split 7a/7b/7c (FLAG-4). Flagged DB-creds gate on 4/5/9 (FLAG-7) and PCA-regime producer gap (FLAG-3).
  **First dispatch: 2a + 3 (parallel, AFK).** Open decisions for the user: FLAG-2 (GPU scope),
  FLAG-3 (PCA-regime ADR), FLAG-5 (scope-widening vendoring), FLAG-7 (creds).

- 2026-06-12 — Wave 4 (Frontend) added after /grill-me on Option C. adr/0002: revive original templates, server-render tables / client-render charts, watchlist on MKLists, live screener technicals. Slices 14-17; first = 14 (chrome).