"""Options section — thin manager (spec §4.2, §5).

`options.handle(req, data)` is the **recipe**: read the `OptionChain` form from the
injected `DataSource`, call the PRIVATE `gex_engine` deep core (untouched — parity),
and wrap the result in the spec §5.1 ViewModel envelope. It holds **no** GEX math
(that is ``gex_engine``) and **no** fetch logic (that is ``data.option_chain``) —
just the wiring.

ViewModel mapping (spec §5.1):
- ``figures``  — one GEX profile figure: per-strike net/call/put GEX bars (Plotly-ready).
- ``tables``   — the strike table (call/put/net GEX + OI) and the walls summary.
- ``meta.readouts`` — headline scalars as badges: ``gamma_flip``, ``total_gex``,
  ``call_wall``, ``put_wall``, ``regime``, ``spot``.
- ``meta.status`` — ``"ok"`` normally, ``"stale"`` when the chain came from stale
  cache (live fetch failed), ``"empty"`` when no strikes survive the band filter,
  ``"error"`` when the chain cannot be fetched at all.
- ``meta.context`` — echo of the request (symbol / band / expirations).

Dependency injection (spec §8): ``handle(req, data)`` receives its provider, so tests
pass a stub ``data`` exposing ``option_chain(...)`` — no Flask, no DB, no network.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import gex_engine

from viewmodel import num, vm

logger = logging.getLogger("mktt.sections.options")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

DEFAULT_N_EXP = 4
DEFAULT_BAND_PCT = 0.15

# Strike-band selector value -> fraction of spot (None = "all", no filter).
# Mirrors app.py:_GEX_BANDS so the section is band-key compatible with today.
_BANDS = {"5": 0.05, "10": 0.10, "15": 0.15, "25": 0.25, "all": None}


@dataclass(frozen=True)
class OptionsRequest:
    """Typed Options request (built by the blueprint from query args — spec §4.1).

    The section is Flask-free and method-agnostic: parsing lives in
    :meth:`from_query`; ``handle`` only ever sees this record.
    """

    symbol: str
    band_pct: Optional[float] = DEFAULT_BAND_PCT
    n_exp: int = DEFAULT_N_EXP
    expirations: Optional[List[str]] = None
    force_refresh: bool = False
    band_key: str = "15"

    @classmethod
    def from_query(cls, symbol: str, args) -> "OptionsRequest":
        """Build a request from a symbol + a query-args mapping (``request.args``).

        ``args.get`` may be Flask's ``MultiDict.get`` or a plain ``dict.get``; both
        support ``get(key, default)``.
        """
        band_key = (args.get("band", "15") or "15")
        band_pct = _BANDS.get(band_key, DEFAULT_BAND_PCT)
        try:
            n_exp = int(args.get("n_exp", DEFAULT_N_EXP))
        except (TypeError, ValueError):
            n_exp = DEFAULT_N_EXP
        exps = _parse_exps(args.get("exps", ""))
        refresh = (args.get("refresh", "0") or "0") in ("1", "true", "yes")
        return cls(
            symbol=str(symbol).upper().strip(),
            band_pct=band_pct,
            n_exp=n_exp,
            expirations=exps,
            force_refresh=refresh,
            band_key=band_key,
        )


def _parse_exps(raw):
    """Comma-separated expirations -> list (or None for default first-N)."""
    if not raw:
        return None
    exps = [e.strip() for e in str(raw).split(",") if e.strip()]
    return exps or None


# --------------------------------------------------------------------------- #
# handle — the recipe
# --------------------------------------------------------------------------- #
def handle(req: OptionsRequest, data) -> dict:
    """Read the `OptionChain`, compute the GEX profile, shape the ViewModel.

    Parameters
    ----------
    req:
        The typed :class:`OptionsRequest`.
    data:
        A `DataSource` (or stub) exposing ``option_chain(symbol, n_exp, expirations,
        force_refresh) -> OptionChain``.
    """
    context = {
        "symbol": req.symbol,
        "band": req.band_key,
        "expirations": req.expirations,
    }
    logger.debug("options.handle symbol=%s band=%s n_exp=%s exps=%s",
                 req.symbol, req.band_key, req.n_exp, req.expirations)

    try:
        chain = data.option_chain(
            req.symbol,
            n_exp=req.n_exp,
            expirations=req.expirations,
            force_refresh=req.force_refresh,
        )
    except Exception as e:  # noqa: BLE001 — provider boundary -> error envelope
        logger.debug("options.handle fetch failed for %s: %s", req.symbol, e)
        return vm(
            status="error",
            message=str(e),
            title=f"{req.symbol} — GEX",
            context=context,
        )

    profile = gex_engine.compute_profile(
        chain.chains, chain.spot, band_pct=req.band_pct
    )

    meta = dict(chain.meta or {})
    asof = meta.get("oi_as_of")
    stale = bool(meta.get("stale"))
    strikes = profile["strikes"]

    if not strikes:
        status = "stale" if stale else "empty"
        message = meta.get("warning") or "No option strikes within the selected band."
        return vm(
            tables=[_walls_table(profile)],
            status=status,
            message=message,
            asof=asof,
            title=f"{req.symbol} — GEX",
            context=context,
            readouts=_readouts(profile),
            expirations=chain.expirations,
            available_expirations=chain.available_expirations,
            default_expirations=chain.default_expirations,
            disclosure=meta,
        )

    status = "stale" if stale else "ok"
    message = meta.get("warning")

    return vm(
        figures=[_gex_figure(req.symbol, profile)],
        tables=[_strike_table(profile), _walls_table(profile)],
        status=status,
        message=message,
        asof=asof,
        title=f"{req.symbol} — GEX",
        context=context,
        readouts=_readouts(profile),
        expirations=chain.expirations,
        available_expirations=chain.available_expirations,
        default_expirations=chain.default_expirations,
        disclosure=meta,
    )


# --------------------------------------------------------------------------- #
# ViewModel shaping helpers
# --------------------------------------------------------------------------- #
def _readouts(profile) -> dict:
    """Headline scalars -> badges (spec §5.1)."""
    return {
        "gamma_flip": num(profile.get("flip")),
        "total_gex": num(profile.get("total_gex")),
        "call_wall": num(profile.get("call_wall")),
        "put_wall": num(profile.get("put_wall")),
        "regime": profile.get("regime"),
        "spot": num(profile.get("spot")),
    }


def _gex_figure(symbol, profile) -> dict:
    """One Plotly-ready figure: per-strike call/put/net GEX bars."""
    strikes = profile["strikes"]
    x = [s["strike"] for s in strikes]
    return {
        "id": "gex_profile",
        "traces": [
            {"type": "bar", "name": "Call GEX", "x": x,
             "y": [s["call_gex"] for s in strikes]},
            {"type": "bar", "name": "Put GEX", "x": x,
             "y": [s["put_gex"] for s in strikes]},
            {"type": "scatter", "mode": "lines+markers", "name": "Net GEX", "x": x,
             "y": [s["net_gex"] for s in strikes]},
        ],
        "layout": {
            "title": f"{symbol} net-GEX profile",
            "barmode": "relative",
            "xaxis": {"title": "Strike"},
            "yaxis": {"title": "$ gamma per +1% move"},
            "shapes": _spot_flip_shapes(profile),
        },
    }


def _spot_flip_shapes(profile):
    """Vertical reference lines for spot and the gamma flip."""
    shapes = []
    spot = profile.get("spot")
    if spot is not None:
        shapes.append({"type": "line", "x0": spot, "x1": spot, "yref": "paper",
                       "y0": 0, "y1": 1, "line": {"dash": "dot"}, "name": "spot"})
    flip = profile.get("flip")
    if flip is not None:
        shapes.append({"type": "line", "x0": flip, "x1": flip, "yref": "paper",
                       "y0": 0, "y1": 1, "line": {"dash": "dash"}, "name": "flip"})
    return shapes


def _strike_table(profile) -> dict:
    """The per-strike GEX table (id-keyed — spec §5.1)."""
    return {
        "id": "gex_strikes",
        "columns": ["strike", "call_gex", "put_gex", "net_gex", "oi"],
        "rows": [
            [s["strike"], s["call_gex"], s["put_gex"], s["net_gex"], s["oi"]]
            for s in profile["strikes"]
        ],
    }


def _walls_table(profile) -> dict:
    """The walls / flip / regime summary table."""
    return {
        "id": "gex_walls",
        "columns": ["metric", "value"],
        "rows": [
            ["call_wall", profile.get("call_wall")],
            ["put_wall", profile.get("put_wall")],
            ["gamma_flip", profile.get("flip")],
            ["total_gex", profile.get("total_gex")],
            ["regime", profile.get("regime")],
        ],
    }
