"""(form, id) registry for the DataSource (spec §4.4, §5.3).

Source-resolution is **config, not branching**: a caller passes ids + params and
never a source. The registry maps:

    id  -> asset_class            (a metadata tag — equity / benchmark / etf / ...)
    (form, asset_class) -> submodule

Adding an asset type = a registry row (+ maybe one handler), never an `if`.

Asset class is metadata, not structure (spec §3): a stock, ETF, futures contract,
macro series, and benchmark are all `TimeSeries`, differing only by this tag — so
the benchmark (SPY) routes through the same `time_series` path as any equity.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


class Registry:
    """Resolves a `(form, id)` to the submodule that can serve it.

    Parameters
    ----------
    asset_class:
        ``id -> asset_class`` lookup. Ids absent here fall back to
        ``default_asset_class`` (so the bulk equity universe needs no per-symbol
        row — only the exceptions, e.g. the benchmark, are tagged).
    submodules:
        ``(form, asset_class) -> submodule`` table. The submodule must expose the
        form's interface (for ``time_series`` that is
        ``time_series(ids, start, end, fields)``).
    default_asset_class:
        Asset class assumed for any id not present in ``asset_class``.
    """

    def __init__(
        self,
        asset_class: Optional[Dict[str, str]] = None,
        submodules: Optional[Dict[Tuple[str, str], Any]] = None,
        default_asset_class: str = "equity",
    ) -> None:
        self._asset_class = dict(asset_class or {})
        self._submodules = dict(submodules or {})
        self._default_asset_class = default_asset_class

    # -- id -> asset_class ------------------------------------------------- #
    def asset_class_of(self, id: str) -> str:
        """Return the asset-class tag for an id (default when untagged)."""
        return self._asset_class.get(id, self._default_asset_class)

    def tag(self, id: str, asset_class: str) -> None:
        """Register/override an id's asset class (e.g. tag a benchmark)."""
        self._asset_class[id] = asset_class

    # -- (form, asset_class) -> submodule ---------------------------------- #
    def register(self, form: str, asset_class: str, submodule: Any) -> None:
        self._submodules[(form, asset_class)] = submodule

    def resolve(self, form: str, id: str):
        """Resolve a `(form, id)` to its submodule (via the id's asset class)."""
        ac = self.asset_class_of(id)
        try:
            return self._submodules[(form, ac)]
        except KeyError as exc:
            raise KeyError(
                f"no submodule registered for form={form!r} asset_class={ac!r} "
                f"(id={id!r})"
            ) from exc

    def group_by_submodule(self, form: str, ids):
        """Group ids by their resolved submodule, preserving order within groups.

        Returns a list of ``(submodule, [ids...])`` pairs so the provider can issue
        one batched call per submodule instead of one call per id.
        """
        order = []
        buckets: Dict[int, Any] = {}
        members: Dict[int, list] = {}
        for id in ids:
            sub = self.resolve(form, id)
            key = id_(sub)
            if key not in buckets:
                buckets[key] = sub
                members[key] = []
                order.append(key)
            members[key].append(id)
        return [(buckets[k], members[k]) for k in order]


def id_(obj: Any) -> int:
    """Identity key (kept as a function so it is easy to stub in tests)."""
    return id(obj)
