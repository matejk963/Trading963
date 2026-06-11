# MKTT Refactor — Handoff

> Pick-up point for any agent. **Read `refactor/MKTT_DASHBOARD.md` first** — it is the architecture map and the source of truth for the codebase. This file only adds the session/process state that the architecture map doesn't carry.

## Goal
Refactor the MKTT Flask app (`src/mktt/`) into **clearer, more modular infrastructure** that is easy to **debug, optimize, and extend**. Not a rewrite — restructure around the patterns it already has.

## ►► THE TARGET (read this first)
- **`refactor/TARGET_ARCHITECTURE.md`** — the agreed design the refactor implements (output of a full grill-me). Kernel-centric: thin HTTP blueprints → thin sections → pure GPU kernel (enrichment pipeline) → DataSource(raw) + ComputedStore(derived) + Lists. Contracts (ViewModel / kernel / providers), the Postgres data model (built), freshness model, DI/testing, and current→target migration map + implementation order.
- **`refactor/mktt_target_architecture.html`** — interactive target map with data-communication edges (clickable I/O contracts).
- **DB is physically built** (empty): Postgres `etc_db` schemas `MKCompStore` (computed, current/history split), `MKFund` (Refinitiv fundamentals), `MKLists` (shared lists). See `TARGET_ARCHITECTURE.md` §6.

## Understand-anything context (the app, current state)
- **`refactor/MKTT_DASHBOARD.md`** — bulleted architecture map: 6 layers, every file, refactor hotspots, stable contracts, "change X → go here" index, 11-step reading order, suggested refactor sequence.
- **`refactor/mktt-knowledge-graph.json`** — full graph (110 nodes / 80 functions / 233 edges, 6 layers, 11-step tour). Mirror lives in `src/mktt/.understand-anything/` (gitignored).
- **Interactive dashboard:** from the plugin dashboard dir (`~/.claude/plugins/cache/understand-anything/understand-anything/2.7.5/packages/dashboard`), run `GRAPH_DIR=<repo>/src/mktt UNDERSTAND_ACCESS_TOKEN=mktt-refactor npx vite --host 127.0.0.1 --port 5173` → open **`http://127.0.0.1:5173/?token=mktt-refactor`**. The token is a per-launch random hex unless you pin it via `UNDERSTAND_ACCESS_TOKEN` (we pin it to `mktt-refactor` for a stable URL).

## Branch state
- Branch: **`refactor/mktt-app`** (off `main` @ `4a58835`), tracks `origin/refactor/mktt-app`.
- Commits so far: `09eb96f chore: gitignore MKTT runtime cache` (just `.gitignore`).
- The repo working tree also has ~254 **unrelated** uncommitted files (a separate liquidity-analysis workstream under `sandbox/analysis/liquidity_rebuild/`). **Do not commit those to this branch** — only commit `src/mktt/**` and `refactor/**` changes here.

## Operational gotchas (important — these bit us)
- **Port 5001 is taken by a DIFFERENT app**: the energy "Price Screen Tool" from the separate `Price_screen_tool` repo (`src_flask/app.py`, runs in the `ATS_2` conda env). Both apps hardcode 5001, so opening `localhost:5001` lands on the energy app, NOT MKTT.
- **Run MKTT on a free port instead.** Launcher used this session: from `src/mktt/`, `python` (use `/home/krajcovic/miniconda3/envs/ATS_2/bin/python` — has Flask) running `import app; app.app.run(host="127.0.0.1", port=5002, threaded=True)`. **Skip `app.py`'s `__main__` auto-update** — its 4835-ticker yfinance fetch starves the single-thread dev server and blocks page loads. `threaded=True` also helps.
- A standing **httpx pin** (`0.25.2`) is in place for an unrelated Refinitiv tool in this env; it breaks `python-telegram-bot`. Not MKTT-related, but noted so nobody is surprised.
- `src/mktt/cache/` (~94MB yfinance pickles) is now gitignored.

## Where we are / next
- **Done:** branch created; cache gitignored; full understand-anything analysis + dashboard produced.
- **Next (from `MKTT_DASHBOARD.md` §6, in order):**
  1. Add tests for the screener + stage paths (mirror the `gex_engine` pure-module + stubbed-service-API test pattern) — lock behavior before moving code.
  2. Extract the `screener_page` orchestration out of `app.py` into `screener.py` (clean service boundary).
  3. Blueprint-ize each feature (`screener_bp`, `options_bp`, `watchlist_bp`, `fundamentals_bp`) the way `macro/` already is; shrink `app.py` to app-factory + blueprint registration.
  4. Make the port env-configurable (`PORT`, default ≠ 5001) to end the collision.
  5. Add off-by-default structured debug logging in `data_freshness` + `data_manager`.
- **Don't break** (high fan-in contracts): `data_manager` loaders (`load_prices`/`load_universe`/`load_spy`), `base.html` template blocks + shared JS, the `update_classifications` JSON output schema.
