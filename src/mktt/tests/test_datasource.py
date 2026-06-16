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


# --------------------------------------------------------------------------- #
# fundamental_series — pkl-backed EPS/Sales actual+forecast blend (FORK-2, #11)
# --------------------------------------------------------------------------- #
def _fake_fund_pkl():
    """A small deterministic Refinitiv-shaped pkl dict (drives the blend math
    without the 37 MB on-disk file). 6 quarterly actuals for AAA (2023 full year +
    2024 H1), a 3-quarter forward fan, and FY1/FY2 forward."""
    q = pd.DataFrame({
        "Symbol": ["AAA"] * 6,
        "Date": ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
                 "2024-03-31", "2024-06-30"],
        "Earnings Per Share - Actual": [1.0, 1.0, 1.0, 1.0, 2.0, 2.0],
        "Revenue - Actual": [100e6, 100e6, 100e6, 100e6, 200e6, 200e6],
    })
    fwd = pd.DataFrame({
        "Symbol": ["AAA"] * 3,
        "Earnings Per Share - Mean": [2.0, 2.0, 3.0],
        "Earnings Per Share - High": [2.5, 2.5, 3.5],
        "Earnings Per Share - Low": [1.5, 1.5, 2.5],
        "Revenue - Mean": [200e6, 200e6, 300e6],
        "Revenue - High": [250e6, 250e6, 350e6],
        "Revenue - Low": [150e6, 150e6, 250e6],
    })
    fy1 = pd.DataFrame({"Symbol": ["AAA"], "Earnings Per Share - Mean": [8.0],
                        "Earnings Per Share - High": [9.0], "Earnings Per Share - Low": [7.0],
                        "Revenue - Mean": [800e6], "Revenue - High": [900e6],
                        "Revenue - Low": [700e6]})
    fy2 = pd.DataFrame({"Symbol": ["AAA"], "Earnings Per Share - Mean": [10.0],
                        "Earnings Per Share - High": [11.0], "Earnings Per Share - Low": [9.0],
                        "Revenue - Mean": [1000e6], "Revenue - High": [1100e6],
                        "Revenue - Low": [900e6]})
    # estimate-revision trend frames: the forward FY1/FY2 estimate as it was revised
    # over time (each row = the estimate as-of `Date`). EPS trends carry High/Low;
    # revenue trends are mean-only (High/Low columns absent — handled gracefully).
    trend_eps_fy1 = pd.DataFrame({
        "Symbol": ["AAA"] * 3,
        "Date": ["2024-01-31", "2024-02-29", "2024-03-31"],
        "Earnings Per Share - Mean": [7.8, 8.0, 8.2],
        "Earnings Per Share - High": [8.3, 8.5, 8.7],
        "Earnings Per Share - Low": [7.3, 7.5, 7.7],
    })
    trend_eps_fy2 = pd.DataFrame({
        "Symbol": ["AAA"] * 3,
        "Date": ["2024-01-31", "2024-02-29", "2024-03-31"],
        "Earnings Per Share - Mean": [9.6, 10.0, 10.4],
        "Earnings Per Share - High": [10.6, 11.0, 11.4],
        "Earnings Per Share - Low": [8.6, 9.0, 9.4],
    })
    trend_rev_fy1 = pd.DataFrame({
        "Symbol": ["AAA"] * 3,
        "Date": ["2024-01-31", "2024-02-29", "2024-03-31"],
        "Revenue - Mean": [780e6, 800e6, 820e6],
    })
    trend_rev_fy2 = pd.DataFrame({
        "Symbol": ["AAA"] * 3,
        "Date": ["2024-01-31", "2024-02-29", "2024-03-31"],
        "Revenue - Mean": [960e6, 1000e6, 1040e6],
    })
    # per-quarter forward EPS estimate trends (FQ1..FQ4): each frame is the
    # estimate for that forward quarter as it was revised across snapshot dates.
    # 3 snapshot dates shared across the 4 quarters -> 3 revision curves.
    def _fq(base):
        return pd.DataFrame({
            "Symbol": ["AAA"] * 3,
            "Date": ["2024-01-31", "2024-02-29", "2024-03-31"],
            "Earnings Per Share - Mean": [base - 0.1, base, base + 0.1],
        })
    trend_eps_fq1 = _fq(2.0)
    trend_eps_fq2 = _fq(2.0)
    trend_eps_fq3 = _fq(3.0)
    trend_eps_fq4 = _fq(3.0)
    return {"quarterly": q, "forward_quarterly": fwd, "fy1": fy1, "fy2": fy2,
            "trend_eps_fy1": trend_eps_fy1, "trend_eps_fy2": trend_eps_fy2,
            "trend_rev_fy1": trend_rev_fy1, "trend_rev_fy2": trend_rev_fy2,
            "trend_eps_fq1": trend_eps_fq1, "trend_eps_fq2": trend_eps_fq2,
            "trend_eps_fq3": trend_eps_fq3, "trend_eps_fq4": trend_eps_fq4}


