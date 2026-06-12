"""Slice 13 boot smoke test — the integration capstone.

Builds the app via ``create_app()`` and drives a Flask test client across the key
routes asserting the app BOOTS and every route resolves with no 500 / no import
error. DB-backed routes work because ``MKTT_PG_DSN`` points at the reachable etc_db
(MKCompStore has 40 symbols, MKFund full); the test still tolerates a clean 4xx so
it does not become a DB-liveness test.
"""
from __future__ import annotations

import os

import pytest

# Ensure the DB-backed routes use the live etc_db DSN (FLAG-7).
os.environ.setdefault(
    "MKTT_PG_DSN", "postgresql://postgres:postgres@10.123.0.9:5432/etc_db"
)


@pytest.fixture(scope="module")
def client():
    import app as app_module
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


# (path, blueprint-owner) — the key routes that must resolve.
KEY_ROUTES = [
    "/",                       # screener_bp landing
    "/screener",               # screener_bp
    "/api/screener",           # screener_bp (DB-backed)
    "/options",                # options_bp page
    "/chart/AAPL",             # monitor_bp page
    "/macro",                  # macro_bp page
    "/rrg",                    # rrg_bp page
    "/watchlist",              # monitor_bp page
]


@pytest.mark.parametrize("path", KEY_ROUTES)
def test_key_route_no_500(client, path):
    """Every key route resolves (no import error, no unhandled 500)."""
    resp = client.get(path)
    assert resp.status_code != 500, f"{path} -> 500: {resp.get_data(as_text=True)[:300]}"
    # Route must be REGISTERED (no 404 from a missing blueprint).
    assert resp.status_code != 404, f"{path} -> 404 (route not registered)"


def test_app_factory_returns_fresh_app():
    """create_app() builds an independent Flask app each call."""
    import app as app_module
    a = app_module.create_app()
    b = app_module.create_app()
    assert a is not b
    # Module-level app is also present for WSGI servers.
    assert app_module.app is not None


def test_all_section_blueprints_registered():
    """The factory registers every section + the legacy blueprint."""
    import app as app_module
    flask_app = app_module.create_app()
    names = set(flask_app.blueprints)
    assert {"screener", "monitor", "options", "rrg", "macro", "legacy"} <= names


def test_legacy_endpoints_resolve(client):
    """The preserved legacy endpoints are registered (no 404 = route exists)."""
    legacy_paths = [
        "/api/rolling_12m/AAPL",
        "/api/sales_ttm_forward/AAPL",
        "/api/eps_ttm_forward/AAPL",
        "/api/revisions/AAPL",
        "/api/sector_map",
        "/api/freshness",
    ]
    for path in legacy_paths:
        resp = client.get(path)
        assert resp.status_code != 404, f"{path} -> 404 (legacy route lost)"
        assert resp.status_code != 500 or "error" in resp.get_data(as_text=True), (
            f"{path} -> unexpected 500"
        )


def test_options_api_route_registered(client):
    """The new options_bp API routes resolve (gex + drilldown)."""
    for path in ("/api/options/gex/SPY", "/api/options/drilldown/SPY?strike=500"):
        resp = client.get(path)
        assert resp.status_code != 404, f"{path} -> 404 (options route not registered)"
        assert resp.status_code != 500, f"{path} -> 500: {resp.get_data(as_text=True)[:200]}"


# --------------------------------------------------------------------------- #
# pool maxconn env-configurable (finding F1-4)
# --------------------------------------------------------------------------- #
def test_resolve_maxconn_default_and_env(monkeypatch):
    import app as app_module
    monkeypatch.delenv("MKTT_DB_MAXCONN", raising=False)
    assert app_module._resolve_maxconn(None) == app_module.DEFAULT_MAXCONN
    assert app_module.DEFAULT_MAXCONN >= 20         # raised from the old hard-coded 10
    assert app_module._resolve_maxconn(7) == 7      # explicit wins
    monkeypatch.setenv("MKTT_DB_MAXCONN", "55")
    assert app_module._resolve_maxconn(None) == 55
    monkeypatch.setenv("MKTT_DB_MAXCONN", "not-an-int")
    assert app_module._resolve_maxconn(None) == app_module.DEFAULT_MAXCONN


# --------------------------------------------------------------------------- #
# graceful DB/pool-error ViewModel instead of a bare 500 (finding F1-4)
# --------------------------------------------------------------------------- #
def test_db_error_returns_error_viewmodel_not_500():
    """A PoolError raised inside a route is mapped to a 503 + error ViewModel for a
    JSON/API route, not a bare 500."""
    import app as app_module
    from flask import Flask
    from psycopg2.pool import PoolError

    flask_app = Flask("dberr_test")
    app_module._register_db_error_handler(flask_app)

    @flask_app.route("/api/boom")
    def _boom():
        raise PoolError("connection pool exhausted")

    flask_app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    with flask_app.test_client() as c:
        resp = c.get("/api/boom")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body is not None
    assert body["meta"]["status"] == "error"
    assert "unavailable" in (body["meta"]["message"] or "").lower()


def test_db_error_page_route_soft_503():
    """A page (non-API) route degrades to a plain 503, not a 500."""
    import app as app_module
    from flask import Flask
    from psycopg2 import OperationalError

    flask_app = Flask("dberr_page_test")
    app_module._register_db_error_handler(flask_app)

    @flask_app.route("/screener")
    def _boom():
        raise OperationalError("db gone")

    flask_app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    with flask_app.test_client() as c:
        resp = c.get("/screener")
    assert resp.status_code == 503
    assert "unavailable" in resp.get_data(as_text=True).lower()
