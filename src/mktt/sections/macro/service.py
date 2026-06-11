"""Macro section — thin manager (spec §4.1, §4.2, §10 — FLAG-5).

`macro.handle(req, data)` is the recipe (spec §4.2):

1. fetch the macro FRED series via `data.time_series(macro_ids)` — NO streamlit
   import, NO direct CSV/loader reach; routing to the `(time_series, macro)`
   submodule is the DataSource's job (spec §4.4),
2. pivot the canonical `symbol × date` panel to the wide `date × FRED-code` frame
   the scoring maths expect,
3. run the PRIVATE layer-scoring core (`scoring.py` — Howell/Boucher Z-scores,
   regime, transmission chain),
4. shape the spec §5.1 ViewModel per view: `figures=[liquidity lines / layer
   indicators / asset overlay / transmission stages]`, `tables`, `meta` (regime).

It holds **no** liquidity formulas (those live in `scoring.py`) and **no** fetch
logic (that is the injected `data`), and is dependency-injected (spec §8): `handle`
receives `data` so tests pass a stub `time_series` returning a small fixture — no
Flask, no DB, no network, and **zero streamlit**.

Parity (FLAG-5): the liquidity / layer / overlay / transmission NUMBERS vs the
current `macro/routes.py:26-60` + `macro/liquidity_service.py` — same Z-scores,
same regime, same stage scores — wrapped in the NEW ViewModel envelope.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import pandas as pd

from viewmodel import vm

from . import scoring as s

logger = logging.getLogger("mktt.sections.macro")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


# Layer-detail trace palette (relocated from liquidity_service.build_layer_detail_response:223).
_LAYER_COLORS = ['#33ff00', '#ffb000', '#05d9e8', '#ff2a6d', '#ff6e27',
                 '#A23B72', '#6BAA75', '#FFD700', '#888888', '#ff3333', '#2E86AB']

_LAYER_MAP = {'1': s.LAYER1_INDICATORS, '2a': s.LAYER2A_INDICATORS, '2b': s.LAYER2B_INDICATORS}
_LAYER_NAME = {'1': 'Layer 1 — CB Liquidity', '2a': 'Layer 2a — Private/Wholesale',
               '2b': 'Layer 2b — Economic Reality'}

_STAGE_NAMES = {1: 'CB Impulse', 2: 'Wholesale', 3: 'Risk Appetite', 4: 'Bank Credit',
                5: 'Asset Response', 6: 'Real Economy', 7: 'Reversal Warning'}
_STAGE_COLORS = {1: '#2E86AB', 2: '#A23B72', 3: '#6BAA75', 4: '#FFD700',
                 5: '#33ff00', 6: '#ff6e27', 7: '#ff3333'}

# Recession shading bands (relocated from build_dashboard_response:161).
_RECESSIONS = [('2007-12-01', '2009-06-01'), ('2020-02-01', '2020-04-01')]


# --------------------------------------------------------------------------- #
# typed request (spec §4.1) — parse lives here, handle only sees this record
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MacroRequest:
    """Typed Macro request. `view` selects the panel; mirrors the old liquidity
    API params (view / layer / asset)."""

    view: str = "liquidity"   # liquidity | layer | overlay | transmission
    layer: str = "1"          # layer-detail id (1 / 2a / 2b)
    asset: str = "SPY"        # overlay asset

    @classmethod
    def from_query(cls, args) -> "MacroRequest":
        """Parse from a query-args mapping (`request.args` or a test FakeArgs)."""
        return cls(
            view=args.get("view", "liquidity") or "liquidity",
            layer=args.get("layer", "1") or "1",
            asset=args.get("asset", "SPY") or "SPY",
        )


# --------------------------------------------------------------------------- #
# handle (the recipe)
# --------------------------------------------------------------------------- #
def handle(req: MacroRequest, data) -> dict:
    """Fetch macro series via `data.time_series`, run the scoring core, shape the VM.

    Parameters
    ----------
    req:
        The typed :class:`MacroRequest`.
    data:
        A `DataSource` (or stub) exposing
        ``time_series(ids, start, end, fields) -> symbol×date TimeSeries``.
    """
    context = {"view": req.view, "layer": req.layer, "asset": req.asset}
    logger.debug("macro.handle view=%s layer=%s asset=%s", req.view, req.layer, req.asset)

    raw = _raw_frame(data)
    if raw is None or raw.empty:
        return vm(status="empty", message="No liquidity data available.",
                  title="Liquidity", context=context)

    if req.view == "layer":
        return _handle_layer(req, raw, context)
    if req.view == "overlay":
        return _handle_overlay(req, data, raw, context)
    if req.view == "transmission":
        return _handle_transmission(raw, context)
    return _handle_liquidity(raw, context)


# --------------------------------------------------------------------------- #
# fetch + pivot
# --------------------------------------------------------------------------- #
def _raw_frame(data) -> pd.DataFrame | None:
    """`data.time_series(FRED_SERIES)` -> wide `date × FRED-code` frame.

    The DataSource returns the canonical `symbol × date` macro TimeSeries (symbol ==
    FRED code, level in the `value` field); the scoring maths want a wide
    `date × FRED-code` frame, so we pivot here.
    """
    panel = data.time_series(list(s.FRED_SERIES), fields=("value",))
    if panel is None or len(panel) == 0:
        return None
    value = panel["value"] if "value" in getattr(panel, "columns", []) else panel
    wide = value.unstack("symbol")
    wide.index = pd.DatetimeIndex(wide.index)
    wide.index.name = "Date"
    return wide


# --------------------------------------------------------------------------- #
# liquidity dashboard view
# --------------------------------------------------------------------------- #
def _handle_liquidity(raw, context) -> dict:
    hist = s.calculate_historical_continuous_totals(
        raw, s.LAYER1_INDICATORS, s.LAYER2A_INDICATORS, s.LAYER2B_INDICATORS)
    if hist.empty or hist.dropna(subset=['Composite']).empty:
        return vm(status="empty", message="Not enough liquidity history.",
                  title="Liquidity", context=context)

    hist_weekly = s.resample_to_weekly(hist)
    latest = hist.dropna(subset=['Composite']).iloc[-1]
    l1, l2a, l2b = float(latest['L1']), float(latest['L2a']), float(latest['L2b'])
    composite = float(latest['Composite'])

    regime = s.classify_regime(l1, l2a, l2b)
    regime['description'] = s.get_regime_description(regime['regime_key'])
    bias = regime['bias'].lower()
    if bias not in ('bullish', 'bearish'):
        bias = 'neutral'

    fig = _liquidity_figure(hist_weekly)
    asof = hist_weekly.index[-1].strftime('%Y-%m-%d') if len(hist_weekly) else None

    return vm(
        figures=[fig],
        tables=[],
        status="ok",
        asof=asof,
        title="Global Liquidity",
        context=context,
        readouts={"l1": round(l1, 3), "l2a": round(l2a, 3), "l2b": round(l2b, 3),
                  "composite": round(composite, 3), "regime": regime['regime'], "bias": bias},
        regime_label=regime['regime'],
        regime_description=regime['description'],
        bias=bias,
    )


def _liquidity_figure(hist) -> dict:
    """L1/L2a/L2b + Composite lines with reference bands + recession shading
    (relocated from build_dashboard_response:114-187 into the spec §5.1 figure form)."""
    dates = [d.strftime('%Y-%m-%d') for d in hist.index]

    def _col(name):
        return [round(v, 3) if pd.notna(v) else None for v in hist[name]]

    traces = [
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': _col('L1'),
         'name': 'L1 (CB)', 'line': {'color': '#2E86AB', 'width': 2}, 'yaxis': 'y'},
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': _col('L2a'),
         'name': 'L2a (Private)', 'line': {'color': '#A23B72', 'width': 2}, 'yaxis': 'y'},
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': _col('L2b'),
         'name': 'L2b (Economy)', 'line': {'color': '#6BAA75', 'width': 2}, 'yaxis': 'y'},
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': _col('Composite'),
         'name': 'Composite', 'line': {'color': '#4f8cf7', 'width': 3}, 'yaxis': 'y2'},
    ]

    for ref_val in [1, -1]:
        traces.append({'type': 'scatter', 'mode': 'lines',
                       'x': [dates[0], dates[-1]], 'y': [ref_val, ref_val],
                       'line': {'color': 'rgba(255,255,255,0.15)', 'width': 1, 'dash': 'dot'},
                       'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y'})
    for ref_val in [0.5, -0.5]:
        traces.append({'type': 'scatter', 'mode': 'lines',
                       'x': [dates[0], dates[-1]], 'y': [ref_val, ref_val],
                       'line': {'color': 'rgba(255,255,255,0.15)', 'width': 1, 'dash': 'dot'},
                       'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y2'})

    for start, end in _RECESSIONS:
        traces.append({'type': 'scatter', 'mode': 'none',
                       'x': [start, start, end, end, start], 'y': [-5, 5, 5, -5, -5],
                       'fill': 'toself', 'fillcolor': 'rgba(255,0,0,0.06)',
                       'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y'})

    layout = {
        'height': 550,
        'yaxis': {'title': 'Layer Z-Scores', 'domain': [0.35, 1],
                  'zeroline': True, 'zerolinecolor': 'rgba(255,255,255,0.2)'},
        'yaxis2': {'title': 'Composite', 'domain': [0, 0.30],
                   'zeroline': True, 'zerolinecolor': 'rgba(255,255,255,0.2)'},
        'xaxis': {'rangeslider': {'visible': False}},
        'shapes': [{'type': 'line', 'xref': 'paper', 'x0': 0, 'x1': 1,
                    'yref': 'paper', 'y0': 0.32, 'y1': 0.32,
                    'line': {'color': 'rgba(255,255,255,0.1)', 'width': 1}}],
    }
    return {"id": "liquidity_composite", "traces": traces, "layout": layout}


# --------------------------------------------------------------------------- #
# layer-detail view
# --------------------------------------------------------------------------- #
def _handle_layer(req, raw, context) -> dict:
    config = _LAYER_MAP.get(req.layer)
    if not config:
        return vm(status="error", message=f"Unknown layer: {req.layer}",
                  title="Layer Detail", context=context)

    scores = s.calculate_continuous_layer_scores(raw, config)
    if scores.empty:
        return vm(status="empty", message="No data for layer.",
                  title="Layer Detail", context=context)

    weekly = s.resample_to_weekly(scores)
    dates = [d.strftime('%Y-%m-%d') for d in weekly.index]

    traces = []
    for i, col in enumerate(weekly.columns):
        color = _LAYER_COLORS[i % len(_LAYER_COLORS)]
        vals = [round(v, 3) if pd.notna(v) else None for v in weekly[col]]
        traces.append({'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': vals,
                       'name': col.replace('_', ' ').title(),
                       'line': {'color': color, 'width': 1.5}})

    traces.append({'type': 'scatter', 'mode': 'lines',
                   'x': [dates[0], dates[-1]], 'y': [0, 0],
                   'line': {'color': 'rgba(255,255,255,0.3)', 'width': 1, 'dash': 'dash'},
                   'showlegend': False, 'hoverinfo': 'skip'})

    layout = {'height': 450,
              'title': {'text': _LAYER_NAME.get(req.layer, ''), 'font': {'size': 14}}}
    fig = {"id": "layer_detail", "traces": traces, "layout": layout}

    table = _layer_table(scores, config)
    asof = weekly.index[-1].strftime('%Y-%m-%d') if len(weekly) else None
    return vm(figures=[fig], tables=[table], status="ok", asof=asof,
              title=_LAYER_NAME.get(req.layer, 'Layer Detail'), context=context,
              readouts={"layer": req.layer, "indicators": len(scores.columns)})


def _layer_table(scores, config) -> dict:
    """Indicator Z-score table (replaces the old `indicators_html` blob with the
    spec §5.1 id/columns/rows table form)."""
    latest = scores.iloc[-1] if not scores.empty else pd.Series(dtype=float)
    rows = []
    for col in scores.columns:
        val = latest.get(col, None)
        val_f = round(float(val), 2) if pd.notna(val) else None
        name = col.replace('_', ' ').title()
        signal = config.get(col, {}).get('signal_type', '')
        rows.append([name, signal, val_f])
    return {"id": "layer_indicators", "columns": ["Indicator", "Type", "Z-Score"], "rows": rows}


# --------------------------------------------------------------------------- #
# asset overlay view
# --------------------------------------------------------------------------- #
def _handle_overlay(req, data, raw, context) -> dict:
    hist = s.calculate_historical_continuous_totals(
        raw, s.LAYER1_INDICATORS, s.LAYER2A_INDICATORS, s.LAYER2B_INDICATORS)
    if hist.empty:
        return vm(status="empty", message="No liquidity history.",
                  title="Overlay", context=context)

    price = _asset_close(data, req.asset)
    if price is None or price.empty:
        return vm(status="empty", message=f"No data for {req.asset}.",
                  title="Overlay", context=context)

    hist_w = s.resample_to_weekly(hist)
    price_w = price.resample('W-FRI').last()
    common = hist_w.index.intersection(price_w.index)
    if len(common) < 10:
        return vm(status="empty", message=f"Not enough overlap for {req.asset}.",
                  title="Overlay", context=context)

    dates = [d.strftime('%Y-%m-%d') for d in common]
    price_vals = [round(float(price_w.loc[d]), 2) for d in common]
    comp_vals = [round(float(hist_w.loc[d, 'Composite']), 3)
                 if pd.notna(hist_w.loc[d, 'Composite']) else None for d in common]

    traces = [
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': price_vals,
         'name': req.asset, 'line': {'color': '#33ff00', 'width': 2}, 'yaxis': 'y'},
        {'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': comp_vals,
         'name': 'Composite', 'line': {'color': '#ffb000', 'width': 2}, 'yaxis': 'y2'},
        {'type': 'scatter', 'mode': 'lines', 'x': [dates[0], dates[-1]], 'y': [0, 0],
         'line': {'color': 'rgba(255,176,0,0.3)', 'width': 1, 'dash': 'dash'},
         'showlegend': False, 'hoverinfo': 'skip', 'yaxis': 'y2'},
    ]
    layout = {
        'height': 500,
        'yaxis': {'title': req.asset + ' Price', 'side': 'left'},
        'yaxis2': {'title': 'Composite Z-Score', 'side': 'right', 'overlaying': 'y',
                   'zeroline': True, 'zerolinecolor': 'rgba(255,176,0,0.3)'},
    }
    fig = {"id": "overlay", "traces": traces, "layout": layout}
    return vm(figures=[fig], tables=[], status="ok", asof=dates[-1],
              title=f"{req.asset} vs Liquidity", context=context,
              readouts={"asset": req.asset, "points": len(common)})


def _asset_close(data, asset) -> pd.Series | None:
    """Overlay asset close via `data.time_series` (the equity/benchmark submodule)."""
    panel = data.time_series([asset], fields=("close",))
    if panel is None or len(panel) == 0:
        return None
    if asset not in panel.index.get_level_values("symbol"):
        return None
    sub = panel.xs(asset, level="symbol")
    close = sub["close"] if "close" in getattr(sub, "columns", []) else sub
    idx = pd.DatetimeIndex(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    close = pd.Series(close.values, index=idx)
    return close.dropna()


# --------------------------------------------------------------------------- #
# transmission-chain view
# --------------------------------------------------------------------------- #
def _handle_transmission(raw, context) -> dict:
    stage_scores = s.calculate_stage_scores(raw)
    current = s.calculate_stage_current(raw)
    break_stage, regime_label = s.detect_transmission_break(current)

    fig = _transmission_figure(stage_scores)
    table = _transmission_table(current)
    asof = _transmission_asof(stage_scores)

    return vm(
        figures=[fig],
        tables=[table],
        status="ok",
        asof=asof,
        title="Liquidity Transmission Chain",
        context=context,
        readouts={"break_stage": break_stage, "regime": regime_label},
        break_stage=break_stage,
        regime_label=regime_label,
    )


def _transmission_table(current) -> dict:
    """Per-stage score table (replaces the old `flow_html` blob)."""
    rows = []
    for i in range(1, 8):
        info = current.get(i, {})
        score = info.get('score', 0) if isinstance(info, dict) else float(info)
        score = 0.0 if pd.isna(score) else round(float(score), 3)
        status = info.get('status', 'neutral') if isinstance(info, dict) else 'neutral'
        rows.append([f"S{i}", _STAGE_NAMES[i], score, status])
    return {"id": "transmission_stages",
            "columns": ["Stage", "Name", "Score", "Status"], "rows": rows}


def _transmission_figure(stage_scores) -> dict:
    """Per-stage Z-score history lines (relocated from build_transmission_response:392-419)."""
    traces = []
    for stage_num, series in stage_scores.items():
        if series is None or series.empty:
            continue
        weekly = series.resample('W-FRI').last().dropna()
        if weekly.empty:
            continue
        dates = [d.strftime('%Y-%m-%d') for d in weekly.index]
        vals = [round(float(v), 3) for v in weekly.values]
        domain = 'y' if stage_num <= 4 else 'y2'
        traces.append({'type': 'scatter', 'mode': 'lines', 'x': dates, 'y': vals,
                       'name': f'S{stage_num} {_STAGE_NAMES[stage_num]}',
                       'line': {'color': _STAGE_COLORS.get(stage_num, '#888'), 'width': 1.5},
                       'yaxis': domain})
    layout = {
        'height': 500,
        'yaxis': {'title': 'Stages 1-4 (Impulse→Credit)', 'domain': [0.35, 1]},
        'yaxis2': {'title': 'Stages 5-7 (Assets→Reversal)', 'domain': [0, 0.30]},
        'shapes': [{'type': 'line', 'xref': 'paper', 'x0': 0, 'x1': 1,
                    'yref': 'paper', 'y0': 0.32, 'y1': 0.32,
                    'line': {'color': 'rgba(255,255,255,0.1)', 'width': 1}}],
    }
    return {"id": "transmission_chain", "traces": traces, "layout": layout}


def _transmission_asof(stage_scores) -> str | None:
    last = None
    for series in stage_scores.values():
        if series is None or series.empty:
            continue
        clean = series.dropna()
        if clean.empty:
            continue
        d = clean.index[-1]
        if last is None or d > last:
            last = d
    return last.strftime('%Y-%m-%d') if last is not None else None
