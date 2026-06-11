"""Computed-derived layer — ComputedStore + Writer + Writer-fed classifiers (Slice #5).

The Writer (``writer.py``) is the **single writer** of derived data (adr/0001): it
reads raw ``TimeSeries`` from the DataSource, runs the kernel enrichment pipeline
(Indicators → RS.compute → RS.rank → Stage) and the Writer-fed classifier units
(PCA-regime / EPS-accel / MA-screen), merges their columns, and upserts into the
``MKCompStore`` tables through the :class:`ComputedStore`.

The :class:`ComputedStore` (``store.py``) is the Postgres-backed current/history
store of those outputs (spec §4.5, §5.3): ``cross_section`` (Screener — fixed-size),
``history`` (Monitor), ``ensure_fresh`` (auto-recompute the stale), ``upsert``.
"""
from __future__ import annotations

from .store import ComputedStore
from .writer import Writer

__all__ = ["ComputedStore", "Writer"]
