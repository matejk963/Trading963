"""Integration tests for the /api/options/* routes via the Flask test client.

yfinance is stubbed by monkeypatching options_service.get_next_chains, so these
tests exercise the route + engine contract without any network access.
"""
import pytest

import app as app_module
import options_service


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


def _payload(selected):
    return {
        "symbol": "SPY",
        "spot": 100.0,
        "chains": [_ALL_CHAINS[e] for e in selected],
        "expirations": selected,
        "available_expirations": _AVAILABLE,
        "default_expirations": _AVAILABLE[:4],
        "meta": {"fetched_at": "2026-05-30 06:00:00", "oi_as_of": "2026-05-29 close",
                 "stale": False, "warning": None},
    }


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def stub_chains(monkeypatch):
    def fake(symbol, n_exp=4, expirations=None, force_refresh=False):
        if symbol.upper() == "BADSYM":
            return {"error": "No option expirations available for BADSYM"}
        if expirations:
            selected = [e for e in expirations if e in _ALL_CHAINS] or _AVAILABLE[:n_exp]
        else:
            selected = _AVAILABLE[:n_exp]
        return _payload(selected)
    monkeypatch.setattr(options_service, "get_next_chains", fake)
    return fake


# --------------------------------------------------------------------------- #
# /api/options/gex
# --------------------------------------------------------------------------- #
def test_gex_returns_contract(client, stub_chains):
    resp = client.get("/api/options/gex/SPY?band=15")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["symbol"] == "SPY"
    assert d["spot"] == 100.0
    assert d["regime"] in ("positive", "negative")
    assert "flip" in d and "call_wall" in d and "put_wall" in d and "total_gex" in d
    assert d["meta"]["oi_as_of"] == "2026-05-29 close"
    # default selection = first 4 of the available list
    assert d["expirations"] == _AVAILABLE[:4]
    assert d["available_expirations"] == _AVAILABLE
    assert d["default_expirations"] == _AVAILABLE[:4]
    for s in d["strikes"]:
        assert {"strike", "call_gex", "put_gex", "net_gex", "oi"} <= set(s.keys())


def test_gex_respects_expiration_selection(client, stub_chains):
    # pick two specific (non-default-order) expirations
    resp = client.get("/api/options/gex/SPY?exps=2026-06-06,2026-07-18")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["expirations"] == ["2026-06-06", "2026-07-18"]
    # available list is still the full set so the picker can show all
    assert d["available_expirations"] == _AVAILABLE


def test_gex_band_filter_excludes_far_strikes(client, stub_chains):
    # 130 strike is outside ±15% of spot=100 -> excluded at band=15
    tight = client.get("/api/options/gex/SPY?band=15").get_json()
    assert 130 not in [s["strike"] for s in tight["strikes"]]
    # ...but present with band=all
    wide = client.get("/api/options/gex/SPY?band=all").get_json()
    assert 130 in [s["strike"] for s in wide["strikes"]]


def test_gex_invalid_symbol_returns_502(client, stub_chains):
    resp = client.get("/api/options/gex/BADSYM")
    assert resp.status_code == 502
    assert "error" in resp.get_json()


# --------------------------------------------------------------------------- #
# /api/options/drilldown
# --------------------------------------------------------------------------- #
def test_drilldown_returns_contracts(client, stub_chains):
    resp = client.get("/api/options/drilldown/SPY?strike=100")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["strike"] == 100.0
    sides = {(c["expiration"], c["side"]) for c in d["contracts"]}
    assert ("2026-06-01", "call") in sides
    assert ("2026-06-01", "put") in sides
    for c in d["contracts"]:
        assert {"expiration", "side", "oi", "iv", "gamma", "gex"} <= set(c.keys())


def test_drilldown_requires_strike(client, stub_chains):
    resp = client.get("/api/options/drilldown/SPY")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_drilldown_honors_expiration_selection(client, stub_chains):
    # strike 100 exists in both 06-01 and 06-06; restrict to 06-06 only
    resp = client.get("/api/options/drilldown/SPY?strike=100&exps=2026-06-06")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["expirations"] == ["2026-06-06"]
    exps_in_rows = {c["expiration"] for c in d["contracts"]}
    assert exps_in_rows == {"2026-06-06"}
