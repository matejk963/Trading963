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

    bench = data.time_series([BENCHMARK_ID], fields=("close",))
    figures: List[dict] = [_ohlc_figure(symbol, enriched, bench)]

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


def _ohlc_figure(symbol, enriched, bench=None) -> dict:
    """Daily OHLC figure for Lightweight Charts (adr/0003; Slice 2 / #9, #10).

    Emits the **non-Plotly** figure shape (no ``traces`` key, so the client takes
    the LWC path, not ``Plotly.newPlot``): ``bars`` (candles), ``volume``, the
    MA50/150/200 ``series`` as ``{time,value}`` arrays aligned to ``bars``, and the
    **benchmark** (SPY) close as ``{time,value}`` aligned 1:1 to ``bars`` by date
    (Slice 3 / #10 — the client recomputes Mansfield RS on the displayed timeframe
    from symbol-close / benchmark-close).

    FORK-1 (recon): the universe price store carries **no open** (``equity.py:33``),
    so ``open`` is derived from the *prior* bar's close (a 1-bar shift); the first
    bar uses its own close. The synthetic open is flagged via
    ``notes.synthetic_open=true`` for the UX caption. All values are JSON-safe via
    :func:`_cell` (NaN -> None)."""
    logger.debug("monitor._ohlc_figure symbol=%s rows=%d", symbol, len(enriched))
    dates = [str(d)[:10] for d in enriched.index.get_level_values("date")]
    closes = [_cell(v) for v in enriched["close"].tolist()]
    highs = [_cell(v) for v in enriched["high"].tolist()] if "high" in enriched.columns else closes
    lows = [_cell(v) for v in enriched["low"].tolist()] if "low" in enriched.columns else closes

    bars = []
    for i, t in enumerate(dates):
        # FORK-1: open = prior bar's close; first bar = its own close.
        open_ = closes[i - 1] if i > 0 else closes[i]
        bars.append({
            "time": t, "open": open_,
            "high": highs[i], "low": lows[i], "close": closes[i],
        })

    volume = []
    if "volume" in enriched.columns:
        vols = [_cell(v) for v in enriched["volume"].tolist()]
        volume = [{"time": dates[i], "value": vols[i]} for i in range(len(dates))]

    series = []
    for ma, label in (("ma_50", "MA50"), ("ma_150", "MA150"), ("ma_200", "MA200")):
        if ma in enriched.columns:
            vals = [_cell(v) for v in enriched[ma].tolist()]
            series.append({
                "name": label,
                "data": [{"time": dates[i], "value": vals[i]} for i in range(len(dates))],
            })

    benchmark = _benchmark_series(bench, dates)

    return {
        "id": "monitor_price",
        "kind": "ohlc",
        "bars": bars,
        "volume": volume,
        "series": series,
        "benchmark": benchmark,
        "layout": {"title": f"{symbol} — Price"},
        "notes": {"synthetic_open": True},
    }


def _benchmark_series(bench, dates) -> List[dict]:
    """Benchmark (SPY) close aligned 1:1 to ``dates`` (the symbol's bar times).

    Builds a ``date -> close`` lookup from the benchmark panel and emits a
    ``{time,value}`` point per symbol bar (Slice 3 / #10 — the client RS recompute
    needs the benchmark close on the same time axis). A missing benchmark date or a
    missing panel degrades to ``value=None`` (JSON-safe), never raising."""
    lookup: Dict[str, Any] = {}
    if bench is not None and len(bench) > 0 and "close" in getattr(bench, "columns", []):
        bench_dates = [str(d)[:10] for d in bench.index.get_level_values("date")]
        bench_close = [_cell(v) for v in bench["close"].tolist()]
        lookup = dict(zip(bench_dates, bench_close))
    return [{"time": t, "value": lookup.get(t)} for t in dates]


#: Indicator column -> (display name, client scale id) for the synced LWC pane.
#: Names are EXACT so the ``.ind-tog`` checkboxes (``data-ind``) match (Slice 6).
_INDICATORS = [
    ("rs_rank", "RS Rank", "rsrank"),
    ("mansfield_rs", "Mansfield RS", "mansfield"),
    ("stage", "Stage", "stage"),
]


