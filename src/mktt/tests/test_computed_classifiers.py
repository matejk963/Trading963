"""Unit tests — Writer-fed classifiers (adr/0001) on hand-built inputs.

Pure, no DB/network. ma_screen and eps_accel are fully deterministic; pca_regime
is tested for shape/codes on a small synthetic universe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from computed.classifiers import eps_accel, ma_screen, pca_regime


def _panel(rows):
    """rows: dict[(symbol, date)] -> dict[col]."""
    idx = pd.MultiIndex.from_tuples(list(rows), names=["symbol", "date"])
    return pd.DataFrame(list(rows.values()), index=idx)


# --------------------------------------------------------------------------- #
# ma_screen
# --------------------------------------------------------------------------- #
def test_ma_screen_buckets():
    d1, d2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")
    panel = _panel({
        # above both → 0
        ("AAA", d1): {"close": 9, "ma_50": 8, "ma_200": 7},
        ("AAA", d2): {"close": 10, "ma_50": 8, "ma_200": 7},
        # above 200 below 50 → 1
        ("BBB", d2): {"close": 9, "ma_50": 10, "ma_200": 8},
        # below 200 above 50 → 2
        ("CCC", d2): {"close": 9, "ma_50": 8, "ma_200": 10},
        # below both → 3
        ("DDD", d2): {"close": 5, "ma_50": 8, "ma_200": 10},
    })
    out = ma_screen.classify(panel)
    assert out.loc["AAA"] == 0  # uses the LATEST row (d2)
    assert out.loc["BBB"] == 1
    assert out.loc["CCC"] == 2
    assert out.loc["DDD"] == 3
    assert out.name == "ma_screen"


def test_ma_screen_nan_ma_is_null():
    d = pd.Timestamp("2024-01-02")
    panel = _panel({("AAA", d): {"close": 9, "ma_50": np.nan, "ma_200": 7}})
    out = ma_screen.classify(panel)
    assert pd.isna(out.loc["AAA"])


def test_ma_screen_missing_cols_raises():
    panel = _panel({("AAA", pd.Timestamp("2024-01-01")): {"close": 1.0}})
    with pytest.raises(ValueError):
        ma_screen.classify(panel)


# --------------------------------------------------------------------------- #
# eps_accel  (g1=fy1-act, g2=fy2-fy1, accel=g2-g1)
# --------------------------------------------------------------------------- #
def test_eps_accel_value():
    f = pd.DataFrame(
        {"eps_actual": [1.0, 5.0], "fy1_eps_mean": [2.0, 6.0], "fy2_eps_mean": [4.0, 6.5]},
        index=pd.Index(["ACC", "DEC"], name="symbol"),
    )
    out = eps_accel.classify(f)
    # ACC: g1=1, g2=2, accel=+1 ; DEC: g1=1, g2=0.5, accel=-0.5
    assert out.loc["ACC"] == pytest.approx(1.0)
    assert out.loc["DEC"] == pytest.approx(-0.5)
    assert out.name == "eps_accel"


def test_eps_accel_drops_missing_inputs():
    f = pd.DataFrame(
        {"eps_actual": [1.0, np.nan], "fy1_eps_mean": [2.0, 6.0], "fy2_eps_mean": [4.0, 6.5]},
        index=pd.Index(["AAA", "BBB"], name="symbol"),
    )
    out = eps_accel.classify(f)
    assert "AAA" in out.index and "BBB" not in out.index


def test_eps_accel_empty():
    assert len(eps_accel.classify(pd.DataFrame())) == 0


# --------------------------------------------------------------------------- #
# pca_regime — synthetic universe, shape + code range
# --------------------------------------------------------------------------- #
def _synthetic_wide(n_sym=30, n_days=300, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n_days, freq="B")
    syms = [f"S{i:03d}" for i in range(n_sym)]
    # distinct drifts so the cross-section has structure to cluster
    close = {}
    for i, s in enumerate(syms):
        drift = (i - n_sym / 2) / n_sym * 0.002
        steps = rng.normal(drift, 0.02, n_days)
        close[s] = 100 * np.exp(np.cumsum(steps))
    close = pd.DataFrame(close, index=dates)
    high = close * 1.01
    low = close * 0.99
    volume = pd.DataFrame(rng.uniform(1e5, 1e6, (n_days, n_sym)), index=dates, columns=syms)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days))), index=dates)
    return close, high, low, volume, spy


def test_pca_regime_shape_and_codes():
    close, high, low, volume, spy = _synthetic_wide()
    out = pca_regime.classify(close, high, low, volume, spy)
    assert out.name == "regime"
    assert len(out) > 0
    assert set(out.unique()).issubset(set(range(5)))
    assert out.index.name == "symbol"


def test_pca_regime_too_few_stocks():
    close, high, low, volume, spy = _synthetic_wide(n_sym=3)
    out = pca_regime.classify(close, high, low, volume, spy)
    assert len(out) == 0
