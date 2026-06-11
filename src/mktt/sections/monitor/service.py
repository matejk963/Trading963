"""Monitor section — thin manager (per-security view + lists; spec §4.2, §5, §8).

The Monitor is the **bottom-up** entry to the funnel: a single name, walked from
its live technicals up through fundamentals, stage/RS evolution and the shared
watchlist. Unlike the Screener (which reads the *precomputed* CrossSection), the
Monitor calls the **kernel LIVE for one symbol** (spec §4.2, §5.2).

``monitor.handle(req, data, computed, kernel, lists)`` is the recipe —

1. ``data.time_series([symbol])`` + ``data.time_series(["SPY"])`` (benchmark) ->
   run the kernel pipeline LIVE: ``indicators.compute`` ->
   ``relative_strength.compute(panel, bench)`` -> ``relative_strength.rank`` ->
   ``stage.compute``. ``rs_rank`` is **null** for one symbol (cross-sectional —
   spec §5.2); the headline rank is read from ``computed.cross_section`` instead.
2. shape ``figures=[price + MA overlay]`` from the enriched panel,
3. ``data.fundamentals([symbol])`` -> ``tables=[fundamentals]`` + ``sector``,
4. ``computed.history(symbol)`` -> ``figures/table=[stage / RS evolution]``,
5. ``meta.readouts={stage, rs_rank, sector}``.

A POST multi-symbol request (Monitor's large-list input — spec §4.1) emits a
watchlist-style ``monitor_list`` table over the symbols (rs_rank read from the
cross-section, mirroring ``app.py:1462-1559``).

Watchlist endpoints (``watchlist_members`` / ``watchlist_add`` /
``watchlist_remove``) proxy to the injected ``lists`` store — **Monitor reads,
Screener writes; neither imports the other** (spec §4.6). No ``Screener`` import.

Holds **no** formulas (kernel) and **no** fetch logic (providers) — just the
wiring, and is dependency-injected (spec §8): ``handle`` receives ``data`` /
``computed`` / ``kernel`` / ``lists`` so tests pass stubs — no Flask, no DB, no
network.

Parity target: the per-symbol API routes (``app.py`` chart / fundamentals /
rolling_12m / sales_ttm / eps_ttm / revisions) + the watchlist
(``app.py:1462-1559``). Parity = the NUMBERS (price+MA overlay, rs_rank, sector),
wrapped in the NEW ViewModel envelope.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from viewmodel import num, vm

logger = logging.getLogger("mktt.sections.monitor")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

#: Benchmark id the kernel's RelativeStrength runs against (FLAG-1 — SPY is just
#: another ``time_series`` id, tagged ``benchmark`` in the registry).
BENCHMARK_ID = "SPY"

#: Default watchlist name (the single shared list before multi-list UI).
DEFAULT_LIST = "default"

#: Fundamentals snake_case column -> (display metric, formatter kind) for the
#: per-symbol fundamentals table. Mirrors the fields ``app.py`` fundamentals/
#: watchlist routes surface.
_FUND_ROWS = [
    ("price_close", "Price", "num"),
    ("eps_actual", "EPS (Act)", "num"),
    ("operating_margin", "Op Margin %", "num"),
    ("net_margin", "Net Margin %", "num"),
    ("roic", "ROIC %", "num"),
    ("free_cash_flow", "Free Cash Flow", "money"),
    ("ev_to_ebitda", "EV/EBITDA", "num"),
    ("net_debt_to_ebitda", "Net Debt/EBITDA", "num"),
    ("num_analysts", "# Analysts", "num"),
    ("price_target_mean", "Price Target", "num"),
    ("gics_sector", "Sector", "str"),
    ("gics_industry", "Industry", "str"),
]

#: Multi-symbol (watchlist-style) table columns (port of app.py watchlist rows).
_LIST_COLUMNS = [
    "Symbol", "Price", "Sector", "Industry", "PE", "RS_Rank", "Analysts",
]


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MonitorRequest:
    """Typed Monitor request (built by the blueprint — spec §4.1).

    Carries one *or more* symbols: ``GET /chart/<symbol>`` builds a single-symbol
    request; ``POST /api/monitor`` with a ``sym`` list builds a multi-symbol one
    (Monitor's large-input POST path — spec §4.1). The section is Flask-free and
    method-agnostic; parsing lives in the classmethods.
    """

    symbols: List[str] = field(default_factory=list)

    @property
    def symbol(self) -> Optional[str]:
        """The primary (first) symbol, or ``None`` when the request is empty."""
        return self.symbols[0] if self.symbols else None

    @property
    def is_multi(self) -> bool:
        return len(self.symbols) > 1

    @classmethod
    def from_symbol(cls, symbol: str) -> "MonitorRequest":
        """Single-symbol request from a path arg (``/chart/<symbol>``)."""
        sym = (symbol or "").strip().upper()
        return cls(symbols=[sym] if sym else [])

    @classmethod
    def from_form(cls, args) -> "MonitorRequest":
        """Multi-symbol request from ``?sym=X&sym=Y`` (or a posted ``sym`` list).

        ``args`` supports ``getlist(key)`` (Flask ``MultiDict`` or the test
        ``FakeArgs``). Empty -> an empty request (``status="error"`` downstream).
        """
        getlist = getattr(args, "getlist", None)
        if getlist is not None:
            raw = list(getlist("sym"))
        else:  # plain dict / mapping fallback
            v = args.get("sym")
            raw = list(v) if isinstance(v, (list, tuple)) else ([v] if v else [])
        syms = [s.strip().upper() for s in raw if s and s.strip()]
        # dedupe preserving order.
        seen, out = set(), []
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return cls(symbols=out)


# --------------------------------------------------------------------------- #
# handle (the recipe)
# --------------------------------------------------------------------------- #
def handle(req: MonitorRequest, data, computed, kernel, lists=None) -> dict:
    """Live single-symbol kernel + history + fundamentals -> ViewModel.

    Parameters
    ----------
    req:
        The typed :class:`MonitorRequest`.
    data:
        ``DataSource`` (or stub): ``time_series(ids, …)`` + ``fundamentals(ids)``.
    computed:
        ``ComputedStore`` (or stub): ``cross_section(filters)`` (for the stored
        ``rs_rank`` / ``regime`` a single live symbol cannot rank) and
        ``history(symbol)`` (stage/RS evolution).
    kernel:
        The kernel facade exposing ``indicators`` / ``relative_strength`` /
        ``stage`` (the live enrichment pipeline — spec §5.2).
    lists:
        ``ListStore`` (or stub). Unused by the chart view; carried so the section
        is wired with all its providers (watchlist endpoints use it directly).
    """
    if not req.symbol:
        return vm(status="error", message="No symbol supplied.", title="Monitor",
                  context={"symbol": None})

    if req.is_multi:
        return _handle_multi(req, data, computed)

    symbol = req.symbol
    context = {"symbol": symbol}
    logger.debug("monitor.handle symbol=%s", symbol)

    panel = data.time_series([symbol], fields=("close", "high", "low", "volume"))
    if panel is None or len(panel) == 0:
        return vm(status="empty", message=f"No price data for {symbol}.",
                  title=f"Monitor — {symbol}", context=context,
                  readouts={"stage": None, "rs_rank": None, "sector": None})

    enriched = _run_kernel(panel, data, kernel)

    figures: List[dict] = [_price_figure(symbol, enriched)]

    # stage / RS evolution from the computed history (Monitor's history read).
    hist = _safe_history(computed, symbol)
    hist_fig = _history_figure(symbol, hist)
    if hist_fig is not None:
        figures.append(hist_fig)

    # fundamentals table + sector readout.
    fund_row = _fund_row(data, symbol)
    tables: List[dict] = [_fundamentals_table(fund_row)]
    sector = fund_row.get("gics_sector") if fund_row else None

    # headline readouts: stage live, rs_rank from the store (one symbol can't rank).
    live_stage = _last_value(enriched, "stage")
    rs_rank = _stored_rs_rank(computed, symbol)
    asof = _last_date(enriched)

    return vm(
        figures=figures,
        tables=tables,
        status="ok",
        asof=asof,
        title=f"Monitor — {symbol}",
        context=context,
        readouts={
            "stage": _int_or_none(live_stage),
            "rs_rank": num(rs_rank),
            "sector": sector,
        },
    )


# --------------------------------------------------------------------------- #
# live kernel pipeline (spec §5.2)
# --------------------------------------------------------------------------- #
def _run_kernel(panel, data, kernel):
    """Indicators -> RS(compute vs benchmark) -> rank -> Stage (live, one symbol).

    ``rank`` yields a NaN ``rs_rank`` for a single symbol (cross-sectional —
    spec §5.2); ``stage.compute`` consumes the ``rs_rank`` column regardless (it
    tolerates the NaN). The headline rank is read from the store, not here.
    """
    bench = data.time_series([BENCHMARK_ID], fields=("close",))
    out = kernel.indicators.compute(panel)
    out = kernel.relative_strength.compute(out, bench)
    out = kernel.relative_strength.rank(out)  # rs_rank NaN for one symbol
    out = kernel.stage.compute(out)
    return out


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #
def _xy(enriched, col):
    """(dates, values) for a column, JSON-safe (NaN -> None)."""
    dates = [str(d)[:10] for d in enriched.index.get_level_values("date")]
    vals = [_cell(v) for v in enriched[col].tolist()] if col in enriched.columns else []
    return dates, vals


def _price_figure(symbol, enriched) -> dict:
    """Price + MA overlay figure (spec §5.1; parity: app.py chart route MAs)."""
    dates = [str(d)[:10] for d in enriched.index.get_level_values("date")]
    traces = [
        {"name": "Close", "x": dates, "y": [_cell(v) for v in enriched["close"].tolist()],
         "type": "scatter", "mode": "lines"},
    ]
    for ma, label in (("ma_50", "MA50"), ("ma_150", "MA150"), ("ma_200", "MA200")):
        if ma in enriched.columns:
            traces.append({
                "name": label, "x": dates,
                "y": [_cell(v) for v in enriched[ma].tolist()],
                "type": "scatter", "mode": "lines",
            })
    return {
        "id": "monitor_price",
        "traces": traces,
        "layout": {"title": f"{symbol} — Price & Moving Averages"},
    }


def _history_figure(symbol, hist) -> Optional[dict]:
    """Stage / RS evolution figure from classification_history (Monitor read)."""
    if hist is None or len(hist) == 0:
        return None
    dates = [str(d)[:10] for d in hist.index.get_level_values("date")]
    traces = []
    if "rs_rank" in hist.columns:
        traces.append({"name": "RS Rank", "x": dates,
                       "y": [_cell(v) for v in hist["rs_rank"].tolist()],
                       "type": "scatter", "mode": "lines"})
    if "mansfield_rs" in hist.columns:
        traces.append({"name": "Mansfield RS", "x": dates,
                       "y": [_cell(v) for v in hist["mansfield_rs"].tolist()],
                       "type": "scatter", "mode": "lines", "yaxis": "y2"})
    if "stage" in hist.columns:
        traces.append({"name": "Stage", "x": dates,
                       "y": [_cell(v) for v in hist["stage"].tolist()],
                       "type": "scatter", "mode": "lines+markers", "yaxis": "y2"})
    if not traces:
        return None
    return {
        "id": "monitor_history",
        "traces": traces,
        "layout": {"title": f"{symbol} — Stage / RS Evolution"},
    }


# --------------------------------------------------------------------------- #
# fundamentals
# --------------------------------------------------------------------------- #
def _fund_row(data, symbol) -> Dict[str, Any]:
    """Read one symbol's fundamentals row as a plain dict (empty-safe).

    The chart view is independent of fundamentals (parity: the chart route never
    reads them); a missing/unwired fundamentals provider must not break it, so a
    raising ``data.fundamentals`` degrades to an empty row, not a 500."""
    try:
        funds = data.fundamentals([symbol])
    except Exception:  # noqa: BLE001
        logger.debug("monitor: fundamentals(%s) unavailable", symbol, exc_info=True)
        return {}
    if funds is None:
        return {}
    try:
        if len(funds) == 0:
            return {}
        lookup = funds.to_dict("index")
    except (AttributeError, TypeError):
        return {}
    return dict(lookup.get(symbol, {}))


def _fundamentals_table(row: Dict[str, Any]) -> dict:
    """Vertical metric/value fundamentals table (spec §5.1)."""
    from viewmodel import money
    rows = []
    for col, label, kind in _FUND_ROWS:
        v = row.get(col)
        if kind == "money":
            rows.append([label, money(v)])
        elif kind == "str":
            rows.append([label, v if v else None])
        else:
            rows.append([label, _cell(v)])
    return {"id": "monitor_fundamentals", "columns": ["Metric", "Value"], "rows": rows}


# --------------------------------------------------------------------------- #
# multi-symbol (watchlist-style) path — app.py:1462-1559 parity
# --------------------------------------------------------------------------- #
def _handle_multi(req: MonitorRequest, data, computed) -> dict:
    """Emit a watchlist-style ``monitor_list`` table over many symbols.

    rs_rank is read per-symbol from ``computed.cross_section`` (the precomputed
    rank — the live kernel cannot rank one-symbol-at-a-time), price/sector/PE from
    fundamentals. Mirrors the watchlist route's enriched rows.
    """
    symbols = req.symbols
    context = {"list": symbols}
    try:
        funds = data.fundamentals(symbols)
    except Exception:  # noqa: BLE001 — list view still renders price/rank without funds.
        logger.debug("monitor: multi fundamentals unavailable", exc_info=True)
        funds = None
    fund_lookup = _frame_lookup(funds)
    rank_lookup = _frame_lookup(computed.cross_section())

    rows = []
    for sym in symbols:
        f = fund_lookup.get(sym, {})
        price = num(f.get("price_close"))
        eps = num(f.get("eps_actual"))
        pe = (price / eps) if (price is not None and eps and eps > 0) else None
        rs = rank_lookup.get(sym, {}).get("rs_rank")
        rows.append([
            sym,
            _cell(price),
            f.get("gics_sector") or None,
            f.get("gics_industry") or None,
            round(pe, 1) if pe is not None else None,
            num(rs),
            num(f.get("num_analysts")),
        ])

    table = {"id": "monitor_list", "columns": list(_LIST_COLUMNS), "rows": rows}
    asof = _asof(computed)
    return vm(
        tables=[table],
        status="ok",
        asof=asof,
        title="Monitor — Watchlist",
        context=context,
        readouts={"count": len(symbols)},
    )


# --------------------------------------------------------------------------- #
# watchlist endpoints — proxy to the injected ListStore (Monitor reads)
# --------------------------------------------------------------------------- #
def watchlist_members(lists, list_name: str = DEFAULT_LIST) -> dict:
    """Read the members of ``list_name`` -> ViewModel (``readouts.members``)."""
    members = lists.members(list_name) if lists is not None else []
    status = "ok" if members else "empty"
    return vm(
        status=status,
        title=f"Watchlist — {list_name}",
        context={"list": list_name},
        readouts={"members": list(members), "count": len(members)},
    )


def watchlist_add(lists, list_name: str, symbol: str, note: Optional[str] = None) -> dict:
    """Add ``symbol`` to ``list_name`` (Screener-writes contract, proxied)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return vm(status="error", message="No symbol supplied.",
                  context={"list": list_name})
    lists.add(list_name, sym, note=note)
    return watchlist_members(lists, list_name)


def watchlist_remove(lists, list_name: str, symbol: str) -> dict:
    """Remove ``symbol`` from ``list_name`` (proxied to the store)."""
    sym = (symbol or "").strip().upper()
    if sym:
        lists.remove(list_name, sym)
    return watchlist_members(lists, list_name)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _frame_lookup(frame) -> Dict[str, Dict[str, Any]]:
    if frame is None:
        return {}
    try:
        if len(frame) == 0:
            return {}
        return {str(s): rec for s, rec in frame.to_dict("index").items()}
    except (AttributeError, TypeError):
        return {}


def _safe_history(computed, symbol):
    try:
        return computed.history(symbol)
    except Exception:  # noqa: BLE001 — a missing history must not break the view.
        logger.debug("monitor: history(%s) failed", symbol, exc_info=True)
        return None


def _stored_rs_rank(computed, symbol) -> Optional[float]:
    """rs_rank from classification_current (one live symbol can't rank — §5.2)."""
    try:
        cross = computed.cross_section()
    except Exception:  # noqa: BLE001
        return None
    lookup = _frame_lookup(cross)
    rec = lookup.get(symbol)
    if not rec:
        return None
    return num(rec.get("rs_rank"))


def _last_value(enriched, col):
    if col not in enriched.columns or len(enriched) == 0:
        return None
    series = enriched[col].dropna()
    if len(series) == 0:
        return None
    return series.iloc[-1]


def _last_date(enriched) -> Optional[str]:
    if len(enriched) == 0:
        return None
    return str(enriched.index.get_level_values("date")[-1])[:10]


def _asof(computed) -> Optional[str]:
    asof = getattr(computed, "asof", None)
    if callable(asof):
        try:
            return asof()
        except Exception:  # noqa: BLE001
            return None
    return asof


def _int_or_none(v):
    f = num(v)
    return int(f) if f is not None else None


def _cell(v):
    """JSON-safe scalar: NaN/None -> None, numpy/pandas -> python float."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        return v
    f = num(v)
    return f if f is not None else None
