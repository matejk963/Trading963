"""Integration tests for the /api/options/* routes via the Flask test client.

Slice 13 re-points these URLs at the refactored Options section (`options_bp` ->
`options.handle`), so the response is now the spec §5.1 **ViewModel envelope**
(figures/tables/meta) rather than the pre-refactor raw GEX dict. The provider is a
STUB `DataSource` (exposing `option_chain(...)`) injected into the blueprint's
`_PROVIDERS` — no yfinance / network. (The legacy raw-dict route contract is
superseded; the section's pure-`handle` coverage lives in test_options_section.py.)
"""
import pytest

import app as app_module
from datasource import OptionChain
from sections.options import routes as options_routes


_AVAILABLE = ["2026-06-01", "2026-06-06", "2026-06-13", "2026-06-20",
              "2026-06-27", "2026-07-18"]

_ALL_CHAINS = {
    "2026-06-01": {"expiration": "2026-06-01", "dte": 2,
                   "calls": [{"strike": 95, "oi": 1000, "iv": 0.2},
                             {"strike": 100, "oi": 5000, "iv": 0.2},
                             {"strike": 105, "oi": 3000, "iv": 0.2},
                             {"strike": 130, "oi": 2000, "iv": 0.2}],  # outside ±15%
                   "puts": [{"strike": 95, "oi": 2000, "iv": 0.22},
                            {"strike": 100, "oi": 800, "iv": 0.22}]},
    "2026-06-06": {"expiration": "2026-06-06", "dte": 7,
                   "calls": [{"strike": 100, "oi": 4000, "iv": 0.21}],
                   "puts": [{"strike": 100, "oi": 1500, "iv": 0.23}]},
    "2026-06-13": {"expiration": "2026-06-13", "dte": 14,
                   "calls": [{"strike": 105, "oi": 2500, "iv": 0.22}], "puts": []},
    "2026-06-20": {"expiration": "2026-06-20", "dte": 21,
                   "calls": [{"strike": 110, "oi": 1800, "iv": 0.23}], "puts": []},
    "2026-06-27": {"expiration": "2026-06-27", "dte": 28,
                   "calls": [{"strike": 100, "oi": 900, "iv": 0.24}], "puts": []},
    "2026-07-18": {"expiration": "2026-07-18", "dte": 49,
                   "calls": [{"strike": 100, "oi": 700, "iv": 0.26}], "puts": []},
}


class _StubData:
    """Returns a fixed OptionChain shaped from the selected expirations (BADSYM
    raises so the error envelope is exercised)."""

    def option_chain(self, symbol, n_exp=4, expirations=None, force_refresh=False):
        if symbol.upper() == "BADSYM":
            raise RuntimeError("No option expirations available for BADSYM")
        if expirations:
            selected = [e for e in expirations if e in _ALL_CHAINS] or _AVAILABLE[:n_exp]
        else:
            selected = _AVAILABLE[:n_exp]
        return OptionChain(
            symbol=symbol.upper(),
            spot=100.0,
            chains=[_ALL_CHAINS[e] for e in selected],
            expirations=selected,
            available_expirations=_AVAILABLE,
            default_expirations=_AVAILABLE[:4],
            meta={"fetched_at": "2026-05-30 06:00:00", "oi_as_of": "2026-05-29 close",
                  "stale": False, "warning": None},
        )


@pytest.fixture
def client():
    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    # Inject the stub provider into the options blueprint (no network).
    options_routes._PROVIDERS["data"] = _StubData()
    try:
        with flask_app.test_client() as c:
            yield c
    finally:
        options_routes._PROVIDERS["data"] = None


def _readouts(d):
    return d["meta"]["readouts"]


def _strike_rows(d):
    t = next(t for t in d["tables"] if t["id"] == "gex_strikes")
    return [dict(zip(t["columns"], row)) for row in t["rows"]]


