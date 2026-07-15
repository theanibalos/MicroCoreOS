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

## Phase 1 — The full plan (the contract, authored FIRST)

Write the complete YAML plan of `docs/PARALLEL_DEVELOPMENT.md` ("Formal plan
format") to `plans/active_plan.yaml`: `phase_0` (every migration with its
`tables:` ownership AND its full `columns:` — phase 0 is built from the plan,
nothing is improvised later), `features` (one per plugin, with
`publishes.model` / `consumes.requires` / the `db:` persistence contract),
and `flows` — each with
its `durability` (may in-flight events die with the process? `durable` needs
the sqlite/redis driver) and the sad-path checklist per link:

- `retries` / `backoff` — re-delivery policy
- `idempotent` — MANDATORY `true` where `retries > 0` OR the flow is `durable`
  (durable transports re-deliver after a crash even with zero retries)
- `idempotency_test` — the double-delivery proof for every idempotent link
- `dlq_watcher` — who consumes `_dlq.<event>` (`null` = loss explicitly
  accepted; a non-null watcher must exist in the plan or live)
- `atomic_with_db` — `true` means this chain cannot lose the event between DB
  commit and publish → it is the implementation trigger for the Transactional
  Outbox (ROADMAP Issue 28); flag it, do not improvise one
- `compensation` — the event that undoes upstream work if the chain dies
  (saga); it must be published AND consumed within the plan
- `sad_path_test` (flow-level) — mandatory when any link declares retries,
  a DLQ watcher or a compensation
- `rpc_links` (flow-level) — every `request()` call, with `timeout` and
  `on_timeout`

Then run the 14 validity rules mechanically: `POST /system/plan/validate`
with the plan (YAML or JSON) against the live system — zero `errors` before
building anything. An invalid plan is a task-allocation error — fix the plan,
never patch it in code.

## Phase 0 — Foundation (built FROM the plan; serial, one author)

1. New **tools** only if the spec demands infrastructure that does not exist
   → follow [new-tool.md](new-tool.md), parity suite included.
2. All **migrations** (`domains/*/migrations/*.sql`) with their **models**,
   written 1:1 from the plan's `columns:`, sequential numbering, `-- depends:`
   for cross-domain ordering.

(1 and 2 are independent at write time — disjoint files; two agents in any
order or in parallel is fine. Migrations keep one author for numbering.)

3. Boot once (`uv run main.py`), only after everything is written →
   regenerated `AI_CONTEXT.md` is the ground truth every agent receives
   (it must include the new tools' interfaces). Freeze phase 0.

## Phase 2 — Execution (parallel)

Dispatch one agent per feature with the **canonical executor prompt**
(`docs/PARALLEL_DEVELOPMENT.md` § Phase 2): a byte-identical shared prefix —
`AI_CONTEXT.md` → full plan → shared rules — plus one final per-agent line
naming its feature. Agents never open the plan or `AI_CONTEXT.md` themselves;
the identical prefix lets any prefix-caching engine process the shared block
once for the whole wave. Each agent produces exactly two files: its plugin
and its unit test. Event payload schemas go inline in each publisher plugin
(`XxxPayload(...).model_dump()`). Never assign two agents to the same feature.

## Phase 3 — Integration boot (the safety net)

```bash
// turbo
uv run main.py
```

1. `GET /system/lint` → zero warnings (arch, drift, event contracts) and no
   `UNTYPED_PAYLOAD` for the plan's events.
2. `GET /system/events/schemas` → every planned event appears with its model.
3. Full suite: `uv run -m pytest` — includes one chain e2e per flow
   (`tests/helpers/trace_chains.py`: `assert_chain(build_tree(...), [...])`),
   the sad-path tests (`_dlq.<event>` chains) and the double-delivery
   idempotency tests the plan declared.
4. Regenerated `AI_CONTEXT.md` == plan. **The spec is done when they match.**
