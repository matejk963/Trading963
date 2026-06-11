# MKTT — As-built architecture (post-refactor)

Current truth about the refactored MKTT app (effort `2026-06-11-mktt-refactor`). Design rationale lives
in `refactor/TARGET_ARCHITECTURE.md`; this records what was actually built.

## Shape
Kernel-centric. `app.py` is a 149-line **app-factory** (`create_app()`) that wires one shared DataSource
and registers six blueprints. No business logic in the HTTP layer.

```
src/mktt/
  app.py                  app-factory: create_app() + blueprint registration + __main__
  legacy_routes.py        legacy_bp — endpoints not yet owned by a section (EPS/rev/sector-map/freshness)
  kernel/                 PURE enrichment pipeline (pandas): indicators · relative_strength(.compute/.rank) · stage
  datasource/             RAW provider: time_series · fundamentals · option_chain + (form,id) registry + submodules/
  computed/               DERIVED: store.py (ComputedStore current/history) · writer.py · classifiers/ (pca_regime, ma_screen, eps_accel)
  lists/                  ListStore over MKLists.list_member (shared; screener writes, monitor reads)
  viewmodel.py            vm() envelope builder + num()/val()/money() formatters
  static/js/viewmodel.js  renderViewModel(vm) — the single generic client renderer
  sections/<name>/        thin managers: service.py (handle) + routes.py (<name>_bp) + templates/<name>.html
     screener · monitor · options(+gex_engine private core) · rrg(+quadrant core) · macro(+scoring core)
```

## Contracts (as built)
- **Forms:** `TimeSeries` (pandas symbol×date), `CrossSection`, `OptionChain`, `Fundamentals`.
- **Kernel:** enrichment pipeline — each primitive `TimeSeries → TimeSeries(+cols)`; pure, source-blind, CPU/pandas (GPU deferred, adr/0001).
- **Providers:** `data.time_series/.fundamentals/.option_chain`; `computed.cross_section/.history/.ensure_fresh`; `lists.add/remove/members`. All dependency-injected.
- **Section:** `handle(req, <providers>) → ViewModel{figures,tables,meta}`; route = parse→handle→jsonify/render.

## Data layer — Postgres `etc_db` (live, populated)
- `MKFund`: fundamentals_current (4,835), estimates_forward (9,670), quarterly (91,203), estimate_revisions (280,640).
- `MKCompStore`: classification_current (40 sample) / classification_history (52,837) — written by the Writer.
- `MKLists`: list_member (0, ready).
- DSN via env `MKTT_PG_DSN` (default `postgresql://postgres:postgres@10.123.0.9:5432/etc_db`).

## Run / verify
- `cd src/mktt && python app.py` (port 5001) — or `flask run` (module-level `app`).
- Tests: `python -m pytest src/mktt/tests/ -q` → **275 passed**.
- The app-factory injects one fund-wired DataSource into every section; a `ChoiceLoader` makes section templates win over the legacy monolith templates (kept on disk).

## Known deltas vs the pre-refactor app
- `/api/options/*` now returns the **ViewModel envelope** (not the old raw GEX dict) — any external consumer must read the envelope (`options.html` already does).
- `rs_rank` in the Writer ranks by 6-month return (perf-style) rather than Mansfield RS.
- Old `src/mktt/macro/`, `screener.py`, `stage_classifier.py`, etc. remain on disk but unregistered/superseded — candidates for later removal.
- Legacy per-symbol fundamental endpoints (rolling_12m, sales_ttm_forward, eps_ttm_forward, revisions, sector_map, freshness) live in `legacy_bp` — not yet ported into a section (future work).

## Deferred / follow-up
- Slice 2b (GPU kernel backend) — deferred by decision (adr/0001).
- Full-universe Writer run (only the 40-symbol parity sample is materialized in MKCompStore so far).
- Port the `legacy_bp` endpoints into Monitor; remove superseded old modules; front-end JS for the new `/api/options` envelope.
