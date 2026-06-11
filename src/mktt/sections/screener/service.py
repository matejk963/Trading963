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
    "change": ("Change%", False),
    "rs": ("RS_Rank", False),
    "mansfield": ("Mansfield_RS", False),
    "dist_high": ("From52H", True),
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
    context = {
        "preset": req.preset,
        "sector": req.sector,
        "sort_by": req.sort_by,
        "min_turnover": req.min_turnover,
        "min_price": req.min_price,
    }
    logger.debug("screener.handle preset=%s sector=%s sort=%s", req.preset,
                 req.sector, req.sort_by)

    cross = computed.cross_section()
    universe = _index_ids(cross)
    universe_total = len(universe)

    if universe_total == 0:
        return vm(status="empty", message="No computed universe available.",
                  title="Screener", context=context,
                  readouts={"universe_total": 0, "passed": 0})

    funds = data.fundamentals(universe)

    # Build the joined rows (one dict per symbol).
    rows = _join(cross, funds)

    # Median-PE premium over the FULL (unfiltered) universe (app.py:592-639).
    sector_med, industry_med = _median_pe(rows)
    for r in rows:
        r["PE_vs_Sector"] = _pe_premium(r.get("PE"), r.get("Sector"), sector_med)
        r["PE_vs_Industry"] = _pe_premium(r.get("PE"), r.get("Industry"), industry_med)

    # Apply filters (order mirrors the route: min_price/turnover/sector, then
    # classification, fundamental, technical).
    passed = [r for r in rows if _passes(r, req)]

    asof = _asof(computed)
    passed = _sort(passed, req.sort_by)

    if not passed:
        return vm(status="empty", message="No symbols passed the filters.",
                  asof=asof, title="Screener", context=context,
                  readouts={"universe_total": universe_total, "passed": 0})

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


def _join(cross, funds) -> List[Dict[str, Any]]:
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
        # Forward EPS (FY1) for FwdPE, if estimates were attached.
        fy1_eps = frec.get("fy1_eps_mean", frec.get("fy1_eps_smart"))
        # Derive PE / FwdPE (app.py:556-559).
        price = _f(row.get("Price"))
        eps_act = _f(row.get("EPS_Act"))
        row["PE"] = (price / eps_act) if (price is not None and eps_act
                                          and eps_act > 0) else None
        fy1 = _f(fy1_eps)
        row["FwdPE"] = (price / fy1) if (price is not None and fy1
                                         and fy1 > 0) else None
        out.append(row)
    return out


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
