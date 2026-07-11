---
description: Plan and build a large spec spanning multiple domains (full formal plan, parallel execution)
---

# Multi-Domain Plan Workflow

The largest planning level: a spec that creates or touches several domains,
with event chains crossing domain boundaries. The methodology is fully
specified in `docs/PARALLEL_DEVELOPMENT.md` — this workflow is its checklist.

**Everything is decided before any code exists**: every migration, model,
tool, plugin, route, event (with its payload model), and every chain with its
happy path and sad paths. Code-time conflicts are structurally impossible;
what remains is getting the plan right.

## Phase 0 — Foundation (serial, one author)

1. All **migrations** (`domains/*/migrations/*.sql`) with their **models**,
   sequential numbering, `-- depends:` for cross-domain ordering. Declare
   table ownership in the plan (`tables:`).
2. New **tools** only if the spec demands infrastructure that does not exist
   → follow [new-tool.md](new-tool.md), parity suite included.
3. Boot once (`uv run main.py`) → regenerated `AI_CONTEXT.md` is the ground
   truth every agent receives. Freeze phase 0.

## Phase 1 — The full plan (the contract)

Write the complete YAML plan of `docs/PARALLEL_DEVELOPMENT.md` ("Formal plan
format"): `phase_0`, `features` (one per plugin, with `publishes.model` /
`consumes.requires`), and `flows` with the sad-path checklist per link:

- `retries` / `backoff` — re-delivery policy
- `idempotent` — MANDATORY `true` where `retries > 0`
- `dlq_watcher` — who consumes `_dlq.<event>` (`null` = loss explicitly accepted)
- `atomic_with_db` — `true` means this chain cannot lose the event between DB
  commit and publish → it is the implementation trigger for the Transactional
  Outbox (ROADMAP Issue 28); flag it, do not improvise one
- `compensation` — the event that undoes upstream work if the chain dies (saga)

Then validate the 8 validity rules mechanically (same doc). An invalid plan is
a task-allocation error — fix the plan, never patch it in code.

## Phase 2 — Execution (parallel)

Dispatch one agent per feature; each receives the full plan + `AI_CONTEXT.md`
and produces exactly two files: its plugin and its unit test. Event payload
schemas go inline in each publisher plugin (`XxxPayload(...).model_dump()`).
Never assign two agents to the same feature.

## Phase 3 — Integration boot (the safety net)

```bash
// turbo
uv run main.py
```

1. `GET /system/lint` → zero warnings (arch, drift, event contracts) and no
   `UNTYPED_PAYLOAD` for the plan's events.
2. `GET /system/events/schemas` → every planned event appears with its model.
3. Full suite: `uv run -m pytest` — includes one chain e2e per flow
   (`tests/helpers/trace_chains.py`: `assert_chain(build_tree(...), [...])`).
4. Regenerated `AI_CONTEXT.md` == plan. **The spec is done when they match.**
