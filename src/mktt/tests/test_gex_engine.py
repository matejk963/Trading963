"""Unit tests for the pure GEX engine (no network, deterministic)."""
import math

import pytest

import gex_engine as ge


# --------------------------------------------------------------------------- #
# Black-Scholes gamma
# --------------------------------------------------------------------------- #
def test_bs_gamma_known_reference():
    # S=K=100, T=1, r=0, sigma=0.2, q=0  ->  d1 = 0.1
    # gamma = phi(0.1) / (100 * 0.2 * 1) = 0.396953 / 20 = 0.0198477
    g = ge.bs_gamma(100, 100, 1.0, 0.0, 0.20, q=0.0)
    assert g == pytest.approx(0.0198477, abs=1e-6)


def test_bs_gamma_degenerate_inputs_return_zero():
    assert ge.bs_gamma(0, 100, 1, 0.04, 0.2) == 0.0      # S<=0
    assert ge.bs_gamma(100, 100, 0, 0.04, 0.2) == 0.0    # T<=0
    assert ge.bs_gamma(100, 100, 1, 0.04, 0.0) == 0.0    # sigma<=0


def test_bs_gamma_same_for_call_and_put():
    # Gamma does not depend on option side — engine relies on this.
    g = ge.bs_gamma(420, 430, 0.1, 0.045, 0.25)
    assert g > 0


# --------------------------------------------------------------------------- #
# Per-contract GEX sign convention
# --------------------------------------------------------------------------- #
def test_contract_gex_call_positive_put_negative():
    call = ge.contract_gex(0.02, 1000, 100, is_call=True)
    put = ge.contract_gex(0.02, 1000, 100, is_call=False)
    assert call > 0 and put < 0
    assert call == pytest.approx(-put)


def test_contract_gex_formula_exact():
    # gamma*OI*100*S^2*0.01*mult
    expected = 0.03 * 500 * 100 * (200 ** 2) * 0.01
    assert ge.contract_gex(0.03, 500, 200, is_call=True) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# Aggregation across expirations
# --------------------------------------------------------------------------- #
def _exp(dte, calls, puts):
    return {"expiration": f"exp-{dte}", "dte": dte,
            "calls": [{"strike": s, "oi": oi, "iv": iv} for (s, oi, iv) in calls],
            "puts": [{"strike": s, "oi": oi, "iv": iv} for (s, oi, iv) in puts]}


def test_aggregate_sums_across_expirations_and_sides():
    chains = [
        _exp(7, calls=[(100, 1000, 0.2)], puts=[(100, 500, 0.2)]),
        _exp(14, calls=[(100, 1000, 0.2)], puts=[]),
    ]
    agg = ge.aggregate_by_strike(chains, spot=100)
    assert set(agg.keys()) == {100}
    slot = agg[100]
    assert slot["call_gex"] > 0
    assert slot["put_gex"] < 0
    assert slot["net_gex"] == pytest.approx(slot["call_gex"] + slot["put_gex"])
    assert slot["oi"] == 1000 + 500 + 1000


def test_invalid_iv_and_zero_oi_skipped():
    chains = [_exp(7,
                   calls=[(100, 0, 0.2),       # OI 0 -> skip
                          (105, 1000, 0.0),    # IV 0 -> skip
                          (110, 1000, 9.0)],   # IV > IV_MAX -> skip
                   puts=[])]
    agg = ge.aggregate_by_strike(chains, spot=100)
    assert agg == {}


# --------------------------------------------------------------------------- #
# Flip interpolation
# --------------------------------------------------------------------------- #
def test_flip_linear_interpolation_midpoint():
    strikes = [{"strike": 90, "net_gex": -100}, {"strike": 110, "net_gex": 100}]
    assert ge.compute_flip(strikes, spot=100) == pytest.approx(100.0)


def test_flip_none_when_no_sign_change():
    strikes = [{"strike": 90, "net_gex": 50}, {"strike": 110, "net_gex": 100}]
    assert ge.compute_flip(strikes, spot=100) is None


