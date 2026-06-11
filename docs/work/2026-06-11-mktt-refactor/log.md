# Log — MKTT refactor

Append-only. Agents: read the open FLAGs + recent entries before starting; append a REPORT when done.
Never edit prior entries — only extend.

## 2026-06-11 · orchestrator · HANDOFF
Effort opened. PRD `Accepted` (strategy over `refactor/TARGET_ARCHITECTURE.md`, the locked design);
`plan-dev.md` derived with 10 slices.

- **State:** design + DB done — `etc_db` schemas `MKCompStore` / `MKFund` / `MKLists` built (empty);
  no application code written yet.
- **Workflow:** just ported from `Agents_arch` into this repo on branch `chore/agents-workflow-port`.
  Application code happens in the worktree `../Trading963-mktt-refactor` (branch `refactor/mktt-impl`)
  — sync it with `git merge refactor/mktt-app` to get the spec before starting.
- **Open FLAGs:** none.
- **Next dispatch:** task 2 (Kernel) — pure, unblocked, de-risks the central design. Then 1 + 3
  (parallelizable), 4, 5.

### TDD planning gate — task 2 (Kernel) [resolved here, ready to dispatch]
- **Public interface:** spec §5.2 — `Indicators.compute(ts)`, `RelativeStrength.compute(ts, benchmark)`,
  `RelativeStrength.rank(panel, by)`, `StageClassification.compute(ts)`; enrichment pipeline
  (each `TimeSeries → TimeSeries(+cols)`); pandas `symbol×date` DataFrame at the seam, tensor internal.
- **Prioritized behaviors to test:** each primitive adds its columns; `rank()` is cross-sectional
  (needs >1 symbol); `stage` reuses prior `ma_*`/`rs_line` columns (no MA recompute); single-symbol
  path works (`rs_rank` null when 1 symbol); device auto-select with CPU fallback.
- **Definition of done:** signatures match §5.2; pure pytest green (no DB/net/Flask); behavior parity
  with `src/mktt/stage_classifier.py` on a sample; REPORT here + task 2 ticked.
