# PRD — Screener: trailing performance returns + universe-percentile for every numeric metric

User request: add trailing performance columns (1W/1M/3M/6M/12M/3Y/5Y) and, for numeric metrics,
not just value-range filtering but a **percentile rank across all stocks** (display + filter).

## Locked decisions (user, 2026-06-22)
- **Returns are TOTAL cumulative** for every horizon (incl. 3Y/5Y) — `P_t / P_{t-lag} − 1`, in %.
- **Percentile applies to ALL numeric screener metrics** (every `kind:"num"` column, incl. the new
  returns) — each gets a universe-percentile value + a percentile filter.
- **Separate optional columns**: each numeric metric keeps its value column AND gains a `%ile` column;
  both are independently toggleable (column picker) and filterable. Percentile columns OFF by default.

## Data reality (verified)
- Price panel `data/mktt/close.parquet`: dates 2020-04-24 → 2026-06-17 (~6y) × 4835 symbols, wide
  `dates × symbols`. So 1W/1M/3M/6M/12M/3Y fully computable; **5Y computable but NULL for symbols listed
  after ~2021-06** (and any horizon is NULL when a symbol lacks that much history) — nulls render as "—".
- No return fields exist today; returns are computed fresh from the close panel (new `panel_returns`).
- Cross-sectional attach pattern already exists (`PE_vs_Sector` via `_median_pe` + a second pass over
  rows) — percentile follows the same two-pass shape, over the FULL universe (all classified rows).

## Contract (frozen)
### Returns — value columns
Trading-day lags (integer index positions, mirroring `panel_technicals` as_of slicing):
`Ret1W=5, Ret1M=21, Ret3M=63, Ret6M=126, Ret12M=252, Ret3Y=756, Ret5Y=1260`.
Value = `(close[as_of] / close[as_of − lag] − 1) * 100`; insufficient history → None.
Column ids / row fields / labels: `ret1w→Ret1W "1W %"`, `ret1m→Ret1M "1M %"`, `ret3m→Ret3M "3M %"`,
`ret6m→Ret6M "6M %"`, `ret12m→Ret12M "12M %"`, `ret3y→Ret3Y "3Y %"`, `ret5y→Ret5Y "5Y %"`.
FLAT_COL_SPEC: fmt `%+.1f`, colored by sign (True), align right, kind num. Value filter stems = the col id
(`ret3m_min`/`ret3m_max`, …).

### Percentile — one companion column per numeric metric
- **Basis:** over the FULL universe (all rows, not just passed). For metric value `v`, percentile =
  rank of `v` among all non-null values in that metric, scaled 0–100, higher value → higher percentile
  (use pandas `Series.rank(pct=True)*100` or equivalent stable rule). Null value → null percentile.
- **Applies to** every base numeric metric = every FLAT_COL_SPEC id with `kind:"num"` in the BASE spec
  (incl. the 7 returns), EXCLUDING the percentile columns themselves (no percentile-of-percentile).
- **Column id** = base value id + `p` (e.g. `pe→pep`, `rs→rsp`, `ret3m→ret3mp`, `from52h→from52hp`).
  Row field = `{ResultName}_Pctile`. Label = base label + ` %ile`. fmt = `P%.0f` (→ "P82", null "—"),
  align right, colored False, kind num.
- **Percentile filter** = `{baseid}_pmin` / `{baseid}_pmax` (0–100) for every base numeric id; a passed
  row is kept only if its metric percentile is within [pmin, pmax] (null percentile fails when a bound
  is set). Parsed generically in `ScreenRequest.from_query`.

### Display / defaults
- `DEFAULT_VISIBLE_COLS` unchanged for percentile cols (off). The new value+pctile cols appear in the
  data-driven column picker automatically (vocab from RESULT_COLUMNS). Client adds a "Performance" picker
  group (the 7 returns) and a "%ile" group helper.
- `screener_data` (embedded full data) must carry the new value + percentile columns so client
  toggle/sort works with zero extra round-trip.

## Out of scope
- Annualized/CAGR returns (user chose total), sector/industry-relative percentile (universe only),
  per-metric percentile heat coloring (kept plain this pass).

## Non-negotiables
- Zero integrity loss; cached pipeline result still value-equal; existing screener/monitor suites green.
- Returns/percentile computed once per pipeline (inside the cached `_pipeline`); no N+1 panel loads.
- Section stays DI/thin; percentile engine is pure + table-driven (no per-metric branching).
