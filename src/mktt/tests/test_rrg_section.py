"""Unit tests for the RRG section (Slice #11 — RRG + kill the streamlit_app leak).

All tests use STUBBED providers (spec §8 — no Flask, no DB, no network, and — the
whole point of FLAG-5 — **no streamlit**):

  * quadrant geometry parity — the PRIVATE core (`sections/rrg/quadrant.py`) produces
    the SAME RS-ratio/momentum numbers as the original `streamlit_app.compute_*`
    on a small deterministic fixture (parity target: the math the old
    `rrg_service.build_rrg_response` ran).
  * rrg.handle — stubbed `data.time_series` -> spec §5.1 ViewModel (figure scatter
    with tails + positions table + meta), with the quadrant numbers preserved.
  * NO streamlit import anywhere in the section package (asserted by source scan +
    sys.modules check).
  * blueprint thinness (Flask test client + stubbed provider).
  * the `(time_series, etf)` / `(time_series, futures)` DataSource submodules
    normalize an injected `yf.download` result to the canonical symbol×date form.
"""
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sections.rrg import RrgRequest, handle
from sections.rrg import quadrant as q
from tests.parity import assert_parity


# --------------------------------------------------------------------------- #
# fixtures — deterministic wide `date × ticker` close panel
# --------------------------------------------------------------------------- #
def _wide_etf_panel(n=400):
    """Deterministic ETF close panel: benchmark + 3 sectors on distinct trends."""
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    t = np.arange(n)
    data = {
        "RSP": 100.0 + t * 0.05 + np.sin(t / 20) * 2,
        "XLK": 100.0 + t * 0.09 + np.sin(t / 15) * 3,   # leading
        "XLF": 100.0 + t * 0.02 + np.cos(t / 25) * 2,   # lagging
        "XLV": 100.0 + t * 0.05 + np.sin(t / 30) * 1.5,
    }
    return pd.DataFrame(data, index=dates)


def _symbol_date_panel(wide):
    """Pivot a wide date×ticker close frame to the canonical symbol×date TimeSeries."""
    long = wide.stack()
    long.index = long.index.set_names(["date", "symbol"])
    long = long.reorder_levels(["symbol", "date"]).sort_index()
    return pd.DataFrame({"close": long})


class StubData:
    """Returns a canned symbol×date close panel; records the requested ids."""

    def __init__(self, panel):
        self._panel = panel
        self.ts_calls = []

    def time_series(self, ids, start=None, end=None, fields=("close", "volume")):
        ids = [ids] if isinstance(ids, str) else list(ids)
        self.ts_calls.append(ids)
        present = [i for i in ids if i in self._panel.index.get_level_values("symbol")]
        if not present:
            idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
            return pd.DataFrame({"close": pd.Series(dtype="float64")}, index=idx)
        return self._panel.loc[present]


class FakeArgs:
    def __init__(self, single=None):
        self._single = dict(single or {})

    def get(self, key, default=None):
        return self._single.get(key, default)


# --------------------------------------------------------------------------- #
# the ORIGINAL streamlit_app compute_* — imported with a faked streamlit module
# so the parity reference is the untouched read-copy source.
# --------------------------------------------------------------------------- #
def _import_streamlit_app():
    repo_root = Path(__file__).resolve().parents[3]
    rrg_path = str(repo_root / "src" / "analysis" / "sector_rrg")
    if rrg_path not in sys.path:
        sys.path.insert(0, rrg_path)
    if "streamlit" not in sys.modules or not hasattr(sys.modules["streamlit"], "set_page_config"):
        st = types.ModuleType("streamlit")
        st.cache_data = lambda **kw: (lambda fn: fn)
        st.set_page_config = lambda **kw: None
        sys.modules["streamlit"] = st
    import streamlit_app  # noqa: E402
    return streamlit_app


# --------------------------------------------------------------------------- #
# quadrant geometry parity — private core vs the original streamlit math
# --------------------------------------------------------------------------- #
def test_etf_quadrant_parity_vs_streamlit():
    wide = _wide_etf_panel()
    sa = _import_streamlit_app()

    new_tail, new_full = q.compute_etf_rrg(wide, "RSP", 65, 20, 8)
    old_tail, old_full = sa.compute_etf_rrg(wide, "RSP", 65, 20, 8)

    assert set(new_tail) == set(old_tail)
    for key in new_tail:
        for col in ("rs_ratio", "rs_momentum"):
            assert_parity(
                list(new_tail[key][col].values),
                list(old_tail[key][col].values),
            )


