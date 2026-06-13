"""Unit tests for the Screener section (Slice #7 — tracer bullet).

Three sub-slices, all with STUBBED providers (spec §8 — no Flask, no DB, no net):

  7a  ScreenRequest.from_query  — parses the ~40 filters from representative combos.
  7b  screener.handle           — joins cross_section + fundamentals, derives PE /
                                  median-PE premium, applies filters, sorts, shapes
                                  the ViewModel; ≥3 filter-combo parity-style asserts.
  7c  the ViewModel shape       — spec §5.1 envelope (tables/meta.readouts/asof).

Parity target = the CURRENT `/screener` route (`app.py:214-880`), the NUMBERS not the
bytes (PRD / log FLAG-8). We rebuild the route's range-filter / growth-preset /
median-PE formulas over hand-built fixtures and assert the joined+filtered+ranked
output matches.
"""
import pandas as pd
import pytest

from parity import assert_parity
from sections.screener import ScreenRequest, handle
from sections.screener import service as svc


# --------------------------------------------------------------------------- #
# test doubles
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


class StubComputed:
    """Returns a fixed cross_section frame; optional asof scalar."""

    def __init__(self, frame, asof=None):
        self._frame = frame
        self.asof = asof

    def cross_section(self, filters=None):
        return self._frame


class StubData:
    """Returns a fixed fundamentals frame; records the requested ids.

    Optionally carries a long ``quarterly`` frame and a ``panel_technicals`` dict
    so the growth-derivation and vectorized-technicals paths can be exercised.
    """

    def __init__(self, frame, quarterly=None, panel=None):
        self._frame = frame
        self._quarterly = quarterly
        self._panel = panel
        self.last_ids = None
        self.last_estimates = None

    def fundamentals(self, ids, fields=None, estimates=False):
        self.last_ids = list(ids)
        self.last_estimates = estimates
        return self._frame

    def quarterly(self, ids, fields=None):
        if self._quarterly is None:
            import pandas as _pd
            return _pd.DataFrame()
        return self._quarterly

    def panel_technicals(self, ids, **kwargs):
        return dict(self._panel or {})


def _cross(rows):
    """Build a symbol-indexed cross_section frame from {symbol: {col: val}}."""
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "symbol"
    return df


def _funds(rows):
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "symbol"
    return df


# --------------------------------------------------------------------------- #
# 7a — ScreenRequest.from_query
# --------------------------------------------------------------------------- #
def test_from_query_defaults():
    req = ScreenRequest.from_query(FakeArgs())
    assert req.preset == "all"
    assert req.min_turnover == 500_000
    assert req.sector == "All"
    assert req.min_price == 0.0
    assert req.sort_by == "turnover"  # all-preset default
    assert not req.has_fund_filters
    assert not req.has_tech_filters
    assert not req.has_class_filters


def test_from_query_sort_default_depends_on_preset():
    req = ScreenRequest.from_query(FakeArgs(single={"preset": "stage2"}))
    assert req.sort_by == "rs"


def test_from_query_fundamental_ranges_and_mins():
    args = FakeArgs(single={
        "pe_min": "5", "pe_max": "30",
        "evebitda_max": "15",
        "rs_min": "70", "analysts_min": "3",
        "opmgn_min": "", "opmgn_max": "",  # blank -> ignored
    })
    req = ScreenRequest.from_query(args)
    assert req.fund_ranges["pe"] == (5.0, 30.0)
    assert req.fund_ranges["evebitda"] == (None, 15.0)
    assert "opmgn" not in req.fund_ranges
    assert req.fund_mins["rs"] == 70.0
    assert req.fund_mins["analysts"] == 3.0
    assert req.has_fund_filters


