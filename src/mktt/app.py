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

import os
from datetime import datetime
from pathlib import Path

from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

# Live DSN (spec FLAG-7). Code reads MKTT_PG_DSN; this is the documented default.
DEFAULT_PG_DSN = "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"


def _build_fund_datasource():
    """Build the shared production DataSource WITH a fundamentals connection factory.

    The screener reads ``data.fundamentals(...)`` (MKFund) — that routing is only
    registered when ``build_default_datasource`` receives a ``fund_conn_factory``
    (Slice-7 FLAG). The DSN resolves explicit → ``MKTT_PG_DSN`` → :data:`DEFAULT_PG_DSN`.
    """
    from datasource import build_default_datasource
    from computed.store import build_conn_factory

    dsn = os.environ.get("MKTT_PG_DSN") or DEFAULT_PG_DSN
    fund_conn_factory = build_conn_factory(dsn)
    return build_default_datasource(fund_conn_factory=fund_conn_factory)


def _inject_shared_datasource(data) -> None:
    """Seed each section's lazy ``_PROVIDERS["data"]`` with the shared, fund-wired
    DataSource so every section shares one provider (and the screener gets
    fundamentals routing). Done before first request; sections that have not been
    imported yet are imported here so their singleton dict exists."""
    from sections.screener import routes as screener_routes
    from sections.monitor import routes as monitor_routes
    from sections.options import routes as options_routes
    from sections.rrg import routes as rrg_routes
    from sections.macro import routes as macro_routes

    for mod in (screener_routes, monitor_routes, options_routes, rrg_routes, macro_routes):
        mod._PROVIDERS["data"] = data


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

    # Shared, fund-wired DataSource (Slice-7 FLAG) injected into every section.
    data = _build_fund_datasource()
    _inject_shared_datasource(data)

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
