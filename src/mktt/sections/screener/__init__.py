"""Screener section package (spec §4.2).

Public surface: the typed request, the pure ``handle`` recipe, and the thin Flask
blueprint. No section imports another section (spec §2); ``handle`` is
dependency-injected (spec §8).
"""
from .service import ScreenRequest, handle

__all__ = ["ScreenRequest", "handle", "screener_bp"]


def __getattr__(name):
    # Lazy so importing the section for unit tests never pulls Flask.
    if name == "screener_bp":
        from .routes import screener_bp
        return screener_bp
    raise AttributeError(name)