def test_from_query_classification_multiselect_and_presets():
    args = FakeArgs(
        single={"eps_growth": "ntm_pos", "rev_growth": "all_pos",
                "eps_accel_filter": "accel", "ma_setup": "above_all"},
        multi={"pca_regime": ["1", "2"], "stage_class": ["2"],
               "eps_accel": ["Accelerating"], "ma_screen": ["3"]},
    )
    req = ScreenRequest.from_query(args)
    assert req.class_multi["pca_regime"] == ["1", "2"]
    assert req.class_multi["stage_class"] == ["2"]
    assert req.eps_growth == "ntm_pos"
    assert req.rev_growth == "all_pos"
    assert req.eps_accel_filter == "accel"
    assert req.ma_setup == "above_all"
    assert req.has_fund_filters  # growth presets count
    assert req.has_tech_filters  # ma_setup counts
    assert req.has_class_filters


def test_from_query_technical_ranges():
    args = FakeArgs(single={"pct50_min": "0", "pct200_min": "10",
                            "from52h_max": "-5", "from52l_min": "20"})
    req = ScreenRequest.from_query(args)
    assert req.tech_ranges["pct50"] == (0.0, None)
    assert req.tech_ranges["pct200"] == (10.0, None)
    assert req.tech_ranges["from52h"] == (None, -5.0)
    assert req.tech_mins["from52l"] == 20.0
    assert req.has_tech_filters


def test_from_query_bad_numerics_fall_back():
    args = FakeArgs(single={"min_turnover": "abc", "min_price": "xyz"})
    req = ScreenRequest.from_query(args)
    assert req.min_turnover == 500_000
    assert req.min_price == 0.0


# --------------------------------------------------------------------------- #
# fixtures: a small 4-symbol universe joined across the two providers
# --------------------------------------------------------------------------- #
def _universe():
    cross = _cross({
        "AAA": {"stage": 2, "rs_rank": 90.0, "mansfield_rs": 1.2,
                "ma_50": 100.0, "ma_150": 95.0, "ma_200": 90.0,
                "regime": 1, "ma_screen": 3, "eps_accel": 1},
        "BBB": {"stage": 4, "rs_rank": 40.0, "mansfield_rs": -0.5,
                "ma_50": 50.0, "ma_150": 55.0, "ma_200": 60.0,
                "regime": 2, "ma_screen": 0, "eps_accel": 0},
        "CCC": {"stage": 2, "rs_rank": 75.0, "mansfield_rs": 0.8,
                "ma_50": 200.0, "ma_150": 190.0, "ma_200": 180.0,
                "regime": 1, "ma_screen": 3, "eps_accel": 1},
        "DDD": {"stage": 1, "rs_rank": 10.0, "mansfield_rs": -1.0,
                "ma_50": 30.0, "ma_150": 32.0, "ma_200": 35.0,
                "regime": 3, "ma_screen": 0, "eps_accel": 0},
    })
    funds = _funds({
        # price_close, eps_actual, gics_sector/industry, margins, etc.
        "AAA": {"price_close": 120.0, "eps_actual": 6.0, "fy1_eps_mean": 8.0,
                "gics_sector": "Tech", "gics_industry": "Software",
                "operating_margin": 25.0, "roic": 18.0, "ev_to_ebitda": 20.0,
                "net_debt_to_ebitda": 1.0, "num_analysts": 12.0},
        "BBB": {"price_close": 48.0, "eps_actual": 4.0, "fy1_eps_mean": 4.5,
                "gics_sector": "Tech", "gics_industry": "Hardware",
                "operating_margin": 10.0, "roic": 8.0, "ev_to_ebitda": 8.0,
                "net_debt_to_ebitda": 3.0, "num_analysts": 5.0},
        "CCC": {"price_close": 210.0, "eps_actual": 10.0, "fy1_eps_mean": 14.0,
                "gics_sector": "Energy", "gics_industry": "Oil",
                "operating_margin": 30.0, "roic": 22.0, "ev_to_ebitda": 6.0,
                "net_debt_to_ebitda": 0.5, "num_analysts": 8.0},
        "DDD": {"price_close": 28.0, "eps_actual": -1.0, "fy1_eps_mean": 0.5,
                "gics_sector": "Energy", "gics_industry": "Oil",
                "operating_margin": 5.0, "roic": 3.0, "ev_to_ebitda": 12.0,
                "net_debt_to_ebitda": 4.0, "num_analysts": 2.0},
    })
    # turnover comes from the cross-section in the precomputed model; add it.
    cross["ADV_Dollar"] = pd.Series({"AAA": 5e8, "BBB": 2e8, "CCC": 9e8, "DDD": 1e8})
    return cross, funds


