"""Screener section — thin manager (spec §4.1, §4.2, §5, §9).

The Screener reads the **precomputed** ``CrossSection`` (no live kernel — spec §4.2):
``screener.handle(req, data, computed)`` is the recipe —

1. read ``computed.cross_section(filters)`` (stage / rs_rank / regime / ma_screen /
   eps_accel + MAs) — the fixed-size derived universe,
2. read ``data.fundamentals(universe)`` (pe / margins / roic / ev_ebitda + sector /
   industry) — the raw fundamentals form,
3. **join** the two on symbol,
4. derive ``PE`` / ``FwdPE`` from price+EPS and the sector/industry-median **PE
   premium** over the FULL universe (port of ``app.py:592-639``),
5. **apply** the parsed filters (fundamental ranges, EPS/Rev growth presets, RS,
   analysts, classification multi-selects, technical ranges, MA setups),
6. **sort** (``app.py:453-458`` sort map),
7. shape a spec §5.1 ViewModel (``tables=[ranked rows]``,
   ``meta.readouts={universe_total, passed}``, ``meta.asof``).

It holds **no** formulas the kernel owns and **no** fetch logic — just the wiring,
and is dependency-injected (spec §8): ``handle`` receives ``data`` / ``computed`` so
tests pass stubs returning small fixtures — no Flask, no DB, no network.

Parity target (spec PRD / log FLAG-8): the CURRENT ``/screener`` route
(``app.py:214-880``), NOT the dead ``screener.py``. Parity means the underlying
NUMBERS match (range-filter semantics, growth presets, median-PE premium, sort
order), wrapped in the NEW ViewModel envelope.
"""
from __future__ import annotations

import datetime
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from viewmodel import num, vm

logger = logging.getLogger("mktt.sections.screener")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


# --------------------------------------------------------------------------- #
# 7a — filter → column map (spec §9)
# --------------------------------------------------------------------------- #
# Each screener filter maps to a CrossSection (computed) or Fundamentals (raw)
# column in the JOINED row. The map is the single source of truth for which
# physical column a filter narrows — config, not branching (spec §4.4 spirit).
#
# Provenance tag: "computed" -> classification_current ; "fund" -> derived from
# fundamentals_current ; "derived" -> computed in handle (PE premium, growth).

#: Fundamental range filters: query-key stem -> joined-row column.
FUND_RANGE_COLUMNS = {
    "pe": "PE",            # derived: price / eps_actual
    "fwdpe": "FwdPE",      # derived: price / fy1 eps
    "opmgn": "OpMargin",   # fund: operating_margin
    "roic": "ROIC",        # fund: roic
    "evebitda": "EV_EBITDA",   # fund: ev_to_ebitda
    "ndebitda": "ND_EBITDA",   # fund: net_debt_to_ebitda
    "pe_sect": "PE_vs_Sector",     # derived: PE / sector-median PE
    "pe_ind": "PE_vs_Industry",    # derived: PE / industry-median PE
}

#: Single-bound (min-only) range filters.
FUND_MIN_COLUMNS = {
    "rs": "RS_Rank",         # computed: rs_rank
    "analysts": "Analysts",  # fund: num_analysts
}

#: Technical range filters (computed/derived technical columns).
TECH_RANGE_COLUMNS = {
    "pct50": "PctAbove50",
    "pct200": "PctAbove200",
    "from52h": "From52H",
    "rschg1w": "RS_Chg1W",
    "rschg1m": "RS_Chg1M",
    "rschg3m": "RS_Chg3M",
}
#: Technical min-only filters.
TECH_MIN_COLUMNS = {"from52l": "From52L"}

#: Classification multi-select filters: query key -> joined-row column.
CLASS_MULTI_COLUMNS = {
    "pca_regime": "PCA_Regime",   # computed: regime
    "stage_class": "Stage_Class", # computed: stage
    "eps_accel": "EPS_Accel",     # computed: eps_accel
    "ma_screen": "MA_Screen",     # computed: ma_screen
}

#: Sort key -> (joined-row column, ascending). Port of app.py:453-458 / 513-525.
SORT_COLUMNS = {
    "turnover": ("ADV_Dollar", False),
    # "mcap" is an original-parity alias: app.py mapped it to ADV_Dollar too (there
    # is no market-cap column), so it sorts identically to turnover — kept for the
    # dropdown's exact option parity.
    "mcap": ("ADV_Dollar", False),
    "change": ("Change%", False),
    "rs": ("RS_Rank", False),
    "mansfield": ("Mansfield_RS", False),
    "dist_high": ("From52H", False),  # From52H ≤ 0; DESC → closest-to-52w-high first
    "pe": ("PE", True),
    "fwdpe": ("FwdPE", True),
    "opmgn": ("OpMargin", False),
    "roic": ("ROIC", False),
    "evebitda": ("EV_EBITDA", True),
}

#: CrossSection (classification_current) value column -> joined-row column.
#  How the computed store's snake_case columns surface in the screener row.
COMPUTED_COLUMN_ALIASES = {
    "stage": "Stage_Class",
    "rs_rank": "RS_Rank",
    "mansfield_rs": "Mansfield_RS",
    "ma_50": "MA50",
    "ma_150": "MA150",
    "ma_200": "MA200",
    "regime": "PCA_Regime",
    "ma_screen": "MA_Screen",
    "eps_accel": "EPS_Accel",
}

#: Fundamentals (fundamentals_current) column -> joined-row column.
FUND_COLUMN_ALIASES = {
    "price_close": "Price",
    "eps_actual": "EPS_Act",
    "operating_margin": "OpMargin",
    "net_margin": "NetMargin",
    "free_cash_flow": "FCF",
    "roic": "ROIC",
    "net_debt_to_ebitda": "ND_EBITDA",
    "ev_to_ebitda": "EV_EBITDA",
    "num_analysts": "Analysts",
    "price_target_mean": "Target",
    "gics_sector": "Sector",
    "gics_industry": "Industry",
}

#: Derived growth columns the presets read (route computes these from quarterly
#: EPS/Rev; if the precomputed store materializes them they pass through the join).
_GROWTH_COLUMNS = {
    "G_NTM_TTM", "G_FY2_FY1", "G_TTM_YOY", "G_FQ_YOY",
    "RG_NTM_TTM", "RG_FY2_FY1", "RG_TTM_YOY", "RG_FQ_YOY",
}

#: EPS growth preset -> predicate over the joined row (port app.py:854-871).
#: Each predicate takes a "getter" g(col)->float|None and returns bool.
EPS_GROWTH_PRESETS = {
    "ntm_pos": lambda g: _gt(g("G_NTM_TTM"), 0),
    "ntm_neg": lambda g: _lt(g("G_NTM_TTM"), 0),
    "fy2_fy1_pos": lambda g: _gt(g("G_FY2_FY1"), 0),
    "fy2_fy1_neg": lambda g: _lt(g("G_FY2_FY1"), 0),
    "ttm_yoy_pos": lambda g: _gt(g("G_TTM_YOY"), 0),
    "ttm_yoy_neg": lambda g: _lt(g("G_TTM_YOY"), 0),
    "fq_yoy_pos": lambda g: _gt(g("G_FQ_YOY"), 0),
    "fq_yoy_neg": lambda g: _lt(g("G_FQ_YOY"), 0),
    "all_pos": lambda g: _gt(g("G_NTM_TTM"), 0) and _gt(g("G_FY2_FY1"), 0),
}

