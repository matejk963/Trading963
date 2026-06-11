# MKTT — Target Architecture

> The design the refactor implements. Produced by a `grill-me` session over the MKTT app.
> Companion artifacts in `refactor/`: `mktt_target_architecture.html` (interactive map + data flow),
> `mktt_architecture.html` (current layer map), `mktt_import_levels.html` (current import DAG),
> `MKTT_DASHBOARD.md` (current-state analysis), `mktt-knowledge-graph.json`.
>
> **Status legend:** ✅ built · 🔒 design locked · ⏸ deferred · ✏️ implementation-time detail.

---

## 1. Purpose

MKTT is an **opportunity-research cockpit** — surfacing equity trade opportunities along a funnel that is traversable **both directions**:

```
TOP-DOWN   macro cycle/liquidity ─► sector & theme rotation ─► relative strength
           (regime, options struct.)  (RRG)                     (fundamentals + perf)
                                                                     │
                                                                     ▼
                                          stage monitoring ─► watchlist (candidates)
BOTTOM-UP  ◄──────────── same chain entered from a single name and walked up ───────────
```

The refactor goal (verbatim): *clearer, more modular infrastructure that is easy to debug, optimize, and extend.* Method: recut into **deep modules organized by responsibility**, with **testability** as the primary lever.

---

## 2. Shape (🔒)

**Kernel-centric**, not module-per-section. A thin shared analytical kernel + thick-where-it-matters sections on top.

```
Client (Plotly.js)
  │  ViewModel JSON ▲ / GET·POST ▼
HTTP — thin per-section blueprints          ① parse → handle → render
  │
Sections — thin managers (Screener·Monitor·RRG·Options·Macro)   ②
  │  forms ▲▼            ViewModel ▲
Kernel — Indicators·RelativeStrength·StageClassification   ③  (pure, source-blind, GPU)
  │
DataSource (raw)   +   ComputedStore (derived)   +   Lists   ④
  │
Sources — yfinance · Refinitiv · calculations.liquidity   ⑤
```

- **No router, no orchestrator.** Flask blueprints route; modules integrate via typed **data-form contracts**. A router/orchestrator would be a shallow pass-through (fails the deletion test).
- **No section calls another section.** Shared meaning lives one layer down (stores/kernel). Cross-section movement (drill from a screener row into a name) is **client navigation**, not a backend call.

---

## 3. Canonical data forms (🔒)

Four forms cross module boundaries. **Asset class is metadata, not structure** — a stock, ETF, futures contract, macro series, and benchmark are all `TimeSeries`, differing only by a tag.

| Form | Shape | Examples |
|---|---|---|
| `TimeSeries` | date-indexed numeric series/panel (`symbol × date × fields`) | prices, ETFs, macro series, spot |
| `CrossSection` | `symbol × attributes` table | the screening universe (computed) |
| `OptionChain` | `expiry × strike` grid (OI/IV) | option chains |
| `Fundamentals` | per-symbol fields + estimate curves | Refinitiv PE/margins/EPS |

At the kernel seam, `TimeSeries` is a **pandas `symbol × date` multi-index DataFrame**; tensors are used only *inside* the kernel.

---

## 4. Layers

### 4.1 HTTP — thin per-section blueprints (🔒)
One blueprint per section. Every route does exactly three things and holds **no business logic**:
```python
@screener_bp.route('/api/screener')
def data():
    req = ScreenRequest.from_query(request.args)   # ① parse → typed request
    vm  = screener.handle(req, data, computed)      # ② call the manager (DI providers)
    return jsonify(vm)                              # ③ return
```
- The section is **Flask-free and method-agnostic** — GET vs POST is resolved entirely in parse.
- **GET-default** (keeps screener URLs shareable/bookmarkable); **POST** only when input is a large symbol list (Monitor).
- Pages = a shell template + client-fetches-API. `app.py` dissolves to **app-factory + `register_blueprint(...)`**.