def _fund_access():
    from datasource.fundamental_series import build_fundamental_series
    data = _fake_fund_pkl()
    return build_fundamental_series(loader=lambda: data)


def test_fundamental_series_quarterly_actuals():
    """Quarterly block carries the dated EPS/Revenue actuals (revenue in $m)."""
    out = _fund_access()("AAA")
    qb = out["quarterly"]
    assert qb["dates"] == ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
                           "2024-03-31", "2024-06-30"]
    assert qb["eps"] == [1.0, 1.0, 1.0, 1.0, 2.0, 2.0]
    assert qb["revenue"] == [100.0, 100.0, 100.0, 100.0, 200.0, 200.0]  # $m


def test_fundamental_series_forward_quarterly_fan_depth_and_scale():
    """Forward-quarterly fan: mean/high/low only as deep as the data (3 quarters),
    revenue scaled to $m, dated +3m off the last actual quarter (no fabrication)."""
    out = _fund_access()("AAA")
    fq = out["forward_q"]
    assert len(fq["dates"]) == 3  # 3 forward quarters, not padded to 8.
    assert fq["eps_mean"] == [2.0, 2.0, 3.0]
    assert fq["eps_high"] == [2.5, 2.5, 3.5]
    assert fq["eps_low"] == [1.5, 1.5, 2.5]
    assert fq["rev_mean"] == [200.0, 200.0, 300.0]  # $m
    assert fq["dates"][0] == "2024-09-30"  # +3m off 2024-06-30


def test_fundamental_series_ttm_rolling_4q_sum():
    """TTM block: rolling 4-quarter sum of the actuals, plus a forward-TTM band."""
    out = _fund_access()("AAA")
    ttm = out["ttm"]
    # first complete TTM window ends 2023-12-31 = sum(1,1,1,1) = 4.0.
    assert ttm["dates"][0] == "2023-12-31"
    assert ttm["eps"][0] == 4.0
    assert ttm["revenue"][0] == 400.0  # $m
    # forward-TTM at step 1 = trailing[1:]+fwd[:1] window -> [1,2,2,2] = 7.0.
    assert ttm["eps_mean"][0] == 7.0
    # the forward band carries through (high/low present, same depth).
    assert len(ttm["eps_high"]) == len(ttm["fwd_dates"])


def test_fundamental_series_ttm_eps_ok_flags_all_quarters_positive():
    """The TTM block exposes ``eps_ok`` aligned 1:1 with ``dates``: True when all 4
    trailing quarters are strictly > 0, False if any is <= 0 or None.

    With a loss quarter injected into the trailing window, the TTM points whose
    4-quarter window touches that quarter must be flagged not-ok, even though the
    summed TTM EPS may still be positive."""
    from datasource.fundamental_series import build_fundamental_series
    data = _fake_fund_pkl()
    # inject a loss quarter at 2023-09-30 (the 3rd of 6 quarters).
    data["quarterly"] = data["quarterly"].copy()
    data["quarterly"].loc[2, "Earnings Per Share - Actual"] = -0.5
    out = build_fundamental_series(loader=lambda: data)("AAA")
    ttm = out["ttm"]
    assert "eps_ok" in ttm
    assert len(ttm["eps_ok"]) == len(ttm["dates"])
    # 6 quarters (idx 0..5), loss at idx 2. TTM windows (each ends at idx i, i>=3):
    #   end 2023-12-31: Q0..Q3 -> touches loss -> False
    #   end 2024-03-31: Q1..Q4 -> touches loss -> False
    #   end 2024-06-30: Q2..Q5 -> touches loss -> False
    assert ttm["eps_ok"] == [False, False, False]


