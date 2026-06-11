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

from .forms import OptionChain
from .provider import DataSource
from .registry import Registry
from .submodules.equity import EquitySubmodule, US_EXCHANGES
from .submodules.fundamentals import FundamentalsSubmodule
from .submodules.options import OptionsSubmodule, OptionChainError
from .submodules.rrg_yf import EtfSubmodule, FuturesSubmodule

__all__ = [
    "DataSource",
    "Registry",
    "EquitySubmodule",
    "FundamentalsSubmodule",
    "OptionsSubmodule",
    "EtfSubmodule",
    "FuturesSubmodule",
    "OptionChain",
    "OptionChainError",
    "build_default_datasource",
    "rrg_asset_class_tags",
]

# Asset-class tags that are NOT the default. The bulk equity universe needs no
# per-symbol rows (it falls back to the default); only the benchmark is tagged
# distinctly (spec §3, FLAG-1 — benchmark is just another time_series id).
_BENCHMARK_IDS = {"SPY"}


def rrg_asset_class_tags() -> dict:
    """`id -> asset_class` rows for the RRG ETF/futures universe (FLAG-5).

    The ETF datasets (sectors + their benchmarks) tag `etf`; the futures contracts
    tag `futures`. Derived from the RRG section's private config so adding a sector
    /contract there flows through to routing without a second edit (spec §4.4 —
    "adding an asset type = a registry row"). Imported lazily to keep the DataSource
    package free of any section import at module load.
    """
    from sections.rrg.quadrant import ETF_DATASETS, FUTURES_GROUPS

    tags: dict = {}
    for cfg in ETF_DATASETS.values():
        tags[cfg["benchmark"]] = "etf"
        for ticker in cfg["sectors"]:
            tags[ticker] = "etf"
    for group_cfg in FUTURES_GROUPS.values():
        for ticker in group_cfg["contracts"]:
            tags[ticker] = "futures"
    return tags


def build_default_datasource(
    data_dir: Optional[Path] = None,
    screen=None,
    equity_query=None,
    fund_conn_factory=None,
    fund_schema: str = "MKFund",
    ticker_factory=None,
    etf_download=None,
    futures_download=None,
) -> DataSource:
    """Build the production DataSource: one equity submodule serving both the
    universe (`equity`) and the benchmark (`benchmark`) asset classes off local
    parquet, plus a `(fundamentals, *)` MKFund submodule, behind a `(form, id)`
    registry.

    `fund_conn_factory` is the DI seam for the fundamentals reader (a zero-arg
    psycopg2 connection factory). When omitted, fundamentals routing is left
    unregistered (price-only DataSource) so callers without DB access are unaffected.

    `ticker_factory` is the DI seam for the options submodule (`symbol -> ticker`).
    When omitted, the submodule imports `yfinance.Ticker` lazily on first live fetch.
    """
    equity = EquitySubmodule(data_dir=data_dir, screen=screen, equity_query=equity_query)

    submodules = {
        ("time_series", "equity"): equity,
        ("time_series", "benchmark"): equity,
        # RRG ETF/futures via yfinance (FLAG-5 — replaces the streamlit_app leak).
        ("time_series", "etf"): EtfSubmodule(download=etf_download),
        ("time_series", "futures"): FuturesSubmodule(download=futures_download),
        # Asset-class blind: every symbol's option chain comes from one source.
        ("option_chain", "*"): OptionsSubmodule(ticker_factory=ticker_factory),
    }
    if fund_conn_factory is not None:
        from .submodules.fundamentals import FundamentalsSubmodule
        submodules[("fundamentals", "*")] = FundamentalsSubmodule(
            conn_factory=fund_conn_factory, schema=fund_schema
        )

    asset_class = {sym: "benchmark" for sym in _BENCHMARK_IDS}
    # ETF/futures id -> asset_class rows (FLAG-5). Benchmark tag wins on collision
    # (e.g. SPY is the equity benchmark, not an RRG ETF leaf).
    for _id, _ac in rrg_asset_class_tags().items():
        asset_class.setdefault(_id, _ac)

    registry = Registry(
        asset_class=asset_class,
        submodules=submodules,
        default_asset_class="equity",
    )
    return DataSource(registry=registry, _equity=equity)