### 4.2 Sections — thin managers (🔒)
Each section is a small package:
```
screener/
  routes.py     # blueprint (thin HTTP)
  service.py    # handle(): the composition ("putting the kernel together")
  templates/
options/
  routes.py
  service.py
  gex_engine.py # PRIVATE deep core
```
- `handle()` is the **recipe**: fetch forms → call kernel / read store → shape ViewModel. It holds *no* formulas (kernel) and *no* fetch logic (providers) — just the wiring.
- **Independent**: no section imports another. Shared meaning lives in stores/kernel.
- **Set:** Screener · Monitor · RRG (+private quadrant core) · Options (+private GEX core) · Macro (+private layer-scoring core). The old `macro/` package **dissolves** into Macro + RRG.
- **Screener** reads the **precomputed** `CrossSection` (no live kernel). **Monitor** calls the kernel **live** for one symbol.

### 4.3 Kernel (🔒)
Pure, **source-blind** (only ever sees a form, never a source/asset type), **GPU-tensorized** (CPU for one symbol, GPU for the universe; device auto-selected internally). **Fed** by sections (live) and the Writer (batch) — it **never fetches**.

Members (each genuinely shared, ≥2 consumers):
- **Indicators** — MA, slopes, returns, resample.
- **RelativeStrength** — RS-line, Mansfield, RS-ratio/momentum, rel-perf, + cross-sectional ranking.
- **StageClassification** — Weinstein stage 1–4.

`GEX`, `macro layer-scoring`, and `RRG quadrant geometry` are **section-private cores** (single consumer each → not kernel).

### 4.4 DataSource — raw (🔒)
Owns **source-resolution** for raw external data behind a form-shaped interface; caller passes ids + params, never a source. A `(form, id)` **registry** (config, not branching) selects the submodule, fetches, normalizes, caches. Adding an asset type = a registry row (+ maybe one handler).

Two refresh regimes: **prices** = incremental delta-fetch (per-symbol last-bar-date); **fundamentals** = scheduled job. Absorbs today's duplicated `yf.screen`, the `streamlit_app` ETF/futures leak, and the 7 scattered Refinitiv pkl reads.

