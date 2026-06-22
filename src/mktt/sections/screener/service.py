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
from collections import OrderedDict
from dataclasses import dataclass, field, fields
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
    "fwdpe_sect": "FwdPE_vs_Sector",   # derived: FwdPE / sector-median FwdPE
    "fwdpe_ind": "FwdPE_vs_Industry",  # derived: FwdPE / industry-median FwdPE
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

#: Trailing-return range filters: query-key stem (= column id) -> joined-row column.
#: Values are TOTAL cumulative trailing returns spliced on from ``data.panel_returns``.
RETURN_RANGE_COLUMNS = {
    "ret1w": "Ret1W", "ret1m": "Ret1M", "ret3m": "Ret3M", "ret6m": "Ret6M",
    "ret12m": "Ret12M", "ret3y": "Ret3Y", "ret5y": "Ret5Y",
}

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

    # trailing-return ranges: {stem: (min, max)} over RETURN_RANGE_COLUMNS
    return_ranges: Dict[str, tuple] = field(default_factory=dict)

    # universe-percentile ranges: {base_id: (pmin, pmax)} over PCTILE_FILTER_IDS
    # (0–100). A passed row is kept iff its {ResultName}_Pctile ∈ [pmin, pmax];
    # null percentile fails when a bound is set.
    pctile_ranges: Dict[str, tuple] = field(default_factory=dict)

    # visible columns (Slice 2): validated, ordered column ids the flat table
    # renders. Empty list == not specified (handle_page falls back to the default
    # visible set). Kept as part of the request identity so a column change is a
    # distinct cache entry / URL.
    cols: List[str] = field(default_factory=list)

    @property
    def has_fund_filters(self) -> bool:
        return bool(self.fund_ranges) or bool(self.fund_mins) or bool(
            self.eps_growth) or bool(self.rev_growth) or bool(self.eps_accel_filter)

    @property
    def has_tech_filters(self) -> bool:
        return bool(self.tech_ranges) or bool(self.tech_mins) or bool(self.ma_setup)

    @property
    def has_return_filters(self) -> bool:
        return bool(self.return_ranges)

    @property
    def has_pctile_filters(self) -> bool:
        return bool(self.pctile_ranges)

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

        return_ranges = {}
        for stem in RETURN_RANGE_COLUMNS:
            lo, hi = _flt(f"{stem}_min"), _flt(f"{stem}_max")
            if lo is not None or hi is not None:
                return_ranges[stem] = (lo, hi)

        # universe-percentile filters: {baseid}_pmin / {baseid}_pmax (0–100) for
        # every base numeric id. Parsed generically (config, not branching).
        pctile_ranges = {}
        for bid in PCTILE_FILTER_IDS:
            lo, hi = _flt(f"{bid}_pmin"), _flt(f"{bid}_pmax")
            if lo is not None or hi is not None:
                pctile_ranges[bid] = (lo, hi)

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
            return_ranges=return_ranges,
            pctile_ranges=pctile_ranges,
            cols=_parse_cols(args.get("cols", "")),
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

    # trans12 preset: attach the per-symbol stage Transition ("prev->current") from
    # history (only when that preset is active — it's the sole consumer).
    if req.preset == "trans12" and hasattr(computed, "stage_transitions"):
        try:
            tmap = computed.stage_transitions().to_dict()
            for r in rows:
                t = tmap.get(r["Symbol"])
                if t:
                    r["Transition"] = t
        except Exception:  # noqa: BLE001
            logger.exception("screener trans12: stage_transitions failed")

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

    # Trailing TOTAL-cumulative returns (1W/1M/3M/6M/12M/3Y/5Y) — one vectorized
    # ``data.panel_returns`` call off the close panel, spliced per row (same shape
    # as panel technicals). Bare stubs without panel_returns skip gracefully.
    if getattr(data, "panel_returns", None) is not None:
        _apply_panel_returns(rows, data, universe, as_of)

    # Median-PE premium over the FULL (unfiltered) universe (app.py:592-639).
    sector_med, industry_med, sector_fwd_med, industry_fwd_med = _median_pe(rows)
    for r in rows:
        r["PE_vs_Sector"] = _pe_premium(r.get("PE"), r.get("Sector"), sector_med)
        r["PE_vs_Industry"] = _pe_premium(r.get("PE"), r.get("Industry"), industry_med)
        r["FwdPE_vs_Sector"] = _pe_premium(
            r.get("FwdPE"), r.get("Sector"), sector_fwd_med)
        r["FwdPE_vs_Industry"] = _pe_premium(
            r.get("FwdPE"), r.get("Industry"), industry_fwd_med)
        # %-above-MA from live Price vs computed MA50/MA200 (only fill when unset,
        # so a precomputed PctAbove* carried on the cross-section still wins).
        if r.get("PctAbove50") is None:
            r["PctAbove50"] = _pct_above(r.get("Price"), r.get("MA50"))
        if r.get("PctAbove200") is None:
            r["PctAbove200"] = _pct_above(r.get("Price"), r.get("MA200"))

    # Universe percentile for every base numeric metric (one vectorized rank per
    # metric over the FULL universe), AFTER returns + cross-sectional (PE_vs_*)
    # attach so those are percentile-able too. Computed on the unfiltered rows so a
    # kept row's percentile is its universe rank (independent of the active filter).
    _attach_percentiles(rows)

    # Apply filters (order mirrors the route: min_price/turnover/sector, then
    # classification, fundamental, technical), then sort.
    passed = _sort([r for r in rows if _passes(r, req)], req.sort_by)
    return _PipelineResult(context, universe_total, rows, passed, asof)


# --------------------------------------------------------------------------- #
# 7b — pipeline result cache (Slice 1 — invalidate-on-data-update)
# --------------------------------------------------------------------------- #
# Repeated/identical screener requests (back-nav, same filters) re-run the whole
# join→enrich→filter→sort recipe every time. We cache the `_PipelineResult` in a
# bounded, process-local LRU keyed on (ScreenRequest identity, cross-section
# freshness version, price-parquet mtime). Both freshness tokens are part of the
# key, so the instant the underlying data changes (a Writer ``upsert`` bumps the
# cross-section version, or the price parquet is rewritten) the key changes and the
# stale entry is never served — a cached view is never staler than the data.
_PIPELINE_CACHE_MAX = 16
#: module-local LRU: ordered {key: _PipelineResult} (oldest first → evict from front).
_PIPELINE_CACHE: "OrderedDict[tuple, _PipelineResult]" = OrderedDict()


