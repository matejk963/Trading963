"""Macro blueprint — thin HTTP (spec §4.1).

The ONLY Flask-aware code in the section. Every route does exactly three things and
holds no business logic:

    GET /macro                  -> render the Macro shell (page)
    GET /macro/api/liquidity    -> MacroRequest(view=liquidity)    -> handle -> jsonify
    GET /macro/api/layer/<id>   -> MacroRequest(view=layer, ...)    -> handle -> jsonify
    GET /macro/api/overlay      -> MacroRequest(view=overlay, ...)  -> handle -> jsonify
    GET /macro/api/transmission -> MacroRequest(view=transmission)  -> handle -> jsonify

The provider (``data``) is built once via the default factory and injected into
``handle`` (spec §8) — the section stays method-agnostic and testable with a stub
``data.time_series``; the blueprint is the wiring seam. There is **no streamlit
import** anywhere in this section.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .service import MacroRequest, handle

macro_bp = Blueprint("macro", __name__, template_folder="templates")

# Lazily-built singleton (importing the blueprint never opens a network/DB seam).
_PROVIDERS = {"data": None}


def _providers():
    """Build (once) and return the injected ``data`` provider.

    Behind a function so the blueprint import is side-effect-free and tests can
    monkeypatch ``_PROVIDERS`` with a stub instead of touching the CSV/yfinance.
    """
    if _PROVIDERS["data"] is None:
        from datasource import build_default_datasource
        _PROVIDERS["data"] = build_default_datasource()
    return _PROVIDERS["data"]


@macro_bp.route("/macro")
def macro_page():
    """Render the Macro shell — placeholder divs + fetch->renderViewModel."""
    view = request.args.get("view", "liquidity")
    return render_template("macro.html", active_section="macro", active_view=view)


@macro_bp.route("/macro/api/liquidity")
def liquidity_api():
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1)."""
    req = MacroRequest(view="liquidity")
    return jsonify(handle(req, _providers()))


@macro_bp.route("/macro/api/layer/<layer_id>")
def layer_api(layer_id):
    req = MacroRequest(view="layer", layer=layer_id)
    return jsonify(handle(req, _providers()))


@macro_bp.route("/macro/api/overlay")
def overlay_api():
    asset = request.args.get("asset", "SPY")
    req = MacroRequest(view="overlay", asset=asset)
    return jsonify(handle(req, _providers()))


@macro_bp.route("/macro/api/transmission")
def transmission_api():
    req = MacroRequest(view="transmission")
    return jsonify(handle(req, _providers()))
