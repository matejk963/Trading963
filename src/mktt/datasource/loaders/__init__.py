"""DataSource loaders — batch jobs that materialize raw external dumps into the
Postgres `etc_db` schemas (spec §4.4, §6).

`mkfund_loader` collapses the 7 scattered `refinitiv_fundamentals.pkl` reads into a
single idempotent loader that upserts `MKFund.{fundamentals_current, estimates_forward,
quarterly, estimate_revisions}`.
"""
from __future__ import annotations

from .mkfund_loader import (
    load,
    map_snapshot,
    map_estimates_forward,
    map_quarterly,
    map_estimate_revisions,
)

__all__ = [
    "load",
    "map_snapshot",
    "map_estimates_forward",
    "map_quarterly",
    "map_estimate_revisions",
]
