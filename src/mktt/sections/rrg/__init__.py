"""RRG section — Relative Rotation Graph (spec §4.2, §10 — FLAG-5).

Public surface: the typed request, the recipe, and the thin blueprint.
"""
from .service import RrgRequest, handle
from .routes import rrg_bp

__all__ = ["RrgRequest", "handle", "rrg_bp"]
