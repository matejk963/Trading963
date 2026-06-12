"""
MKTT — Matej Krajcovic Trading Tool
Flask application factory (slice 13).

``create_app()`` builds the Flask app, wires the shared providers, and registers
every section blueprint plus the legacy blueprint:

- **DataSource** — built via ``build_default_datasource`` WITH a ``fund_conn_factory``
  (from ``MKTT_PG_DSN``, default the etc_db DSN) so the live screener/fundamentals
  work (Slice-7 FLAG). The fund-wired DataSource is injected into each section's
  lazy ``_PROVIDERS`` so the whole app shares one provider.
- **ComputedStore / ListStore** — the sections build these lazily; they already
  default to ``MKTT_PG_DSN`` / DEFAULT_DSN, so no wiring is needed here.

Blueprint URL ownership (no overlaps):
- ``screener_bp`` — ``/``, ``/screener``, ``/api/screener``
- ``monitor_bp``  — ``/chart/<symbol>``, ``/api/chart/<symbol>``, ``/api/monitor*``,
  ``/api/fundamentals/<symbol>``, ``/watchlist``, ``/api/watchlist``
- ``options_bp``  — ``/options``, ``/api/options/gex/<symbol>``,
  ``/api/options/drilldown/<symbol>``
- ``rrg_bp``      — ``/rrg``, ``/api/rrg``, ``/api/rrg/drill``
- ``macro_bp``    — ``/macro``, ``/macro/api/*``
- ``legacy_bp``   — the EPS/revenue/sector-map/freshness endpoints not yet owned by
  a section: ``/api/rolling_12m/<symbol>``, ``/api/sales_ttm_forward/<symbol>``,
  ``/api/eps_ttm_forward/<symbol>``, ``/api/revisions/<symbol>``, ``/api/sector_map``,
  ``/api/freshness``.

The pre-refactor monolith's per-route handlers now live in the section services
(Waves 1-3) and ``legacy_routes.py``; the old ``macro/`` package is left on disk but
its blueprint is no longer registered (the new ``macro_bp`` section supersedes it).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

logger = logging.getLogger(__name__)

# Live DSN (spec FLAG-7). Code reads MKTT_PG_DSN; this is the documented default.
DEFAULT_PG_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"


class _PooledConnection:
    """Thin proxy over a pooled psycopg2 connection.

    The stores (ComputedStore / ListStore / FundamentalsSubmodule) all follow the
    same lifecycle: ``conn = conn_factory(); ...; conn.close()``. To pool real
    connections WITHOUT touching that store code (DI seam preserved), ``close()``
    here returns the connection to the pool instead of tearing it down. Every other
    attribute (``cursor`` / ``commit`` / ``rollback`` / ``cursor_factory`` …)
    delegates straight to the wrapped connection.
    """

    __slots__ = ("_pool", "_conn", "_returned")

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def close(self):
        if not self._returned:
            self._returned = True
            self._pool.putconn(self._conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        # psycopg2 connections support `with conn:` (transaction scope); preserve it.
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)


#: Default pool ceiling (finding F1-4) — was 10, which could exhaust under a few
#: concurrent slow renders and 500 a route. Raised + made env-configurable via
#: ``MKTT_DB_MAXCONN`` so it can scale to expected concurrency without a code change.
DEFAULT_MAXCONN = 20


def _resolve_maxconn(maxconn: int | None) -> int:
    if maxconn is not None:
        return maxconn
    raw = os.environ.get("MKTT_DB_MAXCONN")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning("MKTT_DB_MAXCONN=%r not an int — using default %d", raw, DEFAULT_MAXCONN)
    return DEFAULT_MAXCONN


def build_pooled_conn_factory(dsn: str, minconn: int = 0, maxconn: int | None = None):
    """Build ONE shared ``ThreadedConnectionPool`` and return a zero-arg factory
    that hands out pooled connections (spec §8 DI: factory shape is unchanged, so
    every store keeps reading via ``conn_factory()`` — they just stop opening a
    fresh socket per request).

    ``minconn=0`` keeps the pool lazy — no socket is opened until the first request
    needs one (so ``import app`` / ``create_app()`` never touches the DB).

    ``maxconn`` defaults to ``MKTT_DB_MAXCONN`` env → :data:`DEFAULT_MAXCONN` (20),
    up from the old hard-coded 10 that could exhaust under concurrent slow renders
    and 500 a route (finding F1-4).

    Returns ``(factory, pool)`` so the caller can close the pool on shutdown.
    """
    from psycopg2.pool import ThreadedConnectionPool

    resolved_max = _resolve_maxconn(maxconn)
    pool = ThreadedConnectionPool(minconn, resolved_max, dsn)
    logger.debug("connection pool built (min=%d max=%d) for %s", minconn, resolved_max, dsn)

    def _factory():
        return _PooledConnection(pool, pool.getconn())

    return _factory, pool


def _build_fund_datasource(conn_factory):
    """Build the shared production DataSource WITH a fundamentals connection factory.

    The screener reads ``data.fundamentals(...)`` (MKFund) — that routing is only
    registered when ``build_default_datasource`` receives a ``fund_conn_factory``
    (Slice-7 FLAG). The ``conn_factory`` is the shared, pooled factory so
    fundamentals reads draw from the same pool as the classification stores.
    """
    from datasource import build_default_datasource

    return build_default_datasource(fund_conn_factory=conn_factory)


def _inject_shared_providers(data, conn_factory) -> None:
    """Seed each section's lazy ``_PROVIDERS`` with the shared, pool-backed
    providers so every section shares one DataSource AND one connection pool.

    - ``data`` (fund-wired DataSource) goes to every section.
    - ``computed`` (ComputedStore on the pooled factory) goes to the sections that
      read classifications (screener / monitor).
    - ``lists``    (ListStore on the pooled factory) goes to monitor (watchlist).

    Done at app-build time; sections imported here so their singleton dict exists.
    The pooled factory means DB reads stop opening a fresh connection per request.
    """
    from sections.screener import routes as screener_routes
    from sections.monitor import routes as monitor_routes
    from sections.options import routes as options_routes
    from sections.rrg import routes as rrg_routes
    from sections.macro import routes as macro_routes
    from computed import ComputedStore
    from lists import ListStore

    for mod in (screener_routes, monitor_routes, options_routes, rrg_routes, macro_routes):
        mod._PROVIDERS["data"] = data

    # Pool-backed stores shared across requests (one each, reused).
    # Wire the DataSource's last-bar-date as the staleness signal (finding F1-5) so
    # ensure_fresh flags a symbol whose stored MAX(date) lags the source last bar,
    # not only zero-history symbols.
    last_bar = getattr(data, "last_bar_date", None)
    if not callable(last_bar):
        # the provider doesn't re-export it — fall through to the equity submodule.
        equity = getattr(data, "_equity", None)
        last_bar = getattr(equity, "last_bar_date", None)
    computed = ComputedStore(
        conn_factory=conn_factory,
        last_bar_provider=last_bar if callable(last_bar) else None,
    )
    list_store = ListStore(conn_factory=conn_factory)
    for mod in (screener_routes, monitor_routes):
        if "computed" in mod._PROVIDERS:
            mod._PROVIDERS["computed"] = computed
    if "lists" in monitor_routes._PROVIDERS:
        monitor_routes._PROVIDERS["lists"] = list_store


_SECTION_DIRS = ("screener", "monitor", "options", "rrg", "macro")


def _prioritize_section_templates(app: Flask) -> None:
    """Make each section's ``templates/`` shell win over the pre-refactor app-level
    template of the same name.

    The new section shells (``sections/<name>/templates/<name>.html``) are the
    refactor's render-via-``renderViewModel`` pages. The legacy monolith left
    same-named templates in the app-level ``templates/`` folder (kept on disk), and
    Flask's default loader searches the app folder FIRST — shadowing the section
    shells. A ``ChoiceLoader`` that puts the section folders ahead of the app loader
    flips that precedence without touching any template file.
    """
    base = Path(__file__).parent / "sections"
    section_loaders = [
        FileSystemLoader(str(base / name / "templates"))
        for name in _SECTION_DIRS
        if (base / name / "templates").is_dir()
    ]
    app.jinja_loader = ChoiceLoader(section_loaders + [app.jinja_loader])


def create_app() -> Flask:
    """Application factory: build the Flask app, wire providers, register blueprints."""
    app = Flask(__name__)
    _prioritize_section_templates(app)

    # One shared connection pool (adr/0002) — injected into the fundamentals
    # DataSource + the ComputedStore/ListStore so DB reads draw from the pool
    # instead of opening a fresh socket per request. Pool kept on the app for
    # shutdown / introspection.
    dsn = os.environ.get("MKTT_PG_DSN") or DEFAULT_PG_DSN
    conn_factory, pool = build_pooled_conn_factory(dsn)
    app.config["MKTT_DB_POOL"] = pool

    # Shared, fund-wired DataSource (Slice-7 FLAG) injected into every section.
    data = _build_fund_datasource(conn_factory)
    _inject_shared_providers(data, conn_factory)

    # Section blueprints (Waves 1-3) — each owns a slice of the URL space.
    from sections.screener.routes import screener_bp
    from sections.monitor.routes import monitor_bp
    from sections.options.routes import options_bp
    from sections.rrg.routes import rrg_bp
    from sections.macro.routes import macro_bp
    from legacy_routes import legacy_bp, fmt_number

    app.register_blueprint(screener_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(options_bp)
    app.register_blueprint(rrg_bp)
    app.register_blueprint(macro_bp)
    app.register_blueprint(legacy_bp)

    # Jinja helpers carried over from the monolith.
    app.jinja_env.globals["fmt_number"] = fmt_number

    @app.context_processor
    def _inject_now():
        return {"now": datetime.utcnow()}

    _register_db_error_handler(app)

    return app


def _register_db_error_handler(app: Flask) -> None:
    """Turn a pool-exhaustion / DB error into a graceful error ViewModel, not a 500
    (finding F1-4).

    Under concurrent slow renders ``pool.getconn()`` raises ``PoolError`` and any
    other DB hiccup raises ``psycopg2.Error``; with no handler these propagate out of
    the store read and 500 the route. This catch-all maps those failures to:

    - **JSON/API routes** (``/api/*`` or an XHR ``Accept: application/json``): a
      spec §5.1 ``vm(status='error', …)`` envelope with HTTP 503, so the generic
      client renderer shows the error banner instead of a broken page.
    - **page routes**: a small plain-text 503 so the browser shows a soft failure.

    Other exception types are left to Flask's default 500 (real bugs stay loud).
    """
    from flask import jsonify, request
    from viewmodel import vm

    try:
        from psycopg2 import Error as _PgError
        from psycopg2.pool import PoolError as _PoolError
        _DB_ERRORS = (_PoolError, _PgError)
    except Exception:  # pragma: no cover - psycopg2 always present in prod
        _DB_ERRORS = ()

    if not _DB_ERRORS:
        return

    def _wants_json() -> bool:
        path = request.path or ""
        if path.startswith("/api/") or "/api/" in path or path.endswith("/api"):
            return True
        accept = request.headers.get("Accept", "")
        return "application/json" in accept and "text/html" not in accept

    def _on_db_error(err):  # noqa: ANN001
        logger.warning("DB/pool error on %s: %s", request.path, err)
        message = "Data store temporarily unavailable — please retry."
        if _wants_json():
            envelope = vm(status="error", message=message,
                          title="Service unavailable",
                          context={"path": request.path})
            resp = jsonify(envelope)
            resp.status_code = 503
            return resp
        return (message, 503, {"Content-Type": "text/plain; charset=utf-8"})

    # Flask wants one registration per exception class (no tuples).
    for exc_cls in _DB_ERRORS:
        app.register_error_handler(exc_cls, _on_db_error)
    return


# Module-level app so `flask run` / WSGI servers find `app`.
app = create_app()


if __name__ == "__main__":
    # Auto-update prices in background thread (non-blocking).
    import threading

    def _bg_update():
        from data_manager import auto_update_if_stale
        try:
            auto_update_if_stale(max_age_hours=16)
        except Exception as e:
            print(f"  Auto-update skipped: {e}")

    threading.Thread(target=_bg_update, daemon=True).start()

    app.run(debug=True, port=5001, use_reloader=True, reloader_type="stat")
