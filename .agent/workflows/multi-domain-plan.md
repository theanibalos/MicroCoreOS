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

## Before you plan — read these two, in this order

1. **`plans/active_plan.yaml`** — the file you are about to overwrite. It ships
   as a worked example of all three feature shapes. It **is** the format, not a
   description of one, and it is the cheapest way to have it.
2. **`AI_CONTEXT.md`**, down to `## 🧩 Plugin Authoring Guide` — the tables,
   models, routes and events that already exist. Inherit their names exactly.

Then write to **`plans/active_plan.yaml`** — that exact path, overwriting it —
and run `microcoreos plan validate` until it reports zero errors. Errors carry
the YAML that fixes them: paste it.

**Write the file before you ask anything.** Checking in is fine — planning
often is a conversation — but never *instead of* writing: a plan that exists
only as prose in your reply is a plan the next phase cannot read, and the run
may not be interactive at all. So write the YAML, validate it, and then raise
whatever you wanted to raise; the operator answers against a real file instead
of a description. Where a detail is genuinely undecidable, take what the
existing vocabulary implies, put it in the YAML, and flag it in a comment.

`docs/PARALLEL_DEVELOPMENT.md` § Phase 1 holds the rules behind the format.
Read it when a validator error is unclear, not before — and never reach for
plugin source under `domains/`, `tools/` or `extras/` to infer the shape. A
planner that did produced a plan with every field renamed.

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

Then run the 18 validity rules mechanically: `microcoreos plan validate`
(offline; `POST /system/plan/validate` is the same rules against a running
system) — zero `errors` before building anything. An invalid plan is a task-allocation error — fix the plan,
never patch it in code.

## Phases 0, 2 and 3

Identical to any other plan — `docs/PARALLEL_DEVELOPMENT.md` owns them, and
restating them here is how this file once kept prescribing a boot command that
had stopped regenerating the manifest.

Two things are specific to multi-domain work and are the only reason this
section exists:

- **Migration ordering across domains.** One author for the numbering, and
  `-- depends: other_domain/001_file.sql` wherever a table in one domain must
  exist before another's. The db tool resolves the order and prints each file
  as it applies it.
- **Never assign two agents to the same feature**, and never let one agent
  touch two domains. The wave is safe precisely because the write sets are
  disjoint.
