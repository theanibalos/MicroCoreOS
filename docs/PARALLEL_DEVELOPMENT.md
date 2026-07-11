# Parallel Development — N Agents, Zero Collisions

> How N agents (or developers) build features simultaneously on MicroCoreOS
> without ever touching each other's code — and why this is a structural
> guarantee of the architecture, not a hope.

## The thesis

**In MicroCoreOS, every possible conflict is a plan-time error. Code-time
conflicts are structurally impossible.**

In a traditional framework, even a perfect plan produces merge conflicts,
because features share files by design (the service class, the router, the
models module). Here they cannot:

| Architectural property | What it eliminates |
|---|---|
| 1 file = 1 feature | Two agents never write the same file |
| No cross-feature / cross-domain imports | A change in one feature cannot ripple into another |
| Communication only via event bus | Features integrate through named contracts, not shared code |
| Fractal structure (every plugin has the same skeleton) | Agents need no context about each other's style or layout |
| Self-describing system (`AI_CONTEXT.md` regenerated on boot) | Agents share one source of truth instead of reading each other's code |

The remaining conflicts — two agents given the same route, the same table, the
same feature — are **task-allocation errors**: someone assigned the same work
twice. Assigning the same route to two features is the same mistake as sending
two people to do one job, or telling one agent to build a loop and another to
write an `if` inside it. Task decomposition must respect feature boundaries;
the plan is where that happens.

## The methodology

### Phase 0 — Foundation (serial, before any feature)

The schema and infrastructure are shared contracts, so they are written FIRST
and frozen:

1. **Migrations** (`domains/{domain}/migrations/*.sql`) together with their
   **models** (`domains/{domain}/models/`). One author (human or single agent),
   sequential numbering, `-- depends:` where ordering matters.
2. **Tools**, only if the plan requires new infrastructure. Tools are the one
   legitimate place for shared logic — if two features would need the same
   code, it is either duplicated (small) or promoted to a tool (infrastructure).
3. **Boot once** (`uv run main.py`). This regenerates `AI_CONTEXT.md` with the
   real tables, models and tool interfaces — the ground truth every agent will
   receive.

### Phase 1 — The Plan (the contract)

The plan is the namespace-reservation step. It allocates, per feature, every
name that lives in a global namespace, so nothing is left to improvisation:

- **migrations** (phase 0, listed for traceability, with the tables they own)
- **plugins** — one per feature: name, domain, file, function
- **tools** — only if new infrastructure is needed
- **events** — every published event **with its payload model and fields**, and who consumes it
- **routes** — method + path per endpoint
- **flows** — end-to-end chains with their happy path AND the sad-path
  decisions per link, so every failure mode is decided before any code exists
- **tests** — every feature ships with its unit test file, every flow with its
  e2e chain test; everything has tests

#### Formal plan format

```yaml
plan:
  domain: orders
  phase_0:
    migrations:
      - file: orders/001_create_orders.sql
        tables: [orders]                    # table ownership is declared here
    models:
      - domains/orders/models/order.py
    tools: []                               # new infra tools, only if needed

  features:
    - plugin: CreateOrderPlugin
      file: domains/orders/plugins/create_order_plugin.py
      function: "Create an order and announce it"
      route: { method: POST, path: /orders }
      publishes:
        - event: order.created
          model: OrderCreatedPayload        # Pydantic payload model, inline in the plugin
          payload: { id: int, user_id: int, total: float }
      consumes: []
      mocks: [db, event_bus]                # what its test mocks
      test: tests/test_create_order.py

    - plugin: OrderNotifierPlugin
      file: domains/orders/plugins/order_notifier_plugin.py
      function: "Notify the user when an order is created"
      route: null                           # pure consumer, no endpoint
      publishes:
        - event: order.notified
          model: OrderNotifiedPayload
          payload: { order_id: int, user_id: int }
      consumes:
        - event: order.created
          requires: [id, user_id]           # keys this consumer will read (tolerant reader)
      mocks: [event_bus, logger]
      test: tests/test_order_notifier.py

  flows:
    - name: order-lifecycle
      happy_path: "POST /orders → order.created → OrderNotifierPlugin → order.notified"
      e2e_test: tests/test_order_lifecycle_chain.py   # asserts the chain via /system/traces/tree
      links:                                # one entry per consumed event in the chain
        - consumes: order.created
          consumer: OrderNotifierPlugin
          retries: 3
          backoff: 1.0
          idempotent: true                  # MANDATORY true whenever retries > 0
          dlq_watcher: null                 # who observes _dlq.order.created (null = loss accepted)
          atomic_with_db: false             # commit+publish must be atomic? true → outbox (Issue 28)
          compensation: null                # compensating event if the chain rolls back (saga)
```

