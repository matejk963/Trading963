# ADR 0001 — Kernel primitives vs Writer-fed classifiers; GPU deferred

Status: Accepted (2026-06-11)
Effort: docs/work/2026-06-11-mktt-refactor
Refines: refactor/TARGET_ARCHITECTURE.md §4.3, §4.5  ·  Resolves: FLAG-2, FLAG-3

## Context
The spec names the **kernel** as exactly three pure primitives (Indicators, RelativeStrength,
StageClassification) and states "the kernel is the ComputedStore's only writer" (§4.5). The live code
contradicts both:
- The `/screener` filters on `PCA_Regime`, `EPS_Accel`, `MA_Screen` — produced by a **separate
  PCA+KMeans + EPS pipeline** (`update_classifications.py:142`, `pca_stage_classifier.py`), NOT the
  Weinstein `stage` the kernel computes. `MKCompStore.classification_*` carries a `regime` column that
  no kernel member produces.
- There is **no torch/cuda in the repo** — the kernel's "GPU-tensorized" is greenfield, not a port,
  with no parity baseline.

## Decision
1. **Kernel stays the 3 pure shared primitives.** Indicators / RelativeStrength / StageClassification —
   each genuinely shared (≥2 consumers), pure, source-blind.
2. **PCA-regime, EPS-acceleration, MA-position-screen are "Writer-fed classifiers"** — separate compute
   units the **Writer** runs and upserts into `MKCompStore` *alongside* the kernel output. They are NOT
   kernel members (single consumer / distinct algorithm) but ARE legitimate producers of derived columns.
3. **Refine "only writer":** the **Writer** is the single writer of derived data; it runs *both* the
   kernel *and* the classifier units. ("Kernel is the only writer" → "the Writer is the only writer.")
4. **GPU deferred.** Build the **pure-pandas kernel now** (Slice 2a). A GPU/tensor backend (Slice 2b)
   is a later optimization behind the *same* interface, added only if profiling warrants it.

## Consequences
- The Writer (Slice 5) gains classifier sub-steps; `classification_current/history` carry
  `regime`/`eps_accel`/`ma_screen` populated by those units (port of `update_classifications.py` parts 2–4).
- The kernel stays pure and 3-member; GPU is off the critical path; no parity baseline is needed for GPU.
- The spec's §4.3 "GPU" and §4.5 "kernel is only writer" are read through this ADR.

## Alternatives rejected
- Fold KMeans regime into `StageClassification` — rejected (different algorithm + consumer; would
  recreate the multi-responsibility smell we are removing).
- Drop the PCA/EPS/MA signals — rejected (screener behavior-parity loss).
