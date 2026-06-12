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


def build_pooled_conn_factory(dsn: str, minconn: int = 0, maxconn: int = 10):
    """Build ONE shared ``ThreadedConnectionPool`` and return a zero-arg factory
    that hands out pooled connections (spec §8 DI: factory shape is unchanged, so
    every store keeps reading via ``conn_factory()`` — they just stop opening a
    fresh socket per request).

    ``minconn=0`` keeps the pool lazy — no socket is opened until the first request
    needs one (so ``import app`` / ``create_app()`` never touches the DB).

    Returns ``(factory, pool)`` so the caller can close the pool on shutdown.
    """
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(minconn, maxconn, dsn)
    logger.debug("connection pool built (min=%d max=%d) for %s", minconn, maxconn, dsn)

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
    computed = ComputedStore(conn_factory=conn_factory)
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

    return app


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
