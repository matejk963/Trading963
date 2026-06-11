"""MKTT DataSource — raw external data behind a form-shaped interface (spec §4.4).

Public surface for this slice:
    DataSource              — the RAW provider facade (`time_series`).
    Registry                — the `(form, id)` resolver.
    EquitySubmodule         — local-parquet equity + benchmark reader.
    build_default_datasource() — wires the real registry against local parquet.
"""
from __future__ import annotations

from typing import Optional
from pathlib import Path

from .provider import DataSource
from .registry import Registry
from .submodules.equity import EquitySubmodule, US_EXCHANGES

__all__ = [
    "DataSource",
    "Registry",
    "EquitySubmodule",
    "build_default_datasource",
]

# Asset-class tags that are NOT the default. The bulk equity universe needs no
# per-symbol rows (it falls back to the default); only the benchmark is tagged
# distinctly (spec §3, FLAG-1 — benchmark is just another time_series id).
_BENCHMARK_IDS = {"SPY"}


def build_default_datasource(
    data_dir: Optional[Path] = None,
    screen=None,
    equity_query=None,
) -> DataSource:
    """Build the production DataSource: one equity submodule serving both the
    universe (`equity`) and the benchmark (`benchmark`) asset classes off local
    parquet, behind a `(form, id)` registry."""
    equity = EquitySubmodule(data_dir=data_dir, screen=screen, equity_query=equity_query)

    registry = Registry(
        asset_class={sym: "benchmark" for sym in _BENCHMARK_IDS},
        submodules={
            ("time_series", "equity"): equity,
            ("time_series", "benchmark"): equity,
        },
        default_asset_class="equity",
    )
    return DataSource(registry=registry, _equity=equity)
