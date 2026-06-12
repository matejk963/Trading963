"""Unit tests for the Macro section (Slice #12 — rename of liquidity + relocate
compute, kill the streamlit_app leak).

All tests use STUBBED providers (spec §8 — no Flask, no DB, no network, and — the
whole point of FLAG-5 — **no streamlit**):

  * scoring parity — the PRIVATE core (`sections/macro/scoring.py`) produces the
    SAME layer Z-scores / regime / stage scores as the original
    `liquidity_monitoring.calculations.*` on a small deterministic fixture
    (parity target: the math the old `liquidity_service` ran).
  * macro.handle — stubbed `data.time_series` -> spec §5.1 ViewModel per view
    (liquidity / layer / overlay / transmission), with the scoring numbers preserved.
  * NO streamlit import anywhere in the section package (source scan + import check).
  * blueprint thinness (Flask test client + stubbed provider).
  * the `(time_series, macro)` DataSource submodule normalizes an injected CSV
    reader result to the canonical symbol×date form.
"""
import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sections.macro import MacroRequest, handle
from sections.macro import scoring as sc
from tests.parity import assert_parity


# --------------------------------------------------------------------------- #
# fixtures — deterministic raw `date × FRED-code` frame
# --------------------------------------------------------------------------- #
def _raw_fred_frame(n=900):
    """Deterministic daily raw FRED frame covering the codes the scoring core reads.

    Smooth synthetic trends so the Z-score / ROC maths are well-defined and the
    parity comparison between the relocated core and the original is exact.
    """
    dates = pd.date_range("2018-01-01", periods=n, freq="D")
    t = np.arange(n)
    cols = {
        # Layer 1
        "WALCL": 4_000_000 + t * 800 + np.sin(t / 40) * 5000,
        "WTREGEN": 400_000 + np.cos(t / 50) * 30_000,
        "RRPONTSYD": 100_000 + np.sin(t / 30) * 20_000,
        "DFF": 1.5 + np.sin(t / 200) * 1.2 + t * 0.001,
        "PCEPILFE": 100 + t * 0.01,
        "CPIAUCSL": 250 + t * 0.02,
        "DGS10": 2.0 + np.sin(t / 120) * 0.5,
        "DGS2": 1.5 + np.sin(t / 100) * 0.4,
        "DFII5": 0.2 + np.sin(t / 90) * 0.3,
        # Layer 2a
        "WRMFNS": 3_000_000 + t * 500,
        "BAMLH0A0HYM2": 4.0 + np.sin(t / 60) * 1.0,
        "BAMLC0A0CM": 1.2 + np.sin(t / 70) * 0.3,
        "VIXCLS": 18 + np.sin(t / 25) * 5,
        "NFCI": -0.3 + np.sin(t / 80) * 0.2,
        "SOFR": 1.4 + np.sin(t / 200) * 1.1,
        "EFFR": 1.45 + np.sin(t / 200) * 1.1,
        "TOTLL": 11_000_000 + t * 1000,
        "BUSLOANS": 2_500_000 + t * 300,
        "M2SL": 18_000_000 + t * 2000,
        # Layer 2b
        "TCU": 78 + np.sin(t / 110) * 2,
        "INDPRO": 100 + t * 0.005,
        "UNRATE": 4.0 + np.sin(t / 130) * 0.8,
        "PPIFIS": 120 + t * 0.015,
        "PPIACO": 200 + t * 0.02,
        # Stage 5
        "SP500": 3000 + t * 2.0 + np.sin(t / 35) * 80,
    }
    df = pd.DataFrame(cols, index=dates)
    df.index.name = "Date"
    return df


def _symbol_date_panel(raw):
    """Pivot a wide date×FRED-code frame to the canonical symbol×date macro TimeSeries."""
    long = raw.stack()
    long.index = long.index.set_names(["date", "symbol"])
    long = long.reorder_levels(["symbol", "date"]).sort_index()
    return pd.DataFrame({"value": long})


