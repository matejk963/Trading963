"""MKTT analytical kernel — pure, source-blind enrichment pipeline (spec §4.3, §5.2).

Three composable primitives, each ``TimeSeries → TimeSeries(+columns)`` over a
pandas ``symbol × date`` multi-index DataFrame::

    from kernel import indicators, relative_strength, stage

    panel = indicators.compute(ts)                          # + ma_50/150/200, ma_150_slope, returns, volume_ma
    panel = relative_strength.compute(panel, benchmark)     # + rs_line, mansfield_rs   (per-symbol)
    panel = relative_strength.rank(panel, by="mansfield_rs")# + rs_rank                  (cross-sectional)
    panel = stage.compute(panel)                            # + stage  (reuses ma_*/rs columns)

Pure: no DataSource / ComputedStore / Flask / network imports. A device-agnostic
seam (``device="cpu"``) is kept on every primitive; only the CPU/pandas backend
is implemented — the GPU backend is deferred (adr/0001).
"""
from __future__ import annotations

from . import indicators, relative_strength, stage

__all__ = ["indicators", "relative_strength", "stage"]