def _row_by_symbol(table, symbol):
    cols = table["columns"]
    sidx = cols.index("Symbol")
    for r in table["rows"]:
        if r[sidx] == symbol:
            return dict(zip(cols, r))
    return None


# --------------------------------------------------------------------------- #
# 7b — handle: join + derive + filter + sort
# --------------------------------------------------------------------------- #
def test_handle_shape_and_readouts():
    cross, funds = _universe()
    data, computed = StubData(funds), StubComputed(cross, asof="2026-06-10")

    vm = handle(ScreenRequest.from_query(FakeArgs()), data, computed)

    # spec §5.1 envelope shape.
    assert set(vm.keys()) == {"figures", "tables", "meta"}
    assert vm["figures"] == []
    assert len(vm["tables"]) == 1
    assert vm["tables"][0]["id"] == "screener_results"
    assert vm["meta"]["status"] == "ok"
    assert vm["meta"]["asof"] == "2026-06-10"
    assert vm["meta"]["title"] == "Screener"
    assert vm["meta"]["readouts"]["universe_total"] == 4
    # min_turnover default 500_000 passes all 4 (turnovers are >= 1e8); all 4 priced+sectored.
    assert vm["meta"]["readouts"]["passed"] == 4
    # fundamentals were requested for the whole computed universe.
    assert set(data.last_ids) == {"AAA", "BBB", "CCC", "DDD"}


def test_handle_derives_pe_and_median_premium():
    cross, funds = _universe()
    vm = handle(ScreenRequest.from_query(FakeArgs()),
                StubData(funds), StubComputed(cross))
    tbl = vm["tables"][0]

    aaa = _row_by_symbol(tbl, "AAA")
    # PE = price/eps = 120/6 = 20.0
    assert_parity(aaa["PE"], 20.0)
    # FwdPE = price/fy1_eps = 120/8 = 15.0
    assert_parity(aaa["FwdPE"], 15.0)

    # Sector medians (Tech): AAA PE=20, BBB PE=48/4=12 -> median 16.
    # AAA PE_vs_Sector = 20/16 = 1.25 (rounded 2dp).
    assert_parity(aaa["PE_vs_Sector"], 1.25)

    # Industry Software has only AAA -> PE/median = 20/20 = 1.0.
    assert_parity(aaa["PE_vs_Industry"], 1.0)

    # DDD eps < 0 -> PE None (no premium).
    ddd = _row_by_symbol(tbl, "DDD")
    assert ddd["PE"] is None
    assert ddd["PE_vs_Sector"] is None


