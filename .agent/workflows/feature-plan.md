---
description: Plan and build one or more features (plugins) on an EXISTING domain
---

# Feature Plan Workflow

The smallest planning level: new plugins on a domain that already exists. No
migrations, no new tools — if you need either, escalate to
[new-domain.md](new-domain.md) or [multi-domain-plan.md](multi-domain-plan.md).

## Prerequisites

- Read `AI_CONTEXT.md` — the live inventory (tools, domains, events, routes).
- Check `GET /system/events/schemas` (or the "Events emitted" lines in
  `AI_CONTEXT.md`) for the payload contracts of any event you will consume.

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
      route: { method: POST, path: /orders/{order_id}/cancel }
      db: { writes: [orders], reads: [] }   # persistence contract — own-domain tables only
      publishes:
        - event: order.cancelled
          model: OrderCancelledPayload
          payload: { id: int, reason: str }
      consumes: []
      mocks: [db, event_bus]
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

`POST /system/plan/validate` with the plan (YAML or JSON) — it runs the 14
validity rules of `docs/PARALLEL_DEVELOPMENT.md` against this plan AND the
live system. Zero `errors` before any code; `warnings` are advisory. The main
things it catches at this level:

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
  Mock exactly the tools the plan's `mocks:` lists; run the rest as real
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
// turbo
uv run main.py
```

- `GET /system/lint` → no warnings, no `UNTYPED_PAYLOAD` for your events.
- Regenerated `AI_CONTEXT.md` matches the plan (routes, events, keys).
  **The feature is done when AI_CONTEXT == plan.**
