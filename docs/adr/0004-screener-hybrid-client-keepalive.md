# ADR 0004 — Screener: hybrid server-render + client keep-alive & embedded-data interactivity

Status: Accepted (2026-06-16)
Effort: docs/work/2026-06-16-screener-optimization
Refines: docs/adr/0002 §2 ("tables server-rendered via Jinja")
Source: recon (2 explorers) + grill; user chose the "hybrid" option.

## Context
adr/0002 made the screener a server-rendered Jinja table. Every visit re-runs the full pipeline and
re-renders ~100k DOM nodes, so navigating back to the screener always reloads and waits; the column
picker renders all columns then CSS-hides them. The user wants instant revisit, only-selected columns,
and smoothness, with zero data-integrity loss.

## Decision
1. **Keep server-render for the FIRST load** — first paint is still Jinja-rendered (no blank-screen
   client boot), but the table emits **only the selected columns**.
2. **Embed the full result once as compact JSON** alongside the table. The client uses it for instant
   **column toggle** and **sort** (re-render columns/rows from data, not from a server round-trip) — the
   DOM stays lean (only selected columns materialized).
3. **Client keep-alive**: returning to the screener restores the prior state instantly from a client
   snapshot instead of re-running the pipeline, **guarded by a freshness token** (`/api/screener/version`).
   If the token moved (data changed), it falls back to a normal server render.
4. **Server caches the pipeline result + render**, keyed on `(request, cross_section_version,
   parquet_mtime)`, invalidated on Writer `upsert` / parquet change — a cached response is **never staler
   than the data**.

## Consequences
- adr/0002 §2 now reads: **first render server-side; subsequent column-toggle / sort / revisit are
  client-side from embedded data + a freshness-guarded snapshot.** The numbers are still produced
  server-side (one source of truth); the client only re-arranges/re-shows them.
- Data integrity is structurally protected by version/mtime cache keys + the client's token check —
  a stale view cannot be shown.
- The screener gains a small client state layer (snapshot, restore, token check) — scoped to the
  screener only, not an app-wide SPA.

## Alternatives rejected
- **Full client-render from JSON** (rebuild the whole table client-side, virtualized) — best smoothness
  but a real rewrite + blank-on-boot; deferred (named OUT in the PRD).
- **Server-only heavy caching** (faster reload, no client layer) — back is still a reload/flash and
  column-toggle still round-trips; doesn't meet "no wait on back".