### 4.5 ComputedStore — derived (🔒, DB ✅)
A Postgres-backed store of kernel outputs, **current/history split** (keeps the Screener's read fixed-size regardless of history growth). Self-describes freshness via `MAX(date)`. The kernel is its **only** writer.

### 4.6 Lists — shared (🔒, DB ✅)
Server-side list store. **Screener writes, Monitor reads** — neither calls the other. Replaces the client `localStorage` watchlist; persists, multi-device.

---

## 5. Contracts (🔒)

### 5.1 ViewModel envelope (section output → client renderer)
```js
ViewModel = {
  figures: [ { id, traces:[...], layout:{...} } ],   // 0..N Plotly-ready figures
  tables:  [ { id, columns:[...], rows:[...] } ],     // 0..N
  meta: {
    status:  "ok" | "empty" | "stale" | "error",
    message: string | null,
    asof:    "YYYY-MM-DD",                 // freshness (last-bar-date / batch date)
    title:   string,
    context: { symbol | list | params },   // echo of the request
    readouts:{ stage, rs_rank, gamma_flip, ... }  // headline scalars (badges)
  }
}
```
- Consumed by **one generic client renderer** (`renderViewModel(vm)`): figures → `Plotly.newPlot(id,…)`, tables → HTML, readouts → badges, non-ok status → banner. This uniformity is the whole reason to standardize the shape — it kills per-page bespoke rendering JS.
- `figures`/`tables` are **id-keyed lists** so the envelope is self-describing (a one-figure section returns `figures:[one]`; Monitor returns several).
- **Evolve additively** — adding optional fields is free; renaming/removing breaks the renderer + every section.
- Page **input controls** and **section-specific interactions** are NOT consumers — they build the typed request / bind handlers by `id`.

### 5.2 Kernel interfaces — enrichment pipeline
Each primitive takes the panel-so-far, **adds columns**, passes it on (`TimeSeries → TimeSeries(+cols)`):
```python
panel = indicators.compute(ts)                          # + ma_50/150/200, slopes, returns
panel = relative_strength.compute(panel, benchmark)     # + rs_line, mansfield_rs   (per-symbol)
panel = relative_strength.rank(panel, by="mansfield_rs")# + rs_rank                  (needs the universe)
panel = stage.compute(panel)                            # + stage  (reads ma_*/rs_line already present)
```
- Runs identically on 1 symbol (CPU) or the universe (GPU).
- `rs_rank` is cross-sectional → **not computable for one symbol**; Monitor gets it from `classification_current`, not live.
- Stage **reuses** the MA/RS columns earlier steps added (no recomputation).

### 5.3 Data-provider interfaces — two providers, no facade
```python
# DataSource — RAW
data.time_series(ids, start=None, end=None, fields=("close","volume")) -> TimeSeries
data.option_chain(symbol, n_exp=4)                                     -> OptionChain
data.fundamentals(ids, fields=None)                                    -> Fundamentals   # reads MKFund

# ComputedStore — DERIVED
computed.cross_section(filters=None)            -> CrossSection   # classification_current → Screener
computed.history(symbol, start=None, end=None)  -> TimeSeries     # classification_history → Monitor
computed.ensure_fresh(ids)                       -> None          # diff last-bar-date, Writer for stale
```
- Reads **auto-ensure-fresh internally** — the caller asks for data and always gets fresh; the cold-miss recompute is the documented exception.
- `(form,id)` registry: `id → asset_class`, then `(form, asset_class) → submodule`.
- **Two providers** called directly by sections; **no unified facade** (would be a shallow seam).

---

## 6. Data model — Postgres `etc_db` (✅ built, empty)

Server `10.123.0.9` (db-tools name `etc_db`). Plain Postgres (no TimescaleDB) → plain heap tables. **Option B current/history split.** Prefect runs on the same server (scheduling deferred — see §9).

### `MKCompStore` — computed (written only by the Writer)
| Table | PK | Serves |
|---|---|---|
| `classification_current` | `symbol` | Screener — fixed-size cross-section |
| `classification_history` | `symbol, date` | Monitor — stage/RS evolution |

Columns: `stage, rs_rank, mansfield_rs, ma_50, ma_150, ma_200, ma_150_slope, regime, ma_screen, eps_accel` (+ `date`, audit ts). Extend via `ALTER` as the kernel is wired.

### `MKFund` — raw fundamentals (from `refinitiv_fundamentals.pkl`)
| Table | PK | Notes |
|---|---|---|
| `fundamentals_current` | `symbol` | 37 cols — Screener fundamental filters |
| `estimates_forward` | `symbol, fy_period` | FY1/FY2 consensus (EPS/Rev/EBITDA mean/high/low/smart, n_est, capex, cfps, dps) |
| `quarterly` | `symbol, report_date` | per-quarter actuals + estimates + margins |
| `estimate_revisions` | `symbol, fy_period, metric, asof` | long-form EPS/Rev revision history (trend_* + hist_est_*) |

### `MKLists` — shared lists
| Table | PK | Notes |
|---|---|---|
| `list_member` | `list_name, symbol` | + index on `symbol`; cols `added_at`, `note`. Screener writes, Monitor reads. |

DB connection credentials live in Prefect config on that server (not yet retrieved; db-tools already has the `etc_db` connection).

---

## 7. Freshness & compute model (🔒)

- **Freshness signal:** per-symbol **last-bar-date**. The DB self-describes: `SELECT symbol, MAX(date) FROM classification_history GROUP BY symbol`.
- **Universe = precompute-backed** (warm store; build-on-cold-miss). **Single symbol = live** (kernel on the spot). Same kernel both ways — one definition of how stage/RS is computed.
- **The Writer** (was `update_classifications`) = **materialization only**:
  ```python
  def writer.run(stale_ids):                 # offline / on cold-miss
      panel = data.time_series(stale_ids)    # read raw (DataSource)
      panel = run_kernel(panel)              # Indicators → RS → rank → Stage (GPU)
      computed.upsert(panel)                 # INSERT history + UPSERT current (one txn)
  ```
  It owns **neither** the compute (kernel), **nor** the schedule (external), **nor** the consumption (providers). Incremental, per-symbol keyed, GPU-fast.
- On a normal day every symbol gains one bar → the whole universe is stale-by-one → first access recomputes all (GPU, sub-second), then warm. If only N symbols changed, only N recompute.
- **GPU caveat:** the GPU speeds compute, not the network fetch. "New data available" means the **local price panel** got new bars (DataSource's incremental delta-fetch).

---

## 8. Dependency injection & testing (🔒)

Sections, the Writer, and kernel-callers **receive** their providers — `handle(req, data, computed)`, `Writer(data, computed, kernel)` — so tests pass fakes. This is the concrete fix for today's untestable global/lazy imports.

| Seam | Test | Needs |
|---|---|---|
| Kernel | pure unit — hand-built `TimeSeries` in, assert columns out | nothing |
| Section `handle()` | stub `data`/`computed` → assert ViewModel | no Flask/DB |
| DataSource/ComputedStore | registry + normalization on fixtures; integration vs test schema | disposable Postgres |
| Blueprint | Flask test client + stubbed section | — |
| Writer | stub kernel + store → assert materialization | — |

Pyramid: **many** kernel pure-units + section-with-stubs, **few** integration tests. Model: the existing `tests/test_gex_engine.py` (pure math) + `test_gex_api.py` (stubbed service).

---

## 9. Deferred & implementation-time (⏸ / ✏️)

- ⏸ **Scheduling / data jobs** — handled by the user's **own scheduler** (not Prefect-driven here). The maintenance pipeline (price delta-fetch → Writer → fundamentals refresh) is built later; lazy-on-access remains the cold-cache fallback.
- ✏️ **RRG data home** — kill the `streamlit_app` import; ETF/futures fetching becomes `(time_series, etf)` / `(time_series, futures)` DataSource submodules. RRG then just calls `data.time_series(etfs)`.
- ✏️ **Screener filter map** — the ~40 query filters → `classification_current` + `fundamentals_current` columns (a lookup table, wired during implementation).
- ✏️ **Macro layer-scoring** core — private; fed `TimeSeries` macro series via a `(time_series, macro)` submodule (`calculations.liquidity`).

---

## 10. Current → target migration map

| Today | Becomes |
|---|---|
| `app.py` (2090-line monolith) | app-factory + `register_blueprint(...)`; routes move to per-section `routes.py` |
| `macro/` package | dissolves → **Macro** section + **RRG** section |
| `update_classifications.py` (batch) | **Writer** (incremental, GPU, materialization-only) → `MKCompStore` |
| `screener.py` + screener logic in `app.py` | **Screener** section; duplicated `yf.screen` → DataSource |
| `rrg_service.py` importing `streamlit_app` | **RRG** section + DataSource etf/futures submodules |
| `options_service.py` + `gex_engine.py` | **Options** section + private GEX core (already the right shape) |
| `liquidity_service.py` | **Macro** section + private layer-scoring core |
| `data_manager.py` | **DataSource** (`time_series`/`option_chain`/`fundamentals` + registry) |
| classification JSON files | `MKCompStore` Postgres tables |
| `refinitiv_fundamentals.pkl` (7 scattered reads) | `MKFund` Postgres tables, one DataSource submodule |
| client `localStorage` watchlist | `MKLists` Postgres + shared store |
| `_n`×3 / `_safe_num` scattered formatters | one Format helper (folded into ViewModel shaping) |

## 11. Suggested implementation order

1. **DataSource** (`time_series` first) + registry — most depended-on; kill the `yf.screen` duplication.
2. **Kernel** primitives (Indicators → RS → Stage) as the enrichment pipeline — pure, fully unit-tested.
3. **ComputedStore** + **Writer** — wire kernel → `MKCompStore`; loaders for `MKFund` from the pkl.
4. **Screener** section (reads `computed.cross_section`) — the landing page, proves the path end-to-end.
5. **Monitor** (live kernel + history + Lists), then **Options**, **RRG**, **Macro**.
6. Thin blueprints + the generic ViewModel renderer last; `app.py` shrinks to the factory.
```
