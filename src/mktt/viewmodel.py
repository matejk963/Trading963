"""ViewModel shaping — the server side of the section→client contract (spec §5.1).

A section's ``handle()`` shapes its result into the **ViewModel envelope** consumed
by the one generic client renderer (``static/js/viewmodel.js``). This module holds:

* :func:`vm` — build the spec-shaped envelope additively, and
* the consolidated value formatters :func:`num` / :func:`val` / :func:`money`
  (migration map §10 last row — folds ``_safe_num`` / ``_safe_val`` / ``fmt_number``
  scattered across ``app.py:171-208`` into one place).

Envelope (spec §5.1)::

    ViewModel = {
      figures: [ { id, traces:[...], layout:{...} } ],   # 0..N Plotly-ready
      tables:  [ { id, columns:[...], rows:[...] } ],     # 0..N
      meta: {
        status:  "ok" | "empty" | "stale" | "error",
        message: str | None,
        asof:    "YYYY-MM-DD" | None,
        title:   str | None,
        context: { ... },                 # echo of the request
        readouts:{ stage, rs_rank, ... }  # headline scalars -> badges
      }
    }

Pure: no Flask / DB / network imports. ``math`` only, so the helper stays a
trivially unit-testable seam.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

__all__ = ["vm", "num", "val", "money", "VALID_STATUSES"]

#: The closed set of envelope statuses the client renderer understands (§5.1).
VALID_STATUSES = ("ok", "empty", "stale", "error")


# --------------------------------------------------------------------------- #
# Value formatters — one home (migration map §10).
# --------------------------------------------------------------------------- #

def num(value: Any) -> float | None:
    """Coerce ``value`` to ``float`` or ``None`` (NaN-safe).

    Consolidates the old ``_safe_num`` (``app.py:171``). ``None``, non-numeric
    strings, empty strings and NaN all collapse to ``None``; everything numeric
    becomes a plain ``float`` (JSON-safe scalar for ``meta.readouts`` / table cells).
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(f):
        return None
    return f


def val(value: Any) -> str | None:
    """Stringify ``value``, mapping ``None`` / NaN / pandas ``'<NA>'`` to ``None``.

    Consolidates the old ``_safe_val`` (``app.py:183``). Kept dependency-free:
    a ``float`` NaN is caught directly (no pandas import), and the ``'<NA>'``
    sentinel pandas renders for missing values is normalized to ``None``.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value)
    if s == "<NA>":
        return None
    return s


def money(value: Any) -> str:
    """Human number: ``1.2T`` / ``345.0M`` / ``12K`` / ``42`` — ``—`` when missing.

    Consolidates the old ``fmt_number`` (``app.py:189``). ``None`` / NaN render as
    an em-dash so the client never has to special-case empties.
    """
    if value is None:
        return "—"
    try:
        v = float(value)
    except (ValueError, TypeError):
        return "—"
    if math.isnan(v):
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:.1f}T"
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}"


# --------------------------------------------------------------------------- #
# Envelope builder.
# --------------------------------------------------------------------------- #

def vm(
    figures: Sequence[Mapping[str, Any]] | None = None,
    tables: Sequence[Mapping[str, Any]] | None = None,
    *,
    status: str = "ok",
    message: str | None = None,
    asof: str | None = None,
    title: str | None = None,
    context: Mapping[str, Any] | None = None,
    readouts: Mapping[str, Any] | None = None,
    **extra_meta: Any,
) -> dict[str, Any]:
    """Build the spec §5.1 ViewModel envelope.

    ``figures`` / ``tables`` are id-keyed lists passed through verbatim (a
    one-figure section returns ``figures=[one]``). The remaining keyword args
    populate ``meta``; **unknown** keyword args land in ``meta`` too so the
    envelope can evolve additively (§5.1) without touching this signature.

    Inputs are deep-copied — the returned envelope never aliases caller state.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"status {status!r} not in {VALID_STATUSES} (spec §5.1)"
        )

    meta: dict[str, Any] = {
        "status": status,
        "message": message,
        "asof": asof,
        "title": title,
        "context": copy.deepcopy(dict(context)) if context else {},
        "readouts": copy.deepcopy(dict(readouts)) if readouts else {},
    }
    # Additive evolution: extra meta fields ride along without breaking the renderer.
    for key, value in extra_meta.items():
        meta[key] = copy.deepcopy(value)

    return {
        "figures": copy.deepcopy([dict(f) for f in figures]) if figures else [],
        "tables": copy.deepcopy([dict(t) for t in tables]) if tables else [],
        "meta": meta,
    }
