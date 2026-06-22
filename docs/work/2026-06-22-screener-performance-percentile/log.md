# Log — Screener performance returns + universe percentile

Append-only. Agents: read open FLAGs + recent entries before starting; append a REPORT when done.

## 2026-06-22 · orchestrator · REPORT (effort opened)
New effort: trailing performance returns (1W/1M/3M/6M/12M/3Y/5Y, total cumulative) + a universe-percentile
rank companion column & percentile filter for every numeric screener metric. Recon (explorer a13dbf2f)
confirmed: no return fields today; `data/mktt/close.parquet` spans 2020-04→2026-06 (~6y) so all horizons
computable (5Y null for newer listings); technicals come from `data.panel_technicals` off the close panel;
cross-sectional attach pattern (`PE_vs_Sector` two-pass) is the model for percentile. User locked: total
returns, percentile for ALL numeric metrics, separate optional value+%ile columns. Contract frozen in
`prd.md`. Plan: S1 returns → S2 percentile (one developer, sequential, same service.py) → S3 form+picker
(orchestrator, browser-verify).

No open FLAGs.

## 2026-06-22 · developer · REPORT (Slice 1 — trailing returns) · DONE
Built the trailing-return pipeline end-to-end (TDD red→green per behavior).

**Datasource** (`datasource/submodules/equity.py`, `datasource/provider.py`):
- `EquitySubmodule.panel_returns(ids, as_of=None, lags=None) -> {sym: {Ret1W..Ret5Y}}` —
  reads `close.parquet` via `_load_field_panel("close")`, slices to `ids`, honors `as_of`
  by trimming the date index ≤ as_of, ffills, indexes by integer position:
  `(close[-1] / close[-1-lag] - 1)*100`. One precomputed past-row series per lag (vectorized
  over symbols, no per-symbol rank loop). Insufficient history (lag ≥ n) → field omitted.
  Default lags constant `_DEFAULT_RETURN_LAGS = {Ret1W:5, Ret1M:21, Ret3M:63, Ret6M:126,
  Ret12M:252, Ret3Y:756, Ret5Y:1260}`.
- `DataSource.panel_returns(ids, **kw)` delegate mirroring `panel_technicals`.

**Service** (`sections/screener/service.py`):
- `RETURN_RANGE_COLUMNS` filter-stem→row-field map (stem = column id).
- `ScreenRequest.return_ranges` field + `has_return_filters` property + `from_query`
  parsing of `{stem}_min`/`{stem}_max`; applied in `_passes` (`_in_range` semantics —
  null/insufficient history drops when a bound is set).
- `_pipeline` calls `data.panel_returns(universe, as_of=...)` ONCE after panel technicals via
  new `_apply_panel_returns` helper (`r.update(rec)`); guarded by `getattr(data,"panel_returns",
  None) is not None` so bare stubs skip gracefully.
- Column wiring: 7 ids added to `RESULT_COLUMNS`, `COL_ID_TO_RESULT`, `FLAT_COL_SPEC`
  (label `"1W %".."5Y %"`, fmt `%+.1f`, colored True, align right, kind num — client token
  `s1` already mapped), and `_page_row` snake_case keys (`ret1w`..`ret5y`). `screener_data`
  picks them up automatically (built from `RESULT_COLUMNS` via `_results_table`); no `_page_row`
  change needed beyond the 7 keys.

**Return column-id list (final):** `ret1w, ret1m, ret3m, ret6m, ret12m, ret3y, ret5y`
(→ `Ret1W, Ret1M, Ret3M, Ret6M, Ret12M, Ret3Y, Ret5Y`). Left OFF in `DEFAULT_VISIBLE_COLS`.

**Tests** (`tests/test_datasource.py` +4, `tests/test_screener_section.py` +6):
panel_returns at each lag / default lags / as_of / DataSource delegate; pipeline splices
returns (1 call asserted); graceful without provider; ret3m_min/_max band filter; absent
no-op; id resolves + renders `+12.3`; from_query parses min/max.

**Test counts:** `python -m pytest -q` → 6 failed, 416 passed (was 6/406). The 6 are the
carried `test_kernel::test_parity_kernel_vs_stage_classifier[*]` baseline — untouched.
Screener+datasource suites: 105 passed.

State: S1 unblocks S2 (returns are now base numeric metrics to be percentiled). No FLAGs.

## 2026-06-22 · developer · REPORT (Slice 2 — universe percentile) · DONE
Built the universe-percentile engine + companion columns + percentile filters (TDD red→green).

**Percentile engine** (`sections/screener/service.py`):
- `PCTILE_BASE_IDS` = every FLAT_COL_SPEC id with `kind=="num"` in the BASE spec, snapshotted
  BEFORE the percentile cols are appended (47 ids, incl. the 7 Slice-1 returns) → no
  percentile-of-percentile.
- `_attach_percentiles(rows)` (pure): one vectorized pandas `Series.rank(pct=True)*100` per
  base metric over the FULL universe rows; higher value→higher pctile, null value→null pctile,
  ties averaged. Writes `r["{ResultName}_Pctile"]`. NO per-row Python rank loop.
- Called in `_pipeline` on the unfiltered `rows` AFTER returns + PE_vs_* attach, BEFORE
  `_passes`, so kept rows carry their universe rank and the percentile filter can read it.