def test_fundamental_series_ttm_eps_ok_all_positive_is_true():
    """All 4 trailing quarters > 0 -> the TTM point is eps_ok True (default fixture
    has only positive EPS so every TTM point is ok)."""
    out = _fund_access()("AAA")
    ttm = out["ttm"]
    assert ttm["eps_ok"] == [True] * len(ttm["dates"])


def test_fundamental_series_annual_actual_plus_fy1_fy2_forward():
    """Annual block: complete-year actuals + FY1/FY2 forward (mean/high/low, $m)."""
    out = _fund_access()("AAA")
    ann = out["annual"]
    # only 2023 is a complete 4-quarter year -> EPS sum 4.0, revenue 400 $m.
    assert ann["fy_dates"] == ["2023-12-31"]
    assert ann["eps"] == [4.0]
    assert ann["rev"] == [400.0]
    # FY1/FY2 forward.
    assert ann["eps_mean"] == [8.0, 10.0]
    assert ann["eps_high"] == [9.0, 11.0]
    assert ann["rev_mean"] == [800.0, 1000.0]  # $m
    assert ann["fwd_dates"] == ["2024-12-31", "2025-12-31"]


def test_fundamental_series_asof_filters_quarterly_actuals():
    """asof clips quarterly/TTM actuals to report_date <= asof (the forward fan,
    an as-of-now snapshot, is unaffected)."""
    out = _fund_access()("AAA", asof="2023-12-31")
    assert out["quarterly"]["dates"] == ["2023-03-31", "2023-06-30",
                                         "2023-09-30", "2023-12-31"]
    # forward fan still present (it's the current estimate snapshot).
    assert len(out["forward_q"]["dates"]) == 3


def test_fundamental_series_unknown_symbol_is_empty_not_error():
    """A symbol absent from the pkl returns empty blocks, never raises."""
    out = _fund_access()("ZZZ")
    assert out["quarterly"]["dates"] == []
    assert out["forward_q"]["dates"] == []
    assert out["annual"]["fy_dates"] == []


def test_fundamental_series_revisions_eps_and_revenue_fy1_fy2():
    """The revisions block carries eps + revenue, each with fy1 + fy2 trend lines
    (dates + mean; EPS with high/low, revenue mean-only when high/low absent)."""
    out = _fund_access()("AAA")
    rev = out["revisions"]
    # EPS FY1 trend: dates sorted, mean/high/low present (revenue $-figures /1e6).
    eps_fy1 = rev["eps"]["fy1"]
    assert eps_fy1["dates"] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert eps_fy1["mean"] == [7.8, 8.0, 8.2]
    assert eps_fy1["high"] == [8.3, 8.5, 8.7]
    assert eps_fy1["low"] == [7.3, 7.5, 7.7]
    assert rev["eps"]["fy2"]["mean"] == [9.6, 10.0, 10.4]
    # Revenue FY1 trend: mean in $m; High/Low columns absent -> empty.
    rev_fy1 = rev["revenue"]["fy1"]
    assert rev_fy1["dates"] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert rev_fy1["mean"] == [780.0, 800.0, 820.0]  # $m
    assert rev_fy1["high"] == []
    assert rev_fy1["low"] == []
    assert rev["revenue"]["fy2"]["mean"] == [960.0, 1000.0, 1040.0]


def test_fundamental_series_revisions_asof_drops_rows_after_asof():
    """asof drops revision rows dated after the cutoff (Date <= asof)."""
    out = _fund_access()("AAA", asof="2024-02-29")
    assert out["revisions"]["eps"]["fy1"]["dates"] == ["2024-01-31", "2024-02-29"]
    assert out["revisions"]["eps"]["fy1"]["mean"] == [7.8, 8.0]