def _request_identity(req: ScreenRequest) -> tuple:
    """A hashable, order-stable identity for a :class:`ScreenRequest`.

    ``ScreenRequest`` is frozen but carries dict/list fields (``fund_ranges``,
    ``class_multi`` …) so it is not directly hashable; this freezes every field
    into a deterministic tuple so two equal requests share one cache entry.
    """
    def _freeze(v):
        if isinstance(v, dict):
            return tuple(sorted((k, _freeze(val)) for k, val in v.items()))
        if isinstance(v, (list, tuple)):
            return tuple(_freeze(x) for x in v)
        return v

    return tuple(_freeze(getattr(req, f.name)) for f in fields(req))


def cross_section_version(computed) -> Any:
    """Freshness token for the computed cross-section (bumps on Writer upsert).

    Best-effort: providers/stubs without ``cross_section_version`` contribute a
    constant token (the cache still keys on the request + parquet mtime), so a
    bare stub never crashes the pipeline cache.
    """
    fn = getattr(computed, "cross_section_version", None)
    if callable(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — never let a token read blank the page
            logger.exception("screener cache: cross_section_version failed")
    return None


def price_panel_version(data) -> Any:
    """Freshness token for the price/volume parquet the technicals path reads
    (its mtime). Best-effort, like :func:`cross_section_version`."""
    fn = getattr(data, "price_panel_version", None)
    if callable(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            logger.exception("screener cache: price_panel_version failed")
    return None


def _clear_pipeline_cache() -> None:
    """Drop the process-local pipeline cache (test setup / explicit reset)."""
    _PIPELINE_CACHE.clear()


def _cached_pipeline(req: ScreenRequest, data, computed) -> _PipelineResult:
    """:func:`_pipeline` behind the freshness-keyed LRU result cache.

    Hit  → return a defensive copy of the cached ``_PipelineResult`` WITHOUT
           re-running the heavy work (no ``fundamentals``/``quarterly``/technicals
           fetch, no ``rs_rank_changes`` SQL, no ``_median_pe``).
    Miss → compute via :func:`_pipeline`, store a copy, evict the oldest if full.

    The cache is process-local and bounded; the result is copied on the way in
    and out so a caller mutating its result never corrupts the cached entry.
    """
    key = (_request_identity(req),
           cross_section_version(computed),
           price_panel_version(data))
    hit = _PIPELINE_CACHE.get(key)
    if hit is not None:
        _PIPELINE_CACHE.move_to_end(key)            # LRU: mark most-recently-used
        logger.debug("screener pipeline cache: HIT (entries=%d)", len(_PIPELINE_CACHE))
        return _copy_result(hit)

    logger.debug("screener pipeline cache: MISS (entries=%d)", len(_PIPELINE_CACHE))
    res = _pipeline(req, data, computed)
    _PIPELINE_CACHE[key] = _copy_result(res)
    while len(_PIPELINE_CACHE) > _PIPELINE_CACHE_MAX:
        evicted, _ = _PIPELINE_CACHE.popitem(last=False)  # evict oldest
        logger.debug("screener pipeline cache: evicted oldest entry")
    return res


def _copy_result(res: _PipelineResult) -> _PipelineResult:
    """A shallow-but-safe copy of a ``_PipelineResult`` — new list/dict containers so
    a caller mutating ``passed``/``rows``/``context`` cannot reach the cached copy.
    The row dicts are shared (treated as read-only by callers) but each row is
    re-wrapped so an in-place row mutation also stays out of the cache."""
    return _PipelineResult(
        context=dict(res.context),
        universe_total=res.universe_total,
        rows=[dict(r) for r in res.rows],
        passed=[dict(r) for r in res.passed],
        asof=res.asof,
    )


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
    res = _cached_pipeline(req, data, computed)
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


def _apply_panel_returns(rows, data, universe, as_of=None) -> None:
    """Splice the vectorized trailing returns (``data.panel_returns``) onto rows.

    The whole-universe returns dict (``{sym: {Ret1W..Ret5Y}}``) is computed in one
    vectorized pass off the close panel; here we just update each symbol's row with
    its record (insufficient-history horizons are simply absent → render "—").
    Best-effort: any failure leaves the rows untouched (the page still renders).
    """
    try:
        rets = data.panel_returns(universe, as_of=as_of)
    except Exception:  # noqa: BLE001 — never let a fetch hiccup blank the page
        logger.exception("screener panel returns: vectorized fetch failed")
        return
    if not rets:
        logger.debug("screener panel returns: empty result")
        return
    enriched = 0
    for r in rows:
        rec = rets.get(r["Symbol"])
        if not rec:
            continue
        r.update(rec)
        enriched += 1
    logger.debug("screener panel returns: enriched %d/%d rows", enriched, len(rows))


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
    fwd_by_sector: Dict[str, List[float]] = {}
    fwd_by_industry: Dict[str, List[float]] = {}
    for r in rows:
        sec, ind = r.get("Sector"), r.get("Industry")
        pe = _f(r.get("PE"))
        if pe is not None:
            if sec:
                by_sector.setdefault(sec, []).append(pe)
            if ind:
                by_industry.setdefault(ind, []).append(pe)
        fwd = _f(r.get("FwdPE"))
        if fwd is not None:
            if sec:
                fwd_by_sector.setdefault(sec, []).append(fwd)
            if ind:
                fwd_by_industry.setdefault(ind, []).append(fwd)
    sector_med = {k: _median(v) for k, v in by_sector.items()}
    industry_med = {k: _median(v) for k, v in by_industry.items()}
    sector_fwd_med = {k: _median(v) for k, v in fwd_by_sector.items()}
    industry_fwd_med = {k: _median(v) for k, v in fwd_by_industry.items()}
    return sector_med, industry_med, sector_fwd_med, industry_fwd_med


def _pe_premium(pe, group, medians) -> Optional[float]:
    pe = _f(pe)
    if pe is None or not group:
        return None
    med = medians.get(group)
    if not med or med <= 0:
        return None
    return round(pe / med, 2)


# --------------------------------------------------------------------------- #
# universe percentile for every numeric metric (one vectorized pass per metric)
# --------------------------------------------------------------------------- #
def _attach_percentiles(rows: List[Dict[str, Any]]) -> None:
    """Write a ``{ResultName}_Pctile`` field on every row, over the FULL universe.

    For each base numeric metric (``PCTILE_BASE_IDS``), the percentile is the
    pandas ``Series.rank(pct=True)*100`` of that metric's values across all rows
    (higher value → higher percentile; null value → null percentile; ties share an
    averaged rank). One vectorized rank per metric — NO per-row Python rank loop.

    Called on the full-universe ``rows`` AFTER returns + cross-sectional (PE_vs_*)
    attach, so those metrics are percentile-able too. Idempotent given the same
    rows. Percentile columns are excluded from the base set so there is no
    percentile-of-percentile.
    """
    if not rows:
        return
    import pandas as pd  # local — keep the module import-light for stub tests

    for bid in PCTILE_BASE_IDS:
        result_col = COL_ID_TO_RESULT[bid]
        pctile_col = PCTILE_RESULT_OF[bid]
        # gather the metric values (None where absent / non-numeric).
        vals = [_f(r.get(result_col)) for r in rows]
        s = pd.Series(vals, dtype="float64")
        if s.notna().sum() == 0:
            # nothing to rank — every row gets a null percentile.
            for r in rows:
                r[pctile_col] = None
            continue
        pct = s.rank(pct=True) * 100.0  # NaN ranks stay NaN (null -> null percentile)
        for r, p in zip(rows, pct.tolist()):
            r[pctile_col] = None if (p is None or math.isnan(p)) else float(p)
    logger.debug("screener percentiles: attached %d metrics over %d rows",
                 len(PCTILE_BASE_IDS), len(rows))


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

    # Stage preset (app.py:487-496) — a BASE filter so the table shows only the
    # selected stage, while the stage-distribution banner still counts the full
    # classified universe (handle_page computes it from res.rows, not res.passed).
    # stage1-4 -> Stage_Class == N; trans12 -> a "1->2" Transition (attached in
    # _pipeline from classification_history when that preset is active).
    if req.preset in _STAGE_NUM:
        if _int(g("Stage_Class")) != _STAGE_NUM[req.preset]:
            return False
    elif req.preset == "trans12":
        if _stringify(g("Transition")) != "1->2":
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

    # Trailing-return range filters (ret1w_min/_max .. ret5y_min/_max). Null/insufficient
    # history drops when a bound is set (``_in_range`` semantics, same as the others).
    if req.has_return_filters:
        for stem, (lo, hi) in req.return_ranges.items():
            if not _in_range(g(RETURN_RANGE_COLUMNS[stem]), lo, hi):
                return False

    # Universe-percentile filters ({baseid}_pmin/_pmax over the metric's
    # {ResultName}_Pctile). Null percentile fails when a bound is set (``_in_range``).
    if req.has_pctile_filters:
        for bid, (lo, hi) in req.pctile_ranges.items():
            if not _in_range(g(PCTILE_RESULT_OF[bid]), lo, hi):
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
    "FwdPE_vs_Sector", "FwdPE_vs_Industry",
    "EPS_Act", "EPS_TTM", "EPS_NTM", "EPS_FY1", "EPS_FY2",
    "Rev_TTM", "Rev_NTM", "Rev_FY1", "Rev_FY2",
    "G_NTM_TTM", "G_FY2_FY1", "G_TTM_YOY", "G_FQ_YOY",
    "RG_NTM_TTM", "RG_FY2_FY1", "RG_TTM_YOY", "RG_FQ_YOY",
    "Ret1W", "Ret1M", "Ret3M", "Ret6M", "Ret12M", "Ret3Y", "Ret5Y",
    "PCA_Regime", "Stage_Class", "EPS_Accel", "MA_Screen",
]

#: Canonical column-id vocabulary (Slice 2). The ``cols`` query arg + the
#: ``visible_cols`` context use these readable lowercase ids; each maps 1:1 to a
#: ``RESULT_COLUMNS`` entry. ``screener_data.columns`` carries the RESULT_COLUMNS
#: names; ``COL_ID_TO_RESULT`` is the id↔RESULT_COLUMNS bridge so the client can
#: index the embedded ``rows`` by id. Ids mirror the template's ``data-cid``
#: where one exists; ``symbol`` is the canonical id (the example/spec uses it).
#: id -> RESULT_COLUMNS name (the single source of truth for the id vocabulary).
COL_ID_TO_RESULT = {
    "symbol": "Symbol", "price": "Price", "chg": "Change%",
    "sector": "Sector", "industry": "Industry", "turnover": "ADV_Dollar",
    "rs": "RS_Rank", "rschg1w": "RS_Chg1W", "rschg1m": "RS_Chg1M",
    "rschg3m": "RS_Chg3M",
    "ma50": "MA50", "ma150": "MA150", "ma200": "MA200",
    "pct50": "PctAbove50", "pct200": "PctAbove200",
    "from52h": "From52H", "from52l": "From52L",
    "pe": "PE", "fwdpe": "FwdPE", "opmgn": "OpMargin", "netmgn": "NetMargin",
    "fcf": "FCF", "roic": "ROIC", "ndebitda": "ND_EBITDA", "evebitda": "EV_EBITDA",
    "analysts": "Analysts", "target": "Target",
    "pesect": "PE_vs_Sector", "peind": "PE_vs_Industry",
    "fwdpesect": "FwdPE_vs_Sector", "fwdpeind": "FwdPE_vs_Industry",
    "eps": "EPS_Act", "eps_ttm": "EPS_TTM", "eps_ntm": "EPS_NTM",
    "fy1": "EPS_FY1", "fy2": "EPS_FY2",
    "rev_ttm": "Rev_TTM", "rev_ntm": "Rev_NTM", "rev_fy1": "Rev_FY1",
    "rev_fy2": "Rev_FY2",
    "g_ntm_ttm": "G_NTM_TTM", "g_fy2_fy1": "G_FY2_FY1", "g_ttm_yoy": "G_TTM_YOY",
    "g_fq_yoy": "G_FQ_YOY",
    "rg_ntm_ttm": "RG_NTM_TTM", "rg_fy2_fy1": "RG_FY2_FY1",
    "rg_ttm_yoy": "RG_TTM_YOY", "rg_fq_yoy": "RG_FQ_YOY",
    "ret1w": "Ret1W", "ret1m": "Ret1M", "ret3m": "Ret3M", "ret6m": "Ret6M",
    "ret12m": "Ret12M", "ret3y": "Ret3Y", "ret5y": "Ret5Y",
    "regime": "PCA_Regime", "stage": "Stage_Class", "eps_accel": "EPS_Accel",
    "ma": "MA_Screen",
}
#: RESULT_COLUMNS name -> id (inverse).
RESULT_TO_COL_ID = {v: k for k, v in COL_ID_TO_RESULT.items()}
#: the full set of valid ids (validation set).
RESULT_COL_IDS = list(COL_ID_TO_RESULT.keys())

#: The columns the flat table renders today, in template order — the default
#: visible set when ``cols`` is absent/empty (the ~21 ids screener.html shows).
DEFAULT_VISIBLE_COLS = [
    "symbol", "sector", "industry", "price", "chg", "turnover",
    "rs", "stage", "regime", "ma",
    "pct50", "pct200", "from52h", "from52l",
    "pe", "fwdpe", "pesect", "opmgn", "roic", "evebitda", "target",
]


def _parse_cols(raw) -> List[str]:
    """Parse a ``cols`` arg (comma-separated ids) into a validated, ordered list.

    Drops unknown ids (not in :data:`RESULT_COL_IDS`), preserves the requested
    order, de-dupes. Absent/empty OR all-unknown → :data:`DEFAULT_VISIBLE_COLS`
    (never an empty table).
    """
    if not raw:
        return list(DEFAULT_VISIBLE_COLS)
    valid = set(RESULT_COL_IDS)
    seen: set = set()
    out: List[str] = []
    for tok in str(raw).split(","):
        cid = tok.strip().lower()
        if cid and cid in valid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out or list(DEFAULT_VISIBLE_COLS)


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
    # trailing-return value ranges -> *_min / *_max keys (Performance filter row).
    for stem in RETURN_RANGE_COLUMNS:
        f[f"{stem}_min"] = _lo(stem, req.return_ranges)
        f[f"{stem}_max"] = _hi(stem, req.return_ranges)
    # universe-percentile ranges -> *_pmin / *_pmax keys (every base numeric id).
    for bid in PCTILE_FILTER_IDS:
        f[f"{bid}_pmin"] = _lo(bid, req.pctile_ranges)
        f[f"{bid}_pmax"] = _hi(bid, req.pctile_ranges)
    f["has_return_filters"] = req.has_return_filters
    f["has_pctile_filters"] = req.has_pctile_filters
    return f


def _page_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """One screener row shaped for the server-rendered template (snake_case keys
    + decoded classification labels)."""
    stage = _int(r.get("Stage_Class"))
    ma_screen = _int(r.get("MA_Screen"))
    regime = _int(r.get("PCA_Regime"))
    pr = {
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
        "fwdpe_vs_sector": _f(r.get("FwdPE_vs_Sector")),
        "fwdpe_vs_industry": _f(r.get("FwdPE_vs_Industry")),
        "eps_act": _f(r.get("EPS_Act")),
        "op_margin": _f(r.get("OpMargin")),
        "net_margin": _f(r.get("NetMargin")),
        "roic": _f(r.get("ROIC")),
        "fcf": _f(r.get("FCF")),
        "nd_ebitda": _f(r.get("ND_EBITDA")),
        "ev_ebitda": _f(r.get("EV_EBITDA")),
        "rs_rank": _f(r.get("RS_Rank")),
        "rs_chg1w": _f(r.get("RS_Chg1W")),
        "rs_chg1m": _f(r.get("RS_Chg1M")),
        "rs_chg3m": _f(r.get("RS_Chg3M")),
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
        # trailing total-cumulative returns (1W/1M/3M/6M/12M/3Y/5Y).
        "ret1w": _f(r.get("Ret1W")),
        "ret1m": _f(r.get("Ret1M")),
        "ret3m": _f(r.get("Ret3M")),
        "ret6m": _f(r.get("Ret6M")),
        "ret12m": _f(r.get("Ret12M")),
        "ret3y": _f(r.get("Ret3Y")),
        "ret5y": _f(r.get("Ret5Y")),
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, ""),
        "ma_screen_label": _MA_SCREEN_LABELS.get(ma_screen, ""),
        "regime_label": _REGIME_LABELS.get(regime, ""),
    }
    # Universe-percentile companions ({baseid}p -> the row's {ResultName}_Pctile),
    # table-driven so the flat cell's spec["key"] ({baseid}p) resolves for every
    # base numeric metric (the percentile cols themselves are excluded).
    for bid in PCTILE_BASE_IDS:
        pr[bid + "p"] = _f(r.get(PCTILE_RESULT_OF[bid]))
    return pr


