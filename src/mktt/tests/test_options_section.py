"""Unit tests for the Options section `handle()` (Slice #10).

`handle(req, data)` is exercised with a STUB `data` exposing `option_chain(...)` —
no Flask, no DB, no network (spec §8). Asserts the spec §5.1 ViewModel shape,
selectable expirations, stale-cache status, and parity of the embedded GEX profile
against the frozen Slice-3 golden fixture.
"""
import json
import os

import pytest

from datasource import OptionChain
from parity import assert_parity
from sections.options import drilldown, handle
from sections.options.service import OptionsRequest

GOLDEN = os.path.join(os.path.dirname(__file__), "fixtures", "golden", "gex_profile.json")


# --------------------------------------------------------------------------- #
# Stub DataSource
# --------------------------------------------------------------------------- #
class _StubData:
    """Returns a fixed OptionChain; records the call args for selection assertions."""

    def __init__(self, chain):
        self._chain = chain
        self.last_call = None

    def option_chain(self, symbol, n_exp=4, expirations=None, force_refresh=False):
        self.last_call = dict(symbol=symbol, n_exp=n_exp,
                              expirations=expirations, force_refresh=force_refresh)
        if isinstance(self._chain, Exception):
            raise self._chain
        return self._chain


def _golden_chain(stale=False, warning=None):
    with open(GOLDEN) as f:
        g = json.load(f)
    m = g["meta"]
    return OptionChain(
        symbol="SPY",
        spot=m["spot"],
        chains=m["input_chains"],
        expirations=["2026-06-19", "2026-06-26"],
        available_expirations=["2026-06-19", "2026-06-26", "2026-07-03"],
        default_expirations=["2026-06-19", "2026-06-26", "2026-07-03", "2026-07-17"],
        meta={"fetched_at": "2026-06-11 06:00:00", "oi_as_of": "2026-06-10 close",
              "stale": stale, "warning": warning},
    )


def _req(**kw):
    base = dict(symbol="SPY", band_pct=0.15, n_exp=4, expirations=None,
                force_refresh=False, band_key="15", strike=None)
    base.update(kw)
    return OptionsRequest(**base)


# --------------------------------------------------------------------------- #
# ViewModel shape
# --------------------------------------------------------------------------- #
def test_handle_builds_spec_shaped_viewmodel():
    data = _StubData(_golden_chain())
    vm = handle(_req(), data)

    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["title"] == "SPY — GEX"
    assert vm["meta"]["asof"] == "2026-06-10 close"
    assert vm["meta"]["context"]["symbol"] == "SPY"

    # one GEX figure with id + traces + layout
    fig = vm["figures"][0]
    assert fig["id"] == "gex_profile"
    assert fig["traces"] and "layout" in fig

    # tables: strikes + walls, both id-keyed
    table_ids = {t["id"] for t in vm["tables"]}
    assert {"gex_strikes", "gex_walls"} <= table_ids

    # readouts carry the headline scalars
    r = vm["meta"]["readouts"]
    assert {"gamma_flip", "total_gex", "call_wall", "put_wall", "regime", "spot"} <= set(r)
    assert r["regime"] == "positive"


def test_handle_readouts_match_golden_profile():
    data = _StubData(_golden_chain())
    vm = handle(_req(), data)
    r = vm["meta"]["readouts"]
    with open(GOLDEN) as f:
        prof = json.load(f)["profile"]
    assert r["gamma_flip"] == pytest.approx(prof["flip"])
    assert r["total_gex"] == pytest.approx(prof["total_gex"])
    assert r["call_wall"] == pytest.approx(prof["call_wall"])
    assert r["put_wall"] == pytest.approx(prof["put_wall"])


# --------------------------------------------------------------------------- #
# Parity — embedded GEX profile equals the frozen golden fixture
# --------------------------------------------------------------------------- #
def test_handle_gex_profile_parity_vs_golden():
    data = _StubData(_golden_chain())
    vm = handle(_req(), data)
    with open(GOLDEN) as f:
        golden = json.load(f)["profile"]

    # reconstruct the profile-equivalent view from the ViewModel envelope
    strike_table = next(t for t in vm["tables"] if t["id"] == "gex_strikes")
    cols = strike_table["columns"]
    rows = [dict(zip(cols, row)) for row in strike_table["rows"]]
    r = vm["meta"]["readouts"]
    reconstructed = {
        "spot": r["spot"],
        "strikes": rows,
        "flip": r["gamma_flip"],
        "call_wall": r["call_wall"],
        "put_wall": r["put_wall"],
        "total_gex": r["total_gex"],
        "regime": r["regime"],
    }
    golden_view = {k: golden[k] for k in reconstructed}
    assert_parity(reconstructed, golden_view)


# --------------------------------------------------------------------------- #
# Selectable expirations
# --------------------------------------------------------------------------- #
def test_handle_passes_selected_expirations_to_provider():
    data = _StubData(_golden_chain())
    handle(_req(expirations=["2026-06-26"], n_exp=2), data)
    assert data.last_call["expirations"] == ["2026-06-26"]
    assert data.last_call["n_exp"] == 2


def test_handle_echoes_expiration_lists_in_meta():
    data = _StubData(_golden_chain())
    vm = handle(_req(), data)
    assert vm["meta"]["expirations"] == ["2026-06-19", "2026-06-26"]
    assert vm["meta"]["available_expirations"] == \
        ["2026-06-19", "2026-06-26", "2026-07-03"]