# ----- parity-style filter-combo assertions (≥3) --------------------------- #
def test_parity_combo_sector_and_rs_min():
    """Combo 1: sector=Tech + rs_min=70 -> only AAA (BBB rs=40 drops)."""
    cross, funds = _universe()
    args = FakeArgs(single={"sector": "Tech", "rs_min": "70"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA"}
    assert vm["meta"]["readouts"]["passed"] == 1


def test_parity_combo_fundamental_range_and_classification():
    """Combo 2: evebitda_max=10 + stage_class=[2] -> CCC only.

    EV/EBITDA: AAA=20, BBB=8, CCC=6, DDD=12 -> <=10 keeps BBB,CCC.
    stage==2 keeps AAA,CCC. Intersection (both filters) -> CCC.
    """
    cross, funds = _universe()
    args = FakeArgs(single={"evebitda_max": "10"}, multi={"stage_class": ["2"]})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"CCC"}


def test_parity_combo_ma_setup_above_all():
    """Combo 3: ma_setup=above_all -> Price > MA50,MA150,MA200.

    AAA price120 > (100,95,90) yes; CCC 210 > (200,190,180) yes;
    BBB 48 vs (50,55,60) no; DDD 28 vs (30,32,35) no.
    """
    cross, funds = _universe()
    args = FakeArgs(single={"ma_setup": "above_all"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA", "CCC"}


def test_parity_combo_eps_growth_preset():
    """Combo 4: eps_growth=ntm_pos over a row carrying G_NTM_TTM.

    The route's growth columns come from quarterly EPS; here we inject the derived
    G_* directly onto the cross-section to exercise the preset predicate in
    isolation (the formula port). Only rows with G_NTM_TTM > 0 survive.
    """
    cross, funds = _universe()
    cross["G_NTM_TTM"] = pd.Series({"AAA": 15.0, "BBB": -3.0, "CCC": 5.0, "DDD": 0.0})
    # alias passthrough: handle copies unknown cross cols only via COMPUTED_COLUMN_ALIASES,
    # so inject through fundamentals where the getter reads it. Use a column the join keeps.
    # Simpler: place G_NTM_TTM on funds (join copies FUND_COLUMN_ALIASES only) -> instead
    # assert the preset predicate directly for the formula port.
    g = {"G_NTM_TTM": 15.0}.get
    assert svc.EPS_GROWTH_PRESETS["ntm_pos"](g) is True
    g = {"G_NTM_TTM": -3.0}.get
    assert svc.EPS_GROWTH_PRESETS["ntm_pos"](g) is False
    g = {"G_NTM_TTM": None}.get
    assert svc.EPS_GROWTH_PRESETS["ntm_pos"](g) is False


def test_eps_accel_preset_formula():
    """accel = G_NTM_TTM > G_TTM_YOY (port app.py:894)."""
    g = {"G_NTM_TTM": 20.0, "G_TTM_YOY": 10.0}.get
    assert svc.EPS_ACCEL_PRESETS["accel"](g) is True
    assert svc.EPS_ACCEL_PRESETS["decel"](g) is False
    # accel_pos requires both > 0.
    g = {"G_NTM_TTM": 20.0, "G_TTM_YOY": -5.0}.get
    assert svc.EPS_ACCEL_PRESETS["accel_pos"](g) is False


# ----- sort parity --------------------------------------------------------- #
def test_handle_sort_by_rs_desc():
    cross, funds = _universe()
    args = FakeArgs(single={"sort_by": "rs"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    order = [r[0] for r in vm["tables"][0]["rows"]]
    # RS_Rank desc: AAA(90) > CCC(75) > BBB(40) > DDD(10).
    assert order == ["AAA", "CCC", "BBB", "DDD"]


def test_handle_sort_by_pe_asc_missing_last():
    cross, funds = _universe()
    args = FakeArgs(single={"sort_by": "pe"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    order = [r[0] for r in vm["tables"][0]["rows"]]
    # PE asc: BBB(12) < CCC(21) < AAA(20)? -> AAA=20, BBB=12, CCC=21, DDD=None(last).
    # asc: BBB(12), AAA(20), CCC(21), then DDD missing last.
    assert order == ["BBB", "AAA", "CCC", "DDD"]


def test_handle_turnover_filter_excludes_low():
    cross, funds = _universe()
    args = FakeArgs(single={"min_turnover": "300000000"})  # 3e8
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    # turnovers: AAA 5e8, CCC 9e8 pass; BBB 2e8, DDD 1e8 drop.
    assert syms == {"AAA", "CCC"}


def test_handle_min_price_filter():
    cross, funds = _universe()
    args = FakeArgs(single={"min_price": "100"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    # prices: AAA120, CCC210 pass; BBB48, DDD28 drop.
    assert syms == {"AAA", "CCC"}


# ----- empty paths --------------------------------------------------------- #
def test_handle_empty_universe():
    empty = pd.DataFrame()
    empty.index.name = "symbol"
    vm = handle(ScreenRequest.from_query(FakeArgs()),
                StubData(_funds({})), StubComputed(empty))
    assert vm["meta"]["status"] == "empty"
    assert vm["meta"]["readouts"]["universe_total"] == 0
    assert vm["tables"] == []


def test_handle_all_filtered_out():
    cross, funds = _universe()
    args = FakeArgs(single={"sector": "Healthcare"})  # no Healthcare in universe
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    assert vm["meta"]["status"] == "empty"
    assert vm["meta"]["readouts"]["universe_total"] == 4
    assert vm["meta"]["readouts"]["passed"] == 0


# --------------------------------------------------------------------------- #
# 7c — blueprint thinness (Flask test client + stubbed providers)
# --------------------------------------------------------------------------- #
def test_blueprint_api_route_is_thin(monkeypatch):
    from flask import Flask
    from sections.screener import routes

    cross, funds = _universe()
    monkeypatch.setitem(routes._PROVIDERS, "data", StubData(funds))
    monkeypatch.setitem(routes._PROVIDERS, "computed", StubComputed(cross, asof="2026-06-10"))

    app = Flask(__name__)
    app.register_blueprint(routes.screener_bp)
    client = app.test_client()

    resp = client.get("/api/screener?sort_by=rs")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["meta"]["status"] == "ok"
    assert payload["tables"][0]["id"] == "screener_results"
    assert payload["meta"]["readouts"]["universe_total"] == 4


# --------------------------------------------------------------------------- #
# F2 review fixes — FwdPE via estimates, growth derivation, dist_high sort,
# vectorized panel technicals, sector stats / stage banner.
# --------------------------------------------------------------------------- #
def test_pipeline_requests_estimates():
    """FwdPE bug fix: _pipeline must fetch fundamentals WITH estimates=True so the
    forward FY1 EPS comes back (else FwdPE is always None)."""
    cross, funds = _universe()
    data = StubData(funds)
    handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    assert data.last_estimates is True


def test_fwdpe_and_fy_columns_live():
    """FwdPE = price/fy1_eps and FY1/FY2 EPS columns surface in the table."""
    cross, funds = _universe()
    # add fy2 + fy revenue to exercise FY2/FY1 growth too.
    funds.loc["AAA", "fy2_eps_mean"] = 10.0
    funds.loc["AAA", "fy1_revenue_mean"] = 1000e6
    funds.loc["AAA", "fy2_revenue_mean"] = 1200e6
    vm = handle(ScreenRequest.from_query(FakeArgs()), StubData(funds), StubComputed(cross))
    aaa = _row_by_symbol(vm["tables"][0], "AAA")
    assert_parity(aaa["FwdPE"], 15.0)        # 120 / 8
    assert_parity(aaa["EPS_FY1"], 8.0)
    assert_parity(aaa["EPS_FY2"], 10.0)
    # G_FY2_FY1 = (10/8 - 1)*100 = 25.0 ; RG_FY2_FY1 = (1200/1000 -1)*100 = 20.0
    assert_parity(aaa["G_FY2_FY1"], 25.0)
    assert_parity(aaa["RG_FY2_FY1"], 20.0)


def test_fwdpe_filter_is_live():
    """fwdpe range filter actually narrows now that FwdPE has values."""
    cross, funds = _universe()
    # FwdPE: AAA=120/8=15, BBB=48/4.5=10.7, CCC=210/14=15, DDD=28/0.5=56.
    args = FakeArgs(single={"fwdpe_max": "12"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"BBB"}


def test_eps_growth_preset_live_from_forward_estimates():
    """eps_growth=fy2_fy1_pos works end-to-end from forward FY1/FY2 EPS."""
    cross, funds = _universe()
    funds["fy2_eps_mean"] = pd.Series({"AAA": 10.0, "BBB": 4.0, "CCC": 20.0, "DDD": 0.6})
    # G_FY2_FY1: AAA (10/8) +, BBB (4/4.5) -, CCC (20/14) +, DDD (0.6/0.5) +.
    args = FakeArgs(single={"eps_growth": "fy2_fy1_pos"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA", "CCC", "DDD"}


def test_growth_metrics_from_quarterly_ttm_yoy():
    """G_TTM_YOY derived from 8 quarters of EPS actuals (port app.py:692-696)."""
    cross, funds = _universe()
    # AAA: 8 quarters, last-4 TTM=10, prior-4 TTM=8 -> +25.0%.
    q = pd.DataFrame({
        "symbol": ["AAA"] * 8,
        "report_date": pd.date_range("2024-03-31", periods=8, freq="QE"),
        "eps_actual": [2.0, 2.0, 2.0, 2.0, 2.5, 2.5, 2.5, 2.5],
        "revenue_actual": [None] * 8,
    })
    data = StubData(funds, quarterly=q)
    vm = handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    aaa = _row_by_symbol(vm["tables"][0], "AAA")
    assert_parity(aaa["EPS_TTM"], 10.0)
    assert_parity(aaa["G_TTM_YOY"], 25.0)
    # ttm_yoy_pos preset keeps AAA.
    vm2 = handle(ScreenRequest.from_query(FakeArgs(single={"eps_growth": "ttm_yoy_pos"})),
                 StubData(funds, quarterly=q), StubComputed(cross))
    assert "AAA" in {r[0] for r in vm2["tables"][0]["rows"]}


def test_dist_high_sort_closest_to_high_first():
    """dist_high sort: From52H DESC (closest-to-52w-high, i.e. nearest-zero, first)."""
    cross, funds = _universe()
    panel = {
        "AAA": {"Price": 120.0, "From52H": -2.0, "ADV_Dollar": 5e8},
        "BBB": {"Price": 48.0, "From52H": -40.0, "ADV_Dollar": 2e8},
        "CCC": {"Price": 210.0, "From52H": -10.0, "ADV_Dollar": 9e8},
        "DDD": {"Price": 28.0, "From52H": -25.0, "ADV_Dollar": 1e8},
    }
    args = FakeArgs(single={"sort_by": "dist_high"})
    vm = handle(ScreenRequest.from_query(args),
                StubData(funds, panel=panel), StubComputed(cross))
    order = [r[0] for r in vm["tables"][0]["rows"]]
    assert order == ["AAA", "CCC", "DDD", "BBB"]


def test_panel_technicals_override_price_and_turnover():
    """Vectorized panel technicals override Price/ADV_Dollar on the joined rows."""
    cross, funds = _universe()
    panel = {"AAA": {"Price": 999.0, "ADV_Dollar": 7e8, "From52H": -1.0, "From52L": 80.0}}
    vm = handle(ScreenRequest.from_query(FakeArgs()),
                StubData(funds, panel=panel), StubComputed(cross))
    aaa = _row_by_symbol(vm["tables"][0], "AAA")
    assert_parity(aaa["Price"], 999.0)
    assert_parity(aaa["ADV_Dollar"], 7e8)
    assert_parity(aaa["From52H"], -1.0)


def test_handle_page_emits_sector_stats_and_stage_banner():
    """handle_page restores sector_stats hierarchy + stage_dist/market_regime."""
    from sections.screener.service import handle_page
    cross, funds = _universe()
    ctx = handle_page(ScreenRequest.from_query(FakeArgs(single={"preset": "stage2"})),
                      StubData(funds), StubComputed(cross))
    # sector stats present with medians + hierarchy.
    assert ctx["sector_stats"]
    sec = ctx["sector_stats"][0]
    assert "median_pe" in sec and "industries" in sec and "stocks" in sec
    # stage distribution + regime banner computed for a stage preset.
    assert ctx["stage_dist"] is not None
    assert ctx["market_regime"] in {
        "Healthy Bull", "Late Bull", "Bear", "Bottoming", "Mixed"}


def test_sector_stats_medians_over_passed_not_full_universe():
    """Sector/industry medians must be computed over the PASSED (filtered) stocks,
    matching the original (app.py @9631169 groups the already-filtered results_df).

    RS_Rank is a global 0-100 percentile, so a full-universe sector median sits ~50
    regardless of the active filter — the original instead reports the median of the
    stocks that survived the filter. Regression guard for that parity.
    """
    from sections.screener.service import _sector_stats

    def _row(sym, rs, pe, ind="SoftwareCo"):
        return {"Symbol": sym, "Sector": "Tech", "Industry": ind,
                "RS_Rank": rs, "PE": pe}

    # passed: two high-RS leaders -> median_rs 85, median_pe 25
    passed = [_row("AAA", 80, 20), _row("BBB", 90, 30)]
    # full universe adds three low-RS names -> full median_rs would be 30
    full = passed + [_row("CCC", 10, 100), _row("DDD", 20, 110),
                     _row("EEE", 30, 120)]

    stats = _sector_stats(passed, full)
    assert len(stats) == 1
    sec = stats[0]
    # median over the PASSED set (85), NOT the full-universe median (30).
    assert sec["median_rs"] == 85
    assert sec["median_pe"] == 25
    # counts still use the full universe: 2 passed of 5 total = 40%.
    assert sec["count"] == 2 and sec["total"] == 5
    assert sec["pct_of_sector"] == 40
    # industry medians likewise over the passed stocks.
    ind = sec["industries"][0]
    assert ind["median_rs"] == 85 and ind["count"] == 2


def test_stage_preset_filters_table_to_that_stage():
    """preset=stageN keeps only Stage_Class==N rows (app.py:487 parity).

    Regression: the preset was previously ignored entirely, so every stage preset
    returned the full passing universe (and the sector medians + flat table were
    identical across stage2/stage4).
    """
    from sections.screener.service import handle_page
    cross, funds = _universe()  # AAA,CCC=stage2  BBB=stage4  DDD=stage1
    def syms(preset):
        ctx = handle_page(ScreenRequest.from_query(FakeArgs(single={
            "preset": preset, "min_turnover": "1000000"})),
            StubData(funds), StubComputed(cross))
        return {r["symbol"] for r in ctx["results"]}
    assert syms("stage2") == {"AAA", "CCC"}
    assert syms("stage4") == {"BBB"}
    assert syms("stage1") == {"DDD"}
    # "all" keeps every base-passing symbol (no stage filter).
    assert syms("all") == {"AAA", "BBB", "CCC", "DDD"}


def test_sector_map_summary_buckets_each_dimension():
    """Map view: sector × dimension composition over the passed rows, with the
    original bucket cutoffs (port of app.py /api/sector_map)."""
    from sections.screener.service import _sector_map_summary
    rows = [
        {"Sector": "Tech", "PCA_Regime": 4, "Stage_Class": 2, "EPS_Accel": 5.0,
         "EPS_FY1": 8, "EPS_Act": 6, "RS_Rank": 90, "RS_Chg1M": 7, "PE_vs_Sector": 0.8},
        {"Sector": "Tech", "PCA_Regime": 3, "Stage_Class": 2, "EPS_Accel": -2.0,
         "EPS_FY1": 5, "EPS_Act": 6, "RS_Rank": 65, "RS_Chg1M": -8, "PE_vs_Sector": 1.4},
        {"Sector": "Energy", "PCA_Regime": 0, "Stage_Class": 4, "EPS_Accel": 1.0,
         "EPS_FY1": 6, "EPS_Act": 6, "RS_Rank": 15, "RS_Chg1M": 0, "PE_vs_Sector": None},
    ]
    m = _sector_map_summary(rows)
    assert set(m) == {"pca_regime", "stage", "eps_momentum", "eps_growth",
                      "rs_bucket", "rs_momentum", "pe_vs_sector"}
    assert m["pca_regime"]["overall"] == {"Strong Leader": 1, "Quiet Uptrend": 1, "Declining": 1}
    assert m["rs_bucket"]["overall"] == {"RS 80+": 1, "RS 60-80": 1, "RS 0-20": 1}
    assert m["rs_momentum"]["overall"] == {"Improving": 1, "Deteriorating": 1, "Stable": 1}
    assert m["eps_momentum"]["overall"] == {"Accelerating": 2, "Decelerating": 1}
    assert m["eps_growth"]["overall"] == {"Growing": 1, "Declining": 1, "Flat": 1}
    assert m["pe_vs_sector"]["overall"] == {"Discount": 1, "High Premium": 1, "No PE": 1}
    assert m["stage"]["overall"] == {"Stage 2 Uptrend": 2, "Stage 4 Declining": 1}
    assert m["pca_regime"]["total_stocks"] == 3
    # summary carries per-(sector,category) counts
    assert {"sector": "Energy", "dimension": "Declining", "count": 1} in m["pca_regime"]["summary"]