class StubData:
    """Returns canned symbol×date panels for macro (value) and an asset (close)."""

    def __init__(self, macro_panel, asset_panel=None):
        self._macro = macro_panel
        self._asset = asset_panel
        self.ts_calls = []

    def time_series(self, ids, start=None, end=None, fields=("value",)):
        ids = [ids] if isinstance(ids, str) else list(ids)
        self.ts_calls.append((tuple(ids), tuple(fields)))
        if "close" in fields and self._asset is not None:
            present = [i for i in ids if i in self._asset.index.get_level_values("symbol")]
            if not present:
                return _empty("close")
            return self._asset.loc[present]
        present = [i for i in ids if i in self._macro.index.get_level_values("symbol")]
        if not present:
            return _empty("value")
        return self._macro.loc[present]


def _empty(field):
    idx = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    return pd.DataFrame({field: pd.Series(dtype="float64")}, index=idx)


class FakeArgs:
    def __init__(self, single=None):
        self._single = dict(single or {})

    def get(self, key, default=None):
        return self._single.get(key, default)


# --------------------------------------------------------------------------- #
# the ORIGINAL liquidity_monitoring calculations — imported with a faked
# streamlit module so the parity reference is the untouched read-copy source.
# --------------------------------------------------------------------------- #
def _import_original():
    repo_root = Path(__file__).resolve().parents[3]
    liq_path = str(repo_root / "src" / "analysis" / "liquidity_monitoring")
    if liq_path not in sys.path:
        sys.path.insert(0, liq_path)
    if "streamlit" not in sys.modules or not hasattr(sys.modules["streamlit"], "cache_data"):
        st = types.ModuleType("streamlit")
        st.cache_data = lambda **kw: (lambda fn: fn)
        sys.modules["streamlit"] = st
    li = importlib.import_module("calculations.liquidity_indicators")
    rc = importlib.import_module("calculations.regime_classifier")
    tc = importlib.import_module("calculations.transmission_chain")
    cfg = importlib.import_module("config.indicators")
    return li, rc, tc, cfg


# --------------------------------------------------------------------------- #
# scoring parity — private core vs the original liquidity math
# --------------------------------------------------------------------------- #
def test_layer_score_parity_vs_original():
    raw = _raw_fred_frame()
    li, _, _, cfg = _import_original()

    new = sc.calculate_historical_continuous_totals(
        raw, sc.LAYER1_INDICATORS, sc.LAYER2A_INDICATORS, sc.LAYER2B_INDICATORS)
    old = li.calculate_historical_continuous_totals(
        raw, cfg.LAYER1_INDICATORS, cfg.LAYER2A_INDICATORS, cfg.LAYER2B_INDICATORS)

    assert list(new.columns) == list(old.columns)
    for col in ("L1", "L2a", "L2b", "Composite"):
        assert_parity(
            [None if pd.isna(v) else float(v) for v in new[col].values],
            [None if pd.isna(v) else float(v) for v in old[col].values],
        )


def test_layer_detail_parity_vs_original():
    raw = _raw_fred_frame()
    li, _, _, cfg = _import_original()

    new = sc.calculate_continuous_layer_scores(raw, sc.LAYER2A_INDICATORS)
    old = li.calculate_continuous_layer_scores(raw, cfg.LAYER2A_INDICATORS)

    assert set(new.columns) == set(old.columns)
    for col in new.columns:
        assert_parity(
            [None if pd.isna(v) else float(v) for v in new[col].values],
            [None if pd.isna(v) else float(v) for v in old[col].values],
        )


def test_regime_parity_vs_original():
    _, rc, _, _ = _import_original()
    for trip in [(0.95, 0.33, 0.41), (-1.2, -0.8, 0.6), (0.0, 0.0, 0.0), (1.1, 1.2, -0.9)]:
        new = sc.classify_regime(*trip)
        old = rc.classify_regime(*trip)
        assert new["regime"] == old["regime"]
        assert new["bias"] == old["bias"]
        assert new["regime_key"] == old["regime_key"]


