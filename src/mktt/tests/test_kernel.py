"""Tests for Slice #2a — Kernel (pure pandas) enrichment pipeline.

Spec §5.2 — each primitive takes the panel-so-far and adds exactly its columns
(``TimeSeries → TimeSeries(+cols)``), composable::

    indicators.compute(ts)                  -> + ma_50/150/200, ma_150_slope, returns, volume_ma
    relative_strength.compute(ts, bench)    -> + rs_line, mansfield_rs   (per-symbol)
    relative_strength.rank(panel, by=...)   -> + rs_rank                 (cross-sectional)
    stage.compute(panel)                    -> + stage                   (reuses ma_*/rs)

TimeSeries seam == pandas ``symbol × date`` multi-index DataFrame, columns=fields.

Two layers:
  * pure-unit tests on small hand-built frames (column contracts, single-symbol
    path, cross-sectional rank, stage reuse, no MA recompute, purity);
  * BEHAVIOR PARITY of stage + MAs + mansfield_rs vs ``stage_classifier`` on the
    frozen Slice-3 golden sample (``tests/fixtures/golden/kernel_stage.json``).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kernel import indicators, relative_strength, stage
from parity import assert_parity

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "mktt"


# --------------------------------------------------------------------------- #
# Helpers — build small symbol×date panels.
# --------------------------------------------------------------------------- #
def _panel(data: dict, fields=("close", "volume")) -> pd.DataFrame:
    """data: {symbol: {field: {date_str: value}}} -> symbol×date multi-index."""
    frames = []
    for sym, per_field in data.items():
        cols = {f: pd.Series({pd.Timestamp(d): v for d, v in per_field.get(f, {}).items()})
                for f in fields}
        sub = pd.DataFrame(cols)
        sub.index.name = "date"
        sub = pd.concat({sym: sub}, names=["symbol"])
        frames.append(sub)
    return pd.concat(frames)


def _ramp_panel(symbols, n=300, start="2022-01-03", base=100.0, slope=0.5):
    """A linearly-rising close/volume panel long enough for 200-bar MAs."""
    dates = pd.bdate_range(start=start, periods=n)
    data = {}
    for k, sym in enumerate(symbols):
        closes = {str(d.date()): base + slope * i + 3.0 * k for i, d in enumerate(dates)}
        vols = {str(d.date()): 1_000_000 + 1000 * i for i, d in enumerate(dates)}
        data[sym] = {"close": closes, "volume": vols}
    return _panel(data)


def _benchmark(n=300, start="2022-01-03", base=400.0, slope=0.1):
    dates = pd.bdate_range(start=start, periods=n)
    closes = {str(d.date()): base + slope * i for i, d in enumerate(dates)}
    return _panel({"SPY": {"close": closes}}, fields=("close",))


# --------------------------------------------------------------------------- #
# indicators.compute — adds exactly its columns
# --------------------------------------------------------------------------- #
def test_indicators_adds_exactly_its_columns():
    ts = _ramp_panel(["AAA"])
    before = set(ts.columns)
    out = indicators.compute(ts)
    added = set(out.columns) - before
    assert added == set(indicators.ADDED_COLUMNS)
    # index unchanged
    assert out.index.equals(ts.index)


def test_indicators_ma_values_match_rolling_mean():
    ts = _ramp_panel(["AAA"])
    out = indicators.compute(ts)
    aaa_close = ts.xs("AAA", level="symbol")["close"]
    expected_ma50 = aaa_close.rolling(50).mean()
    got = out.xs("AAA", level="symbol")["ma_50"]
    pd.testing.assert_series_equal(got, expected_ma50, check_names=False)


def test_indicators_slope_is_21d_diff_of_ma150():
    ts = _ramp_panel(["AAA"])
    out = indicators.compute(ts)
    ma150 = out.xs("AAA", level="symbol")["ma_150"]
    slope = out.xs("AAA", level="symbol")["ma_150_slope"]
    pd.testing.assert_series_equal(slope, ma150.diff(21), check_names=False)


def test_indicators_requires_close():
    ts = _panel({"AAA": {"volume": {"2024-01-01": 1.0}}}, fields=("volume",))
    with pytest.raises(ValueError):
        indicators.compute(ts)


def test_indicators_volume_ma_nan_without_volume():
    ts = _ramp_panel(["AAA"])[["close"]]
    out = indicators.compute(ts)
    assert "volume_ma" in out.columns
    assert out["volume_ma"].isna().all()


def test_indicators_does_not_mutate_input():
    ts = _ramp_panel(["AAA"])
    cols_before = list(ts.columns)
    indicators.compute(ts)
    assert list(ts.columns) == cols_before


def test_indicators_gpu_device_raises():
    ts = _ramp_panel(["AAA"])
    with pytest.raises(NotImplementedError):
        indicators.compute(ts, device="gpu")


# --------------------------------------------------------------------------- #
# relative_strength.compute — per-symbol rs_line + mansfield_rs
# --------------------------------------------------------------------------- #
def test_rs_compute_adds_exactly_its_columns():
    ts = indicators.compute(_ramp_panel(["AAA", "BBB"]))
    before = set(ts.columns)
    out = relative_strength.compute(ts, _benchmark())
    assert set(out.columns) - before == set(relative_strength.COMPUTE_COLUMNS)


def test_rs_line_is_close_over_benchmark():
    ts = _ramp_panel(["AAA"])
    bench = _benchmark()
    out = relative_strength.compute(ts, bench)
    bclose = bench.xs("SPY", level="symbol")["close"]
    aaa = out.xs("AAA", level="symbol")
    expected = aaa["close"] / bclose.reindex(aaa.index).ffill()
    pd.testing.assert_series_equal(aaa["rs_line"], expected, check_names=False)


def test_rs_accepts_plain_series_benchmark():
    ts = _ramp_panel(["AAA"])
    bench_df = _benchmark()
    bench_series = bench_df.xs("SPY", level="symbol")["close"]
    out = relative_strength.compute(ts, bench_series)
    assert "rs_line" in out.columns and out["rs_line"].notna().any()


def test_rs_compute_does_not_mutate_input():
    ts = indicators.compute(_ramp_panel(["AAA"]))
    cols = list(ts.columns)
    relative_strength.compute(ts, _benchmark())
    assert list(ts.columns) == cols


# --------------------------------------------------------------------------- #
# relative_strength.rank — cross-sectional; needs >1 symbol
# --------------------------------------------------------------------------- #
def test_rank_adds_exactly_rs_rank():
    panel = relative_strength.compute(indicators.compute(_ramp_panel(["AAA", "BBB"])), _benchmark())
    before = set(panel.columns)
    out = relative_strength.rank(panel, by="mansfield_rs")
    assert set(out.columns) - before == set(relative_strength.RANK_COLUMNS)


def test_rank_single_symbol_is_null():
    panel = relative_strength.compute(indicators.compute(_ramp_panel(["AAA"])), _benchmark())
    out = relative_strength.rank(panel, by="mansfield_rs")
    assert out["rs_rank"].isna().all()


def test_rank_cross_sectional_orders_symbols():
    # Two symbols, last date: BBB has higher mansfield -> higher rank.
    panel = relative_strength.compute(indicators.compute(_ramp_panel(["AAA", "BBB"])), _benchmark())
    out = relative_strength.rank(panel, by="mansfield_rs")
    last_date = out.index.get_level_values("date").max()
    row = out.xs(last_date, level="date")
    # ranks are a percentile in [0,100]; the two symbols get distinct ranks.
    ranks = row["rs_rank"].dropna()
    assert ranks.between(0, 100).all()
    assert ranks.nunique() == 2


def test_rank_missing_column_raises():
    panel = indicators.compute(_ramp_panel(["AAA", "BBB"]))  # no mansfield_rs
    with pytest.raises(ValueError):
        relative_strength.rank(panel, by="mansfield_rs")


def test_rank_returns_6m_basis_available():
    panel = relative_strength.compute(indicators.compute(_ramp_panel(["AAA", "BBB"])), _benchmark())
    out = relative_strength.rank(panel, by="returns_6m")
    assert "rs_rank" in out.columns


# --------------------------------------------------------------------------- #
# stage.compute — reuses ma_*/rs columns, single stage column
# --------------------------------------------------------------------------- #
def test_stage_adds_exactly_stage():
    panel = relative_strength.rank(
        relative_strength.compute(indicators.compute(_ramp_panel(["AAA", "BBB"])), _benchmark()),
        by="returns_6m",
    )
    before = set(panel.columns)
    out = stage.compute(panel)
    assert set(out.columns) - before == set(stage.ADDED_COLUMNS)
    assert out["stage"].isin([0, 1, 2, 3, 4]).all()


def test_stage_requires_prior_columns():
    ts = _ramp_panel(["AAA"])  # raw, no ma_*/rs_rank
    with pytest.raises(ValueError):
        stage.compute(ts)


def test_stage_reuses_ma_columns_without_recompute():
    # Tamper ma_50 with a sentinel; stage must NOT recompute it (column survives).
    panel = relative_strength.rank(
        relative_strength.compute(indicators.compute(_ramp_panel(["AAA", "BBB"])), _benchmark()),
        by="returns_6m",
    )
    sentinel = panel["ma_50"].copy()
    sentinel.iloc[:] = -999.0
    panel = panel.assign(ma_50=sentinel)
    out = stage.compute(panel)
    # ma_50 column is untouched by stage (it is read, never rewritten).
    assert (out["ma_50"] == -999.0).all()


def test_stage_single_symbol_path_runs():
    # Single symbol: rs_rank is NaN -> stage falls through to 0 (Unclassified),
    # but the pipeline must run end-to-end without error.
    panel = relative_strength.rank(
        relative_strength.compute(indicators.compute(_ramp_panel(["AAA"])), _benchmark()),
        by="returns_6m",
    )
    out = stage.compute(panel)
    assert out["stage"].isin([0, 1, 2, 3, 4]).all()


# --------------------------------------------------------------------------- #
# Full pipeline composes
# --------------------------------------------------------------------------- #
def test_pipeline_composes_left_to_right():
    ts = _ramp_panel(["AAA", "BBB", "CCC"])
    panel = indicators.compute(ts)
    panel = relative_strength.compute(panel, _benchmark())
    panel = relative_strength.rank(panel, by="returns_6m")
    panel = stage.compute(panel)
    expected = set(ts.columns) | set(indicators.ADDED_COLUMNS) \
        | set(relative_strength.COMPUTE_COLUMNS) | set(relative_strength.RANK_COLUMNS) \
        | set(stage.ADDED_COLUMNS)
    assert set(panel.columns) == expected


# --------------------------------------------------------------------------- #
# BEHAVIOR PARITY vs stage_classifier on the frozen golden sample (Slice 3)
# --------------------------------------------------------------------------- #
def _load_golden():
    p = GOLDEN_DIR / "kernel_stage.json"
    if not p.exists():
        pytest.skip("golden kernel_stage.json absent")
    return json.loads(p.read_text())


def _wide_to_panel(close_df, volume_df):
    """date×ticker wide frames -> symbol×date multi-index panel.

    Keeps NaN rows (``dropna=False``) so each symbol shares the SAME date axis
    the legacy wide-frame rolling used — otherwise per-symbol rolling windows
    would span different calendar dates and break MA parity.
    """
    c = close_df.stack(dropna=False).rename("close")
    v = (volume_df.reindex(index=close_df.index, columns=close_df.columns)
         .stack(dropna=False).rename("volume"))
    panel = pd.concat([c, v], axis=1)
    panel.index = panel.index.set_names(["date", "symbol"])
    panel = panel.reorder_levels(["symbol", "date"]).sort_index()
    return panel


@pytest.mark.parametrize("col", ["MA50", "MA150", "MA200", "MA150_Slope", "Mansfield_RS", "Stage"])
def test_parity_kernel_vs_stage_classifier(col):
    golden = _load_golden()
    # The golden was generated by feeding the REQUESTED sample into the legacy
    # kernel — so the cross-sectional rs_rank denominator is that universe. We
    # must enrich the same universe, then compare only the symbols it returned.
    sample = golden["meta"]["sample_requested"]
    compared_syms = set(golden["meta"]["sample_returned"])
    asof = pd.Timestamp(golden["meta"]["asof"])  # frozen baseline date
    if not DATA_DIR.exists():
        pytest.skip("local parquet data absent — cannot run parity")

    close_df = pd.read_parquet(DATA_DIR / "close.parquet")
    volume_df = pd.read_parquet(DATA_DIR / "volume.parquet")
    spy_df = pd.read_parquet(DATA_DIR / "spy.parquet")

    # Re-create the baseline's window exactly: the parquet has grown new bars
    # since the golden was frozen, so trim every frame to the golden asof date.
    close_df = close_df[close_df.index <= asof]
    volume_df = volume_df[volume_df.index <= asof]
    spy_df = spy_df[spy_df.index <= asof]

    sample = [s for s in sample if s in close_df.columns]
    close_df = close_df[sample]
    volume_df = volume_df[[s for s in sample if s in volume_df.columns]]

    panel = _wide_to_panel(close_df, volume_df)
    bench = spy_df["Close"].rename("close")
    bench.index = bench.index.rename("date")

    panel = indicators.compute(panel)
    panel = relative_strength.compute(panel, bench)
    panel = relative_strength.rank(panel, by="returns_6m")  # legacy golden basis
    panel = stage.compute(panel)

    # latest valid close row per symbol (mirrors build_results' last_valid_index).
    col_map = {
        "MA50": "ma_50", "MA150": "ma_150", "MA200": "ma_200",
        "MA150_Slope": "ma_150_slope", "Mansfield_RS": "mansfield_rs", "Stage": "stage",
    }
    kcol = col_map[col]

    actual, expected = {}, {}
    golden_by_sym = {r["Symbol"]: r for r in golden["rows"]}
    for sym in sample:
        if sym not in golden_by_sym or sym not in compared_syms:
            continue
        sub = panel.xs(sym, level="symbol")
        last = sub["close"].last_valid_index()
        if last is None:
            continue
        val = sub.at[last, kcol]
        actual[sym] = None if (isinstance(val, float) and np.isnan(val)) else (
            int(val) if col == "Stage" else float(val))
        expected[sym] = golden_by_sym[sym][col]

    assert actual, "no overlapping symbols to compare"
    assert_parity(actual, expected, rel_tol=1e-6, abs_tol=1e-6)