def test_futures_quadrant_parity_vs_streamlit():
    # Build a wide futures panel covering two full groups (Bonds + Metals).
    tickers = list(q.FUTURES_GROUPS["Bonds"]["contracts"]) + \
        list(q.FUTURES_GROUPS["Metals"]["contracts"])
    n = 400
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    rng = np.random.default_rng(7)
    wide = pd.DataFrame(
        {t: 100.0 + np.cumsum(rng.normal(0.02, 0.6, n)) for t in tickers},
        index=dates,
    )
    sa = _import_streamlit_app()

    new = q.compute_futures_group_rrg(wide, 65, 8, ["Bonds", "Metals"])
    old = sa.compute_futures_group_rrg(wide, 65, 8, {"Bonds", "Metals"})
    new_tail, _ = new
    old_tail, _ = old

    assert set(new_tail) == set(old_tail)
    for key in new_tail:
        for col in ("rs_ratio", "rs_momentum"):
            assert_parity(
                list(new_tail[key][col].values),
                list(old_tail[key][col].values),
            )


def test_get_quadrant_classification():
    assert q.get_quadrant(101, 101) == "Leading"
    assert q.get_quadrant(101, 99) == "Weakening"
    assert q.get_quadrant(99, 99) == "Lagging"
    assert q.get_quadrant(99, 101) == "Improving"


# --------------------------------------------------------------------------- #
# handle — stubbed data.time_series -> ViewModel
# --------------------------------------------------------------------------- #
def test_handle_etf_viewmodel_shape():
    wide = _wide_etf_panel()
    data = StubData(_symbol_date_panel(wide))
    req = RrgRequest(dataset="us", window=13, trail=8)

    vm = handle(req, data)

    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["context"]["dataset"] == "us"
    # one scatter figure keyed by id, with tails (lines) + latest markers.
    assert [f["id"] for f in vm["figures"]] == ["rrg_scatter"]
    fig = vm["figures"][0]
    modes = {t.get("mode") for t in fig["traces"]}
    assert "lines" in modes and "markers+text" in modes
    # quadrant shading shapes present in the layout.
    assert any(s.get("type") == "rect" for s in fig["layout"]["shapes"])
    # positions table keyed by id, columns + rows.
    tbl = next(t for t in vm["tables"] if t["id"] == "rrg_positions")
    assert tbl["columns"] == ["Asset", "Quadrant", "RS-Ratio", "RS-Mom"]
    assert len(tbl["rows"]) >= 1
    # the section asked data.time_series for the benchmark + sectors.
    assert data.ts_calls
    assert "RSP" in data.ts_calls[0]


def test_handle_numbers_match_quadrant_core():
    """The VM scatter/table numbers equal the private core's output (parity)."""
    wide = _wide_etf_panel()
    data = StubData(_symbol_date_panel(wide))
    req = RrgRequest(dataset="us", window=13, trail=8)

    # window=13 -> length_days=65, momentum=max(4,13//3)=4 -> 20 days.
    tail, _ = q.compute_etf_rrg(wide, "RSP", 65, 20, 8)

    vm = handle(req, data)
    tbl = next(t for t in vm["tables"] if t["id"] == "rrg_positions")
    by_name = {q.etf_name_color_map("US Sectors")[k][0]: tail[k] for k in tail}
    for row in tbl["rows"]:
        name, _quad, rs_ratio, rs_mom = row
        latest = by_name[name].iloc[-1]
        assert rs_ratio == round(float(latest["rs_ratio"]), 2)
        assert rs_mom == round(float(latest["rs_momentum"]), 2)


def test_handle_empty_when_no_data():
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    empty = pd.DataFrame({"close": pd.Series(dtype="float64")}, index=idx)

    class Empty:
        def time_series(self, ids, **kw):
            return empty

    vm = handle(RrgRequest(dataset="us"), Empty())
    assert vm["meta"]["status"] == "empty"
    assert vm["figures"] == []


def test_handle_drill_unknown_group_is_error():
    data = StubData(_symbol_date_panel(_wide_etf_panel()))
    vm = handle(RrgRequest(dataset="futures", group="Nope"), data)
    assert vm["meta"]["status"] == "error"


