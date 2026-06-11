# PRD: MKTT kernel-centric refactor

Status: Accepted
Created: 2026-06-11
Detailed design: `refactor/TARGET_ARCHITECTURE.md` — the locked spec. This PRD is the strategy
layer over it (what & why); the spec carries the full contracts and data model.

## Intent
Refactor the MKTT Flask app (`src/mktt/`) from a 2090-line monolith into clearer, modular,
debuggable, extensible infrastructure — recut into **deep modules by responsibility**, kernel-centric.

## Why
`app.py` mixes 7 feature areas + screener orchestration + classification loading. Relative-strength
is duplicated across 4 files; data fetch is scattered (duplicated `yf.screen`, a `streamlit_app`
import leak, 7 raw Refinitiv pkl opens); nothing is testable through its current interface.
Background: `refactor/MKTT_DASHBOARD.md` (current-state analysis), `refactor/mktt_import_levels.html`.

## Success criteria
- Sections are thin managers; a shared analytical **kernel** (Indicators / RelativeStrength /
  StageClassification) is defined **once**, pure and unit-tested.
- Data sits behind two providers (**DataSource** raw / **ComputedStore** derived); **no section
  calls another section**.
- Every seam testable in isolation via **dependency injection**; kernel unit-tested with hand-built frames.
- **Behavior parity** with today's screener / stage / options / macro / RRG outputs.
- `app.py` reduced to app-factory + blueprint registration.

## Scope
- **IN:** restructure `src/mktt/**` into kernel + sections + providers per the spec; wire the
  Postgres `ComputedStore` / `MKFund` / `MKLists` (DB already built, empty); one generic ViewModel renderer.
- **OUT (deferred):** scheduling / data-jobs (user's own scheduler); RRG/Macro source-submodule
  specifics and the screener filter→column mapping are implementation-time detail; no new features.

## Constraints
- Code lands in the worktree `../Trading963-mktt-refactor` (branch `refactor/mktt-impl`); this
  effort folder is for coordination only.
- Postgres `etc_db` schemas `MKCompStore` / `MKFund` / `MKLists` already exist (empty) — spec §6.
  Connection creds live in Prefect config on that server (not yet retrieved — FLAG when needed).
- **Contracts are LOCKED** (ViewModel envelope, kernel enrichment pipeline, provider interfaces,
  DI for testability — spec §5, §8). Do not redesign; FLAG if reality contradicts them.

## Changelog
- 2026-06-11 — Accepted. Derived from a grill-me session + `refactor/TARGET_ARCHITECTURE.md`.
