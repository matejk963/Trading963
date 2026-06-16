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

    def __init__(self, panels=None, bench=None, funds=None, fund_series=None,
                 ttm_forward=None):
        self._panels = panels or {}
        self._bench = bench
        self._funds = funds
        self._fund_series = fund_series
        self._ttm_forward = ttm_forward
        self.ts_calls = []
        self.fund_calls = []
        self.fund_series_calls = []
        self.ttm_forward_calls = []

    def fundamental_series(self, symbol, asof=None):
        """Canned structured fundamental series; records the (symbol, asof) call.

        Returns the deterministic dict passed at construction (the
        ``quarterly``/``ttm``/``annual``/``forward_q`` blend the pkl port emits)."""
        self.fund_series_calls.append((symbol, asof))
        if self._fund_series is None:
            return {}
        return self._fund_series

    def eps_ttm_forward(self, symbol, n=3):
        """Canned forward-TTM-EPS curves; records the (symbol, n) call."""
        self.ttm_forward_calls.append((symbol, n))
        if self._ttm_forward is None:
            return {"quarter_labels": [], "curves": [], "current_ttm": None,
                    "n_available": 0}
        return self._ttm_forward

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
    """In-memory ListStore stand-in (same surface as lists.ListStore).

    Stores each member as ``{symbol: (note, added_at)}``. ``added_at`` is a
    monotonic incrementing int (real ``now()`` is unavailable in tests — ordering
    only), so ``members_detailed`` can preserve / expose add order."""

    def __init__(self):
        self._d = {}
        self._seq = 0

    def add(self, list_name, symbol, note=None):
        bucket = self._d.setdefault(list_name, {})
        if symbol in bucket:
            # re-add refreshes the note, keeps the original added_at (PK semantics).
            bucket[symbol] = (note, bucket[symbol][1])
        else:
            self._seq += 1
            bucket[symbol] = (note, self._seq)

    def remove(self, list_name, symbol):
        self._d.get(list_name, {}).pop(symbol, None)

    def members(self, list_name):
        return sorted(self._d.get(list_name, {}).keys())

    def members_with_notes(self, list_name):
        return [
            (sym, note)
            for sym, (note, _added) in sorted(self._d.get(list_name, {}).items())
        ]

    def members_detailed(self, list_name):
        return [
            (sym, note, added)
            for sym, (note, added) in sorted(self._d.get(list_name, {}).items())
        ]

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

    # a price figure exists, keyed by id, rendered as Lightweight-Charts OHLC.
    fig_ids = {f["id"] for f in vm["figures"]}
    assert "monitor_price" in fig_ids

    # the price figure is an OHLC figure (LWC path, NOT Plotly) — no traces key.
    price_fig = next(f for f in vm["figures"] if f["id"] == "monitor_price")
    assert price_fig["kind"] == "ohlc"
    assert "traces" not in price_fig
    # MA50/150/200 ride as named overlay series.
    series_names = {s["name"] for s in price_fig["series"]}
    assert {"MA50", "MA150", "MA200"} <= series_names

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


def _ohlc_fig(panels=None):
    """Run handle() for AAA and return its monitor_price (ohlc) figure."""
    panel = panels["AAA"] if panels else _price_panel("AAA")
    bench = _price_panel("SPY", start=400.0)
    data = StubData(panels={"AAA": panel}, bench=bench, funds=_funds_frame())
    computed = StubComputed(cross=None)
    vm = handle(MonitorRequest.from_symbol("AAA"), data, computed, KERNEL, StubLists())
    return next(f for f in vm["figures"] if f["id"] == "monitor_price"), panel


def test_ohlc_bars_open_is_prior_close():
    """Behavior 2 — bars carry t/o/h/l/c; open == prior bar's close; the first
    bar's open == its own close (FORK-1: universe has no open)."""
    fig, panel = _ohlc_fig()
    bars = fig["bars"]
    assert len(bars) == len(panel)
    # shape of a bar.
    assert set(bars[0]) >= {"time", "open", "high", "low", "close"}
    # first bar: open == its own close.
    assert bars[0]["open"] == bars[0]["close"]
    # every subsequent bar: open == prior bar's close.
    for i in range(1, len(bars)):
        assert bars[i]["open"] == bars[i - 1]["close"]


def test_ohlc_series_ma_aligned_to_bars():
    """Behavior 3 — series carries MA50/150/200, each a {time,value} array
    aligned 1:1 with bars by time."""
    fig, _ = _ohlc_fig()
    bar_times = [b["time"] for b in fig["bars"]]
    by_name = {s["name"]: s for s in fig["series"]}
    assert {"MA50", "MA150", "MA200"} <= set(by_name)
    for name in ("MA50", "MA150", "MA200"):
        pts = by_name[name]["data"]
        assert [p["time"] for p in pts] == bar_times
        assert all(set(p) == {"time", "value"} for p in pts)


def test_ohlc_volume_present_as_time_value():
    """Behavior 4 — volume block present, each entry {time,value}."""
    fig, _ = _ohlc_fig()
    vol = fig["volume"]
    assert len(vol) == len(fig["bars"])
    assert all(set(v) == {"time", "value"} for v in vol)
    # the stub panel has constant volume 1_000_000.
    assert vol[0]["value"] == 1_000_000.0


