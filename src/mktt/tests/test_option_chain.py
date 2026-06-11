"""Unit tests for the `option_chain` DataSource form (Slice #10).

Covers the OptionsSubmodule normalization + selection + caching + stale-cache
fallback, and the DataSource.option_chain registry routing — all with an injected
fake ticker (no yfinance, no network).
"""
import pytest

import pandas as pd

from datasource import (
    DataSource,
    OptionChain,
    OptionChainError,
    OptionsSubmodule,
    Registry,
    build_default_datasource,
)


# --------------------------------------------------------------------------- #
# Fake yfinance ticker
# --------------------------------------------------------------------------- #
class _FakeChain:
    def __init__(self, calls_df, puts_df):
        self.calls = calls_df
        self.puts = puts_df


class _FakeTicker:
    """Minimal yfinance.Ticker stand-in driven by injected data."""

    def __init__(self, options, spot, chains_by_exp, fail_on=None):
        self.options = options
        self._spot = spot
        self._chains = chains_by_exp
        self.fast_info = {"lastPrice": spot}
        self._fail_on = fail_on or set()
        self.calls = 0

    def history(self, period="1d"):
        return pd.DataFrame({"Close": [self._spot]})

    def option_chain(self, exp):
        self.calls += 1
        if exp in self._fail_on:
            raise RuntimeError(f"boom {exp}")
        return self._chains[exp]


def _side_df(rows):
    return pd.DataFrame(rows)


@pytest.fixture
def fake_ticker():
    exps = ["2026-06-19", "2026-06-26", "2026-07-03", "2026-07-17", "2026-08-21"]
    chains = {
        "2026-06-19": _FakeChain(
            _side_df([{"strike": 100.0, "openInterest": 5000, "impliedVolatility": 0.16},
                      {"strike": 105.0, "openInterest": 3000, "impliedVolatility": 0.17},
                      # garbage rows the normalizer must clean:
                      {"strike": float("nan"), "openInterest": 10, "impliedVolatility": 0.2},
                      {"strike": 110.0, "openInterest": float("nan"),
                       "impliedVolatility": float("nan")}]),
            _side_df([{"strike": 95.0, "openInterest": 2000, "impliedVolatility": 0.20}]),
        ),
        "2026-06-26": _FakeChain(
            _side_df([{"strike": 100.0, "openInterest": 2500, "impliedVolatility": 0.17}]),
            _side_df([{"strike": 100.0, "openInterest": 2800, "impliedVolatility": 0.19}]),
        ),
        "2026-07-03": _FakeChain(_side_df([]), _side_df([])),
        "2026-07-17": _FakeChain(_side_df([]), _side_df([])),
        "2026-08-21": _FakeChain(_side_df([]), _side_df([])),
    }
    return _FakeTicker(exps, spot=101.5, chains_by_exp=chains)


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def test_normalize_side_cleans_nan_strike_and_oi_iv():
    from datasource.submodules.options import _normalize_side
    df = _side_df([
        {"strike": 100.0, "openInterest": 5000, "impliedVolatility": 0.16},
        {"strike": float("nan"), "openInterest": 1, "impliedVolatility": 0.2},  # dropped
        {"strike": 105.0, "openInterest": float("nan"), "impliedVolatility": float("nan")},
    ])
    rows = _normalize_side(df)
    assert rows == [
        {"strike": 100.0, "oi": 5000, "iv": 0.16},
        {"strike": 105.0, "oi": 0, "iv": None},   # NaN oi -> 0, NaN iv -> None
    ]


def test_normalize_side_empty():
    from datasource.submodules.options import _normalize_side
    assert _normalize_side(None) == []
    assert _normalize_side(_side_df([])) == []