def _history_figure(symbol, hist) -> Optional[dict]:
    """Indicators pane (RS Rank / Mansfield RS / Stage) as a synced LWC sub-chart.

    Slice 6: emits a **non-Plotly** figure (``kind:"indicators"`` carrying
    ``series``, no ``traces``/3-axis ``layout``) so the client renders it as a
    second Lightweight-Charts pane stacked under the price and time-synced with it
    (adr/0003). Each indicator is one line series on its OWN client scale (``scale``)
    so the differing ranges (RS Rank 0-100, Mansfield ~0, Stage 0-4) don't collide;
    the client toggles each on/off via the ``.ind-tog`` checkboxes. Only a series
    whose column exists in ``hist`` is included. Times are ``str(d)[:10]`` dates;
    values JSON-safe via :func:`_cell` (NaN -> None). Sourced from
    classification_history (Monitor read)."""
    if hist is None or len(hist) == 0:
        return None
    dates = [str(d)[:10] for d in hist.index.get_level_values("date")]
    series = []
    for col, name, scale in _INDICATORS:
        if col in hist.columns:
            vals = [_cell(v) for v in hist[col].tolist()]
            series.append({
                "name": name,
                "scale": scale,
                "data": [{"time": dates[i], "value": vals[i]} for i in range(len(dates))],
            })
    if not series:
        return None
    return {
        "id": "monitor_history",
        "kind": "indicators",
        "series": series,
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
# fundamental pane — EPS + Sales (actual + forecast + band) · Slice 4 / #11
# --------------------------------------------------------------------------- #
def fundamentals_view(symbol, data, granularity: str = "Q", asof=None) -> dict:
    """Build the EPS + Sales fundamental figures (Plotly; adr/0003).

    A focused ViewModel (its own view, NOT ``handle``) so a granularity toggle
    re-renders ONLY the 2x2, not the candle chart. Reads the structured blend from
    the injected ``data.fundamental_series(symbol, asof=…)`` (the pkl port lives in
    the datasource layer — this section stays formula/fetch-free) and shapes two
    Plotly figures, ``fund_eps`` + ``fund_sales``, each carrying an **actual** solid
    trace, a **forecast** dashed trace, a high/low **band** (fill), and a vertical
    **today-divider** shape in ``layout``.

    ``granularity ∈ {Q, Y, TTM}`` selects the series set (Q = quarterly actual +
    forward-quarterly fan; Y = annual actual + FY1/FY2; TTM = rolling TTM +
    forward-TTM). ``asof`` (default latest = ``None``) threads straight into
    ``data.fundamental_series``.
    """
    gran = (granularity or "Q").upper()
    logger.debug("monitor.fundamentals_view symbol=%s gran=%s asof=%s", symbol, gran, asof)
    series = data.fundamental_series(symbol, asof=asof) or {}

    eps_fig = _fund_figure("fund_eps", f"{symbol} — EPS", series, gran, "eps")
    sales_fig = _fund_figure("fund_sales", f"{symbol} — Sales", series, gran, "rev")

    # PE + PS derived panels (Slice 5 / #12) — period-end price for historical
    # periods, current price for forward & TTM (basis locked); PS needs shares.
    period_end, current_price = _price_basis(data, symbol)
    shares = _shares_outstanding(data, symbol)
    pe_fig = _ratio_figure("fund_pe", f"{symbol} — PE", series, gran, "pe",
                           period_end, current_price, shares)
    ps_fig = _ratio_figure("fund_ps", f"{symbol} — PS", series, gran, "ps",
                           period_end, current_price, shares)

    return vm(
        figures=[eps_fig, sales_fig, pe_fig, ps_fig],
        status="ok",
        asof=asof,
        title=f"Monitor — {symbol} fundamentals",
        context={"symbol": symbol, "granularity": gran},
    )


def _fund_figure(fig_id, title, series, gran, kind) -> dict:
    """One fundamental figure (EPS or Sales) at a granularity.

    ``kind`` selects the metric: ``"eps"`` or ``"rev"`` (the series-dict key stems).
    Builds an actual solid trace, a forecast dashed trace, and a high/low band, then
    a today-divider shape between the last actual date and the first forecast date.
    """
    actual_dates, actual_vals = _fund_actual(series, gran, kind)
    fwd = _fund_forecast(series, gran, kind)

    traces = []
    traces.append({
        "name": "Actual", "x": list(actual_dates), "y": list(actual_vals),
        "type": "scatter", "mode": "lines+markers",
        "line": {"color": "#2c7fb8"},
    })
    # high/low band (drawn first so the forecast line sits on top): low, then high
    # with fill='tonexty' shading the area between.
    if fwd["dates"] and any(v is not None for v in fwd["low"]):
        traces.append({
            "name": "Low", "x": list(fwd["dates"]), "y": list(fwd["low"]),
            "type": "scatter", "mode": "lines",
            "line": {"width": 0}, "showlegend": False, "hoverinfo": "skip",
        })
        traces.append({
            "name": "Est. range", "x": list(fwd["dates"]), "y": list(fwd["high"]),
            "type": "scatter", "mode": "lines",
            "line": {"width": 0}, "fill": "tonexty",
            "fillcolor": "rgba(44,127,184,0.15)", "hoverinfo": "skip",
        })
    traces.append({
        "name": "Forecast", "x": list(fwd["dates"]), "y": list(fwd["mean"]),
        "type": "scatter", "mode": "lines+markers",
        "line": {"color": "#2c7fb8", "dash": "dash"},
    })

    layout = {"title": title}
    divider = _today_divider(actual_dates, fwd["dates"])
    if divider is not None:
        layout["shapes"] = [divider]

    return {"id": fig_id, "traces": traces, "layout": layout}


def _fund_actual(series, gran, kind):
    """(dates, values) for the actual series at a granularity, JSON-safe."""
    if gran == "Y":
        block = series.get("annual", {}) or {}
        dates = block.get("fy_dates", []) or []
        vals = block.get("eps" if kind == "eps" else "rev", []) or []
    elif gran == "TTM":
        block = series.get("ttm", {}) or {}
        dates = block.get("dates", []) or []
        vals = block.get("eps" if kind == "eps" else "revenue", []) or []
    else:  # Q
        block = series.get("quarterly", {}) or {}
        dates = block.get("dates", []) or []
        vals = block.get("eps" if kind == "eps" else "revenue", []) or []
    return list(dates), [_cell(v) for v in vals]


def _fund_forecast(series, gran, kind):
    """Forecast {dates, mean, high, low} at a granularity, JSON-safe.

    Q -> forward-quarterly fan; Y -> annual FY1/FY2 forward; TTM -> forward-TTM
    (the port emits the forward-TTM fan under ``ttm`` with the same key stems)."""
    if gran == "Y":
        block = series.get("annual", {}) or {}
        dates = block.get("fwd_dates", []) or []
        stem = "eps" if kind == "eps" else "rev"
    elif gran == "TTM":
        block = series.get("ttm", {}) or {}
        dates = block.get("fwd_dates", []) or []
        stem = "eps" if kind == "eps" else "rev"
    else:  # Q
        block = series.get("forward_q", {}) or {}
        dates = block.get("dates", []) or []
        stem = "eps" if kind == "eps" else "rev"
    mean = block.get(f"{stem}_mean", []) or []
    high = block.get(f"{stem}_high", []) or []
    low = block.get(f"{stem}_low", []) or []
    n = len(dates)
    return {
        "dates": list(dates),
        "mean": [_cell(v) for v in mean[:n]],
        "high": [_cell(v) for v in high[:n]],
        "low": [_cell(v) for v in low[:n]],
    }


def _today_divider(actual_dates, fwd_dates):
    """A vertical 'today' divider shape between the last actual and first forecast.

    Placed at the boundary date (the first forecast date if present, else the last
    actual date) — a full-height paper-referenced vertical line."""
    boundary = None
    if fwd_dates:
        boundary = fwd_dates[0]
    elif actual_dates:
        boundary = actual_dates[-1]
    if boundary is None:
        return None
    return {
        "type": "line", "x0": boundary, "x1": boundary,
        "y0": 0, "y1": 1, "yref": "paper",
        "line": {"color": "#888", "width": 1, "dash": "dot"},
    }


# --------------------------------------------------------------------------- #
# fundamental pane — PE + PS derived panels (period-end / current) · Slice 5 / #12
# --------------------------------------------------------------------------- #
def _price_basis(data, symbol):
    """Return ``(period_end_lookup, current_price)`` for the ratio basis (#12).

    ``period_end_lookup`` is a ``date -> close`` map (sorted) used to find the
    period-end price for each historical ``report_date`` (nearest *prior* trading
    day). ``current_price`` is the last close (forward & TTM basis). A missing /
    raising price panel degrades to ``({}, None)`` — ratios then render as ``None``
    rather than breaking the view (parity with the empty-safe fundamentals read)."""
    try:
        panel = data.time_series([symbol], fields=("close",))
    except Exception:  # noqa: BLE001
        logger.debug("monitor: price panel(%s) unavailable", symbol, exc_info=True)
        return {}, None
    if panel is None or len(panel) == 0 or "close" not in getattr(panel, "columns", []):
        return {}, None
    dates = [str(d)[:10] for d in panel.index.get_level_values("date")]
    closes = [_cell(v) for v in panel["close"].tolist()]
    pairs = [(d, c) for d, c in zip(dates, closes) if c is not None]
    if not pairs:
        return {}, None
    pairs.sort(key=lambda p: p[0])
    lookup = dict(pairs)
    current_price = pairs[-1][1]
    return {"_pairs": pairs, "_lookup": lookup}, current_price


def _period_end_price(period_end, report_date):
    """Close on ``report_date``, else the nearest *prior* trading day (period-end).

    ``period_end`` is the dict from :func:`_price_basis`. Returns ``None`` when no
    trading day on/before the report date exists (no fabrication)."""
    if not period_end or report_date is None:
        return None
    lookup = period_end.get("_lookup", {})
    if report_date in lookup:
        return lookup[report_date]
    prior = None
    for d, c in period_end.get("_pairs", []):
        if d <= report_date:
            prior = c
        else:
            break
    return prior


def _shares_outstanding(data, symbol):
    """``shares_outstanding`` for ``symbol`` from the fundamentals row (empty-safe)."""
    row = _fund_row(data, symbol)
    return num(row.get("shares_outstanding")) if row else None


def _pe(price, eps):
    """PE = price / EPS. Guard divide-by-zero / non-positive EPS -> None."""
    if price is None or eps is None or eps <= 0:
        return None
    return price / eps


#: ``data.fundamental_series`` revenue is in $ MILLIONS (the pkl raw $ figure is
#: divided by 1e6 in ``datasource/fundamental_series.py``), while
#: ``shares_outstanding`` is a RAW share count. To form a dimensionless P/S the two
#: must share a unit, so revenue is scaled back to dollars before dividing.
_REVENUE_MILLIONS_TO_DOLLARS = 1e6


def _ps(price, revenue, shares):
    """PS = market cap / sales = price * shares / revenue_dollars.

    ``revenue`` arrives in $ MILLIONS but ``shares`` is a raw count, so revenue is
    converted to dollars first (``* 1e6``) to keep the ratio dimensionless — without
    this the result is inflated by ~1e6. Guard divide-by-zero / non-positive revenue
    or missing shares -> None."""
    if price is None or revenue is None or revenue <= 0 or shares is None or shares <= 0:
        return None
    revenue_dollars = revenue * _REVENUE_MILLIONS_TO_DOLLARS
    return price * shares / revenue_dollars


def _ratio_figure(fig_id, title, series, gran, kind, period_end, current_price, shares):
    """One ratio figure (PE or PS) at a granularity (Slice 5 / #12).

    Derives the ratio from the EPS/Sales series (#11's ``data.fundamental_series``)
    and price: **period-end** price per historical ``report_date`` for Q/Y actuals,
    **current** price for forward estimates and the whole TTM domain (basis locked).
    PE = price/EPS; PS = price*shares/revenue. The forecast band propagates the
    EPS/revenue high/low through the ratio (high EPS -> high PE; for PS the high
    *revenue* gives the **low** PS, so the band edges swap). Same visual language as
    EPS/Sales: actual solid -> forecast dashed + high/low band + today-divider.

    **EPS gate (#12 fix):** BOTH PE and PS are computed only where EPS > 0 (EPS <= 0
    excluded), per point, for actuals AND the forecast. For TTM the gate is
    ``series["ttm"]["eps_ok"]`` (all 4 constituent quarters strictly positive — a
    loss quarter suppresses the point even when the summed TTM EPS is positive); for
    Q/Y the gate is the per-period actual EPS > 0; the forecast gate is the
    forward EPS *mean* > 0. The gate is on EPS for both PE and PS so PS is suppressed
    through negative/zero earnings even though revenue is positive."""
    base_kind = "eps" if kind == "pe" else "rev"
    actual_dates, actual_vals = _fund_actual(series, gran, kind=base_kind)
    fwd = _fund_forecast(series, gran, kind=base_kind)

    # EPS gate inputs (fetched regardless of PE/PS — the gate is always on EPS).
    eps_actual_dates, eps_actual_vals = _fund_actual(series, gran, "eps")
    eps_fwd = _fund_forecast(series, gran, "eps")

    # per-point actual EPS gate (index-aligned; missing -> gate fails).
    if gran == "TTM":
        eps_ok = (series.get("ttm") or {}).get("eps_ok") or []
        actual_gate = [bool(eps_ok[i]) if i < len(eps_ok) else False
                       for i in range(len(actual_dates))]
    else:  # Q / Y: gate on the per-period actual EPS > 0.
        actual_gate = [
            (eps_actual_vals[i] is not None and eps_actual_vals[i] > 0)
            if i < len(eps_actual_vals) else False
            for i in range(len(actual_dates))
        ]

    # forecast EPS-mean gate (per point; band edges share the mean's gate).
    eps_mean = eps_fwd["mean"]
    fwd_gate = [
        (eps_mean[j] is not None and eps_mean[j] > 0) if j < len(eps_mean) else False
        for j in range(len(fwd["dates"]))
    ]

    # actual ratio: TTM uses current price; Q/Y actuals use the period-end price.
    use_current_for_actual = (gran == "TTM")
    actual_ratio = []
    for i, (d, base) in enumerate(zip(actual_dates, actual_vals)):
        if not actual_gate[i]:
            actual_ratio.append(None)
            continue
        price = current_price if use_current_for_actual else _period_end_price(period_end, d)
        actual_ratio.append(_ratio(kind, price, base, shares))

    # forecast + band: always current price, gated on the forward EPS mean.
    def _gated_fwd(vals):
        out = []
        for j, v in enumerate(vals):
            out.append(_ratio(kind, current_price, v, shares) if (j < len(fwd_gate) and fwd_gate[j]) else None)
        return out

    fwd_mean = _gated_fwd(fwd["mean"])
    if kind == "pe":
        fwd_hi = _gated_fwd(fwd["high"])
        fwd_lo = _gated_fwd(fwd["low"])
    else:  # PS: higher revenue -> lower PS, so the band edges swap.
        fwd_hi = _gated_fwd(fwd["low"])
        fwd_lo = _gated_fwd(fwd["high"])

    traces = [{
        "name": "Actual", "x": list(actual_dates), "y": actual_ratio,
        "type": "scatter", "mode": "lines+markers", "line": {"color": "#2c7fb8"},
    }]
    if fwd["dates"] and any(v is not None for v in fwd_lo):
        traces.append({
            "name": "Low", "x": list(fwd["dates"]), "y": fwd_lo,
            "type": "scatter", "mode": "lines",
            "line": {"width": 0}, "showlegend": False, "hoverinfo": "skip",
        })
        traces.append({
            "name": "Est. range", "x": list(fwd["dates"]), "y": fwd_hi,
            "type": "scatter", "mode": "lines",
            "line": {"width": 0}, "fill": "tonexty",
            "fillcolor": "rgba(44,127,184,0.15)", "hoverinfo": "skip",
        })
    traces.append({
        "name": "Forecast", "x": list(fwd["dates"]), "y": fwd_mean,
        "type": "scatter", "mode": "lines+markers",
        "line": {"color": "#2c7fb8", "dash": "dash"},
    })

    layout = {"title": title}
    divider = _today_divider(actual_dates, fwd["dates"])
    if divider is not None:
        layout["shapes"] = [divider]
    return {"id": fig_id, "traces": traces, "layout": layout}


def _ratio(kind, price, base, shares):
    """Dispatch to PE or PS for one period; ``base`` is EPS (pe) or revenue (ps)."""
    if kind == "pe":
        return _pe(price, base)
    return _ps(price, base, shares)


# --------------------------------------------------------------------------- #
# Estimate Revisions sub-pane — faithful replica of the original app's Revisions
# view (stock_panel.js::loadPanelRevisions): two EPS charts side by side.
#   LEFT  rev_ttm — Forward TTM EPS (Next 8Q): one curve per revision snapshot
#                   (solid current + dashed older) + a dotted Actual-TTM line.
#   RIGHT rev_eps — EPS Estimate Revisions (FY1/FY2): mean lines + dotted high/low.
# Independent of the Q/Y/TTM toggle (granularity-independent). · Slice 7
# --------------------------------------------------------------------------- #
#: the original curve palette (cycled per revision snapshot).
_REV_TTM_PALETTE = [
    "#4f8cf7", "#10b981", "#f59e0b", "#ef4444",
    "#a78bfa", "#ec4899", "#06b6d4", "#84cc16",
]
#: FY1 blue / FY2 green (matches the original right-hand chart).
_REV_FY1_COLOR = "#4f8cf7"
_REV_FY2_COLOR = "#10b981"


def revisions_view(symbol, data, n=3, asof=None) -> dict:
    """Build the Estimate-Revisions sub-pane — a faithful replica of the original
    app's Revisions view (two EPS charts side by side, dark theme).

    Its own view (like :func:`fundamentals_view`), independent of the Q/Y/TTM
    toggle. Emits exactly two figures:

    * ``rev_ttm`` — "Forward TTM EPS (Next 8Q)" from ``data.eps_ttm_forward(symbol,
      n)``: one trace per revision snapshot curve (i=0 solid+thick, i>0 dashed+thin,
      original palette/markers) plus a horizontal dotted "Actual TTM (<val>)" line.
    * ``rev_eps`` — "EPS Estimate Revisions (FY1/FY2)" from
      ``data.fundamental_series(symbol, asof)["revisions"]["eps"]``: FY1/FY2 mean
      lines + dotted (non-legend) high/low lines.

    ``n_available`` (the count of revision snapshots) is carried in ``context`` so
    the client can cap the "Revisions: N" input. Graceful: a missing/thin name ->
    empty figures, ``status`` ``empty``; never raises."""
    logger.debug("monitor.revisions_view symbol=%s n=%s asof=%s", symbol, n, asof)
    ttm = data.eps_ttm_forward(symbol, n=n) or {}
    series = data.fundamental_series(symbol, asof=asof) or {}
    eps = (series.get("revisions") or {}).get("eps") or {}

    ttm_fig = _rev_ttm_figure(ttm)
    eps_fig = _rev_eps_figure(eps)

    has_ttm = bool(ttm.get("curves"))
    has_eps = any(
        (eps.get(fy, {}) or {}).get("dates") for fy in ("fy1", "fy2")
    )
    status = "ok" if (has_ttm or has_eps) else "empty"
    return vm(
        figures=[ttm_fig, eps_fig],
        status=status,
        asof=asof,
        title=f"Monitor — {symbol} estimate revisions",
        context={"symbol": symbol, "n_available": int(ttm.get("n_available") or 0)},
    )


def _rev_ttm_figure(ttm) -> dict:
    """The LEFT chart: "Forward TTM EPS (Next 8Q)" — one trace per revision-snapshot
    curve (i=0 solid/thick/markers-5, i>0 dashed/thin/markers-3) + a dotted
    horizontal Actual-TTM line. Mirrors the original ``loadPanelRevisions``."""
    labels = list(ttm.get("quarter_labels", []) or [])
    curves = ttm.get("curves", []) or []
    traces = []
    for i, curve in enumerate(curves):
        traces.append({
            "name": curve.get("label"),
            "x": list(labels),
            "y": [_cell(v) for v in (curve.get("values", []) or [])],
            "mode": "lines+markers",
            "line": {
                "color": _REV_TTM_PALETTE[i % len(_REV_TTM_PALETTE)],
                "dash": "solid" if i == 0 else "dash",
                "width": 3 if i == 0 else 1.5,
            },
            "marker": {"size": 5 if i == 0 else 3},
        })
    current_ttm = _cell(ttm.get("current_ttm"))
    if current_ttm is not None and labels:
        traces.append({
            "name": f"Actual TTM ({current_ttm})",
            "x": list(labels),
            "y": [current_ttm] * len(labels),
            "mode": "lines",
            "line": {"color": "#666", "dash": "dot", "width": 1},
        })
    return {
        "id": "rev_ttm",
        "traces": traces,
        "layout": {
            "title": "Forward TTM EPS (Next 8Q)",
            "yaxis": {"title": "TTM EPS ($)"},
            "xaxis": {"type": "category"},
        },
    }


def _rev_eps_figure(eps) -> dict:
    """The RIGHT chart: "EPS Estimate Revisions (FY1/FY2)" — FY1/FY2 mean lines +
    dotted (non-legend) high/low lines. Mirrors the original ``loadPanelRevisions``."""
    traces = []
    for fy, label, color in (
        ("fy1", "FY1", _REV_FY1_COLOR),
        ("fy2", "FY2", _REV_FY2_COLOR),
    ):
        trend = eps.get(fy) or {}
        dates = list(trend.get("dates", []) or [])
        mean = [_cell(v) for v in (trend.get("mean", []) or [])]
        high = [_cell(v) for v in (trend.get("high", []) or [])]
        low = [_cell(v) for v in (trend.get("low", []) or [])]
        traces.append({
            "name": f"{label} Mean", "x": list(dates), "y": mean,
            "mode": "lines", "line": {"color": color, "width": 2},
        })
        if dates and any(v is not None for v in high):
            traces.append({
                "name": f"{label} High", "x": list(dates), "y": high,
                "mode": "lines", "showlegend": False,
                "line": {"color": color, "dash": "dot", "width": 1},
            })
        if dates and any(v is not None for v in low):
            traces.append({
                "name": f"{label} Low", "x": list(dates), "y": low,
                "mode": "lines", "showlegend": False,
                "line": {"color": color, "dash": "dot", "width": 1},
            })
    return {
        "id": "rev_eps",
        "traces": traces,
        "layout": {
            "title": "EPS Estimate Revisions (FY1/FY2)",
            "yaxis": {"title": "EPS ($)"},
        },
    }


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
    """Read the members of ``list_name`` -> ViewModel.

    ``readouts.members`` is the flat symbol list (badge + count). ``entries``
    rides in ``context`` as ``[{symbol, side}]`` — ``side`` is read from each
    member's ``note`` (adr/0002 §4: long/short stored in the note), defaulting to
    ``"long"`` when absent. The watchlist page + the nav badge consume this."""
    entries = _watchlist_entries(lists, list_name)
    members = [e["symbol"] for e in entries]
    status = "ok" if members else "empty"
    return vm(
        status=status,
        title=f"Watchlist — {list_name}",
        context={"list": list_name, "entries": entries},
        readouts={"members": list(members), "count": len(members)},
    )


def _watchlist_entries(lists, list_name: str) -> List[Dict[str, Any]]:
    """``[{symbol, side}]`` for ``list_name`` (side from the note; default long).

    Prefers ``members_with_notes`` (carries the side); degrades to ``members``
    (all-long) for a store that only exposes the flat read."""
    if lists is None:
        return []
    with_notes = getattr(lists, "members_with_notes", None)
    if callable(with_notes):
        pairs = with_notes(list_name)
        return [
            {"symbol": sym, "side": (note or "long").strip().lower() or "long"}
            for sym, note in pairs
        ]
    return [{"symbol": sym, "side": "long"} for sym in lists.members(list_name)]


def rail(lists, computed, list_name: str = DEFAULT_LIST) -> dict:
    """Build the saved-instrument rail VM (Slice 1 — workspace spine + rail).

    Reads ``members_detailed`` (symbol, note, added_at), derives ``side`` from the
    note (default ``"long"``), and joins each symbol against the **precomputed**
    ``computed.cross_section()`` for ``stage`` + ``rs_rank`` (mirrors
    ``_handle_multi``'s ``rank_lookup`` — the rail reads stored ranks, it never
    recomputes). Entries default-order by ``added_at`` desc (recently-added first);
    a member missing from the cross-section still renders with ``stage=None,
    rs_rank=None``. ``readouts={members, count}``; empty list -> ``status="empty"``.
    """
    logger.debug("monitor.rail list=%s", list_name)
    detailed = _members_detailed(lists, list_name)
    try:
        cross_lookup = _frame_lookup(computed.cross_section())
    except Exception:  # noqa: BLE001 — rail still renders rows without enrichment.
        logger.debug("monitor.rail: cross_section unavailable", exc_info=True)
        cross_lookup = {}

    enriched = []
    for symbol, note, added_at in detailed:
        rec = cross_lookup.get(symbol, {})
        stage = _int_or_none(rec.get("stage")) if rec else None
        rs_rank = num(rec.get("rs_rank")) if rec else None
        side = (note or "long").strip().lower() or "long"
        enriched.append({
            "symbol": symbol,
            "side": side,
            "stage": stage,
            "rs_rank": rs_rank,
            "added_at": added_at,
        })

    # default order: recently-added first (added_at desc; None sorts last/oldest).
    enriched.sort(key=lambda e: (e["added_at"] is not None, e["added_at"]), reverse=True)

    members = [e["symbol"] for e in enriched]
    status = "ok" if enriched else "empty"
    return vm(
        status=status,
        title=f"Monitor — {list_name}",
        context={"list": list_name, "entries": enriched},
        readouts={"members": list(members), "count": len(members)},
    )


def _members_detailed(lists, list_name: str) -> List[tuple]:
    """``[(symbol, note, added_at)]`` for ``list_name`` (empty-safe).

    Prefers ``members_detailed`` (carries ``added_at``); degrades to
    ``members_with_notes`` (added_at=None) then ``members`` for a thinner store."""
    if lists is None:
        return []
    detailed = getattr(lists, "members_detailed", None)
    if callable(detailed):
        return [(sym, note, added) for sym, note, added in detailed(list_name)]
    with_notes = getattr(lists, "members_with_notes", None)
    if callable(with_notes):
        return [(sym, note, None) for sym, note in with_notes(list_name)]
    return [(sym, None, None) for sym in lists.members(list_name)]


def watchlist_add(lists, list_name: str, symbol: str, note: Optional[str] = None) -> dict:
    """Add ``symbol`` to ``list_name`` (Screener-writes contract, proxied)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return vm(status="error", message="No symbol supplied.",
                  context={"list": list_name})
    lists.add(list_name, sym, note=note)
    return watchlist_members(lists, list_name)


def watchlist_add_bulk(
    lists, list_name: str, symbols: list, note: Optional[str] = None,
    replace: bool = False,
) -> dict:
    """Add many ``symbols`` to ``list_name`` in one call (Slice A, send-to-Monitor).

    Upper-cases + strips each symbol, skips blanks/None, de-dupes (preserving
    first-seen order), then calls ``lists.add(list_name, sym, note)`` per survivor.
    When ``replace`` is true the list is first emptied (every current member removed)
    so the result is exactly ``symbols`` — the "move filtered stocks to Monitor"
    flow uses this so each send defines a clean working set rather than accumulating.
    Returns a flat envelope ``{status, list, added, members}`` (PRD-frozen shape):
    ``added`` counts the symbols attempted after dedupe/blank-skip; ``members`` is
    the list's symbols after the adds (via ``lists.members``)."""
    seen = []
    for raw in symbols or []:
        sym = (raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.append(sym)
    if replace:
        for sym in list(lists.members(list_name)):
            lists.remove(list_name, sym)
    for sym in seen:
        lists.add(list_name, sym, note=note)
    logger.debug(
        "monitor.watchlist_add_bulk list=%s added=%d replace=%s",
        list_name, len(seen), replace,
    )
    return {
        "status": "ok",
        "list": list_name,
        "added": len(seen),
        "members": list(lists.members(list_name)),
    }


def watchlist_remove(lists, list_name: str, symbol: str) -> dict:
    """Remove ``symbol`` from ``list_name`` (proxied to the store)."""
    sym = (symbol or "").strip().upper()
    if sym:
        lists.remove(list_name, sym)
    return watchlist_members(lists, list_name)


def watchlist_lists(lists) -> dict:
    """All watchlist names that currently have members (multi-watchlist selector).

    ``default`` is always offered first even when empty so the rail always has a
    home list; the rest follow in the store's order (de-duped)."""
    try:
        names = list(lists.lists())
    except Exception:  # noqa: BLE001 — a bare/empty store must not break the rail.
        names = []
    out = ["default"]
    for n in names:
        if n and n not in out:
            out.append(n)
    return {"status": "ok", "lists": out}


def watchlist_rename(lists, old_name: str, new_name: str) -> dict:
    """Rename watchlist ``old_name`` -> ``new_name``, preserving each member's note
    (long/short side). MKLists has no atomic rename, so this re-adds every member
    under the new name then drops the old. Refuses to merge into an EXISTING list
    (returns ``status:"exists"``) so a rename can't silently fold two lists together.
    Returns ``{status, old, new, members}``."""
    old = (old_name or "").strip()
    new = (new_name or "").strip()
    if not new:
        return {"status": "error", "message": "empty name", "old": old, "new": new}
    if new == old:
        return {"status": "ok", "old": old, "new": new, "members": list(lists.members(old))}
    try:
        existing = set(lists.lists())
    except Exception:  # noqa: BLE001
        existing = set()
    if new in existing:
        return {"status": "exists", "old": old, "new": new}
    try:
        pairs = list(lists.members_with_notes(old))
    except Exception:  # noqa: BLE001 — stub without notes: fall back to bare symbols.
        pairs = [(s, None) for s in lists.members(old)]
    for sym, note in pairs:
        lists.add(new, sym, note=note)
    for sym in list(lists.members(old)):
        lists.remove(old, sym)
    logger.debug("monitor.watchlist_rename %s -> %s (%d members)", old, new, len(pairs))
    return {"status": "ok", "old": old, "new": new, "members": list(lists.members(new))}


def watchlist_remove_bulk(lists, list_name: str, symbols: list) -> dict:
    """Remove many ``symbols`` from ``list_name`` in one call (bulk-delete from the
    Monitor rail). Upper-cases + strips + de-dupes, skips blanks, calls
    ``lists.remove`` per survivor. Returns the same flat envelope as the add path:
    ``{status, list, removed, members}`` (members = the list AFTER the removals)."""
    seen = []
    for raw in symbols or []:
        sym = (raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.append(sym)
    for sym in seen:
        lists.remove(list_name, sym)
    logger.debug("monitor.watchlist_remove_bulk list=%s removed=%d", list_name, len(seen))
    return {
        "status": "ok",
        "list": list_name,
        "removed": len(seen),
        "members": list(lists.members(list_name)),
    }


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