def test_ohlc_nan_values_serialize_to_none():
    """Behavior 5 — NaN MA values (warm-up window) serialize to None (JSON-safe)."""
    fig, _ = _ohlc_fig()
    # MA200 over a 260-bar walk has a long NaN warm-up at the head.
    ma200 = next(s for s in fig["series"] if s["name"] == "MA200")["data"]
    assert ma200[0]["value"] is None
    # and resolves to a number once the window fills.
    assert ma200[-1]["value"] is not None


def test_ohlc_notes_flag_synthetic_open():
    """Behavior 6 — notes.synthetic_open is True (FORK-1 UX flag)."""
    fig, _ = _ohlc_fig()
    assert fig["notes"]["synthetic_open"] is True


def test_ohlc_benchmark_aligned_to_bars():
    """Slice 3 / #10 — the ohlc figure carries a non-empty ``benchmark`` series
    (SPY close) aligned 1:1 with ``bars`` by ``time`` (the client recomputes
    Mansfield RS on the displayed timeframe from this)."""
    fig, _ = _ohlc_fig()
    bench = fig["benchmark"]
    # non-empty, one point per bar, same time axis.
    assert len(bench) == len(fig["bars"])
    assert len(bench) > 0
    assert [b["time"] for b in bench] == [bar["time"] for bar in fig["bars"]]
    assert all(set(b) == {"time", "value"} for b in bench)
    # carries real benchmark closes (the SPY panel starts at 400.0).
    assert any(b["value"] is not None for b in bench)
    assert bench[0]["value"] == 400.0


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
    # Slice 6: the indicators panel is now a non-Plotly LWC pane (kind:"indicators"
    # carrying `series`), not a Plotly 3-axis figure.
    assert hfig["kind"] == "indicators"
    assert "traces" not in hfig
    names = {s.get("name") for s in hfig["series"]}
    # RS Rank / Mansfield RS / Stage indicator series present (names exact so the
    # .ind-tog checkboxes match by data-ind).
    assert "RS Rank" in names
    assert "Mansfield RS" in names
    assert "Stage" in names


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


# --------------------------------------------------------------------------- #
# rail — the saved-instrument rail VM (Slice 1: workspace spine + rail)
# --------------------------------------------------------------------------- #
def _rail_cross():
    cross = pd.DataFrame.from_dict(
        {
            "AAA": {"stage": 2, "rs_rank": 88.0},
            "BBB": {"stage": 4, "rs_rank": 12.0},
        },
        orient="index",
    )
    cross.index.name = "symbol"
    return cross


def test_members_detailed_preserves_add_order():
    """Behavior 1 — members_detailed returns (symbol, note, added_at); added_at
    is monotonic in add order (it's the recently-added sort key)."""
    lists = StubLists()
    lists.add("default", "AAA", note="long")
    lists.add("default", "BBB", note="short")
    detailed = {sym: (note, added) for sym, note, added in lists.members_detailed("default")}
    assert set(detailed) == {"AAA", "BBB"}
    assert detailed["AAA"][0] == "long"
    # BBB was added after AAA -> strictly larger added_at.
    assert detailed["BBB"][1] > detailed["AAA"][1]


def test_rail_enriches_entries_with_stage_and_rs_rank():
    """Behavior 2 — rail joins each member against computed.cross_section()."""
    lists = StubLists()
    lists.add("default", "AAA", note="long")
    lists.add("default", "BBB", note="short")
    computed = StubComputed(cross=_rail_cross())

    out = svc.rail(lists, computed, "default")
    entries = {e["symbol"]: e for e in out["meta"]["context"]["entries"]}
    assert entries["AAA"]["stage"] == 2
    assert entries["AAA"]["rs_rank"] == 88.0
    assert entries["BBB"]["stage"] == 4
    assert entries["BBB"]["rs_rank"] == 12.0


def test_rail_side_defaults_long_reads_short_from_note():
    """Behavior 3 — side defaults to "long" with no note; "short" read from note."""
    lists = StubLists()
    lists.add("default", "AAA")  # no note -> long
    lists.add("default", "BBB", note="short")
    computed = StubComputed(cross=_rail_cross())

    out = svc.rail(lists, computed, "default")
    entries = {e["symbol"]: e for e in out["meta"]["context"]["entries"]}
    assert entries["AAA"]["side"] == "long"
    assert entries["BBB"]["side"] == "short"


def test_rail_default_orders_recently_added_first():
    """Behavior 4 — entries default-ordered by added_at desc (recent first)."""
    lists = StubLists()
    lists.add("default", "AAA")
    lists.add("default", "BBB")
    lists.add("default", "CCC")
    computed = StubComputed(cross=_rail_cross())

    out = svc.rail(lists, computed, "default")
    order = [e["symbol"] for e in out["meta"]["context"]["entries"]]
    assert order == ["CCC", "BBB", "AAA"]


def test_rail_row_for_symbol_missing_from_cross_section():
    """Behavior 5 — a member absent from the cross-section still renders, with
    stage=None, rs_rank=None."""
    lists = StubLists()
    lists.add("default", "ZZZ")
    computed = StubComputed(cross=_rail_cross())  # no ZZZ row

    out = svc.rail(lists, computed, "default")
    entries = out["meta"]["context"]["entries"]
    assert len(entries) == 1
    assert entries[0]["symbol"] == "ZZZ"
    assert entries[0]["stage"] is None
    assert entries[0]["rs_rank"] is None


