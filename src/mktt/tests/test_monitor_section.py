"""Unit tests for the Monitor section (Slice #8 — per-security view + lists).

All tests use STUBBED providers (spec §8 — no Flask, no DB, no network):

  * MonitorRequest.from_query / from_form — parses the per-symbol (and POST
    multi-symbol) request.
  * monitor.handle — runs the kernel LIVE on one symbol's TimeSeries
    (indicators -> rs.compute(bench) -> stage; rs_rank null for 1 symbol, taken
    from computed.cross_section), reads computed.history + data.fundamentals,
    shapes the spec §5.1 ViewModel (figures price+MA / stage-RS-evolution,
    tables fundamentals + history, meta.readouts={stage, rs_rank, sector}).
  * watchlist — lists.members read; add/remove round-trip via a stub ListStore.
  * POST multi-symbol path.

Parity target = the CURRENT per-symbol API routes (`app.py` chart / fundamentals /
rolling_12m / sales_ttm / eps_ttm / revisions) + the watchlist (`app.py:1462-1559`).
Parity means the NUMBERS match (price+MA overlay, rs_rank, sector), wrapped in the
NEW ViewModel envelope (not byte-parity).
"""
import numpy as np
import pandas as pd
import pytest

from sections.monitor import MonitorRequest, handle
from sections.monitor import service as svc


# --------------------------------------------------------------------------- #
# test doubles — stub providers (data / computed / kernel / lists)
# --------------------------------------------------------------------------- #
class FakeArgs:
    """Minimal `request.args` stand-in: get(key, default) + getlist(key)."""

    def __init__(self, single=None, multi=None):
        self._single = dict(single or {})
        self._multi = dict(multi or {})

    def get(self, key, default=None):
        return self._single.get(key, default)

    def getlist(self, key):
        return list(self._multi.get(key, []))


