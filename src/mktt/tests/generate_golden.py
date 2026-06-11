"""Generate frozen golden fixtures from the CURRENT MKTT code + current data.

This script READS the current `stage_classifier` / `gex_engine` modules and the
local parquet / Refinitiv data, snapshots their outputs for a deterministic
sample of symbols, and writes JSON fixtures into `tests/fixtures/golden/`.

It does NOT modify any production module — it only calls them. Re-run it only to
intentionally re-baseline (the fixtures it writes are the locked parity target
every later refactor slice asserts against).

Usage:
    python tests/generate_golden.py            # capture all reachable fixtures

Determinism of the sample:
    symbols = sorted(close.columns ∩ refinitiv 'Symbol'),
              filtered to >200 non-null close rows,
              then an even stride is taken to land on ~SAMPLE_N symbols.
    The exact sample is recorded in the fixture meta and in sample.json so the
    baseline is reproducible and auditable.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Put the mktt package dir on sys.path so bare imports resolve (mirrors conftest).
MKTT_DIR = Path(__file__).resolve().parent.parent
if str(MKTT_DIR) not in sys.path:
    sys.path.insert(0, str(MKTT_DIR))

import stage_classifier as sc  # noqa: E402  (current code under snapshot)

DATA_DIR = MKTT_DIR.parent.parent / "data" / "mktt"
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_N = 40            # target sample size (~30-50 per slice spec)
MIN_CLOSE_ROWS = 200     # match stage_classifier's valid-ticker threshold

# Kernel-equivalent columns this baseline freezes (from build_results / spec §5.2).
KERNEL_COLS = [
    "Symbol", "Stage", "StageLabel",
    "MA50", "MA150", "MA200", "MA150_Slope",
    "Mansfield_RS", "RS_Rank",
    "Price", "DistDays25",
]


def _jsonable(v):
    """Convert numpy / NaN scalars into JSON-serializable Python values."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return v


def select_sample() -> list:
    """Deterministic ~SAMPLE_N symbols present in BOTH parquet and Refinitiv pkl."""
    close = pd.read_parquet(DATA_DIR / "close.parquet")
    rf = pd.read_pickle(DATA_DIR / "refinitiv_fundamentals.pkl")
    rf_syms = set(rf["snapshot"]["Symbol"].dropna().astype(str))

    valid = close.notna().sum()
    eligible = sorted(
        s for s in close.columns
        if s in rf_syms and valid.get(s, 0) > MIN_CLOSE_ROWS
    )
    if not eligible:
        raise RuntimeError("no eligible symbols (parquet ∩ refinitiv) — cannot baseline")

    if len(eligible) <= SAMPLE_N:
        return eligible
    # Even stride across the sorted list -> stable, spread-out, deterministic.
    step = len(eligible) / SAMPLE_N
    idx = sorted({int(i * step) for i in range(SAMPLE_N)})
    return [eligible[i] for i in idx]


def capture_kernel(sample: list) -> dict:
    """Run the CURRENT vectorized kernel on the sample and freeze latest-row output."""
    close_df = pd.read_parquet(DATA_DIR / "close.parquet")[sample]
    high_df = pd.read_parquet(DATA_DIR / "high.parquet")
    low_df = pd.read_parquet(DATA_DIR / "low.parquet")
    volume_df = pd.read_parquet(DATA_DIR / "volume.parquet")
    spy_df = pd.read_parquet(DATA_DIR / "spy.parquet")
    spy_close = spy_df["Close"]

    high_df = high_df[[t for t in sample if t in high_df.columns]]
    low_df = low_df[[t for t in sample if t in low_df.columns]]
    volume_df = volume_df[[t for t in sample if t in volume_df.columns]]

    d, common = sc.compute_all_derived_vectorized(
        close_df, high_df, low_df, volume_df, spy_close
    )
    stages = sc.classify_all_stages(d)
    # min_price=0 so the baseline keeps every sampled symbol (parity, not display).
    results = sc.build_results(d, stages, min_price=0)

    rows = []
    if not results.empty:
        for col in KERNEL_COLS:
            if col not in results.columns:
                raise RuntimeError(f"expected column {col} absent from build_results")
        results = results.sort_values("Symbol")
        for _, r in results.iterrows():
            rows.append({col: _jsonable(r[col]) for col in KERNEL_COLS})

    last_date = str(close_df.index.max().date())
    return {
        "meta": {
            "source": "src/mktt/stage_classifier.py "
                      "(compute_all_derived_vectorized + classify_all_stages + build_results)",
            "asof": last_date,
            "min_price": 0,
            "min_close_rows": MIN_CLOSE_ROWS,
            "n_symbols": len(rows),
            "kernel_columns": KERNEL_COLS,
            "sample_requested": sample,
            "sample_returned": sorted(r["Symbol"] for r in rows),
        },
        "rows": rows,
    }