def test_rail_empty_list():
    """Behavior 6 — an empty list -> status="empty", count==0, entries==[]."""
    out = svc.rail(StubLists(), StubComputed(cross=_rail_cross()), "default")
    assert out["meta"]["status"] == "empty"
    assert out["meta"]["readouts"]["count"] == 0
    assert out["meta"]["context"]["entries"] == []


# --------------------------------------------------------------------------- #
# blueprint — workspace shell + rail API + redirects (Slice 1)
# --------------------------------------------------------------------------- #
def _monitor_app(monkeypatch, lists=None, computed=None):
    """A minimal Flask app that renders the workspace shell + base chrome.

    base.html references ``url_for`` for every section tab and a ``now`` value, so
    the app registers light stub blueprints for the other sections' page endpoints
    and a ``now`` context — enough for the template to render without spinning the
    DB-backed ``create_app``. The monitor blueprint is the real one under test."""
    import os

    from flask import Blueprint, Flask
    from sections.monitor import routes

    monkeypatch.setitem(routes._PROVIDERS, "lists", lists if lists is not None else StubLists())
    if computed is not None:
        monkeypatch.setitem(routes._PROVIDERS, "computed", computed)

    base_templates = os.path.join(os.path.dirname(__file__), "..", "templates")
    app = Flask(__name__, template_folder=base_templates)
    app.register_blueprint(routes.monitor_bp)

    # Stub the sibling-section page endpoints base.html links to (url_for targets).
    for name, endpoint in (
        ("screener", "screener_page"),
        ("options", "options_page"),
        ("rrg", "rrg_page"),
        ("macro", "macro_page"),
    ):
        bp = Blueprint(name, name)
        bp.add_url_rule(f"/_{name}", endpoint, lambda: "")
        app.register_blueprint(bp)

    @app.context_processor
    def _inject_now():
        import datetime
        return {"now": datetime.datetime.utcnow()}

    return app


def test_blueprint_monitor_page(monkeypatch):
    """Behavior 7 — GET /monitor -> 200, renders the workspace shell."""
    app = _monitor_app(monkeypatch)
    resp = app.test_client().get("/monitor")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # the workspace shell carries the rail host (not the retired watchlist page).
    assert "monitor-rail" in body


def test_blueprint_monitor_page_with_symbol(monkeypatch):
    """Behavior 8 — GET /monitor/AAA -> 200, shell carries symbol="AAA"."""
    app = _monitor_app(monkeypatch)
    resp = app.test_client().get("/monitor/AAA")
    assert resp.status_code == 200
    assert "AAA" in resp.get_data(as_text=True)


def test_blueprint_chart_redirects_to_monitor(monkeypatch):
    """Behavior 9 — GET /chart/AAA -> 302 -> /monitor/AAA."""
    app = _monitor_app(monkeypatch)
    resp = app.test_client().get("/chart/AAA")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/monitor/AAA")


def test_blueprint_watchlist_redirects_to_monitor(monkeypatch):
    """Behavior 10 — GET /watchlist -> 302 -> /monitor."""
    app = _monitor_app(monkeypatch)
    resp = app.test_client().get("/watchlist")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/monitor")


def test_blueprint_monitor_rail_api(monkeypatch):
    """Behavior 11 — GET /api/monitor/rail?list=default -> 200, JSON envelope
    with context.entries."""
    lists = StubLists()
    lists.add("default", "AAA", note="long")
    app = _monitor_app(monkeypatch, lists=lists, computed=StubComputed(cross=_rail_cross()))
    resp = app.test_client().get("/api/monitor/rail?list=default")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    entries = payload["meta"]["context"]["entries"]
    assert [e["symbol"] for e in entries] == ["AAA"]
    assert entries[0]["stage"] == 2
    assert entries[0]["rs_rank"] == 88.0


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


# --------------------------------------------------------------------------- #
# fundamental pane — EPS + Sales (actual + forecast + band) · Slice 4 / #11
# --------------------------------------------------------------------------- #
def _fund_series_fixture():
    """A small deterministic structured fundamental series (the shape the pkl
    port emits): quarterly actuals, rolling TTM, annual FY actual + FY1/FY2
    forward, and the forward-quarterly mean/high/low fan."""
    return {
        "quarterly": {
            "dates": ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"],
            "eps": [1.0, 1.1, 1.2, 1.3],
            "revenue": [100.0, 110.0, 120.0, 130.0],
        },
        "ttm": {
            "dates": ["2024-09-30", "2024-12-31"],
            "eps": [4.2, 4.6],
            "eps_ok": [True, True],
            "revenue": [420.0, 460.0],
        },
        "annual": {
            "fy_dates": ["2022-12-31", "2023-12-31", "2024-12-31"],
            "eps": [3.0, 4.0, 4.6],
            "fwd_dates": ["2025-12-31", "2026-12-31"],
            "eps_mean": [5.0, 5.6],
            "eps_high": [5.4, 6.2],
            "eps_low": [4.6, 5.0],
            "rev": [380.0, 420.0, 460.0],
            "rev_mean": [500.0, 560.0],
            "rev_high": [540.0, 620.0],
            "rev_low": [460.0, 500.0],
        },
        "forward_q": {
            "dates": ["2025-03-31", "2025-06-30", "2025-09-30"],
            "eps_mean": [1.4, 1.5, 1.6],
            "eps_high": [1.5, 1.7, 1.9],
            "eps_low": [1.3, 1.3, 1.3],
            "rev_mean": [140.0, 150.0, 160.0],
            "rev_high": [150.0, 170.0, 190.0],
            "rev_low": [130.0, 130.0, 130.0],
        },
        "revisions": _revisions_fixture(),
    }


