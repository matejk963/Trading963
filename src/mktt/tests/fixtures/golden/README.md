# Golden fixtures — frozen MKTT behavior baseline

These JSON files are the **frozen parity baseline** for the MKTT kernel-centric
refactor (effort `docs/work/2026-06-11-mktt-refactor`, Slice 3). They capture
the outputs of the **current pre-refactor code** (`src/mktt/stage_classifier.py`,
`src/mktt/gex_engine.py`) on the **current local data** at capture time.

Every later refactor slice asserts behavior parity against these files via
`assert_parity(actual, golden, ...)` in `src/mktt/tests/parity.py`. The new
kernel / sections must reproduce these numbers within tolerance — that is the
definition of "behavior parity" in the plan's DoD.

## Files

| File | What it freezes | Produced by |
|---|---|---|
| `kernel_stage.json` | Latest-row kernel-equivalent columns (MAs, MA150 slope, `mansfield_rs`, `rs_rank`, stage) for the sample | `stage_classifier.compute_all_derived_vectorized` → `classify_all_stages` → `build_results(min_price=0)` |
| `gex_profile.json` | A full GEX profile (strikes, flip, walls, total, regime) on a fixed synthetic chain | `gex_engine.compute_profile` |
| `sample.json` | The deterministic symbol sample + as-of date (audit/reproducibility) | sample selector |

## The sample (deterministic)

`generate_golden.py` builds the sample as:

1. intersect `close.parquet` columns with the Refinitiv pkl `snapshot['Symbol']`,
2. keep symbols with > 200 non-null close rows (matches the kernel's own
   valid-ticker threshold),
3. sort, then take an even **stride** to land on ~40 symbols.

The exact requested and returned samples are recorded in each fixture's `meta`
and in `sample.json`. The kernel internally drops symbols lacking the full
high/low/volume intersection, so `n_symbols` returned (38) can be < requested
(40) — that dropping is itself part of the frozen current behavior.

As-of (last close bar) at capture: see `meta.asof` in the fixtures.

## GEX note (why synthetic, not live)

The slice brief asked for a small GEX profile "if option data is reachable".
Live yfinance option chains are **intraday-variable and rate-limited**, so a live
snapshot is a poor *frozen* baseline. We instead freeze the pure GEX math
(`compute_profile`) on a **fixed synthetic chain** embedded in
`gex_profile.json → meta.input_chains`. This deterministically pins the exact
thing the Options slice must preserve (gamma → per-contract GEX → aggregation →
flip/walls/regime). The same input chain, re-run through the refactored engine,
must reproduce `profile` within tolerance.

## Re-baselining

Do **not** regenerate casually — the point is a stable target. Regenerate only to
intentionally re-baseline (e.g. after a deliberate, agreed behavior change),
with:

```bash
cd src/mktt
python tests/generate_golden.py
```

This reads the current code/data and overwrites the fixtures. Commit the diff
with an explanation of why the baseline moved.

## Comparator

`src/mktt/tests/parity.py::assert_parity(actual, golden, rel_tol=1e-6, abs_tol=1e-9)`
— tolerant float compare (abs OR rel, via `math.isclose`); `None` and `NaN` are
interchangeable "missing"; dict keys and list lengths must match exactly.
Smoke + unit coverage in `test_parity.py`.