#### Sad paths are enumerable, not open-ended

In this architecture the failure modes of a chain are finite, because the bus
contract defines them. Each `links:` entry answers the full checklist **at
plan time**, before a line of code exists:

| Field | The question it answers | What forgets to answer it costs |
|---|---|---|
| `retries` / `backoff` | How many re-deliveries before giving up? | Transient failures become final |
| `idempotent` | Can the handler run twice safely? | Duplicates on every retry / reclaim |
| `dlq_watcher` | Who consumes `_dlq.<event>` after final failure? | Silent event loss (`null` makes the loss *explicit and accepted*) |
| `atomic_with_db` | Does losing the event between DB commit and publish break the business? | The case for the Transactional Outbox (Roadmap Issue 28) |
| `compensation` | If a downstream link fails for good, what event undoes the upstream work? | No saga path — partial state forever |

Two failure modes need no per-chain decision because the system already
handles them observably: a subscriber auto-unsubscribed after 5 consecutive
final failures publishes `system.subscriber.dropped` (alerting belongs to a
system-wide watcher, not to each plan), and expired TTLs simply drop delivery.

#### Plan validity rules (mechanically checkable before dispatch)

A plan is valid iff:

1. No two features share a `file`, a `route`, or a `plugin` name.
2. No two migrations declare the same table.
3. Every `consumes.event` has at least one `publishes.event` in the plan (or
   already exists in the live system — check `AI_CONTEXT.md` / `/system/events`).
4. Every key in `consumes.requires` exists in the corresponding publisher's
   `payload`.
5. Every feature has a `test`.
6. Every `publishes` entry names its payload `model` — the Pydantic class the
   publisher plugin defines inline (`GET /system/events/schemas` serves the
   resulting catalog).
7. Every flow lists ALL its consumed events as `links`, each with the sad-path
   checklist answered (`idempotent: true` is mandatory where `retries > 0`).
8. Every flow has an `e2e_test` that triggers the happy path and asserts the
   real causal chain against `/system/traces/tree`. The helper
   `tests/helpers/trace_chains.py` makes it a one-liner:
   `assert_chain(build_tree(bus.get_trace_history()), ["order.created", "order.notified"])`.

### Phase 2 — Execution (parallel, all at once)

The **orchestrator agent** receives two artifacts: the **full plan** and the
freshly regenerated **`AI_CONTEXT.md`**. It validates the plan (rules above)
and dispatches ALL features in a single wave — one agent per feature, each
producing exactly two files: its plugin and its test. No agent needs to see
another agent's output; the plan already told each one which events it may
publish (with exact payloads) and which it consumes.

Never assign two agents to the same feature — evolution of an existing feature
is one task for one agent, not two.

### Phase 3 — Integration boot (the safety net)

Boot the system with all features merged. The linters verify that reality
matches the rules — advisory by design (they warn, never block; a hard gate
belongs in CI via tests):

- **ArchitectureLinterPlugin** — domain isolation, no hardcoded tool imports,
  no documentation drift.
- **EventContractLinterPlugin** — every key a consumer requires is present in
  every statically known publish site (`GET /system/lint`).
- *(Roadmap: route-collision linter and table-ownership linter — see
  `ROADMAP.md` Issues 26–27 — complete the namespace coverage.)*

Then run the whole suite: every feature brought its tests, so the integration
proof is `uv run -m pytest`.

## Summary

```
Phase 0 (serial)     migrations + models + tools → boot → AI_CONTEXT.md
Phase 1 (contract)   plan = namespace reservation (validated mechanically)
Phase 2 (parallel)   orchestrator + N agents → 1 plugin + 1 test each
Phase 3 (verify)     boot linters + full test suite
```

Plan assigns → agents execute → linters verify. With those three layers,
"N agents without collisions" is not an aspiration — it is a property of the
system.