def _revisions_fixture():
    """Estimate-revision trend lines (the shape data.fundamental_series emits):
    EPS FY1/FY2 with mean/high/low, Revenue FY1/FY2 mean-only (high/low absent)."""
    return {
        "eps": {
            "fy1": {
                "dates": ["2024-09-30", "2024-12-31", "2025-03-31"],
                "mean": [5.0, 5.2, 5.6], "high": [5.4, 5.6, 6.0], "low": [4.6, 4.8, 5.2],
            },
            "fy2": {
                "dates": ["2024-09-30", "2024-12-31", "2025-03-31"],
                "mean": [6.0, 6.1, 6.3], "high": [6.4, 6.5, 6.7], "low": [5.6, 5.7, 5.9],
            },
        },
        "revenue": {
            "fy1": {
                "dates": ["2024-09-30", "2024-12-31", "2025-03-31"],
                "mean": [500.0, 520.0, 560.0], "high": [], "low": [],
            },
            "fy2": {
                "dates": ["2024-09-30", "2024-12-31", "2025-03-31"],
                "mean": [600.0, 610.0, 630.0], "high": [], "low": [],
            },
        },
    }


def _fund_data(series=None):
    return StubData(fund_series=series if series is not None else _fund_series_fixture())


# --- PE/PS basis fixtures (Slice 5 / #12) ----------------------------------- #
#: distinct period-end closes at each quarterly report_date, and a DIFFERENT
#: current (last) close, so the period-end vs current basis is observable.
_PERIOD_END_CLOSE = {
    "2024-03-31": 200.0,
    "2024-06-30": 210.0,
    "2024-09-30": 220.0,
    "2024-12-31": 230.0,
}
_CURRENT_CLOSE = 300.0  # the last bar's close (forward & TTM basis).
_SHARES = 50.0  # shares_outstanding (PS uses it).


def _ratio_price_panel(symbol="AAA"):
    """A daily close panel: a close on each quarterly report_date (period-end) plus
    a final, distinct current close two months past the last report (last bar)."""
    rows = sorted(_PERIOD_END_CLOSE.items())
    dates = [pd.Timestamp(d) for d, _ in rows]
    closes = [c for _, c in rows]
    # append a current bar AFTER the last report date with a distinct close.
    dates.append(pd.Timestamp("2025-02-28"))
    closes.append(_CURRENT_CLOSE)
    df = pd.DataFrame(
        {"close": closes, "high": closes, "low": closes,
         "volume": [1.0] * len(closes)},
        index=pd.MultiIndex.from_product([[symbol], dates], names=["symbol", "date"]),
    )
    return df


def _ratio_funds(shares=_SHARES):
    df = pd.DataFrame.from_dict(
        {"AAA": {"price_close": _CURRENT_CLOSE, "shares_outstanding": shares,
                 "eps_actual": 10.0, "gics_sector": "Tech"}},
        orient="index",
    )
    df.index.name = "symbol"
    return df


def _ratio_data(series=None, shares=_SHARES):
    """StubData wired for PE/PS: fund_series blend + price panel + funds (shares)."""
    return StubData(
        panels={"AAA": _ratio_price_panel()},
        funds=_ratio_funds(shares),
        fund_series=series if series is not None else _fund_series_fixture(),
    )


def test_fundamentals_view_emits_pe_and_ps_figures():
    """Behavior 1 (#12) — fundamentals_view ALSO emits fund_pe + fund_ps."""
    out = svc.fundamentals_view("AAA", _ratio_data())
    fig_ids = {f["id"] for f in out["figures"]}
    assert {"fund_pe", "fund_ps"} <= fig_ids


def test_fundamentals_view_pe_historical_period_end_forward_current():
    """Behavior 2 (#12) — historical PE uses the PERIOD-END price (close at each
    report_date); the forward forecast uses the CURRENT (last close) price."""
    fix = _fund_series_fixture()
    out = svc.fundamentals_view("AAA", _ratio_data(), granularity="Q")
    fig = _fund_fig(out, "fund_pe")
    actual = fig["traces"][0]
    # each historical quarter's PE = period-end close / that quarter's EPS.
    expected_actual = [
        _PERIOD_END_CLOSE[d] / eps
        for d, eps in zip(fix["quarterly"]["dates"], fix["quarterly"]["eps"])
    ]
    assert actual["y"] == expected_actual
    # forecast PE = CURRENT price / forward EPS mean (not the period-end basis).
    forecast = next(t for t in fig["traces"] if t.get("name") == "Forecast")
    expected_fwd = [_CURRENT_CLOSE / v for v in fix["forward_q"]["eps_mean"]]
    assert forecast["y"] == expected_fwd


def test_fundamentals_view_ttm_uses_current_price():
    """Behavior 2 (#12) — the whole TTM domain (actual + forward) uses the CURRENT
    price, not a period-end price."""
    fix = _fund_series_fixture()
    out = svc.fundamentals_view("AAA", _ratio_data(), granularity="TTM")
    fig = _fund_fig(out, "fund_pe")
    actual = fig["traces"][0]
    expected = [_CURRENT_CLOSE / eps for eps in fix["ttm"]["eps"]]
    assert actual["y"] == expected


