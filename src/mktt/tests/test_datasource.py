"""Tests for Slice #1 — DataSource: time_series + (form,id) registry + equity submodule + benchmark.

Spec §5.3:
    data.time_series(ids, start=None, end=None, fields=("close","volume")) -> TimeSeries
    TimeSeries == pandas `symbol × date` multi-index DataFrame, columns = fields.

Spec §4.4 / §5.3:
    (form, id) registry: id -> asset_class, then (form, asset_class) -> submodule.

These tests mix pure-unit (fake submodule, no I/O) with integration-light tests
against the real local parquet (skipped gracefully when a file is absent).
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from datasource.provider import DataSource
from datasource.registry import Registry
from datasource.submodules.equity import EquitySubmodule, DATA_DIR


# --------------------------------------------------------------------------- #
# Fakes — pure-unit, no parquet, no network.
# --------------------------------------------------------------------------- #

class FakeSubmodule:
    """A submodule stub returning a deterministic symbol×date panel for known ids."""

    def __init__(self, data):
        # data: {symbol: {field: {date_str: value}}}
        self._data = data
        self.calls = []

    def time_series(self, ids, start=None, end=None, fields=("close", "volume")):
        self.calls.append((tuple(ids), start, end, tuple(fields)))
        frames = []
        for sym in ids:
            if sym not in self._data:
                continue  # missing-id tolerance: skip silently
            per_field = {}
            for f in fields:
                series = self._data[sym].get(f, {})
                per_field[f] = pd.Series(
                    {pd.Timestamp(d): v for d, v in series.items()}
                )
            sub = pd.DataFrame(per_field)
            sub.index.name = "date"
            if start is not None:
                sub = sub[sub.index >= pd.Timestamp(start)]
            if end is not None:
                sub = sub[sub.index <= pd.Timestamp(end)]
            sub = pd.concat({sym: sub}, names=["symbol"])
            frames.append(sub)
        if not frames:
            return _empty_timeseries(fields)
        return pd.concat(frames)


def _empty_timeseries(fields):
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({f: pd.Series(dtype="float64") for f in fields}, index=idx)


@pytest.fixture
def fake_data():
    return {
        "AAA": {
            "close": {"2024-01-01": 10.0, "2024-01-02": 11.0, "2024-01-03": 12.0},
            "volume": {"2024-01-01": 100, "2024-01-02": 110, "2024-01-03": 120},
        },
        "BBB": {
            "close": {"2024-01-01": 20.0, "2024-01-02": 21.0, "2024-01-03": 22.0},
            "volume": {"2024-01-01": 200, "2024-01-02": 210, "2024-01-03": 220},
        },
        "SPY": {
            "close": {"2024-01-01": 400.0, "2024-01-02": 401.0, "2024-01-03": 402.0},
            "volume": {"2024-01-01": 9000, "2024-01-02": 9100, "2024-01-03": 9200},
        },
    }


@pytest.fixture
def fake_provider(fake_data):
    equity = FakeSubmodule(fake_data)
    registry = Registry(
        asset_class={"AAA": "equity", "BBB": "equity", "SPY": "benchmark"},
        submodules={
            ("time_series", "equity"): equity,
            ("time_series", "benchmark"): equity,
        },
        default_asset_class="equity",
    )
    return DataSource(registry=registry, _equity=equity), equity


# --------------------------------------------------------------------------- #
# Registry resolution
# --------------------------------------------------------------------------- #

def test_registry_resolves_equity_id_to_equity_submodule():
    equity = object()
    reg = Registry(
        asset_class={"AAA": "equity"},
        submodules={("time_series", "equity"): equity},
    )
    assert reg.asset_class_of("AAA") == "equity"
    assert reg.resolve("time_series", "AAA") is equity


def test_registry_unknown_id_falls_back_to_default_asset_class():
    equity = object()
    reg = Registry(
        asset_class={},
        submodules={("time_series", "equity"): equity},
        default_asset_class="equity",
    )
    assert reg.asset_class_of("ZZZ") == "equity"
    assert reg.resolve("time_series", "ZZZ") is equity


def test_registry_benchmark_id_tagged_distinctly():
    eq, bench = object(), object()
    reg = Registry(
        asset_class={"AAA": "equity", "SPY": "benchmark"},
        submodules={
            ("time_series", "equity"): eq,
            ("time_series", "benchmark"): bench,
        },
    )
    assert reg.asset_class_of("SPY") == "benchmark"
    assert reg.resolve("time_series", "SPY") is bench


# --------------------------------------------------------------------------- #
# time_series — form & DI (pure unit via fakes)
# --------------------------------------------------------------------------- #

def test_time_series_returns_symbol_date_multiindex(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["AAA"])
    assert isinstance(ts, pd.DataFrame)
    assert list(ts.index.names) == ["symbol", "date"]
    assert "AAA" in ts.index.get_level_values("symbol")


def test_time_series_default_fields_are_close_volume(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["AAA"])
    assert list(ts.columns) == ["close", "volume"]


def test_time_series_fields_subsetting(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["AAA"], fields=("close",))
    assert list(ts.columns) == ["close"]


def test_time_series_multi_id_panel_assembly(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["AAA", "BBB"])
    syms = set(ts.index.get_level_values("symbol"))
    assert syms == {"AAA", "BBB"}
    # 2 symbols x 3 dates
    assert len(ts) == 6


def test_time_series_date_window_slicing(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["AAA"], start="2024-01-02", end="2024-01-03")
    dates = ts.index.get_level_values("date")
    assert dates.min() == pd.Timestamp("2024-01-02")
    assert dates.max() == pd.Timestamp("2024-01-03")
    assert len(ts) == 2


def test_time_series_missing_id_tolerance(fake_provider):
    data, _ = fake_provider
    # NOPE is unknown -> silently skipped, AAA still returned.
    ts = data.time_series(["AAA", "NOPE"])
    syms = set(ts.index.get_level_values("symbol"))
    assert syms == {"AAA"}


def test_time_series_all_missing_returns_empty_with_field_columns(fake_provider):
    data, _ = fake_provider
    ts = data.time_series(["NOPE1", "NOPE2"])
    assert ts.empty
    assert list(ts.columns) == ["close", "volume"]
    assert list(ts.index.names) == ["symbol", "date"]


def test_time_series_string_id_is_accepted(fake_provider):
    data, _ = fake_provider
    ts = data.time_series("AAA")  # single string, not a list
    assert set(ts.index.get_level_values("symbol")) == {"AAA"}


def test_benchmark_id_returns_a_series(fake_provider):
    """FLAG-1: the benchmark (SPY) is just another time_series id with an asset_class tag."""
    data, _ = fake_provider
    ts = data.time_series(["SPY"])
    assert set(ts.index.get_level_values("symbol")) == {"SPY"}
    close = ts.xs("SPY", level="symbol")["close"]
    assert close.loc[pd.Timestamp("2024-01-01")] == 400.0


def test_provider_routes_each_id_through_registry(fake_provider):
    """Mixed equity + benchmark ids resolve via the registry and combine."""
    data, _ = fake_provider
    ts = data.time_series(["AAA", "SPY"])
    assert set(ts.index.get_level_values("symbol")) == {"AAA", "SPY"}


# --------------------------------------------------------------------------- #
# Equity submodule — integration-light against real local parquet.
# --------------------------------------------------------------------------- #

_HAVE_CLOSE = (DATA_DIR / "close.parquet").exists()
_HAVE_SPY = (DATA_DIR / "spy.parquet").exists()


@pytest.mark.skipif(not _HAVE_CLOSE, reason="close.parquet absent")
def test_equity_submodule_reads_real_parquet_panel():
    eq = EquitySubmodule()
    ts = eq.time_series(["AAPL"], fields=("close", "volume"))
    assert list(ts.index.names) == ["symbol", "date"]
    assert "AAPL" in ts.index.get_level_values("symbol")
    assert list(ts.columns) == ["close", "volume"]
    assert len(ts) > 50


@pytest.mark.skipif(not _HAVE_CLOSE, reason="close.parquet absent")
def test_equity_submodule_date_window_on_real_parquet():
    eq = EquitySubmodule()
    ts = eq.time_series(["AAPL"], start="2024-01-01", end="2024-03-31",
                        fields=("close",))
    dates = ts.index.get_level_values("date")
    assert dates.min() >= pd.Timestamp("2024-01-01")
    assert dates.max() <= pd.Timestamp("2024-03-31")


@pytest.mark.skipif(not _HAVE_CLOSE, reason="close.parquet absent")
def test_equity_submodule_missing_ticker_tolerated_on_real_parquet():
    eq = EquitySubmodule()
    ts = eq.time_series(["AAPL", "__NOT_A_TICKER__"], fields=("close",))
    assert set(ts.index.get_level_values("symbol")) == {"AAPL"}


@pytest.mark.skipif(not _HAVE_SPY, reason="spy.parquet absent")
def test_equity_submodule_benchmark_from_spy_parquet():
    """SPY lives in spy.parquet (separate from the universe panels)."""
    eq = EquitySubmodule()
    ts = eq.time_series(["SPY"], fields=("close",))
    assert set(ts.index.get_level_values("symbol")) == {"SPY"}
    assert len(ts) > 50


@pytest.mark.skipif(not _HAVE_SPY, reason="spy.parquet absent")
def test_full_datasource_benchmark_path_real_parquet():
    """End-to-end: build the real DataSource and pull the benchmark via time_series()."""
    from datasource import build_default_datasource

    data = build_default_datasource()
    ts = data.time_series(["SPY"], fields=("close",))
    assert set(ts.index.get_level_values("symbol")) == {"SPY"}


@pytest.mark.skipif(not _HAVE_CLOSE, reason="close.parquet absent")
def test_full_datasource_equity_and_benchmark_combined_real_parquet():
    from datasource import build_default_datasource

    data = build_default_datasource()
    ts = data.time_series(["AAPL", "SPY"], fields=("close",))
    assert {"AAPL", "SPY"} <= set(ts.index.get_level_values("symbol"))


# --------------------------------------------------------------------------- #
# Universe fetch dedup — yf.screen must live in exactly ONE place.
# --------------------------------------------------------------------------- #

def test_equity_universe_uses_injected_screen_client(monkeypatch):
    """The yf.screen/EquityQuery loop is implemented once in the equity submodule
    and accepts an injected screen client (DI) so it is testable without network."""
    calls = []

    class FakeQuery:
        def __init__(self, *a, **k):
            pass

    def fake_screen(q, sortField=None, sortAsc=None, size=250, offset=0):
        calls.append(offset)
        if offset == 0:
            return {"quotes": [{"symbol": "AAA"}, {"symbol": "BBB"}]}
        return {"quotes": []}

    eq = EquitySubmodule(screen=fake_screen, equity_query=FakeQuery)
    quotes = eq.fetch_universe(["NMS"], min_avg_vol=1000)
    assert [q["symbol"] for q in quotes] == ["AAA", "BBB"]
    assert calls == [0, 250]  # paginates until empty


def test_yf_screen_loop_appears_in_exactly_one_module():
    """DoD: the yf.screen / EquityQuery universe-fetch loop exists in exactly one
    place now (the equity submodule). screener.py and data_manager.py must delegate."""
    # tests/ sits inside src/mktt → its parent is the mktt package root.
    src_mktt = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hits = []
    for dirpath, _dirs, files in os.walk(src_mktt):
        if "__pycache__" in dirpath or os.sep + "tests" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path) as fh:
                text = fh.read()
            # The universe-fetch signature: the EquityQuery pagination loop.
            if "EquityQuery(" in text and "result.get(\"quotes\"" in text:
                hits.append(path)
    assert len(hits) == 1, f"universe-fetch loop found in {len(hits)} modules: {hits}"
    assert hits[0].endswith(os.path.join("datasource", "submodules", "equity.py"))


# --------------------------------------------------------------------------- #
# F2 — vectorized panel_technicals (off the wide parquet panels, no per-symbol loop)
# --------------------------------------------------------------------------- #
def test_panel_technicals_vectorized(tmp_path):
    """Vectorized technicals off wide close/volume panels: Price/Change%/ADV/52H/52L."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    close = pd.DataFrame({
        "AAA": [10, 11, 12, 13, 14, 15, 16, 17, 18, 20],
        "BBB": [50, 49, 48, 47, 46, 45, 44, 43, 42, 40],
    }, index=dates)
    volume = pd.DataFrame({"AAA": [1000] * 10, "BBB": [2000] * 10}, index=dates)
    close.to_parquet(tmp_path / "close.parquet")
    volume.to_parquet(tmp_path / "volume.parquet")

    eq = EquitySubmodule(data_dir=tmp_path)
    tech = eq.panel_technicals(["AAA", "BBB", "__MISSING__"], adv_window=5, win_52w=10)

    assert set(tech) == {"AAA", "BBB"}
    assert tech["AAA"]["Price"] == 20.0
    # Change% AAA: 20/18 - 1 = +11.11%
    assert round(tech["AAA"]["Change%"], 2) == 11.11
    # ADV_Dollar = last close * mean(last 5 vols) = 20 * 1000
    assert tech["AAA"]["ADV_Dollar"] == 20.0 * 1000
    # From52H = price/max - 1 = 20/20 - 1 = 0 ; From52L = 20/10 - 1 = +100%
    assert round(tech["AAA"]["From52H"], 2) == 0.0
    assert round(tech["AAA"]["From52L"], 2) == 100.0
    # BBB at its 52w low: From52L ~ 0, From52H negative.
    assert tech["BBB"]["From52H"] < 0


def test_panel_technicals_honors_as_of(tmp_path):
    """as_of slices the price window so Price is the close on/before that date."""
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    close = pd.DataFrame({"AAA": [10, 11, 12, 13, 14]}, index=dates)
    close.to_parquet(tmp_path / "close.parquet")
    eq = EquitySubmodule(data_dir=tmp_path)
    tech = eq.panel_technicals(["AAA"], as_of="2024-01-03")
    assert tech["AAA"]["Price"] == 12.0  # close on 2024-01-03, later bars ignored
