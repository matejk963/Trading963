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

    def __init__(self, frame, quarterly=None, panel=None, returns=None):
        self._frame = frame
        self._quarterly = quarterly
        self._panel = panel
        self._returns = returns
        self.last_ids = None
        self.last_estimates = None
        self.panel_returns_calls = 0

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

    def panel_returns(self, ids, **kwargs):
        self.panel_returns_calls += 1
        return dict(self._returns or {})


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


def test_from_query_parses_fwd_pe_premium_ranges():
    """``fwdpe_sect_min/max`` + ``fwdpe_ind_min/max`` parse into ``fund_ranges``
    under the new stems (auto-handled via FUND_RANGE_COLUMNS)."""
    args = FakeArgs(single={
        "fwdpe_sect_min": "0.5", "fwdpe_sect_max": "1.5",
        "fwdpe_ind_max": "2.0",
    })
    req = ScreenRequest.from_query(args)
    assert req.fund_ranges["fwdpe_sect"] == (0.5, 1.5)
    assert req.fund_ranges["fwdpe_ind"] == (None, 2.0)
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


# ----- Fwd PE vs Sector/Industry (mirrors trailing PE premium) ------------- #
def test_median_pe_returns_forward_medians():
    """``_median_pe`` returns per-sector/industry median FwdPE alongside the
    (unchanged) trailing PE medians."""
    rows = [
        {"PE": 20.0, "FwdPE": 15.0, "Sector": "Tech", "Industry": "Software"},
        {"PE": 12.0, "FwdPE": 11.0, "Sector": "Tech", "Industry": "Hardware"},
        {"PE": 30.0, "FwdPE": 25.0, "Sector": "Energy", "Industry": "Oil"},
        {"PE": None, "FwdPE": 5.0,  "Sector": "Energy", "Industry": "Oil"},
    ]
    sector_med, industry_med, sector_fwd, industry_fwd = svc._median_pe(rows)

    # trailing medians unchanged: Tech -> median(20,12)=16 ; Energy -> 30 (None dropped).
    assert_parity(sector_med["Tech"], 16.0)
    assert_parity(sector_med["Energy"], 30.0)
    assert_parity(industry_med["Software"], 20.0)

    # forward medians: Tech -> median(15,11)=13 ; Energy -> median(25,5)=15.
    assert_parity(sector_fwd["Tech"], 13.0)
    assert_parity(sector_fwd["Energy"], 15.0)
    assert_parity(industry_fwd["Software"], 15.0)
    assert_parity(industry_fwd["Oil"], 15.0)


def test_handle_derives_fwd_pe_median_premium():
    """``FwdPE_vs_Sector``/``FwdPE_vs_Industry`` = FwdPE / median FwdPE for the
    group (mirrors the trailing PE premium, reusing ``_pe_premium``)."""
    cross, funds = _universe()
    vm = handle(ScreenRequest.from_query(FakeArgs()),
                StubData(funds), StubComputed(cross))
    tbl = vm["tables"][0]

    aaa = _row_by_symbol(tbl, "AAA")
    # FwdPE = 120/8 = 15. Sector Tech FwdPE median(15, 48/4.5=10.667)=12.833.
    # 15 / 12.833 = 1.17 (rounded 2dp).
    assert_parity(aaa["FwdPE_vs_Sector"], 1.17)
    # Industry Software has only AAA -> 15/15 = 1.0.
    assert_parity(aaa["FwdPE_vs_Industry"], 1.0)


def test_handle_fwd_pe_premium_none_when_missing():
    """No FwdPE -> no premium (mirrors the trailing-PE None branch)."""
    cross, funds = _universe()
    # strip BBB's forward eps so its FwdPE is missing.
    funds.loc["BBB", "fy1_eps_mean"] = None
    vm = handle(ScreenRequest.from_query(FakeArgs()),
                StubData(funds), StubComputed(cross))
    bbb = _row_by_symbol(vm["tables"][0], "BBB")
    assert bbb["FwdPE"] is None
    assert bbb["FwdPE_vs_Sector"] is None
    assert bbb["FwdPE_vs_Industry"] is None