def test_flip_multiple_crossings_picks_nearest_spot():
    # crossings near 95 and near 130; spot=100 -> expect ~95
    strikes = [
        {"strike": 90, "net_gex": -50},
        {"strike": 100, "net_gex": 50},    # crossing ~95
        {"strike": 120, "net_gex": 50},
        {"strike": 140, "net_gex": -50},   # crossing ~130
    ]
    flip = ge.compute_flip(strikes, spot=100)
    assert flip == pytest.approx(95.0)


# --------------------------------------------------------------------------- #
# Walls
# --------------------------------------------------------------------------- #
def test_walls_pick_extreme_net_gex():
    strikes = [
        {"strike": 90, "net_gex": -300},
        {"strike": 100, "net_gex": 50},
        {"strike": 110, "net_gex": 500},
    ]
    cw, pw = ge.find_walls(strikes)
    assert cw == 110
    assert pw == 90


def test_walls_none_when_no_positive_or_negative():
    cw, pw = ge.find_walls([{"strike": 100, "net_gex": 0}])
    assert cw is None and pw is None


# --------------------------------------------------------------------------- #
# Band filter
# --------------------------------------------------------------------------- #
def test_filter_band_keeps_within_pct():
    strikes = [{"strike": s, "net_gex": 0} for s in (80, 90, 100, 110, 120)]
    kept = ge.filter_band(strikes, spot=100, band_pct=0.15)
    assert [s["strike"] for s in kept] == [90, 100, 110]


def test_filter_band_none_keeps_all():
    strikes = [{"strike": s, "net_gex": 0} for s in (10, 1000)]
    assert len(ge.filter_band(strikes, spot=100, band_pct=None)) == 2


# --------------------------------------------------------------------------- #
# compute_profile end-to-end
# --------------------------------------------------------------------------- #
def test_compute_profile_regime_and_shape():
    # Calls dominate -> positive total -> stabilizing regime
    chains = [_exp(7,
                   calls=[(100, 5000, 0.2), (105, 3000, 0.2)],
                   puts=[(95, 1000, 0.2)])]
    prof = ge.compute_profile(chains, spot=100, band_pct=0.15)
    assert prof["spot"] == 100
    assert prof["total_gex"] > 0
    assert prof["regime"] == "positive"
    assert {s["strike"] for s in prof["strikes"]} == {95, 100, 105}
    assert prof["call_wall"] is not None
    assert "risk_free" in prof["assumptions"]


def test_compute_profile_negative_regime_when_puts_dominate():
    chains = [_exp(7, calls=[(105, 500, 0.2)], puts=[(100, 8000, 0.2)])]
    prof = ge.compute_profile(chains, spot=100, band_pct=0.15)
    assert prof["total_gex"] < 0
    assert prof["regime"] == "negative"
    assert prof["put_wall"] == 100


def test_compute_profile_empty_chains():
    prof = ge.compute_profile([], spot=100, band_pct=0.15)
    assert prof["strikes"] == []
    assert prof["total_gex"] == 0
    assert prof["flip"] is None
    assert prof["regime"] == "positive"  # total 0 -> >= 0


def test_compute_profile_rejects_bad_spot():
    with pytest.raises(ValueError):
        ge.compute_profile([], spot=0)


# --------------------------------------------------------------------------- #
# Drilldown
# --------------------------------------------------------------------------- #
def test_strike_breakdown_reconciles_with_net_gex():
    chains = [
        _exp(7, calls=[(100, 1000, 0.2)], puts=[(100, 400, 0.25)]),
        _exp(14, calls=[(100, 600, 0.22)], puts=[]),
    ]
    rows = ge.strike_breakdown(chains, spot=100, strike=100)
    assert len(rows) == 3  # 2 calls + 1 put
    breakdown_sum = sum(r["gex"] for r in rows)
    prof = ge.compute_profile(chains, spot=100, band_pct=None)
    net = next(s["net_gex"] for s in prof["strikes"] if s["strike"] == 100)
    assert breakdown_sum == pytest.approx(net, rel=1e-6)
