"""Options blueprint — thin HTTP (spec §4.1).

The ONLY Flask-aware code in the section. Every route does exactly three things and
holds no business logic:

    GET /options                          -> render the GEX shell (page)
    GET /api/options/gex/<symbol>         -> OptionsRequest.from_query -> handle -> jsonify
    GET /api/options/drilldown/<symbol>   -> OptionsRequest.from_query -> handle -> jsonify

The provider (``data``) is built once via the default factory and injected into
``handle`` (spec §8) — the section stays method-agnostic and testable with a stub
``data.option_chain``; the blueprint is the wiring seam.

``handle`` returns the spec §5.1 ViewModel envelope (figures/tables/meta). The GEX
profile envelope carries the per-strike ``gex_strikes`` table; clicking a strike
row drills in via ``/api/options/drilldown/<symbol>?strike=...`` which returns the
per-contract breakdown (expiration / side / OI / IV / gamma / GEX) behind it.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .service import OptionsRequest, drilldown, handle

options_bp = Blueprint("options", __name__, template_folder="templates")

# Lazily-built singleton (importing the blueprint never opens a network/DB seam).
_PROVIDERS = {"data": None}


def _providers():
    """Build (once) and return the injected ``data`` provider.

    Behind a function so the blueprint import is side-effect-free and tests can
    monkeypatch ``_PROVIDERS`` with a stub instead of touching yfinance.
    """
    if _PROVIDERS["data"] is None:
        from datasource import build_default_datasource
        _PROVIDERS["data"] = build_default_datasource()
    return _PROVIDERS["data"]


@options_bp.route("/options")
def options_page():
    """Render the Options (GEX) shell — placeholder divs + fetch->renderViewModel."""
    sym = request.args.get("sym", "SPY")
    return render_template("options.html", active_section="options", default_sym=sym)


@options_bp.route("/api/options/gex/<symbol>")
def options_gex_api(symbol):
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1)."""
    req = OptionsRequest.from_query(symbol, request.args)
    return jsonify(handle(req, _providers()))


@options_bp.route("/api/options/drilldown/<symbol>")
def options_drilldown_api(symbol):
    """Per-strike drilldown — parse the ``strike``, return the per-contract rows
    (expiration / side / OI / IV / gamma / GEX) behind it (spec §4.1)."""
    req = OptionsRequest.from_query(symbol, request.args)
    return jsonify(drilldown(req, _providers()))