def test_handle_filters_fwd_pe_vs_sector_range():
    """A ``fwdpe_sect`` range drops rows outside it, keeps those inside.

    FwdPE_vs_Sector: AAA 1.17, BBB 0.83, CCC 0.42, DDD 1.58.
    range [0.5, 1.2] -> keeps AAA, BBB.
    """
    cross, funds = _universe()
    args = FakeArgs(single={"fwdpe_sect_min": "0.5", "fwdpe_sect_max": "1.2"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA", "BBB"}


def test_handle_filters_fwd_pe_vs_industry_range():
    """A ``fwdpe_ind`` range drops rows outside it.

    FwdPE_vs_Industry: AAA 1.0, BBB 1.0, CCC 0.42, DDD 1.58 (Oil median 35.5).
    max 1.0 -> keeps AAA, BBB, CCC (DDD 1.58 drops).
    """
    cross, funds = _universe()
    args = FakeArgs(single={"fwdpe_ind_max": "1.0"})
    vm = handle(ScreenRequest.from_query(args), StubData(funds), StubComputed(cross))
    syms = {r[0] for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA", "BBB", "CCC"}


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


# --------------------------------------------------------------------------- #
# Slice 1 — trailing performance returns (panel_returns -> rows + filters + cols)
# --------------------------------------------------------------------------- #
def test_pipeline_rows_carry_returns_from_panel_returns():
    """_pipeline splices data.panel_returns onto each row (RetNW shape), once."""
    cross, funds = _universe()
    returns = {"AAA": {"Ret1W": 2.0, "Ret3M": 15.0, "Ret12M": 40.0},
               "BBB": {"Ret3M": -8.0}}
    data = StubData(funds, returns=returns)
    vm = handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    aaa = _row_by_symbol(vm["tables"][0], "AAA")
    assert_parity(aaa["Ret3M"], 15.0)
    assert_parity(aaa["Ret12M"], 40.0)
    bbb = _row_by_symbol(vm["tables"][0], "BBB")
    assert_parity(bbb["Ret3M"], -8.0)
    # one panel_returns call per pipeline (no N+1).
    assert data.panel_returns_calls == 1


def test_pipeline_without_panel_returns_provider_is_graceful():
    """A provider lacking panel_returns (bare stub) does not blank the page."""
    cross, funds = _universe()

    class _NoReturns(StubData):
        panel_returns = None  # attribute absent -> hasattr() is False

    data = _NoReturns(funds)
    vm = handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    assert vm["tables"][0]["rows"]  # still renders


def test_return_range_filter_drops_rows_outside_band():
    """ret3m_min/ret3m_max filter the passed set; rows outside the band drop."""
    cross, funds = _universe()
    returns = {"AAA": {"Ret3M": 25.0}, "BBB": {"Ret3M": 5.0},
               "CCC": {"Ret3M": 50.0}, "DDD": {"Ret3M": -10.0}}
    data = StubData(funds, returns=returns)
    args = FakeArgs(single={"ret3m_min": "20", "ret3m_max": "40"})
    vm = handle(ScreenRequest.from_query(args), data, StubComputed(cross))
    syms = {r[vm["tables"][0]["columns"].index("Symbol")]
            for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA"}  # only Ret3M in [20,40]


def test_return_filter_absent_is_noop():
    """No ret*_min/_max -> returns don't filter (all rows kept)."""
    cross, funds = _universe()
    returns = {"AAA": {"Ret3M": 1.0}}
    data = StubData(funds, returns=returns)
    vm = handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    assert len(vm["tables"][0]["rows"]) == 4  # full universe passes base gates


def test_return_column_id_resolves_and_renders():
    """Column id ret3m resolves through COL_ID_TO_RESULT/FLAT_COL_SPEC and renders."""
    assert svc.COL_ID_TO_RESULT["ret3m"] == "Ret3M"
    assert "ret3m" in svc.FLAT_COL_SPEC
    cross, funds = _universe()
    returns = {"AAA": {"Ret3M": 12.3}}
    from sections.screener.service import handle_page
    ctx = handle_page(ScreenRequest.from_query(FakeArgs(single={"cols": "symbol,ret3m"})),
                      StubData(funds, returns=returns), StubComputed(cross))
    flat = ctx["flat_table"]
    assert "ret3m" in flat["columns"]
    aaa = next(r for r in flat["rows"] if r["symbol"] == "AAA")
    cell = aaa["cells"][flat["columns"].index("ret3m")]
    assert cell["text"] == "+12.3"


def test_return_from_query_parses_min_max():
    """ScreenRequest.from_query parses ret*_min/ret*_max into the return-range map."""
    args = FakeArgs(single={"ret3m_min": "10", "ret12m_max": "80"})
    req = ScreenRequest.from_query(args)
    assert req.return_ranges["ret3m"] == (10.0, None)
    assert req.return_ranges["ret12m"] == (None, 80.0)


# --------------------------------------------------------------------------- #
# Slice 2 — universe percentile for every numeric metric
# --------------------------------------------------------------------------- #
def test_attach_percentiles_basic_ranks():
    """_attach_percentiles writes {ResultName}_Pctile over the rows: min≈low, max≈100,
    null metric -> null percentile; ties stable."""
    rows = [{"PE": 10.0}, {"PE": 20.0}, {"PE": 30.0}, {"PE": 40.0}, {"PE": None}]
    svc._attach_percentiles(rows)
    # pandas rank(pct=True)*100: 4 non-null values -> 25/50/75/100.
    assert rows[0]["PE_Pctile"] == 25.0
    assert rows[1]["PE_Pctile"] == 50.0
    assert rows[3]["PE_Pctile"] == 100.0  # max value -> 100
    assert rows[4]["PE_Pctile"] is None    # null value -> null percentile


def test_attach_percentiles_ties_average():
    """Tied metric values share the same (averaged) percentile (stable rule)."""
    rows = [{"RS_Rank": 50.0}, {"RS_Rank": 50.0}, {"RS_Rank": 100.0}]
    svc._attach_percentiles(rows)
    assert rows[0]["RS_Rank_Pctile"] == rows[1]["RS_Rank_Pctile"]
    assert rows[2]["RS_Rank_Pctile"] == 100.0


def test_percentile_basis_is_full_universe_not_passed():
    """A kept row's percentile is computed over the FULL universe — tightening the
    filter (fewer passed) does not shift a kept row's percentile."""
    cross, funds = _universe()
    returns = {"AAA": {"Ret3M": 10.0}, "BBB": {"Ret3M": 20.0},
               "CCC": {"Ret3M": 30.0}, "DDD": {"Ret3M": 40.0}}
    data = StubData(funds, returns=returns)

    vm_all = handle(ScreenRequest.from_query(FakeArgs()), data, StubComputed(cross))
    aaa_all = _row_by_symbol(vm_all["tables"][0], "AAA")
    pctile_all = aaa_all["Ret3M_Pctile"]

    # tighten with a band that keeps AAA but drops some others.
    data2 = StubData(funds, returns=returns)
    vm_filt = handle(ScreenRequest.from_query(FakeArgs(single={"ret3m_max": "25"})),
                     data2, StubComputed(cross))
    aaa_filt = _row_by_symbol(vm_filt["tables"][0], "AAA")
    # AAA's Ret3M percentile is the same in both (full-universe basis of 4 rows).
    assert_parity(aaa_filt["Ret3M_Pctile"], pctile_all)
    assert pctile_all == 25.0  # 10 is the lowest of [10,20,30,40] -> 25th


def test_percentile_filter_keeps_high_percentile_rows():
    """pe_pmin=90 keeps only rows whose PE percentile >= 90."""
    cross, funds = _universe()
    data = StubData(funds)
    args = FakeArgs(single={"pe_pmin": "90"})
    vm = handle(ScreenRequest.from_query(args), data, StubComputed(cross))
    # Of the 4 PEs only the top (100th pct) survives a >=90 gate.
    table = vm["tables"][0]
    pe_idx = table["columns"].index("PE_Pctile")
    kept = [r for r in table["rows"]]
    assert kept and all(r[pe_idx] is not None and r[pe_idx] >= 90 for r in kept)


def test_percentile_filter_band_on_returns():
    """ret3m_pmin/_pmax band filters on the Ret3M percentile."""
    cross, funds = _universe()
    returns = {"AAA": {"Ret3M": 10.0}, "BBB": {"Ret3M": 20.0},
               "CCC": {"Ret3M": 30.0}, "DDD": {"Ret3M": 40.0}}
    data = StubData(funds, returns=returns)
    # percentiles are 25/50/75/100; band [40,60] keeps only the 50th (BBB).
    args = FakeArgs(single={"ret3m_pmin": "40", "ret3m_pmax": "60"})
    vm = handle(ScreenRequest.from_query(args), data, StubComputed(cross))
    syms = {r[vm["tables"][0]["columns"].index("Symbol")]
            for r in vm["tables"][0]["rows"]}
    assert syms == {"BBB"}


def test_percentile_filter_excludes_null_percentile_when_bound_set():
    """A row with a null metric (null percentile) fails when a percentile bound set."""
    cross, funds = _universe()
    # only AAA has a Ret3M -> others have null Ret3M_Pctile.
    returns = {"AAA": {"Ret3M": 10.0}}
    data = StubData(funds, returns=returns)
    args = FakeArgs(single={"ret3m_pmin": "0"})  # 0 still requires non-null
    vm = handle(ScreenRequest.from_query(args), data, StubComputed(cross))
    syms = {r[vm["tables"][0]["columns"].index("Symbol")]
            for r in vm["tables"][0]["rows"]}
    assert syms == {"AAA"}


def test_percentile_columns_resolvable_and_no_recursion():
    """Every base numeric id has a {id}p column via COL_ID_TO_RESULT/FLAT_COL_SPEC;
    percentile cols themselves are NOT in PCTILE_BASE_IDS (no pepp)."""
    base_ids = svc.PCTILE_BASE_IDS
    assert "pe" in base_ids and "ret3m" in base_ids
    for bid in base_ids:
        pid = bid + "p"
        assert pid in svc.FLAT_COL_SPEC, f"missing flat spec for {pid}"
        assert pid in svc.COL_ID_TO_RESULT, f"missing col-id for {pid}"
        assert svc.COL_ID_TO_RESULT[pid].endswith("_Pctile")
    # no percentile-of-percentile: pep not a base id (so no pepp generated).
    assert "pep" not in base_ids
    assert "pepp" not in svc.FLAT_COL_SPEC
    assert svc.COL_ID_TO_RESULT["pep"] == "PE_Pctile"
    assert svc.FLAT_COL_SPEC["pep"]["label"] == "PE %ile"


def test_percentile_column_renders_p_format():
    """A percentile column renders the P%.0f format (e.g. P100), null -> dash."""
    cross, funds = _universe()
    from sections.screener.service import handle_page
    ctx = handle_page(ScreenRequest.from_query(FakeArgs(single={"cols": "symbol,pep"})),
                      StubData(funds), StubComputed(cross))
    flat = ctx["flat_table"]
    assert "pep" in flat["columns"]
    pe_idx = flat["columns"].index("pep")
    texts = {r["symbol"]: r["cells"][pe_idx]["text"] for r in flat["rows"]}
    # CCC has the highest PE (210/10=21) -> P100.
    assert texts.get("CCC") == "P100"


def test_percentile_filter_from_query_parses():
    """from_query parses {baseid}_pmin/_pmax generically for every base numeric id."""
    args = FakeArgs(single={"pe_pmin": "90", "ret3m_pmax": "50"})
    req = ScreenRequest.from_query(args)
    assert req.pctile_ranges["pe"] == (90.0, None)
    assert req.pctile_ranges["ret3m"] == (None, 50.0)


def test_cached_pipeline_percentiles_deterministic():
    """Two identical calls return value-equal percentiles (deterministic + cached)."""
    cross, funds = _universe()
    data = StubData(funds)
    computed = StubComputed(cross)
    svc._clear_pipeline_cache()
    vm1 = handle(ScreenRequest.from_query(FakeArgs()), data, computed)
    vm2 = handle(ScreenRequest.from_query(FakeArgs()), data, computed)
    a1 = _row_by_symbol(vm1["tables"][0], "AAA")
    a2 = _row_by_symbol(vm2["tables"][0], "AAA")
    assert a1["PE_Pctile"] == a2["PE_Pctile"]


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


def test_sector_stats_medians_over_full_universe_not_passed():
    """Sector/industry medians are computed over the FULL universe per sector/
    industry, NOT the passed/filtered subset — a stable baseline the user compares
    their filtered selection against (regardless of the active filter).

    Counts and the listed stocks remain the filtered selection; only the median
    input set changed (passed -> full).
    """
    from sections.screener.service import _sector_stats

    def _row(sym, rs, pe, ind="SoftwareCo"):
        return {"Symbol": sym, "Sector": "Tech", "Industry": ind,
                "RS_Rank": rs, "PE": pe}

    # passed: two high-RS leaders.
    passed = [_row("AAA", 80, 20), _row("BBB", 90, 30)]
    # full universe adds three low-RS names -> full median_rs 30, median_pe 100.
    full = passed + [_row("CCC", 10, 100), _row("DDD", 20, 110),
                     _row("EEE", 30, 120)]

    stats = _sector_stats(passed, full)
    assert len(stats) == 1
    sec = stats[0]
    # median over the FULL universe (RS 30, PE 100), NOT the passed set.
    assert sec["median_rs"] == 30
    assert sec["median_pe"] == 100
    # counts still use the full universe: 2 passed of 5 total = 40%.
    assert sec["count"] == 2 and sec["total"] == 5
    assert sec["pct_of_sector"] == 40
    # listed stocks remain the passed selection.
    assert {s["symbol"] for s in sec["stocks"]} == {"AAA", "BBB"}
    # industry medians likewise over the full industry, count still passed.
    ind = sec["industries"][0]
    assert ind["median_rs"] == 30 and ind["count"] == 2


def test_sector_median_pe_is_full_universe_median_when_subset_passed():
    """Sector median_pe == median over ALL stocks in the sector even when only a
    subset passed. Full PE [10,20,30,40,50] but only [10,20] passed -> 30, not 15.
    """
    from sections.screener.service import _sector_stats

    def _row(sym, pe):
        return {"Symbol": sym, "Sector": "Tech", "Industry": "SoftwareCo",
                "RS_Rank": 50, "PE": pe}

    full = [_row("A", 10), _row("B", 20), _row("C", 30), _row("D", 40), _row("E", 50)]
    passed = [full[0], full[1]]  # PE [10, 20]

    sec = _sector_stats(passed, full)[0]
    assert sec["median_pe"] == 30          # full median, not 15 (passed median)
    assert sec["count"] == 2 and sec["total"] == 5


def test_industry_median_pe_is_full_universe_median_when_subset_passed():
    """Industry median_pe == median over the full industry, not the passed subset."""
    from sections.screener.service import _sector_stats

    def _row(sym, pe):
        return {"Symbol": sym, "Sector": "Tech", "Industry": "SoftwareCo",
                "RS_Rank": 50, "PE": pe}

    full = [_row("A", 10), _row("B", 20), _row("C", 30), _row("D", 40), _row("E", 50)]
    passed = [full[0], full[1]]  # PE [10, 20]

    sec = _sector_stats(passed, full)[0]
    ind = sec["industries"][0]
    assert ind["industry"] == "SoftwareCo"
    assert ind["median_pe"] == 30          # full industry median, not 15
    assert ind["count"] == 2               # passed count unchanged
    assert {s["symbol"] for s in ind["stocks"]} == {"A", "B"}  # passed stocks only


def test_sector_medians_stable_when_filter_tightens():
    """Tightening the filter (fewer passed) changes count/stocks but leaves the
    sector AND industry medians identical — the stable full-universe baseline.
    """
    from sections.screener.service import _sector_stats

    def _row(sym, pe):
        return {"Symbol": sym, "Sector": "Tech", "Industry": "SoftwareCo",
                "RS_Rank": 50, "PE": pe}

    full = [_row("A", 10), _row("B", 20), _row("C", 30), _row("D", 40), _row("E", 50)]

    wide = _sector_stats(full[:4], full)[0]      # 4 passed
    tight = _sector_stats(full[:2], full)[0]     # 2 passed

    # count / stocks reflect the filter.
    assert wide["count"] == 4 and tight["count"] == 2
    assert {s["symbol"] for s in tight["stocks"]} == {"A", "B"}
    # medians are identical — the full-universe baseline does not move.
    assert wide["median_pe"] == tight["median_pe"] == 30
    assert (wide["industries"][0]["median_pe"]
            == tight["industries"][0]["median_pe"] == 30)


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


# --------------------------------------------------------------------------- #
# Slice 1 — pipeline result cache + freshness version + version endpoint
# --------------------------------------------------------------------------- #
class VersionedComputed(StubComputed):
    """StubComputed that also exposes a bumpable ``cross_section_version`` and
    counts ``cross_section`` calls (the heavy producer's first read)."""

    def __init__(self, frame, asof=None, version=1):
        super().__init__(frame, asof=asof)
        self._version = version
        self.cross_section_calls = 0

    def cross_section(self, filters=None):
        self.cross_section_calls += 1
        return self._frame

    def cross_section_version(self):
        return self._version

    def bump(self):
        self._version += 1


class VersionedData(StubData):
    """StubData that exposes a bumpable ``price_panel_version`` and counts
    ``fundamentals`` calls (the heavy work spy)."""

    def __init__(self, frame, quarterly=None, panel=None, version=1.0):
        super().__init__(frame, quarterly=quarterly, panel=panel)
        self._version = version
        self.fundamentals_calls = 0

    def fundamentals(self, ids, fields=None, estimates=False):
        self.fundamentals_calls += 1
        return super().fundamentals(ids, fields=fields, estimates=estimates)

    def price_panel_version(self):
        return self._version

    def bump(self):
        self._version += 1.0


@pytest.fixture(autouse=True)
def _clear_pipeline_cache():
    """Each cache test starts from an empty pipeline cache (no cross-test leak)."""
    svc._clear_pipeline_cache()
    yield
    svc._clear_pipeline_cache()


def test_identical_requests_skip_heavy_recompute():
    """Two identical requests run the heavy pipeline once; the 2nd is a cache hit."""
    cross, funds = _universe()
    data = VersionedData(funds)
    computed = VersionedComputed(cross)
    req = ScreenRequest.from_query(FakeArgs())

    r1 = svc._cached_pipeline(req, data, computed)
    r2 = svc._cached_pipeline(req, data, computed)

    assert data.fundamentals_calls == 1          # heavy work ran exactly once
    assert computed.cross_section_calls == 1
    # the cache hit returns the same passed set (value-equal).
    assert [r["Symbol"] for r in r1.passed] == [r["Symbol"] for r in r2.passed]


def test_cross_section_version_bump_invalidates():
    """A cross-section version bump (simulated upsert) forces a recompute."""
    cross, funds = _universe()
    data = VersionedData(funds)
    computed = VersionedComputed(cross)
    req = ScreenRequest.from_query(FakeArgs())

    svc._cached_pipeline(req, data, computed)
    computed.bump()
    svc._cached_pipeline(req, data, computed)

    assert data.fundamentals_calls == 2          # data changed -> recompute


def test_price_panel_version_bump_invalidates():
    """A price-parquet mtime bump forces a recompute."""
    cross, funds = _universe()
    data = VersionedData(funds)
    computed = VersionedComputed(cross)
    req = ScreenRequest.from_query(FakeArgs())

    svc._cached_pipeline(req, data, computed)
    data.bump()
    svc._cached_pipeline(req, data, computed)

    assert data.fundamentals_calls == 2


def test_different_requests_are_distinct_cache_entries():
    """Different ScreenRequests do not cross-serve (distinct cache entries)."""
    cross, funds = _universe()
    data = VersionedData(funds)
    computed = VersionedComputed(cross)

    r_turn = ScreenRequest.from_query(FakeArgs(single={"sort_by": "turnover"}))
    r_rs = ScreenRequest.from_query(FakeArgs(single={"sort_by": "rs"}))
    r_preset = ScreenRequest.from_query(FakeArgs(single={"preset": "stage2"}))
    r_min = ScreenRequest.from_query(FakeArgs(single={"min_turnover": "1000000"}))

    svc._cached_pipeline(r_turn, data, computed)
    svc._cached_pipeline(r_rs, data, computed)
    svc._cached_pipeline(r_preset, data, computed)
    svc._cached_pipeline(r_min, data, computed)
    # four distinct requests -> four heavy computes (no cross-serve).
    assert data.fundamentals_calls == 4
    # re-running the first is now a hit (no new compute).
    svc._cached_pipeline(r_turn, data, computed)
    assert data.fundamentals_calls == 4


def test_cache_hit_value_equals_fresh_compute():
    """A cache hit must value-equal a fresh compute (no staleness, no mutation)."""
    cross, funds = _universe()
    data = VersionedData(funds)
    computed = VersionedComputed(cross)
    req = ScreenRequest.from_query(FakeArgs())

    cached = svc._cached_pipeline(req, data, computed)
    fresh = svc._pipeline(req, data, computed)   # bypass the cache

    assert [r["Symbol"] for r in cached.passed] == [r["Symbol"] for r in fresh.passed]
    assert cached.universe_total == fresh.universe_total
    assert cached.asof == fresh.asof
    # mutating the returned result must not corrupt the cached copy.
    cached.passed.append({"Symbol": "ZZZ"})
    again = svc._cached_pipeline(req, data, computed)
    assert all(r["Symbol"] != "ZZZ" for r in again.passed)


def test_version_endpoint_returns_combined_token(monkeypatch):
    """GET /api/screener/version returns '<xs>:<panel>:<asset>'.

    The xs/panel components change with the data; the 3rd (asset) component is the
    newest mtime of the screener template + client JS, so a CODE/TEMPLATE deploy
    bumps the token and invalidates a stale client keep-alive snapshot (the bug
    where new filters didn't appear until a hard reload). Asset is stable here (the
    files don't change during the test)."""
    from flask import Flask
    from sections.screener import routes

    cross, funds = _universe()
    data = VersionedData(funds, version=12.0)
    computed = VersionedComputed(cross, version=7)
    monkeypatch.setitem(routes._PROVIDERS, "data", data)
    monkeypatch.setitem(routes._PROVIDERS, "computed", computed)

    app = Flask(__name__)
    app.register_blueprint(routes.screener_bp)
    client = app.test_client()

    resp = client.get("/api/screener/version")
    assert resp.status_code == 200
    parts = resp.get_json()["version"].split(":")
    assert parts[0] == "7" and parts[1] == "12.0"
    assert len(parts) == 3 and parts[2]  # asset-version component present
    asset = parts[2]

    computed.bump()  # data change bumps xs; asset unchanged
    assert client.get("/api/screener/version").get_json()["version"] == f"8:12.0:{asset}"
    data.bump()
    assert client.get("/api/screener/version").get_json()["version"] == f"8:13.0:{asset}"


# --------------------------------------------------------------------------- #
# Slice 2 — render only selected columns + embed full result JSON
# --------------------------------------------------------------------------- #
def test_from_query_cols_selects_validated_ordered():
    """`cols=symbol,price,rs` parses to that exact ordered, validated list."""
    req = ScreenRequest.from_query(FakeArgs(single={"cols": "symbol,price,rs"}))
    assert req.cols == ["symbol", "price", "rs"]


def test_from_query_cols_absent_is_default_visible_set():
    """Absent `cols` resolves to the exact default visible set screener.html shows."""
    from sections.screener.service import DEFAULT_VISIBLE_COLS
    req = ScreenRequest.from_query(FakeArgs())
    assert req.cols == DEFAULT_VISIBLE_COLS


def test_from_query_cols_drops_unknown_preserves_order():
    """Unknown ids are dropped, requested order preserved; all-unknown -> default."""
    from sections.screener.service import DEFAULT_VISIBLE_COLS
    req = ScreenRequest.from_query(
        FakeArgs(single={"cols": "rs,bogus,price,symbol"}))
    assert req.cols == ["rs", "price", "symbol"]
    # all-unknown (and empty) fall back to the default — never an empty table.
    assert ScreenRequest.from_query(
        FakeArgs(single={"cols": "nope,zzz"})).cols == DEFAULT_VISIBLE_COLS
    assert ScreenRequest.from_query(
        FakeArgs(single={"cols": ""})).cols == DEFAULT_VISIBLE_COLS


def test_handle_page_visible_cols_in_context_and_restrict_table():
    """handle_page puts the validated, ordered `visible_cols` in the context and the
    server-rendered flat table is restricted to exactly those columns."""
    from sections.screener.service import handle_page
    cross, funds = _universe()
    ctx = handle_page(
        ScreenRequest.from_query(FakeArgs(single={"cols": "symbol,price,rs"})),
        StubData(funds), StubComputed(cross))
    assert ctx["visible_cols"] == ["symbol", "price", "rs"]
    # the flat-table rendering payload is keyed by the visible_cols only.
    table = ctx["flat_table"]
    assert table["columns"] == ["symbol", "price", "rs"]
    assert all(len(row["cells"]) == 3 for row in table["rows"])


def test_handle_page_screener_data_full_regardless_of_visible_cols():
    """screener_data carries ALL RESULT_COLUMNS + every passed row, at full
    precision, independent of the (narrow) visible_cols."""
    from sections.screener.service import handle_page, RESULT_COLUMNS
    cross, funds = _universe()
    req = ScreenRequest.from_query(FakeArgs(single={"cols": "symbol"}))
    ctx = handle_page(req, StubData(funds), StubComputed(cross))
    sd = ctx["screener_data"]
    # all columns present (not just the 1 visible).
    assert sd["columns"] == list(RESULT_COLUMNS)
    assert len(sd["columns"]) == len(RESULT_COLUMNS)
    # one row per passed symbol.
    assert len(sd["rows"]) == ctx["passed"]
    # full precision retained: AAA price 120.0, PE = 120/6 = 20.0 (not rounded away).
    sym_i = sd["columns"].index("Symbol")
    pe_i = sd["columns"].index("PE")
    aaa = next(r for r in sd["rows"] if r[sym_i] == "AAA")
    assert aaa[pe_i] == 20.0


def test_fwd_pe_premium_registered_as_columns_and_in_screener_data():
    """The new Fwd-PE-premium fields are registered as result columns + pickable
    column-vocab ids, and carried (full precision) in the per-row screener_data."""
    from sections.screener.service import (
        handle_page, RESULT_COLUMNS, COL_ID_TO_RESULT, RESULT_TO_COL_ID,
        FLAT_COL_SPEC,
    )
    # RESULT_COLUMNS + column vocab.
    assert "FwdPE_vs_Sector" in RESULT_COLUMNS
    assert "FwdPE_vs_Industry" in RESULT_COLUMNS
    assert COL_ID_TO_RESULT["fwdpesect"] == "FwdPE_vs_Sector"
    assert COL_ID_TO_RESULT["fwdpeind"] == "FwdPE_vs_Industry"
    assert RESULT_TO_COL_ID["FwdPE_vs_Sector"] == "fwdpesect"
    assert RESULT_TO_COL_ID["FwdPE_vs_Industry"] == "fwdpeind"
    # FLAT_COL_SPEC entries (pickable columns, 2dp like PE/Sec).
    assert FLAT_COL_SPEC["fwdpesect"]["key"] == "fwdpe_vs_sector"
    assert FLAT_COL_SPEC["fwdpeind"]["key"] == "fwdpe_vs_industry"

    # per-row screener_data carries the field, full precision (AAA FwdPE/Sec=1.17).
    cross, funds = _universe()
    ctx = handle_page(ScreenRequest.from_query(FakeArgs(single={"cols": "symbol"})),
                      StubData(funds), StubComputed(cross))
    sd = ctx["screener_data"]
    sym_i = sd["columns"].index("Symbol")
    fs_i = sd["columns"].index("FwdPE_vs_Sector")
    aaa = next(r for r in sd["rows"] if r[sym_i] == "AAA")
    assert_parity(aaa[fs_i], 1.17)


def test_flat_col_spec_js_mirrors_server_format_tokens():
    """The client render spec must mirror the server FLAT_COL_SPEC: every visible
    column has a result_col into SCREENER_DATA and a format token matching python's
    formatter, so a client re-render is byte-identical to the server's first paint."""
    from sections.screener.service import flat_col_spec_js, DEFAULT_VISIBLE_COLS
    spec = flat_col_spec_js()
    cols = spec["cols"]
    # representative token parity (the formats that drive "numbers identical").
    assert cols["price"]["fmt"] == "f2"
    assert cols["pe"]["fmt"] == "f1"
    assert cols["rs"]["fmt"] == "f0"
    assert cols["chg"]["fmt"] == "pct1"
    assert cols["pct50"]["fmt"] == "s1"
    assert cols["turnover"]["fmt"] == "turnover"
    assert cols["symbol"]["fmt"] == "text"
    assert cols["stage"]["fmt"] == "stage_label"
    # every default-visible column maps to a RESULT_COLUMNS source for the client.
    for cid in DEFAULT_VISIBLE_COLS:
        assert cols[cid]["result_col"] is not None
    # decoded-label maps embedded for the label columns.
    assert spec["stage_labels"]["2"] == "Stage 2 Uptrend"