#: Revenue growth preset -> predicate (port app.py:874-891).
REV_GROWTH_PRESETS = {
    "ntm_pos": lambda g: _gt(g("RG_NTM_TTM"), 0),
    "ntm_neg": lambda g: _lt(g("RG_NTM_TTM"), 0),
    "fy2_fy1_pos": lambda g: _gt(g("RG_FY2_FY1"), 0),
    "fy2_fy1_neg": lambda g: _lt(g("RG_FY2_FY1"), 0),
    "ttm_yoy_pos": lambda g: _gt(g("RG_TTM_YOY"), 0),
    "ttm_yoy_neg": lambda g: _lt(g("RG_TTM_YOY"), 0),
    "fq_yoy_pos": lambda g: _gt(g("RG_FQ_YOY"), 0),
    "fq_yoy_neg": lambda g: _lt(g("RG_FQ_YOY"), 0),
    "all_pos": lambda g: _gt(g("RG_NTM_TTM"), 0) and _gt(g("RG_FY2_FY1"), 0),
}

#: EPS-acceleration preset -> predicate (port app.py:894-901).
EPS_ACCEL_PRESETS = {
    "accel": lambda g: _gt2(g("G_NTM_TTM"), g("G_TTM_YOY")),
    "decel": lambda g: _lt2(g("G_NTM_TTM"), g("G_TTM_YOY")),
    "accel_pos": lambda g: (_gt2(g("G_NTM_TTM"), g("G_TTM_YOY"))
                            and _gt(g("G_NTM_TTM"), 0) and _gt(g("G_TTM_YOY"), 0)),
    "decel_neg": lambda g: (_lt2(g("G_NTM_TTM"), g("G_TTM_YOY"))
                            and _lt(g("G_NTM_TTM"), 0)),
}

#: MA-setup predicate over Price/MA50/MA150/MA200 (port app.py:916-944).
MA_SETUP_PRESETS = {
    "above_all": lambda g: (_gt2(g("Price"), g("MA50")) and _gt2(g("Price"), g("MA150"))
                            and _gt2(g("Price"), g("MA200"))),
    "above_50": lambda g: _gt2(g("Price"), g("MA50")),
    "below_50": lambda g: _lt2(g("Price"), g("MA50")),
    "below_all": lambda g: (_lt2(g("Price"), g("MA50")) and _lt2(g("Price"), g("MA150"))
                            and _lt2(g("Price"), g("MA200"))),
    "golden_cross": lambda g: _gt2(g("MA50"), g("MA200")),
    "death_cross": lambda g: _lt2(g("MA50"), g("MA200")),
    "stacked_bull": lambda g: _gt2(g("MA50"), g("MA150")) and _gt2(g("MA150"), g("MA200")),
}


# --------------------------------------------------------------------------- #
# numeric comparison helpers — NaN/None safe (mirror pandas `> n` dropping NaN)
# --------------------------------------------------------------------------- #
def _f(v) -> Optional[float]:
    """Coerce to float or None (NaN/None/non-numeric -> None)."""
    return num(v)


def _gt(v, n) -> bool:
    f = _f(v)
    return f is not None and f > n


def _lt(v, n) -> bool:
    f = _f(v)
    return f is not None and f < n


def _gt2(a, b) -> bool:
    fa, fb = _f(a), _f(b)
    return fa is not None and fb is not None and fa > fb


def _lt2(a, b) -> bool:
    fa, fb = _f(a), _f(b)
    return fa is not None and fb is not None and fa < fb


# --------------------------------------------------------------------------- #
# 7a — ScreenRequest.from_query
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScreenRequest:
    """Typed Screener request — the ~40 query filters parsed once (spec §4.1).

    The section is Flask-free and method-agnostic: parsing lives in
    :meth:`from_query`; ``handle`` only ever sees this record.
    """

    preset: str = "all"
    min_turnover: int = 500_000
    sector: str = "All"
    min_price: float = 0.0
    sort_by: str = "turnover"
    as_of: str = ""

    # fundamental ranges: {stem: (min, max)} over FUND_RANGE_COLUMNS
    fund_ranges: Dict[str, tuple] = field(default_factory=dict)
    # min-only fundamental bounds: {stem: min}
    fund_mins: Dict[str, float] = field(default_factory=dict)

    # growth / accel presets
    eps_growth: str = ""
    rev_growth: str = ""
    eps_accel_filter: str = ""

    # classification multi-selects: {key: [values]}
    class_multi: Dict[str, List[str]] = field(default_factory=dict)

    # technical ranges / min-only / ma-setup
    tech_ranges: Dict[str, tuple] = field(default_factory=dict)
    tech_mins: Dict[str, float] = field(default_factory=dict)
    ma_setup: str = ""

    @property
    def has_fund_filters(self) -> bool:
        return bool(self.fund_ranges) or bool(self.fund_mins) or bool(
            self.eps_growth) or bool(self.rev_growth) or bool(self.eps_accel_filter)

    @property
    def has_tech_filters(self) -> bool:
        return bool(self.tech_ranges) or bool(self.tech_mins) or bool(self.ma_setup)

    @property
    def has_class_filters(self) -> bool:
        return any(self.class_multi.values())

    @classmethod
    def from_query(cls, args) -> "ScreenRequest":
        """Parse the ~40 filters from a query-args mapping (``request.args``).

        ``args`` supports ``get(key, default)`` and ``getlist(key)`` (Flask
        ``MultiDict`` or the test :class:`FakeArgs`). Mirrors the ``_flt`` /
        ``getlist`` block of the live route (``app.py:217-321``).
        """
        getlist = getattr(args, "getlist", None)

        def _flt(name):
            v = args.get(name, "")
            if v == "" or v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _list(name):
            if getlist is not None:
                return list(getlist(name))
            v = args.get(name)
            return list(v) if isinstance(v, (list, tuple)) else ([v] if v else [])

        preset = args.get("preset", "all") or "all"
        # sort default depends on preset (app.py:221).
        sort_default = "turnover" if preset == "all" else "rs"

        fund_ranges = {}
        for stem in FUND_RANGE_COLUMNS:
            lo, hi = _flt(f"{stem}_min"), _flt(f"{stem}_max")
            if lo is not None or hi is not None:
                fund_ranges[stem] = (lo, hi)

        fund_mins = {}
        for stem in FUND_MIN_COLUMNS:
            lo = _flt(f"{stem}_min")
            if lo is not None:
                fund_mins[stem] = lo

        tech_ranges = {}
        for stem in TECH_RANGE_COLUMNS:
            lo, hi = _flt(f"{stem}_min"), _flt(f"{stem}_max")
            if lo is not None or hi is not None:
                tech_ranges[stem] = (lo, hi)

        tech_mins = {}
        for stem in TECH_MIN_COLUMNS:
            lo = _flt(f"{stem}_min")
            if lo is not None:
                tech_mins[stem] = lo

        class_multi = {key: _list(key) for key in CLASS_MULTI_COLUMNS}

        try:
            min_turnover = int(float(args.get("min_turnover", "500000")))
        except (TypeError, ValueError):
            min_turnover = 500_000
        try:
            min_price = float(args.get("min_price", "0"))
        except (TypeError, ValueError):
            min_price = 0.0

        return cls(
            preset=preset,
            min_turnover=min_turnover,
            sector=args.get("sector", "All") or "All",
            min_price=min_price,
            sort_by=args.get("sort_by", sort_default) or sort_default,
            as_of=args.get("as_of", "") or "",
            fund_ranges=fund_ranges,
            fund_mins=fund_mins,
            eps_growth=args.get("eps_growth", "") or "",
            rev_growth=args.get("rev_growth", "") or "",
            eps_accel_filter=args.get("eps_accel_filter", "") or "",
            class_multi=class_multi,
            tech_ranges=tech_ranges,
            tech_mins=tech_mins,
            ma_setup=args.get("ma_setup", "") or "",
        )


