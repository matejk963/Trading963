"""Tests for Slice #6 — server-side ViewModel shaping helper (``src/mktt/viewmodel.py``).

Spec §5.1 — the ViewModel envelope a section returns to the generic client renderer::

    ViewModel = {
      figures: [ { id, traces:[...], layout:{...} } ],
      tables:  [ { id, columns:[...], rows:[...] } ],
      meta: {
        status:  "ok" | "empty" | "stale" | "error",
        message: str | None,
        asof:    "YYYY-MM-DD",
        title:   str,
        context: { ... },              # echo of the request
        readouts:{ stage, rs_rank, ... }  # headline scalars (badges)
      }
    }

Migration map §10 (last row): the scattered ``_n`` / ``_safe_num`` / ``fmt_number``
formatters from ``app.py:171-208`` fold into ONE place here.

Pure unit — no Flask, no DB, no network.
"""
from __future__ import annotations

import math

import pytest

from viewmodel import vm, num, val, money


# --------------------------------------------------------------------------- #
# Formatters — None / NaN / strings.
# --------------------------------------------------------------------------- #

class TestNum:
    """num() == the old _safe_num: coerce to float or None (NaN-safe)."""

    def test_float_passthrough(self):
        assert num(3.5) == 3.5

    def test_int_to_float(self):
        assert num(7) == 7.0
        assert isinstance(num(7), float)

    def test_numeric_string(self):
        assert num("12.25") == 12.25

    def test_none_is_none(self):
        assert num(None) is None

    def test_nan_is_none(self):
        assert num(float("nan")) is None

    def test_non_numeric_string_is_none(self):
        assert num("abc") is None

    def test_empty_string_is_none(self):
        assert num("") is None


class TestVal:
    """val() == the old _safe_val: stringify, with None / NaN / '<NA>' -> None."""

    def test_string_passthrough(self):
        assert val("Tech") == "Tech"

    def test_none_is_none(self):
        assert val(None) is None

    def test_nan_is_none(self):
        assert val(float("nan")) is None

    def test_pandas_na_string_is_none(self):
        assert val("<NA>") is None

    def test_number_stringified(self):
        assert val(42) == "42"


class TestMoney:
    """money() == the old fmt_number: 1.2T / 345.0M / 12.5K display strings."""

    def test_trillions(self):
        assert money(1.2e12) == "1.2T"

    def test_billions(self):
        assert money(3.45e9) == "3.5B"

    def test_millions(self):
        assert money(345e6) == "345.0M"

    def test_thousands(self):
        assert money(12500) == "12K"

    def test_small(self):
        assert money(42) == "42"

    def test_none_is_dash(self):
        assert money(None) == "—"

    def test_nan_is_dash(self):
        assert money(float("nan")) == "—"

    def test_negative(self):
        assert money(-1.2e12) == "-1.2T"


# --------------------------------------------------------------------------- #
# vm() — envelope builder.
# --------------------------------------------------------------------------- #

class TestVm:

    def test_empty_call_builds_spec_shape(self):
        out = vm()
        assert set(out.keys()) == {"figures", "tables", "meta"}
        assert out["figures"] == []
        assert out["tables"] == []
        meta = out["meta"]
        # all envelope meta keys present (self-describing)
        assert set(meta.keys()) == {
            "status", "message", "asof", "title", "context", "readouts"
        }

    def test_defaults(self):
        meta = vm()["meta"]
        assert meta["status"] == "ok"
        assert meta["message"] is None
        assert meta["asof"] is None
        assert meta["title"] is None
        assert meta["context"] == {}
        assert meta["readouts"] == {}

    def test_figures_and_tables_passed_through(self):
        figs = [{"id": "f1", "traces": [{"x": [1]}], "layout": {"title": "t"}}]
        tbls = [{"id": "t1", "columns": ["a"], "rows": [[1]]}]
        out = vm(figures=figs, tables=tbls)
        assert out["figures"] == figs
        assert out["tables"] == tbls

    def test_meta_kwargs_populate(self):
        out = vm(
            status="stale",
            message="cache 2d old",
            asof="2026-06-10",
            title="Screener",
            context={"sector": "Tech"},
            readouts={"stage": 2, "rs_rank": 88},
        )
        meta = out["meta"]
        assert meta["status"] == "stale"
        assert meta["message"] == "cache 2d old"
        assert meta["asof"] == "2026-06-10"
        assert meta["title"] == "Screener"
        assert meta["context"] == {"sector": "Tech"}
        assert meta["readouts"] == {"stage": 2, "rs_rank": 88}

    def test_additive_extra_meta_allowed(self):
        """Evolve additively (§5.1): unknown meta kwargs land in meta, don't break."""
        out = vm(extra_badge="new")
        assert out["meta"]["extra_badge"] == "new"
        # known keys still present
        assert out["meta"]["status"] == "ok"

    def test_single_figure_is_list_of_one(self):
        """A one-figure section returns figures:[one] (§5.1 id-keyed lists)."""
        out = vm(figures=[{"id": "only", "traces": [], "layout": {}}])
        assert len(out["figures"]) == 1
        assert out["figures"][0]["id"] == "only"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            vm(status="bogus")

    def test_does_not_mutate_inputs(self):
        figs = [{"id": "f", "traces": [], "layout": {}}]
        ctx = {"symbol": "AAPL"}
        vm(figures=figs, context=ctx)
        assert figs == [{"id": "f", "traces": [], "layout": {}}]
        assert ctx == {"symbol": "AAPL"}