def test_transmission_parity_vs_original():
    raw = _raw_fred_frame()
    _, _, tc, _ = _import_original()

    new_scores = sc.calculate_stage_scores(raw)
    old_scores = tc.calculate_stage_scores(raw)
    assert set(new_scores) == set(old_scores)
    for stage in new_scores:
        assert_parity(
            [None if pd.isna(v) else float(v) for v in new_scores[stage].values],
            [None if pd.isna(v) else float(v) for v in old_scores[stage].values],
        )

    new_cur = sc.calculate_stage_current(raw)
    old_cur = tc.calculate_stage_current(raw)
    new_brk = sc.detect_transmission_break(new_cur)
    old_brk = tc.detect_transmission_break(old_cur)
    assert new_brk == old_brk


# --------------------------------------------------------------------------- #
# handle — stubbed data.time_series -> ViewModel
# --------------------------------------------------------------------------- #
def test_handle_liquidity_viewmodel_shape():
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    vm = handle(MacroRequest(view="liquidity"), data)

    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["context"]["view"] == "liquidity"
    assert [f["id"] for f in vm["figures"]] == ["liquidity_composite"]
    fig = vm["figures"][0]
    names = {t.get("name") for t in fig["traces"]}
    assert {"L1 (CB)", "L2a (Private)", "L2b (Economy)", "Composite"} <= names
    # readouts carry the regime + layer scalars.
    ro = vm["meta"]["readouts"]
    assert "composite" in ro and "regime" in ro and ro["bias"] in ("bullish", "bearish", "neutral")
    # the section asked data.time_series for the FRED codes.
    assert data.ts_calls
    assert "WALCL" in data.ts_calls[0][0]


def test_handle_liquidity_numbers_match_scoring_core():
    """The VM readout scalars equal the private scoring core's latest values."""
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))

    hist = sc.calculate_historical_continuous_totals(
        raw, sc.LAYER1_INDICATORS, sc.LAYER2A_INDICATORS, sc.LAYER2B_INDICATORS)
    latest = hist.dropna(subset=["Composite"]).iloc[-1]

    vm = handle(MacroRequest(view="liquidity"), data)
    ro = vm["meta"]["readouts"]
    assert ro["l1"] == round(float(latest["L1"]), 3)
    assert ro["l2a"] == round(float(latest["L2a"]), 3)
    assert ro["composite"] == round(float(latest["Composite"]), 3)


def test_handle_layer_viewmodel_shape():
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    vm = handle(MacroRequest(view="layer", layer="2a"), data)

    assert vm["meta"]["status"] == "ok"
    assert [f["id"] for f in vm["figures"]] == ["layer_detail"]
    tbl = next(t for t in vm["tables"] if t["id"] == "layer_indicators")
    assert tbl["columns"] == ["Indicator", "Type", "Z-Score"]
    assert len(tbl["rows"]) >= 1


def test_handle_layer_unknown_is_error():
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    vm = handle(MacroRequest(view="layer", layer="zzz"), data)
    assert vm["meta"]["status"] == "error"


def test_handle_transmission_viewmodel_shape():
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    vm = handle(MacroRequest(view="transmission"), data)

    assert vm["meta"]["status"] == "ok"
    assert [f["id"] for f in vm["figures"]] == ["transmission_chain"]
    tbl = next(t for t in vm["tables"] if t["id"] == "transmission_stages")
    assert tbl["columns"] == ["Stage", "Name", "Score", "Status"]
    assert len(tbl["rows"]) == 7
    assert "break_stage" in vm["meta"]["readouts"]


def test_handle_overlay_viewmodel_shape():
    raw = _raw_fred_frame()
    # build a weekly-ish SPY close panel overlapping the macro history.
    dates = pd.date_range("2018-01-01", periods=900, freq="D")
    spy = pd.DataFrame({"close": 300 + np.arange(900) * 0.5},
                       index=pd.MultiIndex.from_product([["SPY"], dates],
                                                        names=["symbol", "date"]))
    data = StubData(_symbol_date_panel(raw), asset_panel=spy)

    vm = handle(MacroRequest(view="overlay", asset="SPY"), data)
    assert vm["meta"]["status"] == "ok"
    assert [f["id"] for f in vm["figures"]] == ["overlay"]
    names = {t.get("name") for t in vm["figures"][0]["traces"]}
    assert "SPY" in names and "Composite" in names