# --------------------------------------------------------------------------- #
# 7b — pipeline (shared by the JSON API `handle` and the page `handle_page`)
# --------------------------------------------------------------------------- #
@dataclass
class _PipelineResult:
    """Outcome of the join→enrich→filter→sort recipe (one producer, two views)."""

    context: Dict[str, Any]
    universe_total: int
    rows: List[Dict[str, Any]]       # every joined+enriched row (pre-filter)
    passed: List[Dict[str, Any]]     # filtered + sorted rows
    asof: Optional[str]


def _pipeline(req: ScreenRequest, data, computed) -> _PipelineResult:
    """The single Screener recipe: cross_section ⨝ fundamentals ⨝ live time_series,
    then filter + sort. ``handle`` shapes its result into the ViewModel; the page
    route adapts the SAME result into the server-rendered template (adr/0002 §3 —
    one data producer, two presentations)."""
    context = {
        "preset": req.preset,
        "sector": req.sector,
        "sort_by": req.sort_by,
        "min_turnover": req.min_turnover,
        "min_price": req.min_price,
    }
    logger.debug("screener.pipeline preset=%s sector=%s sort=%s", req.preset,
                 req.sector, req.sort_by)

    cross = computed.cross_section()
    universe = _index_ids(cross)
    universe_total = len(universe)
    asof = _asof(computed)

    if universe_total == 0:
        return _PipelineResult(context, 0, [], [], asof)

    # Fetch WITH estimates so FY1/FY2 EPS+Revenue come back (estimates_forward):
    # FwdPE = price / fy1_eps and the FY2/FY1 growth presets read these. Some stub
    # providers don't accept ``estimates``; fall back to the bare signature.
    try:
        funds = data.fundamentals(universe, estimates=True)
    except TypeError:
        funds = data.fundamentals(universe)

    # Per-symbol quarterly-derived EPS/Rev growth metrics (TTM/NTM/YoY) — port of
    # app.py:656-788. Read from MKFund.quarterly + estimates_forward when the
    # provider exposes them; absent on bare stubs (then presets stay inert).
    growth = _growth_metrics(data, universe)

    # Build the joined rows (one dict per symbol). PE/FwdPE derive from the
    # fundamental price_close here (parity), BEFORE live price overrides Price.
    rows = _join(cross, funds, growth)

    # RS momentum (RS_Chg1W/1M/3M) — original screener parity (app.py@9631169).
    # Computed cross-sectionally from classification_history (rs_rank diffed at
    # 5/21/63 trading-day lags); the store's rs_rank shares the 6mo-return percentile
    # basis, so the delta == the original. Best-effort: never let it blank the page.
    if hasattr(computed, "rs_rank_changes"):
        try:
            _apply_rs_changes(rows, computed.rs_rank_changes())
        except Exception:  # noqa: BLE001
            logger.exception("screener rs_changes: fetch failed")

    # Live technicals (adr/0002 §5): turnover/price/day-change/%-from-52w-high+low.
    # Preferred path is the VECTORIZED ``data.panel_technicals`` (computed column-wise
    # off the wide parquet panels — no per-symbol Python loop, sub-second for the full
    # universe). Falls back to the ``time_series`` reassembly for stub providers that
    # only expose ``time_series`` (and the precomputed-only path for bare stubs).
    as_of = req.as_of or None
    if hasattr(data, "panel_technicals"):
        _apply_panel_technicals(rows, data, universe, as_of)
    elif hasattr(data, "time_series"):
        _apply_live_technicals(rows, data, universe)

    # Median-PE premium over the FULL (unfiltered) universe (app.py:592-639).
    sector_med, industry_med = _median_pe(rows)
    for r in rows:
        r["PE_vs_Sector"] = _pe_premium(r.get("PE"), r.get("Sector"), sector_med)
        r["PE_vs_Industry"] = _pe_premium(r.get("PE"), r.get("Industry"), industry_med)
        # %-above-MA from live Price vs computed MA50/MA200 (only fill when unset,
        # so a precomputed PctAbove* carried on the cross-section still wins).
        if r.get("PctAbove50") is None:
            r["PctAbove50"] = _pct_above(r.get("Price"), r.get("MA50"))
        if r.get("PctAbove200") is None:
            r["PctAbove200"] = _pct_above(r.get("Price"), r.get("MA200"))

    # Apply filters (order mirrors the route: min_price/turnover/sector, then
    # classification, fundamental, technical), then sort.
    passed = _sort([r for r in rows if _passes(r, req)], req.sort_by)
    return _PipelineResult(context, universe_total, rows, passed, asof)


# --------------------------------------------------------------------------- #
# 7b — handle (the recipe)
# --------------------------------------------------------------------------- #
def handle(req: ScreenRequest, data, computed) -> dict:
    """Read computed cross-section + fundamentals, join, filter, rank, shape VM.

    Parameters
    ----------
    req:
        The typed :class:`ScreenRequest`.
    data:
        A `DataSource` (or stub) exposing ``fundamentals(ids, fields=None) ->
        Fundamentals`` (symbol-indexed frame).
    computed:
        A `ComputedStore` (or stub) exposing ``cross_section(filters=None) ->
        CrossSection`` (symbol-indexed frame) and (optionally) ``asof``.
    """
    res = _pipeline(req, data, computed)
    context = res.context

    if res.universe_total == 0:
        return vm(status="empty", message="No computed universe available.",
                  title="Screener", context=context,
                  readouts={"universe_total": 0, "passed": 0})

    if not res.passed:
        return vm(status="empty", message="No symbols passed the filters.",
                  asof=res.asof, title="Screener", context=context,
                  readouts={"universe_total": res.universe_total, "passed": 0})

    universe_total, passed, asof = res.universe_total, res.passed, res.asof
    rows = res.rows
    return vm(
        tables=[_results_table(passed)],
        status="ok",
        asof=asof,
        title="Screener",
        context=context,
        readouts={"universe_total": universe_total, "passed": len(passed)},
        sectors=sorted({r["Sector"] for r in rows if r.get("Sector")}),
    )


