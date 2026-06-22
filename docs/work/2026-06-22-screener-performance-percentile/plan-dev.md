# plan-dev.md — Screener performance returns + universe percentile (TDD)

Tactics for `prd.md`. Server TDD (`src/mktt/tests/`, run from `src/mktt/`: `python -m pytest -q`);
client browser-verified by orchestrator. Carried baseline: 6 `test_kernel::
test_parity_kernel_vs_stage_classifier[*]` failures are pre-existing — leave untouched.

S1 and S2 both edit `sections/screener/service.py` heavily and S2 percentiles S1's return fields →
**one developer, S1 then S2 sequentially** (no parallel edits to service.py).

## Slice 1 — Trailing returns (developer, TDD) · DONE
**Goal:** every screener row carries 7 total-cumulative trailing returns, as value columns + filters.
### Interface
1. **`datasource`**: `EquitySubmodule.panel_returns(ids, as_of=None, lags=None) -> {sym: {Ret1W..Ret5Y}}`
   reading `close.parquet` directly (like `panel_technicals`: slice columns to `ids`, honor `as_of` by
   trimming the date index to ≤ as_of, then index by integer position). Default lags per `prd.md`.
   `(close[pos] / close[pos-lag] - 1)*100`; missing symbol or insufficient rows → field omitted/None.
   Expose `DataSource.panel_returns(ids, **kw)` delegating to equity (mirror `panel_technicals` delegate).
2. **`screener.service._pipeline`**: after `_apply_panel_technicals`, call `data.panel_returns(universe,
   as_of=...)` once and `r.update(rets.get(sym, {}))` per row (same shape as panel technicals). Guard for
   a provider without `panel_returns` (stubs) — skip gracefully.
3. **Column wiring** (value cols): add the 7 ids to `RESULT_COLUMNS`, `COL_ID_TO_RESULT`, `FLAT_COL_SPEC`
   (label/fmt/colored/kind per prd), the flat `_page_row` snake_case key, and `screener_data` builder so
   the embedded rows include them. Add a `RETURN_RANGE_COLUMNS = {ret1w:"Ret1W", …}` map; wire into
   `ScreenRequest.from_query` (`{id}_min`/`{id}_max`) + the filter-application step alongside the other
   range maps.
### Behaviors to test (server)
1. `panel_returns` on a tiny synthetic close panel → correct totals at each lag; insufficient history →
   None; `as_of` earlier date uses the right window.
2. `_pipeline` rows carry `Ret3M` etc. when the data provider supplies them (stub `panel_returns`).
3. `ret3m_min`/`ret3m_max` filter the passed set (rows outside the band dropped); absent → no-op.
4. Column id `ret3m` resolves through `COL_ID_TO_RESULT`/`FLAT_COL_SPEC`; `cols=ret3m` renders the value.
### DoD
New tests green; existing suites green. No N+1 (one `panel_returns` call per pipeline). REPORT in log.md.

## Slice 2 — Universe percentile for every numeric metric (developer, TDD) · DONE
**Goal:** each base numeric metric gains a `%ile` column (universe rank) + a percentile filter.
### Interface
1. **Percentile engine** (pure): `PCTILE_BASE_IDS` = every FLAT_COL_SPEC id with `kind=="num"` in the
   BASE spec (incl. the 7 returns; the percentile cols don't exist yet so no recursion). A function
   `_attach_percentiles(rows)` that, over the FULL universe `rows`, computes per base id the rank of each
   row's metric (pandas `Series.rank(pct=True)*100`, higher→higher; null→null) and writes
   `r["{ResultName}_Pctile"]`. Call it in `_pipeline` on the full-universe rows, AFTER returns +
   cross-sectional (PE_vs_*) attach so those are percentile-able too.
2. **Column wiring** (percentile cols): for each base numeric id, generate id `{id}p`, RESULT_COLUMNS
   name `{ResultName}_Pctile`, COL_ID_TO_RESULT + FLAT_COL_SPEC entries (label `+ " %ile"`, fmt `P%.0f`
   via a new `_fmt_pctile`, align right, kind num), flat `_page_row` key, and `screener_data`. Generate
   these table-driven (a loop over PCTILE_BASE_IDS), NOT 30 hand entries.
3. **Percentile filters**: `{baseid}_pmin`/`{baseid}_pmax` (0–100) for every base numeric id. Parse
   generically in `from_query` (a `PCTILE_FILTER_IDS` = PCTILE_BASE_IDS). Apply: passed row kept iff its
   `{ResultName}_Pctile` ∈ [pmin,pmax]; null percentile fails when a bound is set.
### Behaviors to test (server)
1. `_attach_percentiles` on a small rows list → correct 0–100 ranks; min value ≈ low pct, max ≈ 100;
   null metric → null percentile; ties stable.
2. Percentile basis is FULL universe, not the passed subset (filtering rows doesn't move a kept row's
   percentile — mirror the existing full-universe-median test).
3. `pe_pmin=90` keeps only rows whose PE percentile ≥ 90; `ret3m_pmin`/`_pmax` band works; null-percentile
   rows excluded when a bound is set.
4. Every base numeric id has a `{id}p` column resolvable via COL_ID_TO_RESULT/FLAT_COL_SPEC; percentile
   cols themselves are NOT in PCTILE_BASE_IDS (no `pepp`).
5. Cached pipeline result still value-equal (percentiles deterministic across two identical calls).
### DoD
New tests green; existing suites green. Percentile is one vectorized pass per metric (no per-row Python
rank loops over the whole universe). REPORT in log.md; FLAG any contract ambiguity instead of guessing.

## Slice 3 — Filter form + picker groups (orchestrator, browser-verify) · DONE
Depends on S1/S2 frozen ids only.
1. `screener.html`: a new **Performance** advanced-filter row — per return: value `_min`/`_max` + percentile
   `_pmin`/`_pmax` inputs. Add `_pmin`/`_pmax` percentile inputs next to the existing numeric value filters
   (PE, FwdPE, RS, margins, EV/EBITDA, ND/EBITDA, pct50/200, 52H/L, PE/sec, PE/ind, fwdpe/sec, fwdpe/ind).
2. `static/js/screener.js`: add picker groups — `performance` (the 7 return value ids) and a `%ile` helper
   that toggles the percentile companions of the currently-visible value cols. (Columns already appear in
   the data-driven picker; groups are convenience.)
### DoD (browser-verify)
- New value cols render with correct numbers; nulls "—"; percentile cols show P00–P100, sortable.
- `?ret3m_min=20` and `?ret12m_pmin=90` filter correctly; a percentile filter on PE works.
- Percentile basis stays full-universe (filtering doesn't shift kept rows' percentiles).
- No console errors; suites green.