def test_fundamentals_view_emits_eps_and_sales_figures():
    """Behavior 1 — fundamentals_view emits both fund_eps and fund_sales."""
    data = _fund_data()
    out = svc.fundamentals_view("AAA", data)
    assert out["meta"]["status"] == "ok"
    fig_ids = {f["id"] for f in out["figures"]}
    assert {"fund_eps", "fund_sales"} <= fig_ids


def _fund_fig(out, fig_id):
    return next(f for f in out["figures"] if f["id"] == fig_id)


def test_fundamentals_view_actual_forecast_band_per_figure():
    """Behavior 2 — each figure has an actual trace + a dashed forecast trace + a
    high/low band (fill)."""
    out = svc.fundamentals_view("AAA", _fund_data())
    for fig_id in ("fund_eps", "fund_sales"):
        fig = _fund_fig(out, fig_id)
        by_name = {t.get("name"): t for t in fig["traces"]}
        # an actual (solid) trace.
        assert "Actual" in by_name
        assert by_name["Actual"].get("line", {}).get("dash") != "dash"
        # a forecast trace, dashed.
        assert "Forecast" in by_name
        assert by_name["Forecast"]["line"]["dash"] == "dash"
        # a high/low band: a filled trace exists.
        assert any(t.get("fill") for t in fig["traces"])


def test_fundamentals_view_granularity_switches_series_set():
    """Behavior 3 — Q/Y/TTM select distinct series sets (different actual + forecast
    points per granularity)."""
    data = _fund_data()
    fix = _fund_series_fixture()

    def actual(out, fig_id="fund_eps"):
        return _fund_fig(out, fig_id)["traces"][0]  # the Actual trace is first.

    q = svc.fundamentals_view("AAA", data, granularity="Q")
    y = svc.fundamentals_view("AAA", data, granularity="Y")
    ttm = svc.fundamentals_view("AAA", data, granularity="TTM")

    # Q EPS actual == the quarterly actuals.
    assert actual(q)["y"] == fix["quarterly"]["eps"]
    assert actual(q)["x"] == fix["quarterly"]["dates"]
    # Y EPS actual == the annual FY actuals.
    assert actual(y)["y"] == fix["annual"]["eps"]
    assert actual(y)["x"] == fix["annual"]["fy_dates"]
    # TTM EPS actual == the rolling-TTM series.
    assert actual(ttm)["y"] == fix["ttm"]["eps"]
    assert actual(ttm)["x"] == fix["ttm"]["dates"]

    # forecast also differs: Q forecast uses the forward-quarterly fan dates.
    def forecast(out, fig_id="fund_eps"):
        return next(t for t in _fund_fig(out, fig_id)["traces"] if t.get("name") == "Forecast")

    assert forecast(q)["x"] == fix["forward_q"]["dates"]
    assert forecast(y)["x"] == fix["annual"]["fwd_dates"]
    assert forecast(q)["x"] != forecast(y)["x"]


def test_fundamentals_view_ps_uses_shares_outstanding():
    """Behavior 3 (#12) — PS = market cap / sales = price*shares/revenue_dollars,
    using shares_outstanding from data.fundamentals.

    ``revenue`` from data.fundamental_series is in $ MILLIONS while shares is a raw
    count, so revenue is scaled to dollars (``* 1e6``) before dividing — the units
    must match (see the PS unit-bug fix)."""
    fix = _fund_series_fixture()
    out = svc.fundamentals_view("AAA", _ratio_data(), granularity="Q")
    fig = _fund_fig(out, "fund_ps")
    actual = fig["traces"][0]
    expected = [
        _PERIOD_END_CLOSE[d] * _SHARES / (rev * 1e6)
        for d, rev in zip(fix["quarterly"]["dates"], fix["quarterly"]["revenue"])
    ]
    assert actual["y"] == expected


def test_fundamentals_view_ps_units_are_a_sane_ratio_not_inflated():
    """Regression guard (PS unit bug) — with a realistic stub (raw share count in
    the billions, revenue in $ MILLIONS) the resulting P/S must be a small multiple,
    NOT inflated by ~1e6.

    Reproduces the INTC symptom: revenue in $m divided into a raw share count gave a
    P/S of ~1e7. Pins the expected P/S for a known stub so the unit can't silently
    regress."""
    # INTC-like stub: price 125, ~4.3e9 shares, ~$53.4B annual revenue expressed in
    # $ MILLIONS (4 quarters of 13350) -> P/S = 125 * 4.3e9 / 53.4e9 ≈ 10.07.
    price = 125.0
    shares = 4.3e9
    rev_m = 13_350.0  # one quarter's revenue in $ millions ($13.35B)

    ps = svc._ps(price, rev_m, shares)
    assert ps is not None
    assert 0 < ps < 1000, f"P/S should be a small multiple, got {ps!r} (unit bug?)"
    # pinned expectation for this exact stub.
    assert ps == pytest.approx(125.0 * 4.3e9 / (13_350.0 * 1e6))
    assert ps == pytest.approx(40.262172, rel=1e-6)


