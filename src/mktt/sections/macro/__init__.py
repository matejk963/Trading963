"""Macro section — Global Liquidity (Howell/Boucher), regime + transmission chain
(spec §4.2, §10 — FLAG-5). The old `macro/` package dissolves into this Macro
section + the RRG section.

Public surface: the typed request, the recipe, and the thin blueprint.
"""
from .service import MacroRequest, handle
from .routes import macro_bp

__all__ = ["MacroRequest", "handle", "macro_bp"]
