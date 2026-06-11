# docs/ — process artifacts for agent workflows

Shared memory between the main session (orchestrator) and subagents. Files here
survive context compaction; conversation does not. Pick the **lightest artifact
that survives the handoff** — a bounded task needs only a delegation prompt,
no file at all.

```
docs/
├── work/<YYYY-MM-DD-slug>/   one folder per effort, three layers inside
│   ├── prd.md                STRATEGY  — what & why; stable
│   ├── plan.md               TACTICS   — how; adjustable as work reveals reality
│   └── log.md                OPERATIONS — append-only shared board for agents
├── adr/                      decisions that outlive any effort
└── product/                  as-built docs — current truth about the product
```

## The three layers

### prd.md — strategy
Output of idea discussion/grilling (`/grill-me`, `/to-prd`). Intent, success
criteria, scope boundaries, constraints. Status: `Draft` → `Accepted` → `Done`.
Once `Accepted`, edited **only** for scope-level changes, each noted in its
changelog. Small efforts may skip it — then plan.md carries a 3-line intent.

### plan.md — tactics
Derived from the accepted prd.md. This is what looped agents are pointed at.
Contains:

```markdown
# Plan: <stream>
Status: Active | Done
Derived from: prd.md   Respects: adr/NNNN, …

## Parameters       ← premeditated inputs: analysis parameters, target paths,
                      iteration criteria, definition of done per task
## Tasks            ← checklist; one agent loop = read plan → do task →
                      report to log.md → tick task
## Change log       ← dated entries: discovery, what changed in the plan, impact
```

Multiple workstreams under one effort get multiple plans: `plan-dev.md`,
`plan-analysis.md`. Adjustment is expected — edit Tasks/Parameters in place,
record every adjustment in the Change log. The plan is the single source of
truth for *what to do next*; never silently diverge from it.

### log.md — operations (the shared platform)
Append-only. Never edited, only extended. Every agent writes here; every agent
reads the open FLAGs and recent entries before starting. Entry format:

```markdown
## 2026-06-10 14:30 · <agent/task ref> · REPORT|FINDING|FLAG
What was done / found. Refs: task 3, prd §2, adr/0001.
(FLAG only) → Resolved-by: <log entry or change-log ref, filled when closed>
```

- **REPORT** — mandatory when an agent finishes: what was done, where the
  output is, what state it left things in. This applies to analysis and
  exploration the same as development.
- **FINDING** — information of value to other agents, no action needed.
- **FLAG** — mismatch with plan/prd, or a discovered need for change. A FLAG
  is a message to the next agent and the orchestrator. Open FLAGs are triaged
  before new tasks are dispatched; resolution is recorded back on the FLAG.
- **HANDOFF** — written by the orchestrator when a session ends mid-effort:
  where work stopped, what was about to be dispatched, conclusions from triage
  not yet reflected in the plan, the recommended next action. A resuming
  session reads plan.md, open FLAGs, and the last HANDOFF — nothing else is
  needed to continue. (`/handoff` output goes here, not in a separate file.)

Output too large for log.md → separate file in the effort folder
(`<topic>.md`), linked from the REPORT; return only path + ≤5-line summary.

## Change protocol — flags travel up, never silently

A FLAG is resolved at the cheapest layer that contains it:

1. **Operations** — agent adapts within its task → REPORT notes it. No plan edit.
2. **Tactics** — plan must change (tasks, parameters, order) → edit plan.md
   + Change-log entry referencing the FLAG.
3. **Decision** — an accepted decision is invalidated → superseding ADR,
   then rule 2.
4. **Strategy** — prd.md scope is invalidated → prd changelog entry + edit,
   plans re-derived or amended per rule 2.

## Lifecycle of an effort

ideate/grill → prd.md (Draft→Accepted) → plan(s) derived → agents loop
(read plan + open FLAGs → work → REPORT → tick task) → FLAGs trigger the
change protocol → all tasks done → **debrief appended to log.md** (plan vs
change log vs reality, lessons) → product/ written or updated from executed
reality → ADR-worthy lessons promoted → effort folder frozen (`Done`).

Frozen folders are history — never retro-edited to match later reality.

## adr/ — decisions

One decision per file: context, decision, consequences, alternatives.
Naming: `NNNN-<slug>.md`. Never rewrite an accepted ADR; supersede it.
Written whenever a decision's consequences extend beyond the current effort.

## product/ — final version

As-built documentation — the only folder describing current reality rather
than history. First written at debrief from what was actually executed (not
copied from the plan), then updated whenever the product changes. Structure
mirrors the product, one file per component/process.

## Rules for agents

- Before starting: read plan.md, the open FLAGs in log.md, and any ADRs the
  plan lists.
- When done: append a REPORT to log.md, tick the task in plan.md. No silent
  completion.
- Mismatch or needed change discovered: append a FLAG — do not fix the plan
  yourself unless dispatched to.
- Decisions with consequences beyond the current effort → propose an ADR.
- Convert relative dates to absolute dates in all artifacts.