def test_fundamentals_view_ratio_guards_nonpositive_to_none():
    """Behavior 3 (#12) — divide-by-zero / non-positive EPS -> None (no fabricated
    point); zero revenue (with positive EPS) -> PS None; missing shares -> PS None."""
    fix = _fund_series_fixture()
    # zero + negative EPS in the quarterly actuals -> PE None at those periods.
    fix["quarterly"]["eps"] = [0.0, -1.1, 1.2, 1.3]
    # zero revenue at the LAST period (which has EPS > 0) isolates the revenue guard
    # from the EPS gate.
    fix["quarterly"]["revenue"] = [100.0, 110.0, 120.0, 0.0]
    out = svc.fundamentals_view("AAA", _ratio_data(series=fix), granularity="Q")
    pe_actual = _fund_fig(out, "fund_pe")["traces"][0]["y"]
    assert pe_actual[0] is None and pe_actual[1] is None  # zero + negative EPS.
    assert pe_actual[2] is not None
    ps_actual = _fund_fig(out, "fund_ps")["traces"][0]["y"]
    assert ps_actual[0] is None and ps_actual[1] is None  # EPS-gated (<= 0).
    assert ps_actual[2] is not None  # EPS > 0, revenue > 0.
    assert ps_actual[3] is None  # zero revenue (EPS > 0): revenue guard.

    # missing shares_outstanding -> PS None everywhere.
    out2 = svc.fundamentals_view("AAA", _ratio_data(shares=None), granularity="Q")
    assert all(v is None for v in _fund_fig(out2, "fund_ps")["traces"][0]["y"])


def test_fundamentals_view_ps_qy_suppressed_where_eps_nonpositive():
    """EPS-gate (#12 fix) — for Q/Y, PS is suppressed at any period where EPS <= 0,
    even though revenue > 0. PE is also None there (existing behaviour)."""
    fix = _fund_series_fixture()
    # period 0 EPS == 0 (excluded), period 1 EPS < 0 (excluded); revenue all > 0.
    fix["quarterly"]["eps"] = [0.0, -0.5, 1.2, 1.3]
    fix["quarterly"]["revenue"] = [100.0, 110.0, 120.0, 130.0]
    out = svc.fundamentals_view("AAA", _ratio_data(series=fix), granularity="Q")
    ps_actual = _fund_fig(out, "fund_ps")["traces"][0]["y"]
    pe_actual = _fund_fig(out, "fund_pe")["traces"][0]["y"]
    # EPS <= 0 -> both PS and PE None, despite revenue > 0.
    assert ps_actual[0] is None and ps_actual[1] is None
    assert pe_actual[0] is None and pe_actual[1] is None
    # EPS > 0 -> both computed.
    assert ps_actual[2] is not None and ps_actual[3] is not None
    assert pe_actual[2] is not None and pe_actual[3] is not None


def test_fundamentals_view_ttm_suppressed_when_any_constituent_quarter_nonpositive():
    """EPS-gate (#12 fix) — a TTM point whose 4-quarter window contains an EPS <= 0
    has BOTH PE and PS None, even when the summed TTM EPS is positive."""
    fix = _fund_series_fixture()
    # summed TTM EPS positive at both points, but the first window had a loss quarter.
    fix["ttm"]["eps"] = [4.2, 4.6]
    fix["ttm"]["eps_ok"] = [False, True]
    fix["ttm"]["revenue"] = [420.0, 460.0]
    out = svc.fundamentals_view("AAA", _ratio_data(series=fix), granularity="TTM")
    pe_actual = _fund_fig(out, "fund_pe")["traces"][0]["y"]
    ps_actual = _fund_fig(out, "fund_ps")["traces"][0]["y"]
    # window 0 not ok -> both None (despite positive summed EPS 4.2).
    assert pe_actual[0] is None and ps_actual[0] is None
    # window 1 ok -> both computed.
    assert pe_actual[1] is not None and ps_actual[1] is not None


def test_fundamentals_view_ttm_all_quarters_positive_computes():
    """EPS-gate (#12 fix) — a TTM window with all 4 quarters > 0 computes PE & PS."""
    out = svc.fundamentals_view("AAA", _ratio_data(), granularity="TTM")
    pe_actual = _fund_fig(out, "fund_pe")["traces"][0]["y"]
    ps_actual = _fund_fig(out, "fund_ps")["traces"][0]["y"]
    assert all(v is not None for v in pe_actual)
    assert all(v is not None for v in ps_actual)


def test_fundamentals_view_forecast_suppressed_where_eps_mean_nonpositive():
    """EPS-gate (#12 fix) — a forecast point whose EPS mean <= 0 has PE & PS forecast
    (and band edges) None there, even when revenue forecast > 0."""
    fix = _fund_series_fixture()
    # forward EPS mean: first point 0 (excluded), second < 0 (excluded), third > 0.
    fix["forward_q"]["eps_mean"] = [0.0, -0.2, 1.6]
    fix["forward_q"]["eps_high"] = [0.1, -0.1, 1.9]
    fix["forward_q"]["eps_low"] = [-0.1, -0.3, 1.3]
    # revenue forecast all positive (so PS would compute without the EPS gate).
    fix["forward_q"]["rev_mean"] = [140.0, 150.0, 160.0]
    fix["forward_q"]["rev_high"] = [150.0, 170.0, 190.0]
    fix["forward_q"]["rev_low"] = [130.0, 130.0, 130.0]
    out = svc.fundamentals_view("AAA", _ratio_data(series=fix), granularity="Q")
    for fig_id in ("fund_pe", "fund_ps"):
        fig = _fund_fig(out, fig_id)
        fwd = next(t for t in fig["traces"] if t.get("name") == "Forecast")
        assert fwd["y"][0] is None and fwd["y"][1] is None  # EPS mean <= 0.
        assert fwd["y"][2] is not None                       # EPS mean > 0.
        # band edges gated too: every band trace is None where EPS mean <= 0.
        for t in fig["traces"]:
            if t.get("name") in ("Low", "Est. range"):
                assert t["y"][0] is None and t["y"][1] is None


