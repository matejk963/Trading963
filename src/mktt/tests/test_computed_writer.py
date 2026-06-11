"""Unit tests — Writer is materialization-only (spec §7, §8; adr/0001).

Stub the kernel, the classifiers, the DataSource and the ComputedStore; assert the
Writer (a) drives the enrichment pipeline in order, (b) runs the classifiers and
merges their columns, (c) calls ``computed.upsert`` with a panel carrying the full
derived column set — and holds **no compute of its own**.
"""
from __future__ import annotations

import pandas as pd
import pytest

from computed.writer import Writer


# --------------------------------------------------------------------------- #
# stubs
# --------------------------------------------------------------------------- #
def _panel(symbols=("AAA", "BBB"), n=3):
    dates = pd.date_range("2024-01-01", periods=n)
    idx = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "date"])
    df = pd.DataFrame(
        {"close": 1.0, "high": 1.0, "low": 1.0, "volume": 100.0},
        index=idx,
    )
    return df


class StubData:
    def __init__(self):
        self.calls = []

    def time_series(self, ids, start=None, end=None, fields=("close", "volume")):
        self.calls.append(("time_series", tuple(ids), tuple(fields)))
        # benchmark-only call → single SPY series
        if list(ids) == ["SPY"]:
            dates = pd.date_range("2024-01-01", periods=3)
            idx = pd.MultiIndex.from_product([["SPY"], dates], names=["symbol", "date"])
            return pd.DataFrame({"close": 1.0}, index=idx)
        return _panel()  # universe + benchmark; Writer drops SPY itself

    def fundamentals(self, ids, estimates=False, fields=None):
        self.calls.append(("fundamentals", tuple(ids), estimates))
        return pd.DataFrame(
            {"eps_actual": 1.0, "fy1_eps_mean": 2.0, "fy2_eps_mean": 4.0},
            index=pd.Index(list(ids), name="symbol"),
        )


class StubKernelMember:
    def __init__(self, col, recorder, needs_bench=False):
        self.col = col
        self.recorder = recorder
        self.needs_bench = needs_bench

    def compute(self, panel, benchmark=None, device="cpu"):
        self.recorder.append(("compute", self.col))
        out = panel.copy()
        out[self.col] = 1.0
        return out

    def rank(self, panel, by="mansfield_rs", device="cpu"):
        self.recorder.append(("rank", "rs_rank"))
        out = panel.copy()
        out["rs_rank"] = 50.0
        return out


class StubKernel:
    def __init__(self):
        self.order = []
        self.indicators = StubKernelMember("ma_50", self.order)
        self.relative_strength = StubKernelMember("rs_line", self.order)
        self.stage = StubKernelMember("stage", self.order)


def _make_classifier(name, column, recorder):
    import types
    mod = types.SimpleNamespace()
    mod.__name__ = f"computed.classifiers.{name}"
    mod.COLUMN = column

    def classify(*args, **kwargs):
        recorder.append(("classify", name))
        # return a per-symbol series for AAA/BBB
        return pd.Series({"AAA": 1, "BBB": 2}, name=column)

    mod.classify = classify
    return mod


class StubStore:
    def __init__(self):
        self.upserted = None

    def upsert(self, panel):
        self.upserted = panel.copy()
        return {"classification_history": len(panel),
                "classification_current": panel.index.get_level_values("symbol").nunique()}


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def _build():
    data, kernel, store = StubData(), StubKernel(), StubStore()
    rec = []
    classifiers = [
        _make_classifier("pca_regime", "regime", rec),
        _make_classifier("ma_screen", "ma_screen", rec),
        _make_classifier("eps_accel", "eps_accel", rec),
    ]
    w = Writer(data, store, kernel, classifiers=classifiers, benchmark="SPY")
    return w, data, kernel, store, rec, classifiers


def test_writer_runs_kernel_pipeline_in_order():
    w, data, kernel, store, rec, _ = _build()
    w.run(["AAA", "BBB"])
    # indicators → rs.compute → rs.rank → stage
    assert kernel.order == [
        ("compute", "ma_50"),
        ("compute", "rs_line"),
        ("rank", "rs_rank"),
        ("compute", "stage"),
    ]


def test_writer_calls_upsert_with_full_column_set():
    w, data, kernel, store, rec, _ = _build()
    w.run(["AAA", "BBB"])
    assert store.upserted is not None
    cols = set(store.upserted.columns)
    # kernel columns + classifier columns all present
    for c in ("ma_50", "rs_line", "rs_rank", "stage", "regime", "ma_screen", "eps_accel"):
        assert c in cols, f"missing {c}"


def test_writer_runs_each_classifier_and_merges_its_column():
    w, data, kernel, store, rec, _ = _build()
    w.run(["AAA", "BBB"])
    classified = [name for (tag, name) in rec if tag == "classify"]
    assert set(classified) == {"pca_regime", "ma_screen", "eps_accel"}
    # merged values broadcast per symbol (AAA=1, BBB=2 from the stub)
    assert store.upserted.xs("AAA", level="symbol")["regime"].unique().tolist() == [1]
    assert store.upserted.xs("BBB", level="symbol")["ma_screen"].unique().tolist() == [2]


def test_writer_drops_benchmark_from_classified_universe():
    w, data, kernel, store, rec, _ = _build()
    w.run(["AAA", "BBB"])
    syms = set(store.upserted.index.get_level_values("symbol"))
    assert "SPY" not in syms
    assert syms == {"AAA", "BBB"}


def test_writer_noop_on_empty_ids():
    w, data, kernel, store, rec, _ = _build()
    assert w.run([]) == {}
    assert store.upserted is None


def test_writer_has_no_compute_logic():
    """Materialization-only: the upserted columns come solely from the stubbed
    kernel/classifiers — the Writer invents no values."""
    w, data, kernel, store, rec, _ = _build()
    w.run(["AAA", "BBB"])
    # stage came from the stub (constant 1.0), not any Writer formula
    assert store.upserted["stage"].unique().tolist() == [1.0]
    # rs_rank from the stub rank (50.0)
    assert store.upserted["rs_rank"].unique().tolist() == [50.0]
