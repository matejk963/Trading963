"""Writer-fed classifiers (adr/0001) — separate compute units the Writer runs.

These are NOT kernel members (single consumer / distinct algorithm, spec §4.3) but
ARE legitimate producers of derived ``classification_*`` columns, ported from
``update_classifications.py`` parts 2-4 + ``sandbox/.../pca_stage_classifier.py``:

- :mod:`pca_regime` — PCA + KMeans 5-cluster cross-sectional regime -> ``regime``.
- :mod:`eps_accel`  — EPS acceleration (NY-vs-CY EPS growth)        -> ``eps_accel``.
- :mod:`ma_screen`  — price vs MA50/MA200 position bucket           -> ``ma_screen``.

Each exposes a ``classify(...)`` returning a per-symbol ``pandas.Series`` keyed by
symbol (the latest cross-section), so the Writer can merge the columns onto the
panel's latest rows uniformly. They take what they need (the kernel-enriched panel,
and for EPS the ``Fundamentals``) — the Writer wires the inputs.
"""
from __future__ import annotations

from . import eps_accel, ma_screen, pca_regime

#: The classifier units the Writer runs, in order. Each must expose ``classify``
#: and a module-level ``COLUMN`` naming the derived column it produces.
DEFAULT_CLASSIFIERS = (pca_regime, ma_screen, eps_accel)

__all__ = ["pca_regime", "ma_screen", "eps_accel", "DEFAULT_CLASSIFIERS"]
