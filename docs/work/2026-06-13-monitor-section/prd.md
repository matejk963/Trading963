# PRD: Monitor section — per-instrument technical + fundamental workspace

Status: Accepted
Created: 2026-06-13
Effort: `docs/work/2026-06-13-monitor-section/`
Respects: `refactor/TARGET_ARCHITECTURE.md` §4.2/§5/§8 (Monitor contract, ViewModel envelope, DI),
`docs/adr/0002` (revive-originals / client-render charts). As-built baseline: `docs/product/mktt-architecture.md`.

## Intent
Turn the Monitor from a skeletal per-symbol chart shell into the app's **bottom-up workspace**: a single
surface where saved instruments are viewed from both a **technical** and a **fundamental** perspective.
It **replaces the standalone watchlist** and becomes the home for saved/selected names — "a hybrid of
TradingView in simpler form, with a comfortable way to view fundamentals for an instrument."

## Why
The refactor build shipped only the Monitor *contract* (live-kernel-per-symbol, `classification_history`
read, MKLists read, a thin `/chart/<symbol>` shell + a separate `/watchlist` page) — never the feature.
The architecture defines the data seam but the UX was a blank slate (see log 2026-06-12 DEBRIEFs:
"options/rrg/macro pages are chart shells, not the original rich layouts"; Monitor never browser-clicked).
Meanwhile the raw materials for a rich view already exist and are unused: live OHLCV panels + kernel
(MA/RS/stage), and a deep fundamentals store (`MKFund` quarterly actuals + forward estimates + revisions,
plus legacy TTM/forward blend endpoints). The work is **assembly and UX**, not new data plumbing.

## Success criteria
- **One unified workspace** at `/monitor`: detail pane (left) + saved-instrument rail (right). The
  standalone `/watchlist` page retires; `/chart/<symbol>` becomes a deep-link to `/monitor/<symbol>`.
- **The rail is a working watchlist replacement** (MKLists-backed): add by ticker (Screener's
  add-to-watchlist still writes here), long/short toggle, per-row remove, click-to-select (updates URL),
  sortable by stage / RS / symbol / recently-added. Each row: `▲/▼ · SYMBOL · stage · RS · ✕`.
- **Technical pane** — TradingView **Lightweight Charts**: daily candlesticks with **D/W/M** timeframe
  (weekly/monthly aggregated from daily bars); toggleable moving averages + an RS line (Mansfield vs SPY,
  MAs recomputed on the displayed timeframe); crosshair readout.
- **Fundamental pane** — Plotly **2×2 line grid** (EPS · Sales top; PE · PS bottom). Actual solid →
  forecast dashed, forecast high/low as a faint band; a shared **Quarter / Year / TTM** granularity
  toggle; a "today" divider splits actual from forecast. Shows actual history + forward estimates
  (**up to ~8 quarters / 2 years** — as many forward quarters as the data holds per name; annual = FY1+FY2).
- **`asof` is plumbed through the data layer** (default = latest) so a historical date scrubber is a
  clean later slice with no rework.
- Section stays a **thin manager** (no formulas, no fetch logic), **dependency-injected**, returning the
  **ViewModel envelope** — consistent with the locked spec (§5, §8); existing 314 green tests stay green.

## Scope
- **IN:** the `/monitor` workspace (rail + detail); retire `/watchlist`, redirect `/chart/<symbol>`;
  the rail's MKLists CRUD (add/remove/side/sort/select); the Lightweight-Charts technical pane
  (candles + MA/RS toggles + D/W/M + crosshair); the Plotly fundamental 2×2 (EPS/Sales/PE/PS, Q/Y/TTM,
  actual+forecast bands, today-divider); `asof`-parameterized fundamental data access reusing the existing
  `MKFund` / `forward_quarterly` / legacy TTM-forward blend logic.
- **OUT (deferred, named so they're cheap later):** the historical **as-of date scrubber** (data plumbed,
  UI later); **margins** in the fundamental grid; the technical pane's **volume pane / stage-tint /
  drawing tools**; **multiple named lists** (list-name is threaded; switcher later); **drag-to-reorder**
  and **per-instrument notes**; intraday charting (no intraday data exists).

## Constraints
- **New frontend dependency:** TradingView Lightweight Charts (MIT) for the technical pane only — the
  rest of the app (incl. the fundamental pane) stays Plotly/`renderViewModel`. This deviates from
  adr/0002's "client-render charts via Plotly" → **needs an ADR** decided at planning time (mixed charting:
  Lightweight Charts for OHLC technical, Plotly for analytical figures).
- **PE/PS basis (default, confirmable):** historical periods use the **period-end price**; forward & TTM
  use the **current price** (standard trailing-vs-forward convention).
- **Honest data limit:** forward-quarter depth is **up to ~8–9Q for ~78% of names**, fewer for thin names
  (measured, not assumed); the pane renders as many forward points as exist. Annual forward is exactly
  FY1+FY2 = 2 years.
- Monitor **reads** MKLists; the Screener **writes** — neither imports the other (spec §4.6).
- Stays within `src/mktt/**` (the section + its templates/JS). No section calls another section.

## Changelog
- 2026-06-13 — Accepted. Derived from a `/grill-me` session (this conversation): spine (unified
  workspace, rail-right), rail semantics (one flat list now, list-name threaded), technical engine
  (Lightweight Charts, daily/W/M, lean MA+RS+crosshair), fundamental content (EPS/Sales actual+forecast,
  Q/Y/TTM, derived PE/PS, 2×2 all-lines), as-of (latest now, plumbed), watchlist CRUD. Data backing
  verified against `refinitiv_fundamentals.pkl` / `MKFund` before acceptance.