def test_handle_disclosure_carries_freshness_and_assumptions():
    # The disclosure footer needs BOTH the chain freshness and the GEX modeling
    # assumptions so the numbers are disclosed as estimates, not exact facts.
    data = _StubData(_golden_chain())
    vm = handle(_req(), data)
    disc = vm["meta"]["disclosure"]
    assert disc["fetched_at"] == "2026-06-11 06:00:00"
    assert disc["oi_as_of"] == "2026-06-10 close"
    a = disc["assumptions"]
    assert {"risk_free", "dividend_yield", "dealer_positioning",
            "oi_basis", "units"} <= set(a)


# --------------------------------------------------------------------------- #
# Stale-cache + error status
# --------------------------------------------------------------------------- #
def test_handle_stale_chain_yields_stale_status():
    data = _StubData(_golden_chain(stale=True, warning="Live fetch failed; cached."))
    vm = handle(_req(), data)
    assert vm["meta"]["status"] == "stale"
    assert vm["meta"]["message"] == "Live fetch failed; cached."
    # figures still present (we have cached strikes)
    assert vm["figures"]


def test_handle_fetch_error_yields_error_envelope():
    data = _StubData(RuntimeError("No option expirations available for BADSYM"))
    vm = handle(_req(symbol="BADSYM"), data)
    assert vm["meta"]["status"] == "error"
    assert "BADSYM" in vm["meta"]["message"]
    assert vm["figures"] == [] and vm["tables"] == []


def test_handle_empty_band_yields_empty_status():
    # an OptionChain whose strikes all fall outside the band -> no strikes -> empty.
    # spot far from the only strikes (90..110) so a tight band keeps nothing.
    chain = OptionChain(
        symbol="SPY", spot=500.0,
        chains=[{"expiration": "2026-06-19", "dte": 7,
                 "calls": [{"strike": 100.0, "oi": 1000, "iv": 0.2}], "puts": []}],
        expirations=["2026-06-19"],
        available_expirations=["2026-06-19"],
        default_expirations=["2026-06-19"],
        meta={"oi_as_of": "2026-06-10 close", "stale": False, "warning": None},
    )
    data = _StubData(chain)
    vm = handle(_req(band_pct=0.05), data)
    assert vm["meta"]["status"] == "empty"
    assert vm["figures"] == []


# --------------------------------------------------------------------------- #
# from_query parsing
# --------------------------------------------------------------------------- #
def test_request_from_query_parses_band_exps_refresh():
    args = {"band": "25", "exps": "2026-06-26, 2026-07-03", "refresh": "1", "n_exp": "3"}
    req = OptionsRequest.from_query("spy", args)
    assert req.symbol == "SPY"
    assert req.band_pct == 0.25
    assert req.band_key == "25"
    assert req.expirations == ["2026-06-26", "2026-07-03"]
    assert req.force_refresh is True
    assert req.n_exp == 3


def test_request_from_query_band_all_is_none():
    req = OptionsRequest.from_query("SPY", {"band": "all"})
    assert req.band_pct is None
    assert req.expirations is None


def test_request_from_query_parses_strike():
    assert OptionsRequest.from_query("SPY", {"strike": "100.5"}).strike == 100.5
    # absent / garbage -> None (no drilldown target)
    assert OptionsRequest.from_query("SPY", {}).strike is None
    assert OptionsRequest.from_query("SPY", {"strike": "abc"}).strike is None
    assert OptionsRequest.from_query("SPY", {"strike": ""}).strike is None


# --------------------------------------------------------------------------- #
# drilldown — per-contract breakdown behind one strike
# --------------------------------------------------------------------------- #
def test_drilldown_returns_per_contract_rows():
    data = _StubData(_golden_chain())
    vm = drilldown(_req(strike=100.0), data)

    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["strike"] == 100.0
    assert vm["meta"]["title"] == "SPY — GEX drilldown"
    assert vm["meta"]["asof"] == "2026-06-10 close"

    drill = next(t for t in vm["tables"] if t["id"] == "gex_drill")
    assert drill["columns"] == ["expiration", "side", "oi", "iv", "gamma", "gex"]
    rows = [dict(zip(drill["columns"], r)) for r in drill["rows"]]
    assert rows
    for r in rows:
        assert r["side"] in ("call", "put")
    # contracts also surfaced in meta for the client renderer
    assert vm["meta"]["contracts"] == rows
    # the GEX of the contracts at strike 100 sums to that strike's net GEX
    net = round(sum(r["gex"] for r in rows))
    gex_strikes = next(t for t in handle(_req(), data)["tables"]
                       if t["id"] == "gex_strikes")
    # gex_strikes columns: [strike, call_gex, put_gex, net_gex, oi]
    net_by_strike = {row[0]: row[3] for row in gex_strikes["rows"]}
    assert net == pytest.approx(net_by_strike[100], abs=1)


def test_drilldown_without_strike_yields_error():
    data = _StubData(_golden_chain())
    vm = drilldown(_req(strike=None), data)
    assert vm["meta"]["status"] == "error"
    assert "strike" in vm["meta"]["message"].lower()
    assert vm["tables"] == [] and vm["figures"] == []


def test_drilldown_unknown_strike_yields_empty():
    data = _StubData(_golden_chain())
    vm = drilldown(_req(strike=99999.0), data)
    assert vm["meta"]["status"] == "empty"
    drill = next(t for t in vm["tables"] if t["id"] == "gex_drill")
    assert drill["rows"] == []


def test_drilldown_fetch_error_yields_error_envelope():
    data = _StubData(RuntimeError("No option expirations available for BADSYM"))
    vm = drilldown(_req(symbol="BADSYM", strike=100.0), data)
    assert vm["meta"]["status"] == "error"
    assert "BADSYM" in vm["meta"]["message"]


def test_drilldown_passes_selected_expirations_to_provider():
    data = _StubData(_golden_chain())
    drilldown(_req(strike=100.0, expirations=["2026-06-26"], n_exp=2), data)
    assert data.last_call["expirations"] == ["2026-06-26"]