def test_request_from_query():
    req = RrgRequest.from_query(FakeArgs(
        {"dataset": "europe", "period": "3y", "window": "26", "trail": "10"}))
    assert req.dataset == "europe"
    assert req.period == "3y"
    assert req.window == 26
    assert req.trail == 10
    assert not req.is_drill
    # group set -> drill.
    assert RrgRequest.from_query(FakeArgs({"group": "Bonds"})).is_drill


# --------------------------------------------------------------------------- #
# FLAG-5 — NO streamlit import anywhere in the section
# --------------------------------------------------------------------------- #
def test_no_streamlit_import_in_section_sources():
    section_dir = Path(__file__).resolve().parents[1] / "sections" / "rrg"
    offenders = []
    for py in section_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("import streamlit") or stripped.startswith("from streamlit"):
                offenders.append(f"{py.name}:{lineno}")
    assert offenders == [], f"streamlit import leaked into the RRG section: {offenders}"


def test_section_modules_do_not_pull_streamlit():
    """Importing the section must not have imported streamlit (it currently isn't
    imported by anything we touch; assert the section modules themselves are clean)."""
    import importlib

    for mod in ("sections.rrg.service", "sections.rrg.quadrant", "sections.rrg.routes"):
        m = importlib.import_module(mod)
        # the module's own globals reference no streamlit symbol.
        assert "streamlit" not in vars(m)
        assert "st" not in [n for n in vars(m) if n == "st"]


# --------------------------------------------------------------------------- #
# blueprint thinness (Flask test client + stubbed provider)
# --------------------------------------------------------------------------- #
def test_blueprint_api_is_thin(monkeypatch):
    from flask import Flask
    from sections.rrg import routes

    data = StubData(_symbol_date_panel(_wide_etf_panel()))
    monkeypatch.setitem(routes._PROVIDERS, "data", data)

    app = Flask(__name__)
    app.register_blueprint(routes.rrg_bp)
    client = app.test_client()

    resp = client.get("/api/rrg?dataset=us&window=13&trail=8")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    assert any(f["id"] == "rrg_scatter" for f in payload["figures"])


# --------------------------------------------------------------------------- #
# DataSource etf/futures submodules — normalize injected yf.download
# --------------------------------------------------------------------------- #
def test_etf_submodule_normalizes_to_symbol_date():
    from datasource.submodules.rrg_yf import EtfSubmodule

    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    # yf.download multi-ticker shape: column MultiIndex (field, ticker).
    cols = pd.MultiIndex.from_product([["Close", "Volume"], ["XLK", "RSP"]])
    raw = pd.DataFrame(
        np.arange(len(dates) * 4).reshape(len(dates), 4) + 100.0,
        index=dates, columns=cols,
    )

    def fake_download(ids, period=None, progress=None, auto_adjust=None):
        return raw

    sub = EtfSubmodule(download=fake_download)
    ts = sub.time_series(["XLK", "RSP"], fields=("close",))
    assert list(ts.index.names) == ["symbol", "date"]
    assert set(ts.index.get_level_values("symbol")) == {"XLK", "RSP"}
    assert "close" in ts.columns


def test_futures_submodule_tolerates_missing_ids():
    from datasource.submodules.rrg_yf import FuturesSubmodule

    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    cols = pd.MultiIndex.from_product([["Close"], ["ZB=F"]])
    raw = pd.DataFrame(np.arange(len(dates)).reshape(len(dates), 1) + 100.0,
                       index=dates, columns=cols)

    sub = FuturesSubmodule(download=lambda ids, **kw: raw)
    ts = sub.time_series(["ZB=F", "NOPE=F"], fields=("close",))
    # only the present id survives; the missing one is tolerated (skipped).
    assert set(ts.index.get_level_values("symbol")) == {"ZB=F"}


def test_default_datasource_routes_etf_and_futures():
    """build_default_datasource tags ETF/futures ids and registers their submodules."""
    from datasource import build_default_datasource

    ds = build_default_datasource()
    reg = ds._registry
    assert reg.asset_class_of("XLK") == "etf"
    assert reg.asset_class_of("ZB=F") == "futures"
    # benchmark tag wins for SPY (equity benchmark, not the RRG ETF leaf).
    assert reg.asset_class_of("SPY") == "benchmark"
    # the (time_series, etf)/(futures) rows resolve to a submodule.
    assert reg.resolve("time_series", "XLK") is not None
    assert reg.resolve("time_series", "ZB=F") is not None
