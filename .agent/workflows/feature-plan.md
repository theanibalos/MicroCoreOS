---
description: Plan and build one or more features (plugins) on an EXISTING domain
---

# Feature Plan Workflow

The smallest planning level: new plugins on a domain that already exists. No
migrations, no new tools — if you need either, escalate to
[new-domain.md](new-domain.md) or [multi-domain-plan.md](multi-domain-plan.md).

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
plugin source under `domains/`, `tools/` or `extras/` to infer the shape:
reading an implementation to infer the format renames every field in your plan.

## Prerequisites

Both files above. For an event you will consume, its payload contract is the
"Events emitted" line of the publishing domain in `AI_CONTEXT.md` (or
`GET /system/events/schemas` on a running system).

## Steps

### 1. Write the mini-plan

Write it to `plans/active_plan.yaml`: one `features:` entry per plugin
(~10-15 lines each), plus a `flows:` entry ONLY if the feature publishes or
consumes events — omit `flows` entirely otherwise. Same schema as the formal
plan format (`docs/PARALLEL_DEVELOPMENT.md`), just without `phase_0`:

```yaml
plan:
  domain: orders            # existing domain
  features:
    - plugin: CancelOrderPlugin
      file: domains/orders/plugins/cancel_order_plugin.py
      function: "Cancel an order and announce it"
      route: { method: POST, path: "/orders/{order_id}/cancel" }  # quote paths with {params}
      db: { writes: [orders], reads: [] }   # persistence contract — own-domain tables only
      publishes:
        - event: order.cancelled
          model: OrderCancelledPayload
          payload: { id: int, reason: str }
      consumes: []
      tools: [http, db, event_bus, logger]   # every tool __init__ takes
      test: tests/test_cancel_order.py
  flows:
    - name: order-cancellation
      durability: ephemeral   # durable → in-flight events must survive a crash (needs sqlite/redis driver)
      happy_path: "POST /orders/{id}/cancel → order.cancelled → RefundPlugin → order.refunded"
      e2e_test: tests/test_order_cancellation_chain.py
      sad_path_test: tests/test_order_cancellation_dlq.py  # mandatory: a link declares retries
      links:
        - consumes: order.cancelled
          consumer: RefundPlugin
          retries: 3
          backoff: 1.0
          idempotent: true        # mandatory when retries > 0 OR the flow is durable
          idempotency_test: tests/test_refund.py::test_on_order_cancelled_delivered_twice
          dlq_watcher: null
          atomic_with_db: false   # true → this feature is the trigger for Issue 28 (outbox)
          compensation: null
      rpc_links: []               # every request() call, with timeout + on_timeout
```

### 2. Validate before writing code

`microcoreos plan validate` — it runs the 18 validity rules of
`docs/PARALLEL_DEVELOPMENT.md` against this plan AND what the repo already
occupies, with no server running. Zero `errors` before any code; `warnings` are
advisory. The main things it catches at this level:

- The `route` and `file` collide with nothing live.
- Every consumed event exists (live system or this plan) and provides the
  `requires` keys.
- Every flow link has the sad-path checklist answered (`idempotent: true` +
  `idempotency_test` where `retries > 0` or the flow is `durable`).
- `sad_path_test` present where the flow declares retries / DLQ / compensation.
- `db:` tables are owned by this domain.

### 3. Implement

One file per feature. Request, response AND event payload schemas inline.
Publish with `XxxPayload(...).model_dump()` — bare call, no arguments.

### 4. Test

- One test per plugin proving the black-box contract: input → output, DB
  effects on the declared tables, published payloads with the declared fields.
  Mock exactly the tools the plan's `tools:` lists; run the rest as real
  in-memory instances (`INSTRUCTIONS_FOR_AI.md` § Testing).
- One double-delivery test per idempotent link (same envelope twice → same
  final state), at the path declared in `idempotency_test`.
- One chain test per flow, using the helper:

```python
from tests.helpers.trace_chains import build_tree, assert_chain
# trigger the flow, then:
assert_chain(build_tree(bus.get_trace_history()), ["order.cancelled", "order.refunded"])
```

- One sad-path test per flow that declares retries / DLQ / compensation: force
  the consumer to fail (mock that raises) and assert the decided outcome —
  `_dlq.<event>` is causally chained to the event that failed, so the same
  helper works: `assert_chain(tree, ["order.cancelled", "_dlq.order.cancelled"])`.

### 5. Close

```bash
microcoreos migrate   # the boot that ends: applies migrations, regenerates AI_CONTEXT.md
```

- Regenerated `AI_CONTEXT.md` matches the plan (routes, events, keys).
  **The feature is done when AI_CONTEXT == plan.**

Then, for the lint only — the one boot this workflow sanctions (`AGENTS.md`
§ reading route). This boot **serves forever**: foreground, read, Ctrl-C.
Never background it; a process holding port 5000 makes the next
`microcoreos migrate` refuse to run.

```bash
microcoreos           # or: uv run main.py (identical) — Ctrl-C when done
```

- `GET /system/lint` → no warnings, no `UNTYPED_PAYLOAD` for your events.
