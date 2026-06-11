"""Canonical data forms that cross module boundaries (spec §3).

`TimeSeries` is a pandas ``symbol × date`` frame (no wrapper needed). The
`OptionChain` form, by contrast, is an ``expiry × strike`` grid of OI/IV per side
plus the spot and freshness metadata the GEX core and the Options section consume.
It is modeled as a small immutable record so sections receive a typed form rather
than a bare dict (the old ``options_service.get_next_chains`` payload shape).

Kept dependency-light (stdlib ``dataclasses`` only) — pure form, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

__all__ = ["OptionChain"]


@dataclass(frozen=True)
class OptionChain:
    """An ``expiry × strike`` option grid for one symbol (spec §3).

    Attributes
    ----------
    symbol:
        The underlying (upper-cased).
    spot:
        Resolved spot price.
    chains:
        Per-expiration normalized grids — ``[{expiration, dte, calls, puts}, ...]``
        where ``calls``/``puts`` are ``[{strike, oi, iv}, ...]``. This is exactly the
        shape ``gex_engine.compute_profile`` / ``strike_breakdown`` consume.
    expirations:
        The expirations actually used (selected subset).
    available_expirations:
        Full list of available expirations (for the client picker).
    default_expirations:
        The default first-N expirations.
    meta:
        Freshness disclosure — ``{fetched_at, oi_as_of, stale, warning}``.
    """

    symbol: str
    spot: float
    chains: List[Mapping[str, Any]]
    expirations: List[str]
    available_expirations: List[str] = field(default_factory=list)
    default_expirations: List[str] = field(default_factory=list)
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        """Whether this chain was served from stale cache (live fetch failed)."""
        return bool(self.meta.get("stale", False))