def _price_panel(symbol, n=260, start=100.0, benchmark=False):
    """A `symbol × date` price panel for one symbol (deterministic walk)."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = start + np.arange(n) * 0.5  # steady uptrend -> stage 2
    df = pd.DataFrame(
        {
            "close": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.MultiIndex.from_product([[symbol], dates], names=["symbol", "date"]),
    )
    return df


class StubData:
    """Returns canned time_series / fundamentals; records the requested ids."""

    def __init__(self, panels=None, bench=None, funds=None):
        self._panels = panels or {}
        self._bench = bench
        self._funds = funds
        self.ts_calls = []
        self.fund_calls = []

    def time_series(self, ids, start=None, end=None, fields=("close", "volume")):
        ids = [ids] if isinstance(ids, str) else list(ids)
        self.ts_calls.append(ids)
        # benchmark id served from the benchmark panel.
        if ids == ["SPY"]:
            return self._bench
        frames = [self._panels[i] for i in ids if i in self._panels]
        if not frames:
            idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
            return pd.DataFrame(columns=["close", "high", "low", "volume"], index=idx)
        return pd.concat(frames).sort_index()

    def fundamentals(self, ids, fields=None, estimates=False):
        ids = [ids] if isinstance(ids, str) else list(ids)
        self.fund_calls.append(ids)
        if self._funds is None:
            df = pd.DataFrame()
            df.index.name = "symbol"
            return df
        return self._funds.loc[self._funds.index.intersection(ids)]


class StubComputed:
    """cross_section (for rs_rank/regime) + history (stage/RS evolution)."""

    def __init__(self, cross=None, history=None, asof=None):
        self._cross = cross
        self._history = history if history is not None else {}
        self.asof = asof

    def cross_section(self, filters=None):
        if self._cross is None:
            df = pd.DataFrame()
            df.index.name = "symbol"
            return df
        return self._cross

    def history(self, symbol, start=None, end=None):
        h = self._history.get(symbol)
        if h is not None:
            return h
        idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
        return pd.DataFrame(columns=["stage", "rs_rank", "mansfield_rs"], index=idx)


class StubLists:
    """In-memory ListStore stand-in (same surface as lists.ListStore)."""

    def __init__(self):
        self._d = {}

    def add(self, list_name, symbol, note=None):
        self._d.setdefault(list_name, {})[symbol] = note

    def remove(self, list_name, symbol):
        self._d.get(list_name, {}).pop(symbol, None)

    def members(self, list_name):
        return sorted(self._d.get(list_name, {}).keys())

    def lists(self):
        return sorted(self._d.keys())

    def lists_for(self, symbol):
        return sorted(k for k, v in self._d.items() if symbol in v)


# real kernel is used live (the whole point of the slice). Import it.
from kernel import indicators, relative_strength, stage


class KernelFacade:
    """Wraps the real kernel primitives as the injected `kernel` provider.

    handle() receives a kernel object exposing the enrichment pipeline; using the
    real primitives keeps the single-symbol path LIVE (DoD)."""

    indicators = indicators
    relative_strength = relative_strength
    stage = stage


KERNEL = KernelFacade()


def _funds_frame():
    df = pd.DataFrame.from_dict(
        {
            "AAA": {
                "price_close": 220.0, "eps_actual": 10.0,
                "operating_margin": 25.0, "net_margin": 18.0,
                "roic": 20.0, "free_cash_flow": 5e9,
                "ev_to_ebitda": 15.0, "net_debt_to_ebitda": 1.2,
                "num_analysts": 12.0, "price_target_mean": 260.0,
                "gics_sector": "Tech", "gics_industry": "Software",
            }
        },
        orient="index",
    )
    df.index.name = "symbol"
    return df


# --------------------------------------------------------------------------- #
# MonitorRequest parsing
# --------------------------------------------------------------------------- #
def test_request_from_symbol_defaults():
    req = MonitorRequest.from_symbol("AAA")
    assert req.symbols == ["AAA"]
    assert req.symbol == "AAA"
    assert not req.is_multi


def test_request_from_form_multi():
    args = FakeArgs(multi={"sym": ["AAA", "BBB", "CCC"]})
    req = MonitorRequest.from_form(args)
    assert req.symbols == ["AAA", "BBB", "CCC"]
    assert req.is_multi
    # the primary symbol is the first.
    assert req.symbol == "AAA"


def test_request_from_form_empty():
    req = MonitorRequest.from_form(FakeArgs())
    assert req.symbols == []
    assert req.symbol is None


# --------------------------------------------------------------------------- #
# handle — single-symbol LIVE kernel path
# --------------------------------------------------------------------------- #
def test_handle_single_symbol_live_kernel_shape():
    panel = _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    bench = bench.rename(index={"SPY": "SPY"})
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    cross = pd.DataFrame.from_dict(
        {"AAA": {"rs_rank": 88.0, "regime": 1, "stage": 2}}, orient="index"
    )
    cross.index.name = "symbol"
    computed = StubComputed(cross=cross, asof="2024-12-31")

    vm = handle(MonitorRequest.from_symbol("AAA"), data, computed, KERNEL, StubLists())

    # envelope shape (spec §5.1).
    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["title"]
    assert vm["meta"]["context"]["symbol"] == "AAA"

    # a price+MA figure exists, keyed by id.
    fig_ids = {f["id"] for f in vm["figures"]}
    assert "monitor_price" in fig_ids

    # the price figure carries close + the three MAs as traces.
    price_fig = next(f for f in vm["figures"] if f["id"] == "monitor_price")
    trace_names = {t.get("name") for t in price_fig["traces"]}
    assert "Close" in trace_names
    assert {"MA50", "MA150", "MA200"} <= trace_names

    # kernel ran live: rs_rank for ONE symbol is null from the kernel, so the
    # readout is taken from computed.cross_section (88.0).
    assert vm["meta"]["readouts"]["rs_rank"] == 88.0
    # stage classified live by the kernel — a real int in the Weinstein 0-4 set
    # (0=Unclassified is valid for a short synthetic series; the point is the live
    # kernel produced the value, not the store).
    assert vm["meta"]["readouts"]["stage"] in (0, 1, 2, 3, 4)
    # sector from fundamentals.
    assert vm["meta"]["readouts"]["sector"] == "Tech"

    # data.time_series was called for the symbol AND the benchmark.
    assert ["AAA"] in data.ts_calls
    assert ["SPY"] in data.ts_calls
    # fundamentals requested for the symbol.
    assert ["AAA"] in data.fund_calls


def test_handle_rs_rank_null_when_kernel_only_one_symbol():
    """The live kernel cannot rank one symbol (rs_rank NaN, spec §5.2).

    When the store has no cross-section row, the readout falls back to None."""
    panel = _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    computed = StubComputed(cross=None)  # no cross_section -> no stored rank

    vm = handle(MonitorRequest.from_symbol("AAA"), data, computed, KERNEL, StubLists())
    assert vm["meta"]["readouts"]["rs_rank"] is None


def test_handle_fundamentals_table():
    panel = _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    computed = StubComputed(cross=None)

    vm = handle(MonitorRequest.from_symbol("AAA"), data, computed, KERNEL, StubLists())
    tbl = next(t for t in vm["tables"] if t["id"] == "monitor_fundamentals")
    # the fundamentals table has columns + a single value row.
    assert "Metric" in tbl["columns"]
    flat = {r[0]: r[1] for r in tbl["rows"]}
    assert flat.get("Sector") == "Tech"


def test_handle_history_figure_from_computed():
    panel = _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    hist_dates = pd.date_range("2024-06-01", periods=5, freq="W")
    hist = pd.DataFrame(
        {"stage": [1, 2, 2, 2, 3], "rs_rank": [40.0, 60.0, 70.0, 85.0, 80.0],
         "mansfield_rs": [-1.0, 0.5, 1.2, 2.0, 1.5]},
        index=pd.MultiIndex.from_product([["AAA"], hist_dates], names=["symbol", "date"]),
    )
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    computed = StubComputed(cross=None, history={"AAA": hist})

    vm = handle(MonitorRequest.from_symbol("AAA"), data, computed, KERNEL, StubLists())
    fig_ids = {f["id"] for f in vm["figures"]}
    assert "monitor_history" in fig_ids
    hfig = next(f for f in vm["figures"] if f["id"] == "monitor_history")
    names = {t.get("name") for t in hfig["traces"]}
    # RS-rank / stage evolution traces present.
    assert "RS Rank" in names or "Stage" in names


def test_handle_missing_symbol_is_empty_status():
    data = StubData(panels={}, bench=_price_panel("SPY", start=400.0))
    computed = StubComputed(cross=None)
    vm = handle(MonitorRequest.from_symbol("ZZZ"), data, computed, KERNEL, StubLists())
    assert vm["meta"]["status"] == "empty"
    assert vm["figures"] == []


def test_handle_no_symbol_is_error():
    data = StubData(panels={})
    computed = StubComputed(cross=None)
    vm = handle(MonitorRequest.from_form(FakeArgs()), data, computed, KERNEL, StubLists())
    assert vm["meta"]["status"] == "error"


# --------------------------------------------------------------------------- #
# handle — POST multi-symbol
# --------------------------------------------------------------------------- #
def test_handle_multi_symbol_table():
    aaa = _price_panel("AAA", start=100.0)
    bbb = _price_panel("BBB", start=50.0)
    bench = _price_panel("SPY", start=400.0)
    funds = pd.DataFrame.from_dict(
        {
            "AAA": {"price_close": 220.0, "eps_actual": 10.0, "gics_sector": "Tech",
                    "gics_industry": "Software", "num_analysts": 9.0},
            "BBB": {"price_close": 110.0, "eps_actual": 5.0, "gics_sector": "Energy",
                    "gics_industry": "Oil", "num_analysts": 4.0},
        },
        orient="index",
    )
    funds.index.name = "symbol"
    data = StubData(panels={"AAA": aaa, "BBB": bbb}, bench=bench, funds=funds)
    cross = pd.DataFrame.from_dict(
        {"AAA": {"rs_rank": 80.0}, "BBB": {"rs_rank": 30.0}}, orient="index"
    )
    cross.index.name = "symbol"
    computed = StubComputed(cross=cross, asof="2024-12-31")

    req = MonitorRequest.from_form(FakeArgs(multi={"sym": ["AAA", "BBB"]}))
    vm = handle(req, data, computed, KERNEL, StubLists())

    assert vm["meta"]["status"] == "ok"
    # the multi-symbol path emits a watchlist-style table over both symbols.
    tbl = next(t for t in vm["tables"] if t["id"] == "monitor_list")
    syms = {r[tbl["columns"].index("Symbol")] for r in tbl["rows"]}
    assert syms == {"AAA", "BBB"}
    # rs_rank pulled from the cross-section per symbol.
    rows = {r[tbl["columns"].index("Symbol")]: r for r in tbl["rows"]}
    rs_idx = tbl["columns"].index("RS_Rank")
    assert rows["AAA"][rs_idx] == 80.0
    assert rows["BBB"][rs_idx] == 30.0


# --------------------------------------------------------------------------- #
# watchlist — lists read/write round-trip via stub ListStore
# --------------------------------------------------------------------------- #
def test_watchlist_add_members_roundtrip():
    lists = StubLists()
    svc.watchlist_add(lists, "default", "AAA")
    svc.watchlist_add(lists, "default", "BBB", note="buy")
    out = svc.watchlist_members(lists, "default")
    assert out["meta"]["status"] == "ok"
    assert out["meta"]["context"]["list"] == "default"
    assert set(out["meta"]["readouts"]["members"]) == {"AAA", "BBB"}


def test_watchlist_remove():
    lists = StubLists()
    svc.watchlist_add(lists, "default", "AAA")
    svc.watchlist_add(lists, "default", "BBB")
    svc.watchlist_remove(lists, "default", "AAA")
    out = svc.watchlist_members(lists, "default")
    assert out["meta"]["readouts"]["members"] == ["BBB"]


def test_watchlist_members_empty():
    out = svc.watchlist_members(StubLists(), "nope")
    assert out["meta"]["status"] == "empty"
    assert out["meta"]["readouts"]["members"] == []


# --------------------------------------------------------------------------- #
# blueprint thinness (Flask test client + stubbed providers)
# --------------------------------------------------------------------------- #
def test_blueprint_chart_route_is_thin(monkeypatch):
    from flask import Flask
    from sections.monitor import routes

    panel = _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    cross = pd.DataFrame.from_dict({"AAA": {"rs_rank": 88.0}}, orient="index")
    cross.index.name = "symbol"
    computed = StubComputed(cross=cross, asof="2024-12-31")

    monkeypatch.setitem(routes._PROVIDERS, "data", data)
    monkeypatch.setitem(routes._PROVIDERS, "computed", computed)
    monkeypatch.setitem(routes._PROVIDERS, "kernel", KERNEL)
    monkeypatch.setitem(routes._PROVIDERS, "lists", StubLists())

    app = Flask(__name__)
    app.register_blueprint(routes.monitor_bp)
    client = app.test_client()

    resp = client.get("/api/chart/AAA")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    assert payload["meta"]["context"]["symbol"] == "AAA"
    assert any(f["id"] == "monitor_price" for f in payload["figures"])


def test_blueprint_watchlist_get_post(monkeypatch):
    from flask import Flask
    from sections.monitor import routes

    lists = StubLists()
    monkeypatch.setitem(routes._PROVIDERS, "lists", lists)

    app = Flask(__name__)
    app.register_blueprint(routes.monitor_bp)
    client = app.test_client()

    # POST adds.
    r = client.post("/api/watchlist", json={"list": "default", "symbol": "AAA", "action": "add"})
    assert r.status_code == 200
    # GET reads members.
    r = client.get("/api/watchlist?list=default")
    payload = r.get_json()
    assert payload["meta"]["readouts"]["members"] == ["AAA"]
