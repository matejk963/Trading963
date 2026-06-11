# Project workflow

This project uses a documented agent workflow. The full contract is in
`docs/README.md` — read it before creating or editing anything under `docs/`.

## Orchestrator duties (main session)

- All multi-agent work runs through an effort folder:
  `docs/work/<YYYY-MM-DD-slug>/` with `prd.md` (strategy), `plan*.md`
  (tactics), `log.md` (operations). No plans, reports, or findings outside it.
- Before dispatching any task: triage open FLAGs in the effort's `log.md`.
- Delegation prompts must point the subagent at the effort's `plan*.md` and
  the open FLAGs in `log.md`, and state which task it owns.
- Dev tasks are dispatched to the `developer` agent only after the plan
  settles, per task: the public interface, the prioritized behaviors to
  test, and a testable definition of done. These questions (the TDD
  planning gate) are resolved in the main session — with the user where
  judgment is needed — never delegated.
- Accept no silent completion: every finished subagent task must have a
  REPORT entry in `log.md` and a ticked task in the plan.
- Apply the change protocol from `docs/README.md` — changes land at the
  cheapest layer that contains them (log → plan → adr/ → prd).
- Session ending mid-effort: append a HANDOFF entry to the effort's `log.md`.
- At effort completion: debrief in `log.md`, update `docs/product/`, promote
  durable decisions to `docs/adr/`, then freeze the effort folder.

## Subagent duties

Subagents receive this file automatically. When working inside an effort:
read the plan and open FLAGs before starting; append a REPORT when done;
raise a FLAG for any mismatch instead of silently diverging; oversized
output goes in a sibling file in the effort folder, linked from the REPORT.

## Documentation boundaries

- `docs/work/` is history — frozen once an effort is Done, never retro-edited.
- `docs/product/` is current truth — updated whenever the product changes.
- `docs/adr/` is append-only — supersede, never rewrite.