def _int(v) -> Optional[int]:
    f = _f(v)
    return int(f) if f is not None else None


# --------------------------------------------------------------------------- #
# Slice 2 — flat-table cell rendering (server side; the client JS mirrors this)
# --------------------------------------------------------------------------- #
# Per-column render spec for the flat results table, keyed by the column id. Each
# entry: (header label, _page_row key, formatter, alignment, colored). The
# formatter takes the (already _f-coerced) value and returns the display text;
# ``colored`` cells get a positive/negative class from the sign. This is the
# SINGLE source of truth for the flat table's labels/format/coloring — the
# template loops over it and the client re-render JS mirrors it exactly so a
# column toggle looks identical to a server render.
def _fmt_dash(spec):
    def _f2(v):
        return spec % v if v is not None else "—"
    return _f2


def _fmt_turnover(v):
    return ("%.1fM" % (v / 1e6)) if v else "—"


def _fmt_text(v):
    return v if v else "—"


#: id -> dict(label, key, fmt, align, colored, kind)
#: ``kind`` is "num"/"str" for client sort parity with the template's sortTable.
FLAT_COL_SPEC = {
    "symbol":  {"label": "Symbol",    "key": "symbol",       "fmt": _fmt_text,            "align": "left",  "colored": False, "kind": "str"},
    "sector":  {"label": "Sector",    "key": "sector",       "fmt": _fmt_text,            "align": "left",  "colored": False, "kind": "str"},
    "industry":{"label": "Industry",  "key": "industry",     "fmt": _fmt_text,            "align": "left",  "colored": False, "kind": "str"},
    "price":   {"label": "Price",     "key": "price",        "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "chg":     {"label": "Chg%",      "key": "change",       "fmt": _fmt_dash("%+.1f%%"), "align": "right", "colored": True,  "kind": "num"},
    "turnover":{"label": "Turnover",  "key": "turnover",     "fmt": _fmt_turnover,        "align": "right", "colored": False, "kind": "num"},
    "rs":      {"label": "RS",        "key": "rs_rank",      "fmt": _fmt_dash("%.0f"),    "align": "right", "colored": False, "kind": "num"},
    "stage":   {"label": "Stage",     "key": "stage_label",  "fmt": _fmt_text,            "align": "left",  "colored": False, "kind": "str"},
    "regime":  {"label": "PCA Regime","key": "regime_label", "fmt": _fmt_text,            "align": "left",  "colored": False, "kind": "str"},
    "ma":      {"label": "MA Pos",    "key": "ma_screen_label","fmt": _fmt_text,          "align": "left",  "colored": False, "kind": "str"},
    "pct50":   {"label": "%MA50",     "key": "pct50",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "pct200":  {"label": "%MA200",    "key": "pct200",       "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "from52h": {"label": "52H%",      "key": "from52h",      "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": False, "kind": "num"},
    "from52l": {"label": "52L%",      "key": "from52l",      "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": False, "kind": "num"},
    "pe":      {"label": "PE",        "key": "pe",           "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "fwdpe":   {"label": "Fwd PE",    "key": "fwd_pe",       "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "pesect":  {"label": "PE/Sec",    "key": "pe_vs_sector", "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "peind":   {"label": "PE/Ind",    "key": "pe_vs_industry","fmt": _fmt_dash("%.2f"),   "align": "right", "colored": False, "kind": "num"},
    "fwdpesect":{"label": "FwdPE/Sec", "key": "fwdpe_vs_sector","fmt": _fmt_dash("%.2f"),  "align": "right", "colored": False, "kind": "num"},
    "fwdpeind":{"label": "FwdPE/Ind", "key": "fwdpe_vs_industry","fmt": _fmt_dash("%.2f"), "align": "right", "colored": False, "kind": "num"},
    "opmgn":   {"label": "OpMgn%",    "key": "op_margin",    "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "netmgn":  {"label": "NetMgn%",   "key": "net_margin",   "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "roic":    {"label": "ROIC%",     "key": "roic",         "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "fcf":     {"label": "FCF",       "key": "fcf",          "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "ndebitda":{"label": "ND/EBITDA", "key": "nd_ebitda",    "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "evebitda":{"label": "EV/EBITDA", "key": "ev_ebitda",    "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "analysts":{"label": "Analysts",  "key": "analysts",     "fmt": _fmt_dash("%.0f"),    "align": "right", "colored": False, "kind": "num"},
    "target":  {"label": "Target",    "key": "target",       "fmt": _fmt_dash("%.0f"),    "align": "right", "colored": False, "kind": "num"},
    "rschg1w": {"label": "RS 1W",     "key": "rs_chg1w",     "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "rschg1m": {"label": "RS 1M",     "key": "rs_chg1m",     "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "rschg3m": {"label": "RS 3M",     "key": "rs_chg3m",     "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "eps":     {"label": "EPS",       "key": "eps_act",      "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "eps_ttm": {"label": "EPS TTM",   "key": "eps_ttm",      "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "eps_ntm": {"label": "EPS NTM",   "key": "eps_ntm",      "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "fy1":     {"label": "FY1",       "key": "eps_fy1",      "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "fy2":     {"label": "FY2",       "key": "eps_fy2",      "fmt": _fmt_dash("%.2f"),    "align": "right", "colored": False, "kind": "num"},
    "rev_ttm": {"label": "Rev TTM",   "key": "rev_ttm",      "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "rev_ntm": {"label": "Rev NTM",   "key": "rev_ntm",      "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "rev_fy1": {"label": "Rev FY1",   "key": "rev_fy1",      "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "rev_fy2": {"label": "Rev FY2",   "key": "rev_fy2",      "fmt": _fmt_dash("%.1f"),    "align": "right", "colored": False, "kind": "num"},
    "g_ntm_ttm":{"label": "G NTM/TTM","key": "g_ntm_ttm",    "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "g_fy2_fy1":{"label": "G FY2/FY1","key": "g_fy2_fy1",    "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "g_ttm_yoy":{"label": "G TTM YoY","key": "g_ttm_yoy",    "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "g_fq_yoy": {"label": "G FQ YoY", "key": "g_fq_yoy",     "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "rg_ntm_ttm":{"label": "RG NTM/TTM","key":"rg_ntm_ttm",  "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "rg_fy2_fy1":{"label": "RG FY2/FY1","key":"rg_fy2_fy1",  "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret1w":   {"label": "1W %",      "key": "ret1w",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret1m":   {"label": "1M %",      "key": "ret1m",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret3m":   {"label": "3M %",      "key": "ret3m",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret6m":   {"label": "6M %",      "key": "ret6m",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret12m":  {"label": "12M %",     "key": "ret12m",       "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret3y":   {"label": "3Y %",      "key": "ret3y",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
    "ret5y":   {"label": "5Y %",      "key": "ret5y",        "fmt": _fmt_dash("%+.1f"),   "align": "right", "colored": True,  "kind": "num"},
}


# --------------------------------------------------------------------------- #
# Slice 2 — universe percentile companion columns (table-driven, no hand entries)
# --------------------------------------------------------------------------- #
def _fmt_pctile(v):
    """Percentile cell: ``P82`` (rounded), null -> dash."""
    return ("P%.0f" % v) if v is not None else "—"


#: Every BASE numeric metric id (FLAT_COL_SPEC kind=="num" BEFORE percentile cols
#: are appended) — the set that gains a ``%ile`` companion + percentile filter.
#: Snapshot the keys NOW so the percentile cols we append below never recurse
#: (no percentile-of-percentile). Incl. the 7 returns from Slice 1.
PCTILE_BASE_IDS = [cid for cid, spec in FLAT_COL_SPEC.items() if spec["kind"] == "num"]

#: Generate one percentile companion per base numeric id, table-driven:
#:   id        = ``{baseid}p``                (e.g. pe -> pep, ret3m -> ret3mp)
#:   RESULT    = ``{ResultName}_Pctile``      (PE -> PE_Pctile)
#:   label     = base label + " %ile"
#:   row field = the RESULT name; flat ``key`` is the lowercase id
#:   fmt       = P%.0f via _fmt_pctile ; align right ; colored False ; kind num
for _bid in PCTILE_BASE_IDS:
    _base_result = COL_ID_TO_RESULT[_bid]
    _pid = _bid + "p"
    _presult = f"{_base_result}_Pctile"
    RESULT_COLUMNS.append(_presult)
    COL_ID_TO_RESULT[_pid] = _presult
    FLAT_COL_SPEC[_pid] = {
        "label": FLAT_COL_SPEC[_bid]["label"] + " %ile",
        "key": _pid,
        "fmt": _fmt_pctile,
        "align": "right",
        "colored": False,
        "kind": "num",
    }

#: Re-derive the id↔RESULT bridges now that the percentile cols are registered.
RESULT_TO_COL_ID = {v: k for k, v in COL_ID_TO_RESULT.items()}
RESULT_COL_IDS = list(COL_ID_TO_RESULT.keys())

#: Percentile filter ids = the base numeric ids (filters are ``{baseid}_pmin/_pmax``).
PCTILE_FILTER_IDS = list(PCTILE_BASE_IDS)

#: base id -> the ``{ResultName}_Pctile`` row field the filter reads.
PCTILE_RESULT_OF = {bid: f"{COL_ID_TO_RESULT[bid]}_Pctile" for bid in PCTILE_BASE_IDS}

#: Form specs (Slice 3) — drive the data-driven Performance + Percentile filter rows
#: in screener.html. RETURN row = value (_min/_max) + percentile (_pmin/_pmax) per
#: horizon; PERCENTILE row = _pmin/_pmax for every NON-return base numeric metric
#: (returns already carry their %ile inputs in the Performance row). Labels from spec.
RETURN_FILTER_SPECS = [
    {"stem": sid, "label": FLAT_COL_SPEC[sid]["label"].replace(" %", "")}
    for sid in RETURN_RANGE_COLUMNS
]
PCTILE_FILTER_SPECS = [
    {"stem": bid, "label": FLAT_COL_SPEC[bid]["label"]}
    for bid in PCTILE_BASE_IDS if bid not in RETURN_RANGE_COLUMNS
]


def _stage_color(stage) -> str:
    """Stage-cell inline color (template parity: S2 green, S4 red, S1 amber, S3 orange)."""
    return {
        2: "color:var(--phosphor-bright,var(--green));",
        4: "color:var(--red,#ff3333);",
        1: "color:var(--amber,#ffb000);",
        3: "color:var(--orange,#ff6e27);",
    }.get(stage, "")


def _colored_class(v) -> str:
    f = _f(v)
    if f is None or f == 0:
        return ""
    return "positive" if f > 0 else "negative"


def _flat_cell(pr: Dict[str, Any], cid: str) -> Dict[str, Any]:
    """Render one flat-table cell for column ``cid`` from a ``_page_row`` dict.

    Returns ``{text, cls, align, style}`` — the exact label/format/coloring the
    template emits today, factored so server-Jinja and the client re-render share
    one definition. Unknown ids degrade to a dash cell (never raises)."""
    spec = FLAT_COL_SPEC.get(cid)
    if spec is None:
        return {"text": "—", "cls": "", "align": "right", "style": ""}
    raw = pr.get(spec["key"])
    text = spec["fmt"](raw)
    cls = _colored_class(raw) if spec["colored"] else ""
    style = _stage_color(pr.get("stage")) if cid == "stage" else ""
    return {"text": text, "cls": cls, "align": spec["align"], "style": style}


#: JS-friendly format token per column id (mirrors the python ``fmt`` so the client
#: re-render produces byte-identical text). Tokens the client interprets:
#:   "f2"=%.2f  "f1"=%.1f  "f0"=%.0f  "pct1"=%+.1f%%  "s1"=%+.1f
#:   "turnover"=%.1fM(/1e6)  "text"=string-or-dash  "label"=decoded label (text)
_FMT_TOKEN = {
    _fmt_text: "text", _fmt_turnover: "turnover", _fmt_pctile: "pctile",
}
_FMT_DASH_TOKEN = {"%.2f": "f2", "%.1f": "f1", "%.0f": "f0",
                   "%+.1f%%": "pct1", "%+.1f": "s1"}


def _fmt_token(cid: str) -> str:
    """The client-side format token for a column id (mirror of its python fmt)."""
    spec = FLAT_COL_SPEC.get(cid, {})
    fmt = spec.get("fmt")
    # label columns (stage/regime/ma) read a decoded *_label off the data, but the
    # embedded SCREENER_DATA carries the RAW code — so the client cannot reconstruct
    # the label from the number. Mark them so the client renders the raw value's
    # decoded label via the shared LABEL maps embedded below.
    if cid in ("stage", "regime", "ma"):
        return {"stage": "stage_label", "regime": "regime_label",
                "ma": "ma_label"}[cid]
    if fmt in _FMT_TOKEN:
        return _FMT_TOKEN[fmt]
    # _fmt_dash closures: identify by formatting a probe value.
    try:
        probe = fmt(1.0)
        for spec_str, tok in _FMT_DASH_TOKEN.items():
            if (spec_str % 1.0) == probe:
                return tok
    except Exception:  # noqa: BLE001
        pass
    return "text"


def flat_col_spec_js() -> Dict[str, Any]:
    """A JSON-serializable mirror of :data:`FLAT_COL_SPEC` for the client re-render.

    Per id: ``{label, result_col, fmt, align, colored, kind}`` where ``result_col``
    is the RESULT_COLUMNS name (the index into SCREENER_DATA.rows) and ``fmt`` is a
    token :func:`_fmt_token` the client maps to the same formatting python applies.
    Plus the decoded-label maps (stage/regime/ma) so label columns render off the
    raw codes carried in SCREENER_DATA."""
    cols = {}
    for cid, spec in FLAT_COL_SPEC.items():
        cols[cid] = {
            "label": spec["label"],
            "result_col": COL_ID_TO_RESULT.get(cid),
            "fmt": _fmt_token(cid),
            "align": spec["align"],
            "colored": spec["colored"],
            "kind": spec["kind"],
        }
    return {
        "cols": cols,
        "stage_labels": {str(k): v for k, v in _STAGE_LABELS.items()},
        "regime_labels": {str(k): v for k, v in _REGIME_LABELS.items()},
        "ma_labels": {str(k): v for k, v in _MA_SCREEN_LABELS.items()},
    }


def _flat_table(page_rows: List[Dict[str, Any]], visible_cols: List[str]) -> Dict[str, Any]:
    """Build the server-render payload for the flat table restricted to
    ``visible_cols``: ordered headers + one rendered cell per visible column per
    row. ``symbol`` is carried per-row for the row-level click handler."""
    headers = [{"cid": cid,
                "label": FLAT_COL_SPEC.get(cid, {}).get("label", cid),
                "align": FLAT_COL_SPEC.get(cid, {}).get("align", "right"),
                "kind": FLAT_COL_SPEC.get(cid, {}).get("kind", "str")}
               for cid in visible_cols]
    rows = []
    for pr in page_rows:
        rows.append({
            "symbol": pr.get("symbol"),
            "cells": [_flat_cell(pr, cid) for cid in visible_cols],
        })
    return {"columns": list(visible_cols), "headers": headers, "rows": rows}


def _screener_data(passed_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The FULL result embedded for the client (all RESULT_COLUMNS × all passed
    rows, full precision). Independent of ``visible_cols`` — powers instant
    client-side column toggle / sort / keep-alive without a server round-trip.

    ``col_ids`` and ``col_id_of`` let the client map a visible-column id to its
    index in each ``rows`` tuple. Reuses :func:`_results_table` (the VM table
    shape) so the embedded numbers are byte-identical to the JSON API's."""
    table = _results_table(passed_rows)
    return {
        "columns": table["columns"],
        "rows": table["rows"],
        "col_id_of": {RESULT_TO_COL_ID[c]: i
                      for i, c in enumerate(table["columns"])
                      if c in RESULT_TO_COL_ID},
    }


# --------------------------------------------------------------------------- #
# stage distribution + market regime (port app.py:478-493)
# --------------------------------------------------------------------------- #
_STAGE_PRESETS = {"stage1", "stage2", "stage3", "stage4", "trans12"}
#: Stage-preset -> Stage_Class value the table filters to (app.py:487-494).
_STAGE_NUM = {"stage1": 1, "stage2": 2, "stage3": 3, "stage4": 4}


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

    Medians (``median_rs``, ``median_pe``, …) are computed over the **FULL universe**
    per sector / industry — NOT the passed/filtered subset — so they are a stable
    baseline the user can compare their filtered selection against (the medians stay
    put regardless of the active filter). The industry-vs-sector ratio
    (``pe_vs_sector``) is likewise full-universe over full-universe.

    Counts and the listed ``stocks`` remain the filtered selection: ``count`` =
    passed in the sector/industry, ``total`` = full-universe symbols in the sector,
    ``pct_of_sector`` = count/total, and only sectors/industries that have passed
    stocks appear. (The per-stock ``PE_vs_Sector`` premium is a SEPARATE,
    full-universe figure computed in ``_pipeline`` — unchanged.)
    """
    full_by_sector: Dict[str, List[Dict[str, Any]]] = {}
    full_by_industry: Dict[str, List[Dict[str, Any]]] = {}
    for r in full_rows:
        sec = r.get("Sector")
        if sec:
            full_by_sector.setdefault(sec, []).append(r)
        ind = r.get("Industry")
        if ind:
            full_by_industry.setdefault(ind, []).append(r)
    passed_by_sector: Dict[str, List[Dict[str, Any]]] = {}
    for r in passed_rows:
        sec = r.get("Sector")
        if sec:
            passed_by_sector.setdefault(sec, []).append(r)

    sector_totals = {s: len(v) for s, v in full_by_sector.items()}
    n_passed = len(passed_rows) or 1
    out: List[Dict[str, Any]] = []
    for sec, prows in passed_by_sector.items():
        total = sector_totals.get(sec, len(prows))
        stats: Dict[str, Any] = {
            "sector": sec,
            "count": len(prows),
            "total": total,
            "pct_of_sector": len(prows) / total * 100 if total else 0,
            "pct_of_results": len(prows) / n_passed * 100,
        }
        # medians over the FULL universe in this sector (stable baseline).
        stats.update(_group_medians(full_by_sector.get(sec, prows)))
        stats["stocks"] = sorted((_page_row(r) for r in prows),
                                 key=lambda x: x.get("rs_rank") or 0, reverse=True)

        # industry breakdown — counts/stocks from passed, medians over the full
        # universe per industry.
        passed_by_ind: Dict[str, List[Dict[str, Any]]] = {}
        for r in prows:
            ind = r.get("Industry")
            if ind:
                passed_by_ind.setdefault(ind, []).append(r)
        industries = []
        for ind, iprows in passed_by_ind.items():
            imeds = _group_medians(full_by_industry.get(ind, iprows))
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


# --------------------------------------------------------------------------- #
# sector map — sector × dimension composition (revived "Map" view)
# port of app.py /api/sector_map (_sector_map_impl)
# --------------------------------------------------------------------------- #
#: Map dimension key -> (display label, ordered categories). The category order
#: is the matrix column order; labels mirror the original cutoff buckets.
_MAP_DIMENSIONS = {
    "pca_regime":   ("PCA Regime",
                     ["Strong Leader", "Quiet Uptrend", "Erupting", "Distributing", "Declining"]),
    "stage":        ("Weinstein Stage",
                     ["Stage 2 Uptrend", "Stage 1 Basing", "Stage 3 Topping", "Stage 4 Declining"]),
    "eps_momentum": ("EPS Momentum", ["Accelerating", "Decelerating"]),
    "eps_growth":   ("EPS Growth", ["Growing", "Flat", "Declining"]),
    "rs_bucket":    ("RS Rank Bucket", ["RS 80+", "RS 60-80", "RS 40-60", "RS 20-40", "RS 0-20"]),
    "rs_momentum":  ("RS Momentum (1M)", ["Improving", "Stable", "Deteriorating"]),
    "pe_vs_sector": ("PE vs Sector",
                     ["Deep Discount", "Discount", "Fair", "Premium", "High Premium", "No PE"]),
}


def _map_category(dim: str, row: Dict[str, Any]) -> Optional[str]:
    """The category a row falls into for a Map ``dim`` (port of the bucket logic in
    app.py ``_sector_map_impl``). ``None`` excludes the row from that dimension."""
    if dim == "pca_regime":
        v = _int(row.get("PCA_Regime"))
        return _REGIME_LABELS.get(v) if v is not None else None
    if dim == "stage":
        v = _int(row.get("Stage_Class"))
        return _STAGE_LABELS.get(v) if v is not None else None
    if dim == "eps_momentum":
        v = _f(row.get("EPS_Accel"))            # acceleration = (FY2-FY1) − (FY1-TTM)
        return None if v is None else ("Accelerating" if v > 0 else "Decelerating")
    if dim == "eps_growth":
        fy1, ttm = _f(row.get("EPS_FY1")), _f(row.get("EPS_Act"))
        if fy1 is None or ttm is None:
            return None
        return "Growing" if fy1 > ttm else "Declining" if fy1 < ttm else "Flat"
    if dim == "rs_bucket":
        v = _f(row.get("RS_Rank"))
        if v is None:
            return None
        return ("RS 80+" if v >= 80 else "RS 60-80" if v >= 60 else "RS 40-60"
                if v >= 40 else "RS 20-40" if v >= 20 else "RS 0-20")
    if dim == "rs_momentum":
        v = _f(row.get("RS_Chg1M"))
        if v is None:
            return None
        return "Improving" if v > 5 else "Stable" if v > -5 else "Deteriorating"
    if dim == "pe_vs_sector":
        v = _f(row.get("PE_vs_Sector"))         # row premium = PE / sector-median PE
        if v is None or v <= 0:
            return "No PE"
        return ("Deep Discount" if v < 0.7 else "Discount" if v < 0.9 else "Fair"
                if v < 1.1 else "Premium" if v < 1.3 else "High Premium")
    return None


def _sector_map_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sector × dimension composition for the "Map" view (port of /api/sector_map).

    For every dimension, returns a per-(sector, category) ``summary`` count list +
    the ``overall`` category distribution — shaped exactly like the original AJAX
    response so the original renderer consumes it unchanged. Computed over the
    **passed** rows (the Map reflects the active filter) and keyed by dimension so
    the selector switches client-side with no extra round-trip.
    """
    out: Dict[str, Any] = {}
    for dim, (label, categories) in _MAP_DIMENSIONS.items():
        counts: Dict[tuple, int] = {}
        overall: Dict[str, int] = {}
        total = 0
        for r in rows:
            sec = r.get("Sector")
            if not sec:
                continue
            cat = _map_category(dim, r)
            if cat is None:
                continue
            counts[(sec, cat)] = counts.get((sec, cat), 0) + 1
            overall[cat] = overall.get(cat, 0) + 1
            total += 1
        out[dim] = {
            "dimension": dim,
            "label": label,
            "categories": categories,
            "summary": [{"sector": s, "dimension": c, "count": n}
                        for (s, c), n in counts.items()],
            "overall": overall,
            "total_stocks": total,
        }
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
    res = _cached_pipeline(req, data, computed)
    sectors = sorted({r["Sector"] for r in res.rows if r.get("Sector")})
    results = [_page_row(r) for r in res.passed]

    # Selected columns (Slice 2): the validated, ordered visible set. ``req.cols``
    # is already resolved (falls back to DEFAULT_VISIBLE_COLS when absent/empty).
    visible_cols = req.cols or list(DEFAULT_VISIBLE_COLS)
    flat_table = _flat_table(results, visible_cols)
    # Full picker vocabulary (ordered, id + label) — server-provided so the client
    # column picker no longer scans the DOM to discover columns.
    all_cols = [{"cid": RESULT_TO_COL_ID[c],
                 "label": FLAT_COL_SPEC.get(RESULT_TO_COL_ID[c], {}).get(
                     "label", RESULT_TO_COL_ID[c])}
                for c in RESULT_COLUMNS if c in RESULT_TO_COL_ID]
    # The FULL result embedded once for the client (all columns, full precision),
    # independent of visible_cols — powers client toggle/sort/keep-alive.
    screener_data = _screener_data(res.passed)

    # Stage-distribution status bar + market-regime banner (stage presets only).
    stage_dist = None
    market_regime = None
    if req.preset in _STAGE_PRESETS and res.rows:
        dist, market_regime = _stage_distribution(res.rows)
        # template iterates stage_dist.items(); keep S1-S4 (+S0 for the qualified math).
        stage_dist = {k: v for k, v in sorted(dist.items())}

    # Sector/industry median statistics + hierarchy (medians over the PASSED set,
    # original parity — see _sector_stats). res.rows supplies full-universe counts.
    sector_stats = _sector_stats(res.passed, res.rows)

    # Sector × dimension composition for the "Map" view (regime/stage/eps/rs/pe),
    # computed over the passed set and embedded for client-side dimension switching.
    sector_map = _sector_map_summary(res.passed)

    fetch_ms = (time.time() - t0) * 1000.0
    logger.debug("screener.handle_page passed=%d/%d in %.0fms",
                 len(results), res.universe_total, fetch_ms)
    return {
        "active_section": "screener",
        "filters": _filters_dict(req),
        "return_filter_specs": RETURN_FILTER_SPECS,
        "pctile_filter_specs": PCTILE_FILTER_SPECS,
        "sectors": sectors,
        "results": results,
        "visible_cols": visible_cols,
        "all_cols": all_cols,
        "flat_col_spec": flat_col_spec_js(),
        "flat_table": flat_table,
        "screener_data": screener_data,
        "sector_stats": sector_stats,
        "sector_map": sector_map,
        "stage_dist": stage_dist,
        "market_regime": market_regime,
        "universe_total": res.universe_total,
        "passed": len(results),
        "as_of_date": res.asof,
        "fetch_time": f"{fetch_ms:.0f} ms",
    }
