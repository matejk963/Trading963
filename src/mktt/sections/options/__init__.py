"""Options section (spec §4.2) — thin manager over the private `gex_engine` core.

Public surface: ``handle(req, data) -> ViewModel`` and the typed ``OptionsRequest``.
``gex_engine`` stays the PRIVATE deep core (its math is untouched — parity).
"""
from __future__ import annotations

from .service import DEFAULT_N_EXP, OptionsRequest, handle

__all__ = ["handle", "OptionsRequest", "DEFAULT_N_EXP"]
