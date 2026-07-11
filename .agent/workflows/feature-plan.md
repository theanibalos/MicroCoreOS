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

One `features:` entry per plugin, plus a `flows:` entry if the feature
publishes or consumes events. Same schema as the formal plan format
(`docs/PARALLEL_DEVELOPMENT.md`), just without `phase_0`:

```yaml
plan:
  domain: orders            # existing domain
  features:
    - plugin: CancelOrderPlugin
      file: domains/orders/plugins/cancel_order_plugin.py
      function: "Cancel an order and announce it"
      route: { method: POST, path: /orders/{order_id}/cancel }
      publishes:
        - event: order.cancelled
          model: OrderCancelledPayload
          payload: { id: int, reason: str }
      consumes: []
      mocks: [db, event_bus]
      test: tests/test_cancel_order.py
  flows:
    - name: order-cancellation
      happy_path: "POST /orders/{id}/cancel → order.cancelled → RefundPlugin → order.refunded"
      e2e_test: tests/test_order_cancellation_chain.py
      links:
        - consumes: order.cancelled
          consumer: RefundPlugin
          retries: 3
          backoff: 1.0
          idempotent: true
          dlq_watcher: null
          atomic_with_db: false   # true → this feature is the trigger for Issue 28 (outbox)
          compensation: null
```

### 2. Validate before writing code

- The `route` and `file` collide with nothing in `AI_CONTEXT.md`.
- Every consumed event exists (live system or this plan) and provides the
  `requires` keys.
- Every flow link has the sad-path checklist answered
  (`idempotent: true` is mandatory where `retries > 0`).

### 3. Implement

One file per feature. Request, response AND event payload schemas inline.
Publish with `XxxPayload(...).model_dump()` — bare call, no arguments.

### 4. Test

- Unit test per plugin (mock every injected tool).
- One chain test per flow, using the helper:

```python
from tests.helpers.trace_chains import build_tree, assert_chain
# trigger the flow, then:
assert_chain(build_tree(bus.get_trace_history()), ["order.cancelled", "order.refunded"])
```

### 5. Close

```bash
// turbo
uv run main.py
```

- `GET /system/lint` → no warnings, no `UNTYPED_PAYLOAD` for your events.
- Regenerated `AI_CONTEXT.md` matches the plan (routes, events, keys).
  **The feature is done when AI_CONTEXT == plan.**