# --------------------------------------------------------------------------- #
# join — CrossSection ⨝ Fundamentals on symbol
# --------------------------------------------------------------------------- #
def _index_ids(frame) -> List[str]:
    if frame is None:
        return []
    try:
        return [str(s) for s in frame.index.tolist()]
    except AttributeError:
        return list(frame)


def _row_lookup(frame) -> Dict[str, Dict[str, Any]]:
    """Symbol-indexed frame -> {symbol: {col: value}} (empty-frame safe)."""
    if frame is None:
        return {}
    try:
        if len(frame) == 0:
            return {}
        return {str(sym): rec for sym, rec in frame.to_dict("index").items()}
    except (AttributeError, TypeError):
        return {}


def _growth_metrics(data, universe) -> Dict[str, Dict[str, Any]]:
    """Per-symbol EPS/Rev growth metrics derived from quarterly actuals.

    Port of app.py:656-788 (the quarterly-derived growth block), reading the long
    ``MKFund.quarterly`` table via ``data.quarterly`` instead of the legacy pkl:

    - ``EPS_TTM`` / ``Rev_TTM`` — sum of the last 4 reported quarters,
    - ``G_TTM_YOY`` / ``RG_TTM_YOY`` — TTM vs the prior TTM (quarters -8:-4),
    - ``G_FQ_YOY`` / ``RG_FQ_YOY`` — latest quarter vs the same quarter a year ago.

    The FY2/FY1 and NTM/TTM presets are filled from the forward estimates in
    :func:`_join` (they need the per-symbol FY1/FY2 EPS the join already carries).
    Returns ``{}`` when the provider has no ``quarterly`` (bare stubs) so the
    presets simply stay inert rather than zeroing the screen.
    """
    if not hasattr(data, "quarterly"):
        return {}
    try:
        q = data.quarterly(universe)
    except Exception:  # noqa: BLE001
        logger.exception("screener growth: quarterly fetch failed")
        return {}
    if q is None or getattr(q, "empty", True):
        return {}

    import pandas as pd  # local — keep the module import-light for stub tests

    out: Dict[str, Dict[str, Any]] = {}
    q = q.copy()
    if "report_date" in q.columns:
        q["report_date"] = pd.to_datetime(q["report_date"], errors="coerce")
    for sym, grp in q.groupby("symbol"):
        grp = grp.sort_values("report_date")
        rec: Dict[str, Any] = {}
        for field, ttm_key, yoy_key, fq_key in (
            ("eps_actual", "EPS_TTM", "G_TTM_YOY", "G_FQ_YOY"),
            ("revenue_actual", "Rev_TTM", "RG_TTM_YOY", "RG_FQ_YOY"),
        ):
            if field not in grp.columns:
                continue
            vals = pd.to_numeric(grp[field], errors="coerce").dropna().to_numpy()
            n = len(vals)
            if n < 4:
                continue
            ttm = float(vals[-4:].sum())
            rec[ttm_key] = round(ttm / 1e6, 1) if field == "revenue_actual" else round(ttm, 2)
            if n >= 8:
                prior = float(vals[-8:-4].sum())
                if prior:
                    rec[yoy_key] = round((ttm / prior - 1.0) * 100.0, 1)
            if n >= 5:
                fq_latest, fq_yoy = float(vals[-1]), float(vals[-5])
                if fq_yoy:
                    rec[fq_key] = round((fq_latest / fq_yoy - 1.0) * 100.0, 1)
        if rec:
            out[str(sym)] = rec
    logger.debug("screener growth: %d symbols with quarterly metrics", len(out))
    return out


def _join(cross, funds, growth=None) -> List[Dict[str, Any]]:
    """Join the computed cross-section with fundamentals, aliasing columns to the
    screener row names and deriving PE/FwdPE from price+EPS.

    Two carry mechanisms:
    - **alias maps** translate the stores' snake_case columns (``rs_rank`` ->
      ``RS_Rank``) to the screener row names, and
    - **pass-through** copies any column already named like a screener row column
      (``ADV_Dollar`` / ``Change%`` / ``PctAbove50`` / ``RS_Chg1W`` / ``G_*`` …) so
      additional materialized columns surface without touching the alias map.
    """
    passthrough = set(RESULT_COLUMNS) | _GROWTH_COLUMNS
    cross_rows = _row_lookup(cross)
    fund_rows = _row_lookup(funds)
    out: List[Dict[str, Any]] = []
    for sym, crec in cross_rows.items():
        row: Dict[str, Any] = {"Symbol": sym}
        for src, dst in COMPUTED_COLUMN_ALIASES.items():
            if src in crec:
                row[dst] = crec[src]
        for col, v in crec.items():
            if col in passthrough:
                row[col] = v
        frec = fund_rows.get(sym, {})
        for src, dst in FUND_COLUMN_ALIASES.items():
            if src in frec:
                row[dst] = frec[src]
        for col, v in frec.items():
            if col in passthrough:
                row[col] = v

        # Forward EPS / Revenue (FY1 / FY2) from estimates_forward (attached when
        # data.fundamentals(estimates=True)). FwdPE = price / FY1 EPS.
        fy1_eps = _f(frec.get("fy1_eps_mean", frec.get("fy1_eps_smart")))
        fy2_eps = _f(frec.get("fy2_eps_mean", frec.get("fy2_eps_smart")))
        fy1_rev = _f(frec.get("fy1_revenue_mean"))
        fy2_rev = _f(frec.get("fy2_revenue_mean"))
        row["EPS_FY1"] = fy1_eps
        row["EPS_FY2"] = fy2_eps
        # Revenue reported in millions for display parity (app.py:715).
        row["Rev_FY1"] = round(fy1_rev / 1e6, 1) if fy1_rev is not None else None
        row["Rev_FY2"] = round(fy2_rev / 1e6, 1) if fy2_rev is not None else None

        # Derive PE / FwdPE (app.py:556-559).
        price = _f(row.get("Price"))
        eps_act = _f(row.get("EPS_Act"))
        row["EPS_Act"] = eps_act
        row["PE"] = (price / eps_act) if (price is not None and eps_act
                                          and eps_act > 0) else None
        row["FwdPE"] = (price / fy1_eps) if (price is not None and fy1_eps
                                             and fy1_eps > 0) else None

        # Merge quarterly-derived growth metrics (TTM/YoY/FQ) — app.py:730-788.
        if growth:
            grec = growth.get(sym)
            if grec:
                row.update(grec)

        # FY2-vs-FY1 growth (forward estimates) — app.py:685-689 / 761-765.
        if fy1_eps and fy1_eps != 0 and fy2_eps is not None:
            row["G_FY2_FY1"] = round((fy2_eps / fy1_eps - 1.0) * 100.0, 1)
        if fy1_rev and fy1_rev != 0 and fy2_rev is not None:
            row["RG_FY2_FY1"] = round((fy2_rev / fy1_rev - 1.0) * 100.0, 1)

        # NTM-vs-TTM growth — the legacy NTM came from a forward_quarterly pkl not
        # in MKFund; FY1 (next-fiscal-year mean) is the available forward annual
        # proxy for next-twelve-months EPS/Rev (documented approximation).
        eps_ttm = _f(row.get("EPS_TTM"))
        if eps_ttm and eps_ttm != 0 and fy1_eps is not None:
            row["EPS_NTM"] = round(fy1_eps, 2)
            row["G_NTM_TTM"] = round((fy1_eps / eps_ttm - 1.0) * 100.0, 1)
        rev_ttm = _f(row.get("Rev_TTM"))
        fy1_rev_m = (fy1_rev / 1e6) if fy1_rev is not None else None
        if rev_ttm and rev_ttm != 0 and fy1_rev_m is not None:
            row["Rev_NTM"] = round(fy1_rev_m, 1)
            row["RG_NTM_TTM"] = round((fy1_rev_m / rev_ttm - 1.0) * 100.0, 1)

        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# live technicals from data.time_series (adr/0002 §5)