**Column wiring (table-driven loop over PCTILE_BASE_IDS):** generated `{baseid}p` → RESULT
`{ResultName}_Pctile`, label `base label + " %ile"`, fmt `P%.0f` via new `_fmt_pctile`
(client token `pctile`), align right, colored False, kind num. Appended to `RESULT_COLUMNS`,
`COL_ID_TO_RESULT`, `FLAT_COL_SPEC`; `RESULT_TO_COL_ID`/`RESULT_COL_IDS` re-derived after.
`_page_row` extended with `{baseid}p` keys (so `_flat_cell`'s `spec["key"]` resolves);
`screener_data` carries the 47 `_Pctile` cols automatically (built from RESULT_COLUMNS).

**Percentile filters:** `ScreenRequest.pctile_ranges` + `has_pctile_filters` + generic
`from_query` parse of `{baseid}_pmin`/`{baseid}_pmax` over `PCTILE_FILTER_IDS` (= PCTILE_BASE_IDS);
applied in `_passes` via `PCTILE_RESULT_OF[bid]` with `_in_range` (null percentile fails when a
bound is set).

**Counts:** 47 base numeric ids → **47 percentile columns** generated (`pep, chgp, turnoverp,
rsp, pct50p, pct200p, from52hp, from52lp, pep…` incl. `ret1wp..ret5yp`). Percentile + return
cols left OFF in `DEFAULT_VISIBLE_COLS`.

**Percentile-basis decision as implemented:** FULL universe (all classified `rows`, not the
passed subset); `Series.rank(pct=True)*100` (higher→higher); null metric → null percentile;
null percentile fails a percentile filter when any bound is set. Verified by the
full-universe-basis test (filtering doesn't move a kept row's percentile) — mirrors the
existing median-PE full-universe test.

**Contract-ambiguity checks (no FLAG needed):**
- `screener_data` builder shape: built from RESULT_COLUMNS via `_results_table`; appending the
  `_Pctile` names is sufficient — embedded rows carry them, `col_id_of` maps `{id}p`→index.
- `_page_row`: yes, each new percentile key was added explicitly (table-driven loop) because
  `_flat_cell` looks up `spec["key"]` in the page_row dict.
- Null-percentile filter semantics: a null `_Pctile` fails when a `_pmin` OR `_pmax` is set
  (`_in_range` drops None when any bound present) — matches "null percentile fails when a bound
  is set" in the frozen contract; `_pmin=0` still requires non-null (verified by test).

**Tests** (`tests/test_screener_section.py` +10): attach ranks / ties-average / full-universe
basis / pe_pmin≥90 / ret3m_pmin-pmax band / null-percentile excluded / every base id has a
resolvable `{id}p` + no `pepp` + `pep`→`PE_Pctile` / P-format render (`P100`) / from_query
parses `_pmin`/`_pmax` / cached deterministic.

**Test counts:** `python -m pytest -q` → 6 failed, 426 passed (was 6/416 after S1). The 6 are
the carried `test_kernel::test_parity_kernel_vs_stage_classifier[*]` baseline — untouched.
Screener+datasource suites: 115 passed.

State: S1+S2 complete; frozen ids (returns + 47 `{id}p` percentile cols + `_pmin`/`_pmax`
filters) ready for S3 (orchestrator: filter form + picker groups). No FLAGs. Did not touch
templates or static/js (Slice 3 owns those).

## 2026-06-22 · orchestrator · REPORT (Slice 3 — filter form + picker groups + browser-verify)
Built the client/form half and browser-verified all three pieces live on :5001.
Files: `sections/screener/service.py` (`_filters_dict` echo + `RETURN_FILTER_SPECS`/`PCTILE_FILTER_SPECS`
+ handle_page context), `sections/screener/templates/screener.html` (2 filter rows + 2 picker buttons),
`static/js/screener.js` (Performance group, `addPctileCols`, `pctile` render token).

- **Filter form** — extended `_filters_dict` to round-trip `{ret*}_min/_max`, `{ret*}_pmin/_pmax` and every
  base-numeric `{id}_pmin/_pmax`; added `has_return_filters`/`has_pctile_filters` (drive advanced-open).
  Two data-driven rows: **Performance** (7 horizons × value Min%/Max% + percentile P≥/P≤) and **Percentile
  vs all stocks** (P≥/P≤ for all 40 non-return base numerics). Verified inputs render
  (`ret3m_min`, `ret12m_pmin`, `pe_pmin`).
- **Picker** — added a `performance` group button (7 returns) and a **+ %ile** button (`addPctileCols`
  adds the `{id}p` companion of every checked value col). Verified: Performance → 7 returns; +%ile → all 7
  `ret*p` companions added.
- **Render token** — server emits fmt token `pctile`; the client `_fmtCell` lacked it (cells showed raw
  "100"). Added `case 'pctile': return 'P'+n.toFixed(0)` → cells now show `P100`/`P97`/… Bumps
  `_asset_version` (keep-alive self-heals).

**Browser-verified (live):**
- Return columns compute correctly: 12M sorted desc → SNDK +4330.7 (P100) → median +14.5 (P53) → PAVS
  −99.98 (P0.02); ret3m/pe percentiles consistent; PE nulls → null percentile (cell "—").
- Filters narrow: `ret3m_min=20`→1146, `ret12m_pmin=90`→447 (~top 11%), `pe_pmin=90`→271 (fewer; PE has
  many nulls). API counts match the rendered table (1146).
- **Full-universe basis confirmed**: SNDK ret12m percentile = 100 in the unfiltered AND the `ret3m_min=20`
  filtered view (filtering doesn't shift a kept row's percentile).
- Cells render `+772.6` / `P100`; no console errors.

**Tests:** `python -m pytest -q` → 426 passed, 6 failed (carried `test_parity_kernel_vs_stage_classifier[*]`
baseline, untouched). Screener suite 69 passed after the `_filters_dict` echo edits.

**State:** effort complete (S1+S2+S3 done); UNCOMMITTED (awaiting user go-ahead). No open FLAGs.