# --------------------------------------------------------------------------- #
# option_chain — happy path + selection
# --------------------------------------------------------------------------- #
def test_option_chain_returns_form(fake_ticker):
    sub = OptionsSubmodule(ticker_factory=lambda s: fake_ticker)
    oc = sub.option_chain("spy", n_exp=2)
    assert isinstance(oc, OptionChain)
    assert oc.symbol == "SPY"
    assert oc.spot == 101.5
    assert oc.expirations == ["2026-06-19", "2026-06-26"]
    assert oc.available_expirations == fake_ticker.options
    assert oc.default_expirations == fake_ticker.options[:2]
    assert oc.stale is False
    # normalized chains the GEX engine consumes
    first = oc.chains[0]
    assert {"expiration", "dte", "calls", "puts"} <= set(first.keys())
    assert {"strike", "oi", "iv"} <= set(first["calls"][0].keys())
    # NaN-strike garbage row dropped
    assert all(c["strike"] == c["strike"] for c in first["calls"])  # no NaN


def test_option_chain_explicit_expirations(fake_ticker):
    sub = OptionsSubmodule(ticker_factory=lambda s: fake_ticker)
    oc = sub.option_chain("SPY", n_exp=4, expirations=["2026-06-26"])
    assert oc.expirations == ["2026-06-26"]


def test_option_chain_invalid_expirations_fall_back_to_default(fake_ticker):
    sub = OptionsSubmodule(ticker_factory=lambda s: fake_ticker)
    oc = sub.option_chain("SPY", n_exp=2, expirations=["NOT-A-DATE"])
    assert oc.expirations == fake_ticker.options[:2]


def test_option_chain_caches_per_expiration(fake_ticker):
    sub = OptionsSubmodule(ticker_factory=lambda s: fake_ticker)
    sub.option_chain("SPY", n_exp=1)            # fetches 06-19
    first_calls = fake_ticker.calls
    sub.option_chain("SPY", n_exp=2)            # adds 06-26, reuses 06-19 from cache
    # only one *new* chain fetch happened (06-26), 06-19 came from cache
    assert fake_ticker.calls == first_calls + 1


# --------------------------------------------------------------------------- #
# stale-cache fallback
# --------------------------------------------------------------------------- #
def test_option_chain_stale_fallback_when_live_fails():
    exps = ["2026-06-19", "2026-06-26"]
    chains = {
        "2026-06-19": _FakeChain(
            _side_df([{"strike": 100.0, "openInterest": 5000, "impliedVolatility": 0.16}]),
            _side_df([]),
        ),
        "2026-06-26": _FakeChain(_side_df([]), _side_df([])),
    }
    t = _FakeTicker(exps, spot=100.0, chains_by_exp=chains)
    sub = OptionsSubmodule(ticker_factory=lambda s: t)

    warm = sub.option_chain("SPY", n_exp=1)     # warms cache for 06-19
    assert warm.stale is False

    # now make every subsequent chain fetch fail; with force_refresh the
    # submodule must fall back to the cached 06-19 and flag it stale.
    t._fail_on = {"2026-06-19", "2026-06-26"}
    stale = sub.option_chain("SPY", n_exp=1, force_refresh=True)
    assert stale.stale is True
    assert stale.meta["warning"]
    assert stale.expirations == ["2026-06-19"]
    assert stale.chains[0]["calls"][0]["strike"] == 100.0


def test_option_chain_raises_when_no_cache_and_fetch_fails():
    class _Boom:
        options = []  # no expirations -> ValueError inside, no cache to fall back to

    sub = OptionsSubmodule(ticker_factory=lambda s: _Boom())
    with pytest.raises(OptionChainError):
        sub.option_chain("SPY")


# --------------------------------------------------------------------------- #
# DataSource routing via the (option_chain, *) registry row
# --------------------------------------------------------------------------- #
def test_datasource_routes_option_chain(fake_ticker):
    sub = OptionsSubmodule(ticker_factory=lambda s: fake_ticker)
    registry = Registry(submodules={("option_chain", "*"): sub})
    ds = DataSource(registry=registry)
    oc = ds.option_chain("SPY", n_exp=2)
    assert isinstance(oc, OptionChain)
    assert oc.symbol == "SPY"


def test_build_default_datasource_registers_option_chain(fake_ticker):
    ds = build_default_datasource(ticker_factory=lambda s: fake_ticker)
    oc = ds.option_chain("SPY", n_exp=1)
    assert isinstance(oc, OptionChain)
    assert oc.expirations == ["2026-06-19"]