# --------------------------------------------------------------------------- #
#: Rolling windows (trading days) for the live derivations.
_ADV_WINDOW = 50        # avg dollar volume lookback
_52W_WINDOW = 252       # 52-week high/low lookback
_TS_LOOKBACK_DAYS = 420  # calendar days fetched (covers ~252 trading days)


def _apply_panel_technicals(rows, data, universe, as_of=None) -> None:
    """Vectorized live technicals via ``data.panel_technicals`` (the perf path).

    The whole-universe technicals dict is computed column-wise off the wide parquet
    panels in one shot; here we just splice each symbol's record onto its row.
    ``as_of`` honors the screener As-Of picker (price window ends on that date).
    Best-effort: any failure leaves the precomputed/fundamental rows untouched.
    """
    try:
        tech = data.panel_technicals(
            universe, adv_window=_ADV_WINDOW, win_52w=_52W_WINDOW, as_of=as_of)
    except Exception:  # noqa: BLE001 — never let a fetch hiccup blank the page
        logger.exception("screener panel technicals: vectorized fetch failed")
        return
    if not tech:
        logger.debug("screener panel technicals: empty result")
        return
    enriched = 0
    for r in rows:
        t = tech.get(r["Symbol"])
        if not t:
            continue
        r.update(t)
        enriched += 1
    logger.debug("screener panel technicals: enriched %d/%d rows", enriched, len(rows))


def _apply_live_technicals(rows: List[Dict[str, Any]], data, universe) -> None:
    """Override ``Price`` and add live technicals on each joined row in place.

    Derives, per symbol, from the ``symbol × date`` (close, volume) panel:

    - ``Price``       — latest close (replaces the fundamental ``price_close``),
    - ``Change%``     — latest close vs the prior close (day change),
    - ``ADV_Dollar``  — latest close × mean volume over the last ``_ADV_WINDOW`` days
                        (the screener's turnover figure → the ``min_turnover`` gate),
    - ``From52H``     — % the latest close sits below the trailing 52-week high (≤ 0),
    - ``From52L``     — % the latest close sits above the trailing 52-week low (≥ 0),
    - ``PctAbove50`` / ``PctAbove200`` — % the close is above the (computed) MA50/MA200.

    Symbols absent from the panel keep their pre-existing (fundamental) values.
    The whole step is best-effort: any failure leaves the precomputed/fundamental
    rows untouched (the page still renders, just without live turnover).
    """
    try:
        start = (datetime.date.today()
                 - datetime.timedelta(days=_TS_LOOKBACK_DAYS)).isoformat()
        panel = data.time_series(universe, start=start)
    except Exception:  # noqa: BLE001 — never let a fetch hiccup blank the page
        logger.exception("screener live technicals: time_series fetch failed")
        return
    if panel is None or getattr(panel, "empty", True):
        logger.debug("screener live technicals: empty time_series panel")
        return

    tech = _derive_panel_technicals(panel)
    enriched = 0
    for r in rows:
        t = tech.get(r["Symbol"])
        if not t:
            continue
        r.update(t)
        enriched += 1
    logger.debug("screener live technicals: enriched %d/%d rows", enriched, len(rows))


#: store rs_chg column -> screener row column (RS momentum range filters + medians).
_RS_CHG_COLUMNS = {"rs_chg1w": "RS_Chg1W", "rs_chg1m": "RS_Chg1M", "rs_chg3m": "RS_Chg3M"}


def _apply_rs_changes(rows: List[Dict[str, Any]], rs_chg) -> None:
    """Splice RS-momentum (rs_chg1w/1m/3m) onto rows as ``RS_Chg1W/1M/3M`` (parity).

    ``rs_chg`` is the symbol-indexed frame from ``ComputedStore.rs_rank_changes``.
    Best-effort: symbols absent from the frame (short history) keep ``RS_Chg = None``,
    so the range filters simply don't match them (``_in_range`` drops None) — the
    same exclusion the original applied. Never raises.
    """
    if rs_chg is None or getattr(rs_chg, "empty", True):
        return
    recs = rs_chg.to_dict("index")
    enriched = 0
    for r in rows:
        rec = recs.get(r["Symbol"])
        if not rec:
            continue
        for src, dst in _RS_CHG_COLUMNS.items():
            v = rec.get(src)
            if v is not None and v == v:  # not None / not NaN
                r[dst] = round(float(v), 1)
        enriched += 1
    logger.debug("screener rs_changes: enriched %d/%d rows", enriched, len(rows))


def _derive_panel_technicals(panel) -> Dict[str, Dict[str, Any]]:
    """``symbol × date`` (close, volume) panel -> {symbol: {derived columns}}.

    Vectorized per symbol via groupby; tolerant of short histories (a symbol with
    a single row still yields Price + ADV, with day-change/52w left None).
    """
    out: Dict[str, Dict[str, Any]] = {}
    if "close" not in panel.columns:
        return out
    has_vol = "volume" in panel.columns

    for sym, grp in panel.groupby(level="symbol"):
        closes = grp["close"].dropna()
        if closes.empty:
            continue
        price = float(closes.iloc[-1])
        rec: Dict[str, Any] = {"Price": price}

        if len(closes) >= 2:
            prev = float(closes.iloc[-2])
            if prev:
                rec["Change%"] = (price / prev - 1.0) * 100.0

        if has_vol:
            vols = grp["volume"].dropna()
            if not vols.empty:
                adv_vol = float(vols.tail(_ADV_WINDOW).mean())
                rec["ADV_Dollar"] = price * adv_vol

        window = closes.tail(_52W_WINDOW)
        hi, lo = float(window.max()), float(window.min())
        if hi > 0:
            rec["From52H"] = (price / hi - 1.0) * 100.0   # ≤ 0
        if lo > 0:
            rec["From52L"] = (price / lo - 1.0) * 100.0   # ≥ 0

        out[str(sym)] = rec
    return out


