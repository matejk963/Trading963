"""Monitor section — per-security view + shared watchlist (spec §4.2, Slice #8).

Public surface (what the blueprint and tests import):
    MonitorRequest    — the typed request (single- or multi-symbol).
    handle            — the recipe: live kernel + history + fundamentals -> ViewModel.
    watchlist_members / watchlist_add / watchlist_remove — list proxies (Monitor reads).
"""
from __future__ import annotations

from .service import (
    MonitorRequest,
    handle,
    watchlist_add,
    watchlist_members,
    watchlist_remove,
)

__all__ = [
    "MonitorRequest",
    "handle",
    "watchlist_members",
    "watchlist_add",
    "watchlist_remove",
]