def test_fundamentals_view_pe_ps_honor_toggle_divider_asof():
    """Behavior 4 (#12) — PE/PS honor the same Q/Y/TTM toggle + today-divider, and
    asof threads through to data.fundamental_series (as #11)."""
    fix = _fund_series_fixture()

    def actual_x(out, fig_id):
        return _fund_fig(out, fig_id)["traces"][0]["x"]

    q = svc.fundamentals_view("AAA", _ratio_data(), granularity="Q")
    y = svc.fundamentals_view("AAA", _ratio_data(), granularity="Y")
    ttm = svc.fundamentals_view("AAA", _ratio_data(), granularity="TTM")
    for fig_id in ("fund_pe", "fund_ps"):
        # toggle selects the actual-period dates (Q quarterly / Y FY / TTM rolling).
        assert actual_x(q, fig_id) == fix["quarterly"]["dates"]
        assert actual_x(y, fig_id) == fix["annual"]["fy_dates"]
        assert actual_x(ttm, fig_id) == fix["ttm"]["dates"]
        # a today-divider shape at the forecast boundary, per granularity.
        for out, boundary in (
            (q, fix["forward_q"]["dates"][0]),
            (y, fix["annual"]["fwd_dates"][0]),
        ):
            shapes = _fund_fig(out, fig_id)["layout"].get("shapes", [])
            assert len(shapes) >= 1
            assert shapes[0]["x0"] == shapes[0]["x1"] == boundary
            assert shapes[0]["yref"] == "paper"

    # asof threads through (same plumbing as #11).
    data = _ratio_data()
    svc.fundamentals_view("AAA", data, asof="2024-09-30")
    assert ("AAA", "2024-09-30") in data.fund_series_calls


def test_fundamentals_view_today_divider_shape():
    """Behavior 4 — each figure's layout carries a vertical today-divider shape at
    the actual/forecast boundary (the first forecast date)."""
    out = svc.fundamentals_view("AAA", _fund_data(), granularity="Q")
    boundary = _fund_series_fixture()["forward_q"]["dates"][0]
    for fig_id in ("fund_eps", "fund_sales"):
        shapes = _fund_fig(out, fig_id)["layout"].get("shapes", [])
        assert len(shapes) >= 1
        div = shapes[0]
        # a full-height (paper-referenced) vertical line at the boundary date.
        assert div["x0"] == div["x1"] == boundary
        assert div["type"] == "line"
        assert div.get("yref") == "paper"


def test_fundamentals_view_asof_passes_through_and_defaults_none():
    """Behavior 5 — asof threads into data.fundamental_series(asof=…); omitted ->
    None (latest)."""
    data = _fund_data()
    # explicit asof is forwarded verbatim.
    svc.fundamentals_view("AAA", data, asof="2024-09-30")
    assert ("AAA", "2024-09-30") in data.fund_series_calls
    # omitted -> defaults to None (latest).
    data2 = _fund_data()
    svc.fundamentals_view("AAA", data2)
    assert data2.fund_series_calls == [("AAA", None)]


def test_fundamentals_view_forecast_only_as_deep_as_data():
    """Behavior 6 — forward points render only as deep as the data holds; no
    fabricated points for thin names (the forecast length tracks the forward dates,
    never padded out to a fixed horizon)."""
    thin = _fund_series_fixture()
    # a thin name: only TWO forward quarters of EPS estimates.
    thin["forward_q"] = {
        "dates": ["2025-03-31", "2025-06-30"],
        "eps_mean": [1.4, 1.5],
        "eps_high": [1.5, 1.7],
        "eps_low": [1.3, 1.3],
        "rev_mean": [140.0, 150.0],
        "rev_high": [150.0, 170.0],
        "rev_low": [130.0, 130.0],
    }
    out = svc.fundamentals_view("AAA", _fund_data(thin), granularity="Q")
    fig = _fund_fig(out, "fund_eps")
    forecast = next(t for t in fig["traces"] if t.get("name") == "Forecast")
    assert forecast["x"] == thin["forward_q"]["dates"]
    assert len(forecast["y"]) == 2  # not padded out to 8.
    # the band tracks the same depth.
    for t in fig["traces"]:
        if t.get("fill"):
            assert len(t["y"]) == 2


def test_blueprint_fundamentals_route_is_thin(monkeypatch):
    """Behavior — GET /api/monitor/fundamentals/<sym>?granularity=&asof= ->
    fundamentals_view -> jsonify (focused 2x2 payload; granularity + asof forwarded)."""
    from flask import Flask
    from sections.monitor import routes

    data = _fund_data()
    monkeypatch.setitem(routes._PROVIDERS, "data", data)
    monkeypatch.setitem(routes._PROVIDERS, "computed", StubComputed())
    monkeypatch.setitem(routes._PROVIDERS, "kernel", KERNEL)
    monkeypatch.setitem(routes._PROVIDERS, "lists", StubLists())

    app = Flask(__name__)
    app.register_blueprint(routes.monitor_bp)
    client = app.test_client()

    resp = client.get("/api/monitor/fundamentals/AAA?granularity=Y&asof=2024-09-30")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    assert payload["meta"]["context"]["granularity"] == "Y"
    fig_ids = {f["id"] for f in payload["figures"]}
    assert {"fund_eps", "fund_sales"} <= fig_ids
    # the route forwarded granularity + asof to the service (via the stub).
    assert ("AAA", "2024-09-30") in data.fund_series_calls


