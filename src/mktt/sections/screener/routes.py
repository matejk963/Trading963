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

from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from .service import (
    ScreenRequest,
    cross_section_version,
    handle,
    handle_page,
    price_panel_version,
)

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
    """Server-render the screener (adr/0002): parse -> handle_page -> render the
    revived Jinja template with the colored results table + rich filter form."""
    req = ScreenRequest.from_query(request.args)
    data, computed = _providers()
    ctx = handle_page(req, data, computed)
    return render_template("screener.html", **ctx)


@screener_bp.route("/api/screener")
def screener_api():
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1)."""
    req = ScreenRequest.from_query(request.args)
    data, computed = _providers()
    vm_out = handle(req, data, computed)
    return jsonify(vm_out)


@screener_bp.route("/api/screener/version")
def screener_version():
    """Combined freshness token ``"<cross_section_version>:<price_panel_version>"``.

    Thin: reads the two provider freshness tokens (cross-section version bumped on
    Writer upsert + price-parquet mtime) so the client keep-alive (Slice 3) can
    validate a cached snapshot against the live data without a heavy round-trip.
    """
    data, computed = _providers()
    token = (f"{cross_section_version(computed)}:{price_panel_version(data)}"
             f":{_asset_version()}")
    return jsonify({"version": token})


#: Screener client assets — the template + JS that render the page. Their newest
#: mtime is folded into the freshness token so a CODE/TEMPLATE deploy (e.g. adding
#: a filter) bumps the version and invalidates a stale client keep-alive snapshot
#: (whose token would otherwise still match on unchanged DATA — the bug where new
#: filters didn't appear until a hard reload). Best-effort; missing files skipped.
def _asset_version() -> str:
    here = Path(__file__).resolve()
    root = here.parents[2]  # src/mktt
    files = (
        here.parent / "templates" / "screener.html",
        root / "static" / "js" / "screener.js",
        root / "static" / "js" / "keepalive.js",
        root / "templates" / "base.html",
    )
    newest = 0.0
    for f in files:
        try:
            m = f.stat().st_mtime
            if m > newest:
                newest = m
        except OSError:
            pass
    return str(round(newest, 3))