def test_handle_empty_when_no_data():
    class Empty:
        def time_series(self, ids, **kw):
            return _empty("value")

    vm = handle(MacroRequest(view="liquidity"), Empty())
    assert vm["meta"]["status"] == "empty"
    assert vm["figures"] == []


def test_request_from_query():
    req = MacroRequest.from_query(FakeArgs({"view": "layer", "layer": "2b", "asset": "QQQ"}))
    assert req.view == "layer"
    assert req.layer == "2b"
    assert req.asset == "QQQ"
    # defaults.
    d = MacroRequest.from_query(FakeArgs({}))
    assert d.view == "liquidity" and d.layer == "1" and d.asset == "SPY"


# --------------------------------------------------------------------------- #
# FLAG-5 — NO streamlit import anywhere in the section
# --------------------------------------------------------------------------- #
def test_no_streamlit_import_in_section_sources():
    section_dir = Path(__file__).resolve().parents[1] / "sections" / "macro"
    offenders = []
    for py in section_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("import streamlit") or stripped.startswith("from streamlit"):
                offenders.append(f"{py.name}:{lineno}")
    assert offenders == [], f"streamlit import leaked into the Macro section: {offenders}"


def test_section_modules_do_not_pull_streamlit():
    for mod in ("sections.macro.service", "sections.macro.scoring", "sections.macro.routes"):
        m = importlib.import_module(mod)
        assert "streamlit" not in vars(m)
        assert "st" not in vars(m)


# --------------------------------------------------------------------------- #
# blueprint thinness (Flask test client + stubbed provider)
# --------------------------------------------------------------------------- #
def test_blueprint_api_is_thin(monkeypatch):
    from flask import Flask
    from sections.macro import routes

    data = StubData(_symbol_date_panel(_raw_fred_frame()))
    monkeypatch.setitem(routes._PROVIDERS, "data", data)

    app = Flask(__name__)
    app.register_blueprint(routes.macro_bp)
    client = app.test_client()

    resp = client.get("/macro/api/liquidity")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    assert any(f["id"] == "liquidity_composite" for f in payload["figures"])

    resp2 = client.get("/macro/api/transmission")
    assert resp2.status_code == 200
    assert resp2.get_json()["meta"]["status"] == "ok"


# --------------------------------------------------------------------------- #
# F4 fix — liquidity meta carries the regime badge + score-card data; the shell
# renders the regime badge, score cards, two-level sub-nav, and flow strip.
# --------------------------------------------------------------------------- #
def test_handle_liquidity_emits_regime_badge_and_score_data():
    """The colored regime badge + L1/L2a/L2b/Composite cards need regime_label,
    regime_description, bias, and the four scalars in readouts (F4 gap 4)."""
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    meta = handle(MacroRequest(view="liquidity"), data)["meta"]

    assert isinstance(meta.get("regime_label"), str) and meta["regime_label"]
    assert isinstance(meta.get("regime_description"), str) and meta["regime_description"]
    assert meta.get("bias") in ("bullish", "bearish", "neutral")
    ro = meta["readouts"]
    for k in ("l1", "l2a", "l2b", "composite"):
        assert k in ro and isinstance(ro[k], (int, float))


def test_handle_transmission_emits_stage_rows_and_break():
    """The flow strip is built from the transmission_stages rows + break_stage."""
    raw = _raw_fred_frame()
    data = StubData(_symbol_date_panel(raw))
    vm = handle(MacroRequest(view="transmission"), data)

    tbl = next(t for t in vm["tables"] if t["id"] == "transmission_stages")
    assert tbl["columns"] == ["Stage", "Name", "Score", "Status"]
    assert [r[0] for r in tbl["rows"]] == [f"S{i}" for i in range(1, 8)]
    assert "break_stage" in vm["meta"]


