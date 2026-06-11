# Plan: MKTT refactor — dev
Status: Active
Derived from: prd.md   Respects: `refactor/TARGET_ARCHITECTURE.md` (locked contracts §5, §8)

## Parameters
- **Where code lands:** worktree `../Trading963-mktt-refactor` (branch `refactor/mktt-impl`).
  One slice = one branch off `refactor/mktt-impl` = one PR. Sync the worktree first
  (`git merge refactor/mktt-app`) so the spec is present.
- **Definition of done (per task):**
  - matches the spec's locked interface for that piece;
  - tests green — **kernel** = pure unit (hand-built frames); **sections** = stubbed providers;
    **stores** = integration vs a disposable Postgres schema;
  - **behavior parity** where it replaces existing logic (spot-check against current output);
  - dependency-injected (no global provider imports);
  - REPORT appended to `log.md`, task ticked here.
- **DB:** `etc_db` schemas `MKCompStore` / `MKFund` / `MKLists` exist, empty. Creds in Prefect
  config — FLAG when a task needs the live connection.

## Tasks

**Foundation** (unblocked, parallelizable):
- [ ] **1. DataSource** — `time_series` + `(form,id)` registry + equity submodule (dedupe `yf.screen`). [AFK]
- [ ] **2. Kernel** — enrichment pipeline `Indicators → RelativeStrength → StageClassification`, pure + unit-tested. [AFK]  ← **FIRST DISPATCH**
- [ ] **3. MKFund loader** — `refinitiv_fundamentals.pkl` → `MKFund` tables. [AFK]

**Wiring:**
- [ ] **4. ComputedStore + Writer** — read `time_series` → run kernel → upsert `MKCompStore`. [AFK]  (blocked by 1, 2)

**Tracer bullet:**
- [ ] **5. Screener end-to-end** — `computed.cross_section` → ViewModel → **generic renderer** → thin blueprint. [AFK]  (blocked by 3, 4)

**Features:**
- [ ] **6. Monitor** — live kernel + `classification_history` + `MKLists`. [AFK]  (blocked by 4, 5)
- [ ] **7. Options** — port `gex_engine` as private core (+ `option_chain` form). [AFK]  (blocked by 1, 5)
- [ ] **8. RRG** — section + kill the `streamlit_app` leak (etf/futures submodules). [AFK]  (blocked by 1, 5)
- [ ] **9. Macro** — private layer-scoring core + macro `TimeSeries` submodule. [AFK]  (blocked by 1, 5)

**Cleanup:**
- [ ] **10. app.py → app-factory + blueprint registration** (final monolith shrink). [AFK]  (blocked by 5–9)

## Change log
- 2026-06-11 — Plan derived from prd.md + spec §11. First dispatch: **task 2 (Kernel)** — pure,
  unblocked, de-risks the central design.