def _pct_above(price, ma) -> Optional[float]:
    p, m = _f(price), _f(ma)
    if p is None or m is None or m <= 0:
        return None
    return (p / m - 1.0) * 100.0


# --------------------------------------------------------------------------- #
# median-PE premium over the full universe (app.py:592-639)
# --------------------------------------------------------------------------- #
def _median(values: Sequence[float]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None and not (
        isinstance(v, float) and math.isnan(v)))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def _median_pe(rows: List[Dict[str, Any]]):
    by_sector: Dict[str, List[float]] = {}
    by_industry: Dict[str, List[float]] = {}
    for r in rows:
        pe = _f(r.get("PE"))
        if pe is None:
            continue
        sec, ind = r.get("Sector"), r.get("Industry")
        if sec:
            by_sector.setdefault(sec, []).append(pe)
        if ind:
            by_industry.setdefault(ind, []).append(pe)
    sector_med = {k: _median(v) for k, v in by_sector.items()}
    industry_med = {k: _median(v) for k, v in by_industry.items()}
    return sector_med, industry_med


def _pe_premium(pe, group, medians) -> Optional[float]:
    pe = _f(pe)
    if pe is None or not group:
        return None
    med = medians.get(group)
    if not med or med <= 0:
        return None
    return round(pe / med, 2)


# --------------------------------------------------------------------------- #
# filtering (port of app.py:402-944)
# --------------------------------------------------------------------------- #
def _in_range(v, lo, hi) -> bool:
    """``_range_filter`` semantics: NaN/None drops out when a bound is set."""
    f = _f(v)
    if lo is not None:
        if f is None or f < lo:
            return False
    if hi is not None:
        if f is None or f > hi:
            return False
    return True


def _passes(row: Dict[str, Any], req: ScreenRequest) -> bool:
    g = row.get  # getter g(col) -> value

    # Base filters (min_price / min_turnover / sector) — app.py:402-415.
    price = _f(g("Price"))
    if price is None or price <= 0 or price < req.min_price:
        return False
    turnover = _f(g("ADV_Dollar")) or 0.0
    if turnover < req.min_turnover:
        return False
    sec = g("Sector")
    if not sec:
        return False
    if req.sector and req.sector != "All" and sec != req.sector:
        return False

    # Classification multi-selects (app.py:819-827).
    if req.has_class_filters:
        for key, col in CLASS_MULTI_COLUMNS.items():
            selected = req.class_multi.get(key) or []
            if selected:
                val = g(col)
                if _stringify(val) not in {str(s) for s in selected}:
                    return False

    # Fundamental range filters (app.py:841-850).
    if req.has_fund_filters:
        for stem, (lo, hi) in req.fund_ranges.items():
            if not _in_range(g(FUND_RANGE_COLUMNS[stem]), lo, hi):
                return False
        for stem, lo in req.fund_mins.items():
            if not _in_range(g(FUND_MIN_COLUMNS[stem]), lo, None):
                return False
        # growth / accel presets.
        if req.eps_growth and req.eps_growth in EPS_GROWTH_PRESETS:
            if not EPS_GROWTH_PRESETS[req.eps_growth](g):
                return False
        if req.rev_growth and req.rev_growth in REV_GROWTH_PRESETS:
            if not REV_GROWTH_PRESETS[req.rev_growth](g):
                return False
        if req.eps_accel_filter and req.eps_accel_filter in EPS_ACCEL_PRESETS:
            if not EPS_ACCEL_PRESETS[req.eps_accel_filter](g):
                return False

    # Technical range filters (app.py:908-944).
    if req.has_tech_filters:
        for stem, (lo, hi) in req.tech_ranges.items():
            if not _in_range(g(TECH_RANGE_COLUMNS[stem]), lo, hi):
                return False
        for stem, lo in req.tech_mins.items():
            if not _in_range(g(TECH_MIN_COLUMNS[stem]), lo, None):
                return False
        if req.ma_setup and req.ma_setup in MA_SETUP_PRESETS:
            if not MA_SETUP_PRESETS[req.ma_setup](g):
                return False

    return True


