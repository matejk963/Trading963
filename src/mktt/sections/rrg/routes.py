"""RRG blueprint — thin HTTP (spec §4.1).

The ONLY Flask-aware code in the section. Every route does exactly three things and
holds no business logic:

    GET /rrg            -> render the RRG shell (page)
    GET /api/rrg        -> RrgRequest.from_query(args) -> handle(req, data) -> jsonify
    GET /api/rrg/drill  -> RrgRequest.from_query(args) (with group) -> handle -> jsonify

The provider (``data``) is built once via the default factory and injected into
``handle`` (spec §8) — the section stays method-agnostic and testable with a stub
``data.time_series``; the blueprint is the wiring seam. There is **no streamlit
import** anywhere in this section.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .service import RrgRequest, handle

rrg_bp = Blueprint("rrg", __name__, template_folder="templates")

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


@rrg_bp.route("/rrg")
def rrg_page():
    """Render the RRG shell — placeholder divs + fetch->renderViewModel.

    The futures drill groups are passed so the (futures-only) drill dropdown can
    be populated from the PRIVATE quadrant config instead of hard-coding labels.
    """
    from . import quadrant as q
    return render_template("rrg.html", active_section="rrg",
                           futures_groups=list(q.FUTURES_GROUPS.keys()))


@rrg_bp.route("/api/rrg")
def rrg_api():
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1)."""
    req = RrgRequest.from_query(request.args)
    data = _providers()
    return jsonify(handle(req, data))


@rrg_bp.route("/api/rrg/drill")
def rrg_drill_api():
    """Intra-group drill-down — same parse/handle/jsonify; `group` set in the query."""
    req = RrgRequest.from_query(request.args)
    data = _providers()
    return jsonify(handle(req, data))