def capture_gex():
    """Best-effort GEX profile from a deterministic SYNTHETIC chain.

    The slice spec asks for a small GEX profile "if option data is reachable".
    Live yfinance option data is non-deterministic (changes intraday) and often
    rate-limited, so a live snapshot is a poor frozen baseline. Instead we freeze
    `gex_engine.compute_profile` on a fixed synthetic chain: this captures the
    pure GEX math (the thing the Options slice must preserve) deterministically.
    """
    try:
        import gex_engine as ge
    except Exception as e:  # pragma: no cover - import guard
        return None, f"gex_engine import failed: {e}"

    spot = 100.0
    chains = [
        {"expiration": "2026-06-19", "dte": 7,
         "calls": [{"strike": 95, "oi": 1200, "iv": 0.18},
                   {"strike": 100, "oi": 5000, "iv": 0.16},
                   {"strike": 105, "oi": 3000, "iv": 0.17},
                   {"strike": 110, "oi": 1500, "iv": 0.19}],
         "puts":  [{"strike": 90, "oi": 2200, "iv": 0.22},
                   {"strike": 95, "oi": 1800, "iv": 0.20},
                   {"strike": 100, "oi": 4000, "iv": 0.18}]},
        {"expiration": "2026-06-26", "dte": 14,
         "calls": [{"strike": 100, "oi": 2500, "iv": 0.17},
                   {"strike": 105, "oi": 2000, "iv": 0.18}],
         "puts":  [{"strike": 95, "oi": 1500, "iv": 0.21},
                   {"strike": 100, "oi": 2800, "iv": 0.19}]},
    ]
    profile = ge.compute_profile(chains, spot=spot, band_pct=0.15)
    fixture = {
        "meta": {
            "source": "src/mktt/gex_engine.py (compute_profile)",
            "basis": "deterministic synthetic chain (live option data is "
                     "intraday-variable; pure GEX math frozen instead)",
            "spot": spot,
            "band_pct": 0.15,
            "input_chains": chains,
        },
        "profile": profile,
    }
    return fixture, None


def main():
    print(f"Golden dir: {GOLDEN_DIR}")
    sample = select_sample()
    print(f"Sample: {len(sample)} symbols -> {sample}")

    kernel = capture_kernel(sample)
    (GOLDEN_DIR / "kernel_stage.json").write_text(json.dumps(kernel, indent=2))
    print(f"Wrote kernel_stage.json ({kernel['meta']['n_symbols']} rows)")

    (GOLDEN_DIR / "sample.json").write_text(json.dumps({
        "sample_requested": sample,
        "sample_returned": kernel["meta"]["sample_returned"],
        "asof": kernel["meta"]["asof"],
    }, indent=2))
    print("Wrote sample.json")

    gex, err = capture_gex()
    if gex is not None:
        (GOLDEN_DIR / "gex_profile.json").write_text(json.dumps(gex, indent=2))
        print("Wrote gex_profile.json")
    else:
        print(f"Skipped gex_profile.json: {err}")


if __name__ == "__main__":
    main()