# --------------------------------------------------------------------------- #
# Estimate Revisions sub-pane (Slice 7) — figures + momentum table
# --------------------------------------------------------------------------- #
def _ttm_forward_fixture():
    """Forward-TTM-EPS curves (the shape data.eps_ttm_forward emits): 2 revision
    snapshots, curve[0] = the current snapshot."""
    return {
        "quarter_labels": ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2"],
        "quarter_dates": ["2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30"],
        "curves": [
            {"label": "Current (03/31)", "values": [6.0, 6.2, 6.4, 6.6]},
            {"label": "2024-02-29", "values": [5.8, 6.0, 6.2, 6.4]},
        ],
        "current_ttm": 6.0,
        "forward_mean": [6.0, 6.2, 6.4, 6.6],
        "n_available": 2,
    }


def _rev_data(revisions=None, ttm_forward=None):
    """StubData wired so fundamental_series returns the given revisions block and
    eps_ttm_forward returns the given forward-TTM curves."""
    series = {"revisions": revisions if revisions is not None else _revisions_fixture()}
    return StubData(
        fund_series=series,
        ttm_forward=ttm_forward if ttm_forward is not None else _ttm_forward_fixture(),
    )


def test_revisions_view_emits_ttm_and_eps_figures():
    """Behavior 3 — revisions_view emits rev_ttm (forward-TTM curves + an Actual-TTM
    line) and rev_eps (FY1/FY2 mean + high/low), and NO rev_sales / rev_momentum."""
    out = svc.revisions_view("AAA", _rev_data(), n=2)
    assert out["meta"]["status"] == "ok"
    by_id = {f["id"]: f for f in out["figures"]}
    assert {"rev_ttm", "rev_eps"} == set(by_id)
    # the old design's figures/table are gone.
    assert "rev_sales" not in by_id
    assert all(t["id"] != "rev_momentum" for t in out.get("tables", []))

    ttm = by_id["rev_ttm"]
    ttm_names = [t.get("name") for t in ttm["traces"]]
    # one trace per curve (the curve labels) + the horizontal Actual-TTM line.
    assert "Current (03/31)" in ttm_names
    assert "2024-02-29" in ttm_names
    assert any("Actual TTM" in (n or "") for n in ttm_names)

    eps = by_id["rev_eps"]
    eps_names = [t.get("name") for t in eps["traces"]]
    assert any("FY1" in (n or "") for n in eps_names)
    assert any("FY2" in (n or "") for n in eps_names)


def test_revisions_view_carries_n_available_in_context():
    """Behavior 1/2 — n_available is carried so the client can cap the N input;
    n threads into data.eps_ttm_forward(symbol, n)."""
    data = _rev_data()
    out = svc.revisions_view("AAA", data, n=2)
    assert out["meta"]["context"]["n_available"] == 2
    assert ("AAA", 2) in data.ttm_forward_calls


def test_revisions_view_asof_drops_rows_after_asof():
    """asof threads into data.fundamental_series(asof=…)."""
    data = _rev_data()
    svc.revisions_view("AAA", data, asof="2024-12-31")
    assert ("AAA", "2024-12-31") in data.fund_series_calls


def test_revisions_view_thin_name_is_graceful():
    """Behavior 4 — a thin/empty name -> empty figures, status empty, never raises."""
    empty = {
        "eps": {"fy1": {"dates": [], "mean": [], "high": [], "low": []},
                "fy2": {"dates": [], "mean": [], "high": [], "low": []}},
        "revenue": {"fy1": {"dates": [], "mean": [], "high": [], "low": []},
                    "fy2": {"dates": [], "mean": [], "high": [], "low": []}},
    }
    empty_ttm = {"quarter_labels": [], "curves": [], "current_ttm": None,
                 "n_available": 0}
    out = svc.revisions_view("ZZZ", _rev_data(revisions=empty, ttm_forward=empty_ttm))
    assert out["meta"]["status"] == "empty"
    by_id = {f["id"]: f for f in out["figures"]}
    assert {"rev_ttm", "rev_eps"} == set(by_id)
    for fig in out["figures"]:
        assert all(not t.get("x") for t in fig["traces"])

    # totally missing series/curves -> still graceful.
    out2 = svc.revisions_view("ZZZ", StubData(fund_series={}))
    assert out2["meta"]["status"] == "empty"


def test_blueprint_revisions_route_is_thin(monkeypatch):
    """GET /api/monitor/revisions/<sym>?n= -> revisions_view -> jsonify
    (focused payload; n forwarded to the service via the stub)."""
    from flask import Flask
    from sections.monitor import routes

    data = _rev_data()
    monkeypatch.setitem(routes._PROVIDERS, "data", data)
    monkeypatch.setitem(routes._PROVIDERS, "computed", StubComputed())
    monkeypatch.setitem(routes._PROVIDERS, "kernel", KERNEL)
    monkeypatch.setitem(routes._PROVIDERS, "lists", StubLists())

    app = Flask(__name__)
    app.register_blueprint(routes.monitor_bp)
    resp = app.test_client().get("/api/monitor/revisions/AAA?n=2")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    fig_ids = {f["id"] for f in payload["figures"]}
    assert {"rev_ttm", "rev_eps"} == fig_ids
    assert payload["meta"]["context"]["n_available"] == 2
    assert ("AAA", 2) in data.ttm_forward_calls