def test_fundamental_series_revisions_unknown_symbol_empty():
    """A symbol absent from the trend frames -> empty revision lines, never raises."""
    rev = _fund_access()("ZZZ")["revisions"]
    assert rev["eps"]["fy1"]["dates"] == []
    assert rev["revenue"]["fy2"]["mean"] == []


# --------------------------------------------------------------------------- #
# eps_ttm_forward — the forward-TTM-EPS revision curves (Slice 7 replica)
# --------------------------------------------------------------------------- #
def _fake_ttm_pkl():
    """Like _fake_fund_pkl but with a 4-quarter forward fan + FQ1..FQ4 trends, the
    minimum the forward-TTM-EPS roll needs (legacy requires >= 4 forward quarters)."""
    data = _fake_fund_pkl()
    data["forward_quarterly"] = pd.DataFrame({
        "Symbol": ["AAA"] * 4,
        "Earnings Per Share - Mean": [2.0, 2.0, 3.0, 3.0],
    })
    return data


def _ttm_access():
    from datasource.fundamental_series import build_eps_ttm_forward
    data = _fake_ttm_pkl()
    return build_eps_ttm_forward(loader=lambda: data)


def test_eps_ttm_forward_shape_and_current_curve_first():
    """eps_ttm_forward returns quarter_labels + curves + current_ttm + n_available;
    one curve per revision snapshot (newest first, curve[0] label 'Current (...)')."""
    out = _ttm_access()("AAA", n=3)
    assert out["n_available"] == 3
    assert len(out["curves"]) == 3
    # newest-first: curve[0] is the latest snapshot, labelled 'Current (mm/dd)'.
    assert out["curves"][0]["label"].startswith("Current")
    # forward quarter labels (4 forward quarters off 2024-06-30).
    assert out["quarter_labels"][0] == "2024-Q3"
    # current TTM = sum of the last 4 actual EPS (1,1,2,2) = 6.0.
    assert out["current_ttm"] == 6.0
    # each curve carries a values list aligned to the quarter labels.
    assert len(out["curves"][0]["values"]) == len(out["quarter_labels"])


def test_eps_ttm_forward_n_clamps_to_available():
    """n clamps to [1, n_available]: n>available -> available, n<1 -> 1 curve."""
    over = _ttm_access()("AAA", n=10)
    assert len(over["curves"]) == 3  # clamped to n_available
    under = _ttm_access()("AAA", n=0)
    assert len(under["curves"]) == 1  # clamped up to 1


def test_eps_ttm_forward_unknown_symbol_graceful():
    """A symbol absent from the pkl -> empty curves, never raises."""
    out = _ttm_access()("ZZZ", n=3)
    assert out["curves"] == []
    assert out["n_available"] == 0


def test_datasource_fundamental_series_delegates_to_injected_access():
    """DataSource.fundamental_series delegates to the injected access (DI seam)."""
    from datasource.provider import DataSource
    from datasource.registry import Registry

    calls = []

    def access(symbol, asof=None):
        calls.append((symbol, asof))
        return {"quarterly": {"dates": [symbol]}}

    ds = DataSource(registry=Registry(asset_class={}, submodules={},
                                      default_asset_class="equity"),
                    fundamental_series=access)
    out = ds.fundamental_series("AAA", asof="2024-01-01")
    assert calls == [("AAA", "2024-01-01")]
    assert out["quarterly"]["dates"] == ["AAA"]


def test_datasource_eps_ttm_forward_delegates_to_injected_access():
    """DataSource.eps_ttm_forward delegates to the injected access (DI seam)."""
    from datasource.provider import DataSource
    from datasource.registry import Registry

    calls = []

    def access(symbol, n=3):
        calls.append((symbol, n))
        return {"curves": [{"label": "Current (01/01)", "values": []}], "n_available": 1}

    ds = DataSource(registry=Registry(asset_class={}, submodules={},
                                      default_asset_class="equity"),
                    eps_ttm_forward=access)
    out = ds.eps_ttm_forward("AAA", n=5)
    assert calls == [("AAA", 5)]
    assert out["n_available"] == 1
