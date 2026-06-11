"""Screener blueprint — thin HTTP (spec §4.1).

The ONLY Flask-aware code in the section. Every route does exactly three things and
holds no business logic:

    GET /            -> render the screener shell (landing page)
    GET /screener    -> render the screener shell
    GET /api/screener-> ScreenRequest.from_query(args) -> handle(req, data, computed) -> jsonify

The providers (``data`` / ``computed``) are built once via the default factories and
injected into ``handle`` (spec §8) — the section stays method-agnostic and testable
with stubs; the blueprint is the wiring seam.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .service import ScreenRequest, handle

screener_bp = Blueprint(
    "screener", __name__, template_folder="templates"
)

# Lazily-built singletons (so importing the blueprint never opens a DB connection).
_PROVIDERS = {"data": None, "computed": None}


def _providers():
    """Build (once) and return the injected ``(data, computed)`` providers.

    Kept behind a function so the blueprint import is side-effect-free and tests can
    monkeypatch ``_PROVIDERS`` with stubs instead of touching the DB.
    """
    if _PROVIDERS["data"] is None:
        from datasource import build_default_datasource
        _PROVIDERS["data"] = build_default_datasource()
    if _PROVIDERS["computed"] is None:
        from computed import ComputedStore
        _PROVIDERS["computed"] = ComputedStore()
    return _PROVIDERS["data"], _PROVIDERS["computed"]


@screener_bp.route("/")
@screener_bp.route("/screener")
def screener_page():
    """Render the screener shell — the page is a placeholder + fetch->renderViewModel."""
    return render_template("screener.html", active_section="screener")


@screener_bp.route("/api/screener")
def screener_api():
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1)."""
    req = ScreenRequest.from_query(request.args)
    data, computed = _providers()
    vm_out = handle(req, data, computed)
    return jsonify(vm_out)