def _page_app():
    """A Flask app with all section blueprints registered (so base.html's url_for
    chrome resolves) and the package + section template dirs on the loader path.
    No DB/provider is touched — only the page route (pure template render) is hit."""
    from flask import Flask
    from jinja2 import ChoiceLoader, FileSystemLoader
    from sections.rrg import routes as rrg_routes
    from sections.macro import routes as macro_routes
    from sections.options import routes as options_routes
    from sections.screener import routes as screener_routes
    from sections.monitor import routes as monitor_routes

    pkg_templates = Path(macro_routes.__file__).resolve().parents[2] / "templates"
    app = Flask(__name__, template_folder=str(pkg_templates))
    # Section shells must win over the legacy app-level templates of the same name
    # (mirrors app._prioritize_section_templates) — section dirs FIRST.
    section_dirs = [FileSystemLoader(str(Path(r.__file__).resolve().parent / "templates"))
                    for r in (rrg_routes, macro_routes, options_routes,
                              screener_routes, monitor_routes)]
    app.jinja_loader = ChoiceLoader(section_dirs + [app.jinja_loader])
    from datetime import datetime
    app.context_processor(lambda: {"now": datetime.utcnow()})
    for bp in (rrg_routes.rrg_bp, macro_routes.macro_bp, options_routes.options_bp,
               screener_routes.screener_bp, monitor_routes.monitor_bp):
        app.register_blueprint(bp)
    return app


def test_macro_page_renders_subnav_badge_and_cards():
    """The shell restores the two-level sub-tab nav, the regime badge, the four
    labelled score cards, the curated overlay list, and the flow strip host
    (F4 gaps 4-5)."""
    html = _page_app().test_client().get("/macro").get_data(as_text=True)

    # two-level sub-tab affordance.
    assert 'id="macro-sub-tabs"' in html
    for view in ("liquidity", "layer", "overlay", "transmission"):
        assert 'data-view="' + view + '"' in html
    # colored regime badge + four labelled score cards + description sink.
    assert 'id="regime-badge"' in html and "regime-badge neutral" in html
    for sid in ("l1-score", "l2a-score", "l2b-score", "composite-score"):
        assert 'id="' + sid + '"' in html
    assert 'id="regime-description"' in html
    # transmission flow strip host.
    assert 'id="transmission-flow"' in html
    # curated overlay list (not a free-text box).
    assert "HYG" in html and "High Yield" in html


# --------------------------------------------------------------------------- #
# DataSource macro submodule — normalize an injected CSV reader
# --------------------------------------------------------------------------- #
def test_macro_submodule_normalizes_to_symbol_date():
    from datasource.submodules.macro import MacroSubmodule

    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    raw = pd.DataFrame({"WALCL": np.arange(5) + 100.0, "DGS10": np.arange(5) + 2.0},
                       index=dates)
    sub = MacroSubmodule(reader=lambda: raw)

    ts = sub.time_series(["WALCL", "DGS10"], fields=("value",))
    assert list(ts.index.names) == ["symbol", "date"]
    assert set(ts.index.get_level_values("symbol")) == {"WALCL", "DGS10"}
    assert "value" in ts.columns
    # the WALCL level survives intact.
    walcl = ts.xs("WALCL", level="symbol")["value"]
    assert list(walcl.values) == [100.0, 101.0, 102.0, 103.0, 104.0]


def test_macro_submodule_tolerates_missing_ids():
    from datasource.submodules.macro import MacroSubmodule

    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    raw = pd.DataFrame({"WALCL": np.arange(3) + 1.0}, index=dates)
    sub = MacroSubmodule(reader=lambda: raw)

    ts = sub.time_series(["WALCL", "NOPE"], fields=("value",))
    assert set(ts.index.get_level_values("symbol")) == {"WALCL"}


def test_default_datasource_routes_macro():
    from datasource import build_default_datasource

    ds = build_default_datasource()
    reg = ds._registry
    assert reg.asset_class_of("WALCL") == "macro"
    assert reg.asset_class_of("DGS10") == "macro"
    assert reg.resolve("time_series", "WALCL") is not None
