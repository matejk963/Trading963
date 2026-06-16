"""Monitor blueprint — thin HTTP (spec §4.1).

The ONLY Flask-aware code in the section. Every route does exactly three things and
holds no business logic:

    GET  /chart/<symbol>            -> page shell
    GET  /api/chart/<symbol>        -> MonitorRequest.from_symbol -> handle -> jsonify
    GET  /api/fundamentals/<symbol> -> handle -> jsonify (same envelope, focus client-side)
    GET  /api/monitor/<symbol>      -> handle -> jsonify (alias)
    POST /api/monitor               -> MonitorRequest.from_form(sym=[...]) -> handle (multi)
    GET  /watchlist                 -> watchlist page shell
    GET  /api/watchlist?list=…      -> watchlist_members(lists, list) -> jsonify
    POST /api/watchlist {list,symbol,action} -> watchlist_add/remove(lists, …) -> jsonify

GET-default keeps chart URLs shareable; POST carries the large symbol list (spec
§4.1). Providers (``data`` / ``computed`` / ``kernel`` / ``lists``) are built once
via the default factories and injected into ``handle`` (spec §8) — the section
stays method-agnostic and testable with stubs.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import service
from .service import MonitorRequest, handle

monitor_bp = Blueprint("monitor", __name__, template_folder="templates")

# Lazily-built singletons (importing the blueprint never opens a DB connection).
_PROVIDERS = {"data": None, "computed": None, "kernel": None, "lists": None}


def _providers():
    """Build (once) and return the injected providers.

    Behind a function so the import is side-effect-free and tests can monkeypatch
    ``_PROVIDERS`` with stubs instead of touching the DB / network.
    """
    if _PROVIDERS["data"] is None:
        from datasource import build_default_datasource
        _PROVIDERS["data"] = build_default_datasource()
    if _PROVIDERS["computed"] is None:
        from computed import ComputedStore
        _PROVIDERS["computed"] = ComputedStore()
    if _PROVIDERS["kernel"] is None:
        import kernel
        _PROVIDERS["kernel"] = kernel
    if _PROVIDERS["lists"] is None:
        from lists import ListStore
        _PROVIDERS["lists"] = ListStore()
    return (
        _PROVIDERS["data"], _PROVIDERS["computed"],
        _PROVIDERS["kernel"], _PROVIDERS["lists"],
    )


# ------------------------------------------------------------------ #
# per-security view
# ------------------------------------------------------------------ #
@monitor_bp.route("/monitor")
@monitor_bp.route("/monitor/<symbol>")
def monitor_page(symbol=None):
    """Render the unified workspace shell (detail pane left + rail right).

    ``/monitor`` is the bare workspace; ``/monitor/<symbol>`` deep-links a name
    into the detail pane (Slice 1)."""
    return render_template("monitor.html", symbol=symbol, active_section="monitor")


@monitor_bp.route("/chart/<symbol>")
def chart_page(symbol):
    """Deep-link retired -> 302 to the workspace (old bookmarks don't 404)."""
    return redirect(url_for("monitor.monitor_page", symbol=symbol))


@monitor_bp.route("/api/chart/<symbol>")
@monitor_bp.route("/api/monitor/<symbol>")
@monitor_bp.route("/api/fundamentals/<symbol>")
def monitor_api(symbol):
    """Parse -> handle -> jsonify (the three-line thin route, spec §4.1).

    The chart / fundamentals / history figures all live in one envelope; the
    client renders the slice it needs by figure/table id."""
    data, computed, kernel, lists = _providers()
    vm_out = handle(MonitorRequest.from_symbol(symbol), data, computed, kernel, lists)
    return jsonify(vm_out)


@monitor_bp.route("/api/monitor", methods=["POST"])
def monitor_multi_api():
    """POST multi-symbol (large list) -> handle -> jsonify (spec §4.1)."""
    args = _form_args()
    data, computed, kernel, lists = _providers()
    vm_out = handle(MonitorRequest.from_form(args), data, computed, kernel, lists)
    return jsonify(vm_out)


@monitor_bp.route("/api/monitor/fundamentals/<symbol>")
def monitor_fundamentals_api(symbol):
    """Focused fundamental 2x2 payload (Slice 4 / #11) -> jsonify.

    A separate endpoint from the full monitor envelope so a granularity toggle
    re-renders ONLY the EPS/Sales (PE/PS later) figures, never the candle chart.
    ``?granularity=Q|Y|TTM`` (default ``Q``) + ``?asof=YYYY-MM-DD`` (default latest)
    thread straight into ``fundamentals_view`` (the thin parse->service route)."""
    data, _, _, _ = _providers()
    granularity = request.args.get("granularity") or "Q"
    asof = request.args.get("asof") or None
    return jsonify(service.fundamentals_view(symbol, data, granularity=granularity, asof=asof))


@monitor_bp.route("/api/monitor/revisions/<symbol>")
def monitor_revisions_api(symbol):
    """Focused Estimate-Revisions payload (Slice 7) -> jsonify.

    A faithful replica of the original app's Revisions view (two EPS charts).
    Granularity-independent (not subject to the Q/Y/TTM toggle). ``?n=N`` (default 3)
    sets how many forward-TTM revision snapshots to draw; ``?asof=YYYY-MM-DD``
    (default latest) threads into ``revisions_view`` (the thin parse->service route)."""
    data, _, _, _ = _providers()
    try:
        n = int(request.args.get("n", 3))
    except (TypeError, ValueError):
        n = 3
    asof = request.args.get("asof") or None
    return jsonify(service.revisions_view(symbol, data, n=n, asof=asof))


@monitor_bp.route("/api/monitor/rail")
def monitor_rail_api():
    """Saved-instrument rail VM (Slice 1) -> jsonify (the thin parse->service route)."""
    _, computed, _, lists = _providers()
    list_name = request.args.get("list") or service.DEFAULT_LIST
    return jsonify(service.rail(lists, computed, list_name))


# ------------------------------------------------------------------ #
# watchlist — Monitor reads the shared lists; add/remove proxy to the store
# ------------------------------------------------------------------ #
@monitor_bp.route("/watchlist")
def watchlist_page():
    """Standalone watchlist retired -> 302 to the unified workspace (Slice 1)."""
    return redirect(url_for("monitor.monitor_page"))


@monitor_bp.route("/api/watchlist", methods=["GET", "POST"])
def watchlist_api():
    """GET reads members; POST add/remove — both proxy to the injected store."""
    _, _, _, lists = _providers()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        list_name = body.get("list") or service.DEFAULT_LIST
        symbol = body.get("symbol", "")
        action = (body.get("action") or "add").lower()
        if action == "remove":
            vm_out = service.watchlist_remove(lists, list_name, symbol)
        else:
            vm_out = service.watchlist_add(lists, list_name, symbol, note=body.get("note"))
        return jsonify(vm_out)

    list_name = request.args.get("list") or service.DEFAULT_LIST
    return jsonify(service.watchlist_members(lists, list_name))


def _form_args():
    """Unify POST form / JSON into a ``getlist``-capable args object.

    Flask ``request.form`` already exposes ``getlist``; a JSON body of
    ``{"sym": [...]}`` is wrapped so ``MonitorRequest.from_form`` sees the same
    interface (the section stays method-agnostic — spec §4.1)."""
    if request.form:
        return request.form
    body = request.get_json(silent=True) or {}

    class _JsonArgs:
        def __init__(self, d):
            self._d = d

        def get(self, key, default=None):
            return self._d.get(key, default)

        def getlist(self, key):
            v = self._d.get(key)
            if isinstance(v, (list, tuple)):
                return list(v)
            return [v] if v else []

    return _JsonArgs(body)
