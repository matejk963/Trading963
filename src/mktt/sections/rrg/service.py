"""RRG section — thin manager (spec §4.1, §4.2, §10 — FLAG-5).

`rrg.handle(req, data)` is the recipe (spec §4.2):

1. resolve the dataset -> ETF tickers + benchmark (or the futures universe) from the
   PRIVATE quadrant core's config,
2. fetch the `symbol × date` price panel via `data.time_series(...)` — NO streamlit
   import, NO direct fetcher; routing to the `(time_series, etf)` / `(time_series,
   futures)` submodules is the DataSource's job (spec §4.4),
3. pivot to the wide `date × ticker` frame the quadrant maths expect,
4. run the quadrant core (RS-ratio/momentum + tail geometry),
5. shape the spec §5.1 ViewModel: `figures=[RRG scatter with tails]`,
   `tables=[positions]`, `meta` (asof / readouts / full-series for client replay).

It holds **no** RRG formulas (those live in `quadrant.py`) and **no** fetch logic
(that is the injected `data`), and is dependency-injected (spec §8): `handle`
receives `data` so tests pass a stub `time_series` returning a small fixture — no
Flask, no DB, no network, and **zero streamlit**.

Parity target (FLAG-5): the RRG response NUMBERS vs the current
`macro/rrg_service.build_rrg_response` (:233-273) — same RS-ratio/momentum, same
tail geometry — wrapped in the NEW ViewModel envelope.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from viewmodel import vm

from . import quadrant as q

logger = logging.getLogger("mktt.sections.rrg")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


# Quadrant shading / annotation colors (relocated from rrg_service.py:44-55).
QUADRANT_COLORS = {
    "Leading": "rgba(76,175,80,0.08)",
    "Weakening": "rgba(255,152,0,0.08)",
    "Lagging": "rgba(244,67,54,0.08)",
    "Improving": "rgba(33,150,243,0.08)",
}
QUADRANT_TEXT_COLORS = {
    "Leading": "rgba(76,175,80,0.4)",
    "Weakening": "rgba(255,152,0,0.4)",
    "Lagging": "rgba(244,67,54,0.4)",
    "Improving": "rgba(33,150,243,0.4)",
}


# --------------------------------------------------------------------------- #
# typed request (spec §4.1) — parse lives here, handle only sees this record
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RrgRequest:
    """Typed RRG request. Mirrors `build_rrg_response` / `build_rrg_drill_response`
    params (dataset / period / window / trail [+ drill group])."""

    dataset: str = "us"
    period: str = "2y"
    window: int = 13
    trail: int = 8
    group: str = ""  # set for the intra-group drill-down

    @property
    def is_futures(self) -> bool:
        return self.dataset == "futures"

    @property
    def is_drill(self) -> bool:
        return bool(self.group)

    @classmethod
    def from_query(cls, args) -> "RrgRequest":
        """Parse from a query-args mapping (`request.args` or test FakeArgs)."""
        def _int(name, default):
            try:
                return int(float(args.get(name, default)))
            except (TypeError, ValueError):
                return default

        return cls(
            dataset=args.get("dataset", "us") or "us",
            period=args.get("period", "2y") or "2y",
            window=_int("window", 13),
            trail=_int("trail", 8),
            group=args.get("group", "") or "",
        )


# --------------------------------------------------------------------------- #
# handle (the recipe)
# --------------------------------------------------------------------------- #
def handle(req: RrgRequest, data) -> dict:
    """Fetch prices via `data.time_series`, run the quadrant core, shape the VM.

    Parameters
    ----------
    req:
        The typed :class:`RrgRequest`.
    data:
        A `DataSource` (or stub) exposing
        ``time_series(ids, start, end, fields) -> symbol×date TimeSeries``.
    """
    context = {
        "dataset": req.dataset, "period": req.period,
        "window": req.window, "trail": req.trail, "group": req.group,
    }
    logger.debug("rrg.handle dataset=%s window=%s trail=%s group=%s",
                 req.dataset, req.window, req.trail, req.group)

    window = int(req.window)
    trail = int(req.trail)

    if req.is_drill:
        return _handle_drill(req, data, context, window, trail)
    if req.is_futures:
        return _handle_futures(req, data, context, window, trail)
    return _handle_etf(req, data, context, window, trail)


# --- ETF datasets --------------------------------------------------------- #
def _handle_etf(req, data, context, window, trail) -> dict:
    momentum_window = max(4, window // 3)
    length_days = window * 5
    momentum_days = momentum_window * 5
    tail_length = trail

    dataset_key = q.DATASET_KEYS.get(req.dataset, "US Sectors")
    config = q.ETF_DATASETS[dataset_key]
    benchmark = config["benchmark"]
    tickers = list(config["sectors"].keys())

    wide = _wide_close(data, [benchmark] + tickers, req.period)
    if wide is None or wide.empty or benchmark not in wide.columns:
        return vm(status="empty", message="No price data available.",
                  title="RRG", context=context)

    tail_data, full_data = q.compute_etf_rrg(
        wide, benchmark, length_days, momentum_days, tail_length)
    if not tail_data:
        return vm(status="empty", message="Not enough data for RRG calculation.",
                  title="RRG", context=context)

    name_color_map = q.etf_name_color_map(dataset_key)
    return _shape(tail_data, full_data, name_color_map, context, title="RRG — Sectors")


# --- futures groups overview ---------------------------------------------- #
def _handle_futures(req, data, context, window, trail) -> dict:
    length_days = window * 5
    tail_length = trail

    tickers = _futures_universe()
    wide = _wide_close(data, tickers, req.period)
    if wide is None or wide.empty:
        return vm(status="empty", message="No futures price data.",
                  title="RRG", context=context)
    wide = wide.ffill()

    selected_groups = list(q.FUTURES_GROUPS.keys())
    result = q.compute_futures_group_rrg(wide, length_days, tail_length, selected_groups)
    if not result or len(result) < 2:
        return vm(status="empty", message="Not enough groups for RRG.",
                  title="RRG", context=context)

    tail_data, full_data = result
    name_color_map = q.futures_group_name_color_map()
    return _shape(tail_data, full_data, name_color_map, context, title="RRG — Futures Groups")


# --- intra-group drill-down ----------------------------------------------- #
def _handle_drill(req, data, context, window, trail) -> dict:
    if req.group not in q.FUTURES_GROUPS:
        return vm(status="error", message=f"Unknown group: {req.group}",
                  title="RRG", context=context)

    length_days = window * 5
    tail_length = trail

    group_config = q.FUTURES_GROUPS[req.group]
    tickers = list(group_config["contracts"].keys())
    wide = _wide_close(data, tickers, req.period)
    if wide is None or wide.empty:
        return vm(status="empty", message="No price data available.",
                  title="RRG", context=context)
    wide = wide.ffill()

    tail_data, full_data = q.compute_intra_group_rrg(
        wide, length_days, tail_length, group_config)
    if not tail_data:
        return vm(status="empty",
                  message=f"Not enough data for {req.group} intra-group RRG.",
                  title="RRG", context=context)

    name_color_map = q.intra_group_name_color_map(req.group)
    out = _shape(tail_data, full_data, name_color_map, context,
                 title=f"{req.group} — Intra-group Rotation")
    if out["figures"]:
        out["figures"][0]["layout"]["title"] = {
            "text": f"{req.group} — Intra-group Rotation", "font": {"size": 14}}
    return out


# --------------------------------------------------------------------------- #
# helpers — fetch + pivot
# --------------------------------------------------------------------------- #
def _futures_universe() -> list:
    seen, out = set(), []
    for cfg in q.FUTURES_GROUPS.values():
        for ticker in cfg["contracts"]:
            if ticker not in seen:
                seen.add(ticker)
                out.append(ticker)
    return out


def _wide_close(data, ids, period) -> Optional[pd.DataFrame]:
    """`data.time_series(ids)` -> wide `date × ticker` close frame.

    The DataSource returns the canonical `symbol × date` multi-index TimeSeries
    (spec §3); the quadrant maths want a wide `date × ticker` close frame, so we
    pivot here. ``period`` is not a `time_series` kwarg — the submodule owns the
    lookback; we keep it on the request for parity/echo and let the submodule fetch
    its default window.
    """
    panel = data.time_series(ids, fields=("close",))
    if panel is None or len(panel) == 0:
        return None
    close = panel["close"] if "close" in getattr(panel, "columns", []) else panel
    # symbol×date Series -> date×symbol wide frame.
    wide = close.unstack("symbol")
    # Preserve the requested column order where present.
    cols = [c for c in ids if c in wide.columns]
    return wide[cols] if cols else wide


# --------------------------------------------------------------------------- #
# ViewModel shaping (figures=[scatter], tables=[positions], meta)
# --------------------------------------------------------------------------- #
def _shape(tail_data, full_data, name_color_map, context, title) -> dict:
    fig = _scatter_figure(tail_data, name_color_map)
    table = _positions_table(tail_data, name_color_map)
    full_serialized = _serialize_full(full_data, name_color_map)
    all_dates = sorted({d for v in full_serialized.values() for d in v["dates"]})
    asof = all_dates[-1] if all_dates else None

    return vm(
        figures=[fig],
        tables=[table],
        status="ok",
        asof=asof,
        title=title,
        context=context,
        readouts={"assets": len(tail_data)},
        full_data=full_serialized,
        all_dates=all_dates,
    )


def _scatter_figure(tail_data, name_color_map) -> dict:
    """One RRG scatter figure (traces + quadrant-shaded layout).

    Relocated from rrg_service.build_rrg_traces (:117-185), reshaped into the spec
    §5.1 figure form `{id, traces, layout}`.
    """
    traces = []
    all_x, all_y = [], []
    for df in tail_data.values():
        all_x.extend(df["rs_ratio"].values)
        all_y.extend(df["rs_momentum"].values)

    margin = 0.3
    x_min = min(min(all_x), 100) - margin
    x_max = max(max(all_x), 100) + margin
    y_min = min(min(all_y), 100) - margin
    y_max = max(max(all_y), 100) + margin

    for key, df in tail_data.items():
        name, color = name_color_map.get(key, (key, "#999"))
        latest = df.iloc[-1]
        quadrant = q.get_quadrant(latest["rs_ratio"], latest["rs_momentum"])

        if len(df) > 1:
            traces.append({
                "type": "scatter", "mode": "lines",
                "x": [round(v, 3) for v in df["rs_ratio"]],
                "y": [round(v, 3) for v in df["rs_momentum"]],
                "line": {"color": color, "width": 1.5}, "opacity": 0.4,
                "showlegend": False, "hoverinfo": "skip", "legendgroup": key,
            })

        traces.append({
            "type": "scatter", "mode": "markers+text",
            "x": [round(float(latest["rs_ratio"]), 3)],
            "y": [round(float(latest["rs_momentum"]), 3)],
            "marker": {"size": 14, "color": color, "line": {"width": 2, "color": "white"}},
            "text": [name], "textposition": "top center",
            "textfont": {"size": 11, "color": color},
            "name": f"{name} ({quadrant})", "legendgroup": key,
            "hovertemplate": (f"<b>{name}</b><br>Quadrant: {quadrant}"
                              "<br>RS-Ratio: %{x:.2f}<br>RS-Mom: %{y:.2f}<extra></extra>"),
        })

    layout = {
        "height": 600,
        "xaxis": {"title": "RS-Ratio", "zeroline": False},
        "yaxis": {"title": "RS-Momentum", "zeroline": False},
        "legend": {"x": 1.02, "y": 1, "font": {"size": 10}},
        "margin": {"r": 200},
        "shapes": [
            {"type": "rect", "x0": 100, "y0": 100, "x1": x_max + 1, "y1": y_max + 1,
             "fillcolor": QUADRANT_COLORS["Leading"], "line_width": 0, "layer": "below"},
            {"type": "rect", "x0": 100, "y0": y_min - 1, "x1": x_max + 1, "y1": 100,
             "fillcolor": QUADRANT_COLORS["Weakening"], "line_width": 0, "layer": "below"},
            {"type": "rect", "x0": x_min - 1, "y0": y_min - 1, "x1": 100, "y1": 100,
             "fillcolor": QUADRANT_COLORS["Lagging"], "line_width": 0, "layer": "below"},
            {"type": "rect", "x0": x_min - 1, "y0": 100, "x1": 100, "y1": y_max + 1,
             "fillcolor": QUADRANT_COLORS["Improving"], "line_width": 0, "layer": "below"},
            {"type": "line", "x0": x_min - 1, "x1": x_max + 1, "y0": 100, "y1": 100,
             "line": {"color": "rgba(255,255,255,0.2)", "width": 1, "dash": "dash"}},
            {"type": "line", "x0": 100, "x1": 100, "y0": y_min - 1, "y1": y_max + 1,
             "line": {"color": "rgba(255,255,255,0.2)", "width": 1, "dash": "dash"}},
        ],
        "annotations": [
            {"x": 100 + (x_max - 100) * 0.5, "y": 100 + (y_max - 100) * 0.5,
             "text": "<b>LEADING</b>", "showarrow": False,
             "font": {"size": 14, "color": QUADRANT_TEXT_COLORS["Leading"]}},
            {"x": 100 + (x_max - 100) * 0.5, "y": y_min + (100 - y_min) * 0.5,
             "text": "<b>WEAKENING</b>", "showarrow": False,
             "font": {"size": 14, "color": QUADRANT_TEXT_COLORS["Weakening"]}},
            {"x": x_min + (100 - x_min) * 0.5, "y": y_min + (100 - y_min) * 0.5,
             "text": "<b>LAGGING</b>", "showarrow": False,
             "font": {"size": 14, "color": QUADRANT_TEXT_COLORS["Lagging"]}},
            {"x": x_min + (100 - x_min) * 0.5, "y": 100 + (y_max - 100) * 0.5,
             "text": "<b>IMPROVING</b>", "showarrow": False,
             "font": {"size": 14, "color": QUADRANT_TEXT_COLORS["Improving"]}},
        ],
    }
    return {"id": "rrg_scatter", "traces": traces, "layout": layout}


def _positions_table(tail_data, name_color_map) -> dict:
    """id-keyed positions table (spec §5.1) — relocated from build_positions_table."""
    columns = ["Asset", "Quadrant", "RS-Ratio", "RS-Mom"]
    rows = []
    for key, df in tail_data.items():
        name, _ = name_color_map.get(key, (key, "#999"))
        latest = df.iloc[-1]
        quadrant = q.get_quadrant(latest["rs_ratio"], latest["rs_momentum"])
        rows.append([
            name, quadrant,
            round(float(latest["rs_ratio"]), 2),
            round(float(latest["rs_momentum"]), 2),
        ])
    return {"id": "rrg_positions", "columns": columns, "rows": rows}


def _serialize_full(full_data, name_color_map) -> Dict[str, Any]:
    """Full RRG time series for client-side date replay (rrg_service:218-230)."""
    result = {}
    for key, df in full_data.items():
        name, color = name_color_map.get(key, (key, "#999"))
        dates = [d.strftime("%Y-%m-%d") for d in df.index]
        result[key] = {
            "name": name, "color": color, "dates": dates,
            "rs_ratio": [round(v, 3) for v in df["rs_ratio"]],
            "rs_momentum": [round(v, 3) for v in df["rs_momentum"]],
        }
    return result