# --------------------------------------------------------------------------- #
# /api/options/gex  (ViewModel envelope)
# --------------------------------------------------------------------------- #
def test_gex_returns_viewmodel_contract(client):
    resp = client.get("/api/options/gex/SPY?band=15")
    assert resp.status_code == 200
    d = resp.get_json()
    assert set(d.keys()) == {"figures", "tables", "meta"}
    r = _readouts(d)
    assert d["meta"]["context"]["symbol"] == "SPY"
    assert r["spot"] == 100.0
    assert r["regime"] in ("positive", "negative")
    assert {"gamma_flip", "call_wall", "put_wall", "total_gex"} <= set(r)
    assert d["meta"]["asof"] == "2026-05-29 close"
    # default selection = first 4 of the available list
    assert d["meta"]["expirations"] == _AVAILABLE[:4]
    assert d["meta"]["available_expirations"] == _AVAILABLE
    assert d["meta"]["default_expirations"] == _AVAILABLE[:4]
    for s in _strike_rows(d):
        assert {"strike", "call_gex", "put_gex", "net_gex", "oi"} <= set(s.keys())


def test_gex_respects_expiration_selection(client):
    resp = client.get("/api/options/gex/SPY?exps=2026-06-06,2026-07-18")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["meta"]["expirations"] == ["2026-06-06", "2026-07-18"]
    assert d["meta"]["available_expirations"] == _AVAILABLE


def test_gex_band_filter_excludes_far_strikes(client):
    tight = client.get("/api/options/gex/SPY?band=15").get_json()
    assert 130 not in [s["strike"] for s in _strike_rows(tight)]
    wide = client.get("/api/options/gex/SPY?band=all").get_json()
    assert 130 in [s["strike"] for s in _strike_rows(wide)]


def test_gex_invalid_symbol_yields_error_envelope(client):
    resp = client.get("/api/options/gex/BADSYM")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["meta"]["status"] == "error"
    assert "BADSYM" in d["meta"]["message"]


# --------------------------------------------------------------------------- #
# /api/options/drilldown  (per-contract breakdown behind one strike)
# --------------------------------------------------------------------------- #
def _drill_rows(d):
    t = next(t for t in d["tables"] if t["id"] == "gex_drill")
    return [dict(zip(t["columns"], row)) for row in t["rows"]]


def test_drilldown_returns_per_contract_rows(client):
    resp = client.get("/api/options/drilldown/SPY?strike=100")
    assert resp.status_code == 200
    d = resp.get_json()
    assert set(d.keys()) == {"figures", "tables", "meta"}
    assert d["meta"]["context"]["symbol"] == "SPY"
    assert d["meta"]["strike"] == 100.0
    # the per-contract table carries expiration/side/oi/iv/gamma/gex columns
    rows = _drill_rows(d)
    assert rows, "drilldown should return contract rows for strike 100"
    for r in rows:
        assert {"expiration", "side", "oi", "iv", "gamma", "gex"} <= set(r.keys())
        assert r["side"] in ("call", "put")
    # both sides exist at strike 100 in the first 4 default expirations
    assert {"call", "put"} <= {r["side"] for r in rows}
    # contracts ride meta.contracts too (for the client renderer)
    assert d["meta"]["contracts"] == rows


def test_drilldown_is_strike_specific(client):
    # strike 100 and strike 95 must return different (strike-specific) contract sets.
    at_100 = _drill_rows(client.get("/api/options/drilldown/SPY?strike=100").get_json())
    at_95 = _drill_rows(client.get("/api/options/drilldown/SPY?strike=95").get_json())
    # strike 95 only has the 2026-06-01 call+put in the default first-4 window
    assert {r["expiration"] for r in at_95} == {"2026-06-01"}
    assert {r["expiration"] for r in at_100} != {r["expiration"] for r in at_95}


def test_drilldown_without_strike_yields_error(client):
    # No strike -> the drilldown cannot resolve a contract set -> error envelope.
    resp = client.get("/api/options/drilldown/SPY")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["meta"]["status"] == "error"
    assert "strike" in d["meta"]["message"].lower()


def test_drilldown_unknown_strike_yields_empty(client):
    resp = client.get("/api/options/drilldown/SPY?strike=12345")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["meta"]["status"] == "empty"
    assert _drill_rows(d) == []


def test_drilldown_honors_expiration_selection(client):
    resp = client.get("/api/options/drilldown/SPY?strike=100&exps=2026-06-06")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["meta"]["expirations"] == ["2026-06-06"]
    rows = _drill_rows(d)
    assert {r["expiration"] for r in rows} == {"2026-06-06"}