def _stringify(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    # ints from classification columns compare against string selections too.
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# --------------------------------------------------------------------------- #
# sort (app.py:453-458)
# --------------------------------------------------------------------------- #
def _sort(rows: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
    col, asc = SORT_COLUMNS.get(sort_by, ("ADV_Dollar", False))

    def key(r):
        v = _f(r.get(col))
        missing = v is None
        # na_position="last": missing always sorts last for either direction.
        return (missing, v if v is not None else 0.0)

    rows_sorted = sorted(rows, key=key, reverse=not asc)
    # reverse=True flips the missing flag too, so re-pin missing to the end.
    if not asc:
        present = [r for r in rows_sorted if _f(r.get(col)) is not None]
        absent = [r for r in rows if _f(r.get(col)) is None]
        return present + absent
    return rows_sorted


# --------------------------------------------------------------------------- #
# ViewModel shaping
# --------------------------------------------------------------------------- #
RESULT_COLUMNS = [
    "Symbol", "Price", "Change%", "Sector", "Industry", "ADV_Dollar",
    "RS_Rank", "RS_Chg1W", "RS_Chg1M", "RS_Chg3M",
    "MA50", "MA150", "MA200", "PctAbove50", "PctAbove200", "From52H", "From52L",
    "PE", "FwdPE", "OpMargin", "NetMargin", "FCF", "ROIC", "ND_EBITDA",
    "EV_EBITDA", "Analysts", "Target", "PE_vs_Sector", "PE_vs_Industry",
    "EPS_Act", "EPS_TTM", "EPS_NTM", "EPS_FY1", "EPS_FY2",
    "Rev_TTM", "Rev_NTM", "Rev_FY1", "Rev_FY2",
    "G_NTM_TTM", "G_FY2_FY1", "G_TTM_YOY", "G_FQ_YOY",
    "RG_NTM_TTM", "RG_FY2_FY1", "RG_TTM_YOY", "RG_FQ_YOY",
    "PCA_Regime", "Stage_Class", "EPS_Accel", "MA_Screen",
]


def _results_table(rows: List[Dict[str, Any]]) -> dict:
    """id-keyed ranked-rows table (spec §5.1)."""
    return {
        "id": "screener_results",
        "columns": list(RESULT_COLUMNS),
        "rows": [[_cell(r.get(c)) for c in RESULT_COLUMNS] for r in rows],
    }


def _cell(v):
    """JSON-safe cell: NaN/None -> None, numpy/pandas scalars -> python."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        return v
    f = num(v)
    return f if f is not None else _stringify(v)


def _asof(computed) -> Optional[str]:
    asof = getattr(computed, "asof", None)
    if callable(asof):
        try:
            return asof()
        except Exception:  # noqa: BLE001
            return None
    return asof


# --------------------------------------------------------------------------- #
# 7c — page rendering (adr/0002: server-render the original Jinja table)
# --------------------------------------------------------------------------- #
#: Integer stage code (cross_section ``stage``) -> the original display label.
_STAGE_LABELS = {
    1: "Stage 1 Basing", 2: "Stage 2 Uptrend",
    3: "Stage 3 Topping", 4: "Stage 4 Declining",
}
#: Integer ``ma_screen`` code -> display label. MUST match
#: ``computed.classifiers.ma_screen.LABELS`` (the producer's encoding).
_MA_SCREEN_LABELS = {
    0: "Above Both", 1: "Above 200 Below 50",
    2: "Below 200 Above 50", 3: "Below Both",
}
#: Integer ``regime`` code -> display label. MUST match
#: ``computed.classifiers.pca_regime.LABELS`` (0=Declining … 4=Strong Leader).
_REGIME_LABELS = {
    0: "Declining", 1: "Distributing", 2: "Erupting",
    3: "Quiet Uptrend", 4: "Strong Leader",
}


def _filters_dict(req: ScreenRequest) -> Dict[str, Any]:
    """Map the typed :class:`ScreenRequest` back to the flat ``filters`` dict the
    original ``screener.html`` reads (``filters.preset`` / ``filters.pe_min`` /
    ``filters.pca_regime`` list / ``filters.has_*_filters`` …)."""
    def _lo(stem, table):
        return table.get(stem, (None, None))[0]

    def _hi(stem, table):
        return table.get(stem, (None, None))[1]

    f: Dict[str, Any] = {
        "preset": req.preset,
        "min_turnover": req.min_turnover,
        "sector": req.sector,
        "min_price": req.min_price,
        "sort_by": req.sort_by,
        "as_of": req.as_of,
        "eps_growth": req.eps_growth,
        "rev_growth": req.rev_growth,
        "eps_accel_filter": req.eps_accel_filter,
        "ma_setup": req.ma_setup,
        # classification multi-selects (lists)
        "pca_regime": req.class_multi.get("pca_regime") or [],
        "stage_class": req.class_multi.get("stage_class") or [],
        "eps_accel": req.class_multi.get("eps_accel") or [],
        "ma_screen": req.class_multi.get("ma_screen") or [],
        # has_* flags (drive the "advanced filters open" + active tags)
        "has_fund_filters": req.has_fund_filters,
        "has_tech_filters": req.has_tech_filters,
        "has_class_filters": req.has_class_filters,
        # min-only bounds
        "rs_min": req.fund_mins.get("rs"),
        "analysts_min": req.fund_mins.get("analysts"),
        "from52l_min": req.tech_mins.get("from52l"),
    }
    # fundamental ranges -> *_min / *_max keys.
    for stem in FUND_RANGE_COLUMNS:
        f[f"{stem}_min"] = _lo(stem, req.fund_ranges)
        f[f"{stem}_max"] = _hi(stem, req.fund_ranges)
    # technical ranges -> *_min / *_max keys.
    for stem in TECH_RANGE_COLUMNS:
        f[f"{stem}_min"] = _lo(stem, req.tech_ranges)
        f[f"{stem}_max"] = _hi(stem, req.tech_ranges)
    return f


def _page_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """One screener row shaped for the server-rendered template (snake_case keys
    + decoded classification labels)."""
    stage = _int(r.get("Stage_Class"))
    ma_screen = _int(r.get("MA_Screen"))
    regime = _int(r.get("PCA_Regime"))
    return {
        "symbol": r.get("Symbol"),
        "sector": r.get("Sector"),
        "industry": r.get("Industry"),
        "price": _f(r.get("Price")),
        "change": _f(r.get("Change%")),
        "turnover": _f(r.get("ADV_Dollar")),
        "pe": _f(r.get("PE")),
        "fwd_pe": _f(r.get("FwdPE")),
        "pe_vs_sector": _f(r.get("PE_vs_Sector")),
        "pe_vs_industry": _f(r.get("PE_vs_Industry")),
        "eps_act": _f(r.get("EPS_Act")),
        "op_margin": _f(r.get("OpMargin")),
        "net_margin": _f(r.get("NetMargin")),
        "roic": _f(r.get("ROIC")),
        "fcf": _f(r.get("FCF")),
        "nd_ebitda": _f(r.get("ND_EBITDA")),
        "ev_ebitda": _f(r.get("EV_EBITDA")),
        "rs_rank": _f(r.get("RS_Rank")),
        "mansfield_rs": _f(r.get("Mansfield_RS")),
        "analysts": _f(r.get("Analysts")),
        "target": _f(r.get("Target")),
        "pct50": _f(r.get("PctAbove50")),
        "pct200": _f(r.get("PctAbove200")),
        "from52h": _f(r.get("From52H")),
        "from52l": _f(r.get("From52L")),
        # estimate / growth columns (now that estimates_forward + quarterly join in)
        "eps_ttm": _f(r.get("EPS_TTM")),
        "eps_ntm": _f(r.get("EPS_NTM")),
        "eps_fy1": _f(r.get("EPS_FY1")),
        "eps_fy2": _f(r.get("EPS_FY2")),
        "rev_ttm": _f(r.get("Rev_TTM")),
        "rev_ntm": _f(r.get("Rev_NTM")),
        "rev_fy1": _f(r.get("Rev_FY1")),
        "rev_fy2": _f(r.get("Rev_FY2")),
        "g_ntm_ttm": _f(r.get("G_NTM_TTM")),
        "g_fy2_fy1": _f(r.get("G_FY2_FY1")),
        "g_ttm_yoy": _f(r.get("G_TTM_YOY")),
        "g_fq_yoy": _f(r.get("G_FQ_YOY")),
        "rg_ntm_ttm": _f(r.get("RG_NTM_TTM")),
        "rg_fy2_fy1": _f(r.get("RG_FY2_FY1")),
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, ""),
        "ma_screen_label": _MA_SCREEN_LABELS.get(ma_screen, ""),
        "regime_label": _REGIME_LABELS.get(regime, ""),
    }


def _int(v) -> Optional[int]:
    f = _f(v)
    return int(f) if f is not None else None


# --------------------------------------------------------------------------- #
# stage distribution + market regime (port app.py:478-493)
# --------------------------------------------------------------------------- #
_STAGE_PRESETS = {"stage1", "stage2", "stage3", "stage4", "trans12"}


def _stage_distribution(rows: List[Dict[str, Any]]):
    """Per-stage counts over the FULL universe (S1-S4 + unclassified S0).

    Returns ``({stage_id: {count}}, market_regime)`` mirroring the original status
    bar + colored regime banner (app.py:478-493). Only meaningful for the stage
    presets, so callers gate on the preset.
    """
    dist: Dict[int, Dict[str, int]] = {}
    for r in rows:
        s = _int(r.get("Stage_Class")) or 0
        dist.setdefault(s, {"count": 0})["count"] += 1
    total = len(rows)
    qualified = total - dist.get(0, {}).get("count", 0)
    s2 = (dist.get(2, {}).get("count", 0) / qualified * 100) if qualified > 0 else 0
    s4 = (dist.get(4, {}).get("count", 0) / qualified * 100) if qualified > 0 else 0
    if s2 >= 40 and s4 < 10:
        regime = "Healthy Bull"
    elif s2 >= 25 and s4 < 20:
        regime = "Late Bull"
    elif s2 < 20 and s4 >= 30:
        regime = "Bear"
    elif s2 < 25 and s4 >= 20:
        regime = "Bottoming"
    else:
        regime = "Mixed"
    return dist, regime


# --------------------------------------------------------------------------- #
# sector / industry median statistics + hierarchy (port app.py:957-1119)
# --------------------------------------------------------------------------- #
def _med_pos(rows, col, positive_only=False):
    vals = [_f(r.get(col)) for r in rows]
    vals = [v for v in vals if v is not None and (not positive_only or v > 0)]
    return _median(vals)


def _mean(rows, col):
    vals = [_f(r.get(col)) for r in rows if _f(r.get(col)) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


_MEDIAN_COLS = [
    ("median_pe", "PE", True), ("median_fwd_pe", "FwdPE", True),
    ("median_eps", "EPS_Act", False), ("median_eps_ttm", "EPS_TTM", False),
    ("median_eps_ntm", "EPS_NTM", False), ("median_fy1", "EPS_FY1", False),
    ("median_fy2", "EPS_FY2", False), ("median_rev_ttm", "Rev_TTM", False),
    ("median_rev_ntm", "Rev_NTM", False), ("median_op_margin", "OpMargin", False),
    ("median_net_margin", "NetMargin", False), ("median_roic", "ROIC", False),
    ("median_fcf", "FCF", False), ("median_nd_ebitda", "ND_EBITDA", False),
    ("median_ev_ebitda", "EV_EBITDA", True), ("median_rs", "RS_Rank", False),
    ("median_target", "Target", False),
]
_MEAN_COLS = [("median_rs_chg1w", "RS_Chg1W"), ("median_rs_chg1m", "RS_Chg1M"),
              ("median_rs_chg3m", "RS_Chg3M")]


def _group_medians(rows) -> Dict[str, Any]:
    stats = {key: _med_pos(rows, col, pos) for key, col, pos in _MEDIAN_COLS}
    stats.update({key: _mean(rows, col) for key, col in _MEAN_COLS})
    return stats


def _sector_stats(passed_rows, full_rows) -> List[Dict[str, Any]]:
    """Sector→industry→stock hierarchy with sector/industry median stats.

    Medians use the FULL (unfiltered) universe; stock lists use the passed rows
    (port app.py:957-1119). Each sector entry carries its medians + an industry
    breakdown (each with its own medians + stock list) + a flat stock list.
    """
    full_by_sector: Dict[str, List[Dict[str, Any]]] = {}
    for r in full_rows:
        sec = r.get("Sector")
        if sec:
            full_by_sector.setdefault(sec, []).append(r)
    passed_by_sector: Dict[str, List[Dict[str, Any]]] = {}
    for r in passed_rows:
        sec = r.get("Sector")
        if sec:
            passed_by_sector.setdefault(sec, []).append(r)

    sector_totals = {s: len(v) for s, v in full_by_sector.items()}
    n_passed = len(passed_rows) or 1
    out: List[Dict[str, Any]] = []
    for sec, prows in passed_by_sector.items():
        full_group = full_by_sector.get(sec, prows)
        total = sector_totals.get(sec, len(full_group))
        stats: Dict[str, Any] = {
            "sector": sec,
            "count": len(prows),
            "total": total,
            "pct_of_sector": len(prows) / total * 100 if total else 0,
            "pct_of_results": len(prows) / n_passed * 100,
        }
        stats.update(_group_medians(full_group))
        stats["stocks"] = sorted((_page_row(r) for r in prows),
                                 key=lambda x: x.get("rs_rank") or 0, reverse=True)

        # industry breakdown
        full_by_ind: Dict[str, List[Dict[str, Any]]] = {}
        for r in full_group:
            ind = r.get("Industry")
            if ind:
                full_by_ind.setdefault(ind, []).append(r)
        passed_by_ind: Dict[str, List[Dict[str, Any]]] = {}
        for r in prows:
            ind = r.get("Industry")
            if ind:
                passed_by_ind.setdefault(ind, []).append(r)
        industries = []
        for ind, iprows in passed_by_ind.items():
            full_ind = full_by_ind.get(ind, iprows)
            imeds = _group_medians(full_ind)
            ind_pe, sec_pe = imeds.get("median_pe"), stats.get("median_pe")
            imeds["pe_vs_sector"] = (round(ind_pe / sec_pe, 2)
                                     if ind_pe and sec_pe and sec_pe > 0 else None)
            imeds["industry"] = ind
            imeds["count"] = len(iprows)
            imeds["stocks"] = sorted((_page_row(r) for r in iprows),
                                     key=lambda x: x.get("rs_rank") or 0, reverse=True)
            industries.append(imeds)
        industries.sort(key=lambda x: x["count"], reverse=True)
        stats["industries"] = industries
        out.append(stats)
    out.sort(key=lambda x: x["pct_of_sector"], reverse=True)
    return out


def handle_page(req: ScreenRequest, data, computed) -> Dict[str, Any]:
    """Adapt the shared pipeline into the original ``screener.html`` template
    context (adr/0002 §3: same producer, server-rendered presentation).

    Returns the variables the revived template reads: ``filters`` (flat dict),
    ``sectors`` (dropdown), ``results`` (the colored flat table rows),
    ``universe_total`` / ``passed`` (status bar), ``as_of_date``, ``fetch_time``.
    """
    import time

    t0 = time.time()
    res = _pipeline(req, data, computed)
    sectors = sorted({r["Sector"] for r in res.rows if r.get("Sector")})
    results = [_page_row(r) for r in res.passed]

    # Stage-distribution status bar + market-regime banner (stage presets only).
    stage_dist = None
    market_regime = None
    if req.preset in _STAGE_PRESETS and res.rows:
        dist, market_regime = _stage_distribution(res.rows)
        # template iterates stage_dist.items(); keep S1-S4 (+S0 for the qualified math).
        stage_dist = {k: v for k, v in sorted(dist.items())}

    # Sector/industry median statistics + hierarchy (medians over full universe).
    sector_stats = _sector_stats(res.passed, res.rows)

    fetch_ms = (time.time() - t0) * 1000.0
    logger.debug("screener.handle_page passed=%d/%d in %.0fms",
                 len(results), res.universe_total, fetch_ms)
    return {
        "active_section": "screener",
        "filters": _filters_dict(req),
        "sectors": sectors,
        "results": results,
        "sector_stats": sector_stats,
        "stage_dist": stage_dist,
        "market_regime": market_regime,
        "universe_total": res.universe_total,
        "passed": len(results),
        "as_of_date": res.asof,
        "fetch_time": f"{fetch_ms:.0f} ms",
    }
