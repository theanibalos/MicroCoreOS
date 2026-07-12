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
- **persistence** — which tables each feature reads and writes (`db:`), so the
  black-box contract covers input, output AND storage
- **flows** — end-to-end chains with their happy path, the sad-path decisions
  per link, AND the flow's `durability` (may in-flight events die with the
  process?), so every failure mode and crash point is decided before any code
  exists
- **tests** — every feature ships with its unit test file, every flow with its
  e2e chain test, every idempotent link with its double-delivery test, every
  flow that declares failures with its sad-path test; everything has tests

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
      db: { writes: [orders], reads: [] }   # persistence contract — only tables this domain owns
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
      db: null                              # never touches the database
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
      durability: ephemeral                 # ephemeral | durable — may in-flight events die with the process?
      happy_path: "POST /orders → order.created → OrderNotifierPlugin → order.notified"
      e2e_test: tests/test_order_lifecycle_chain.py   # asserts the chain via /system/traces/tree
      sad_path_test: tests/test_order_lifecycle_dlq.py # mandatory here: a link declares retries
      links:                                # one entry per consumed event in the chain
        - consumes: order.created
          consumer: OrderNotifierPlugin
          retries: 3
          backoff: 1.0
          idempotent: true                  # MANDATORY true when retries > 0 OR the flow is durable
          idempotency_test: tests/test_order_notifier.py::test_on_order_created_delivered_twice
          dlq_watcher: null                 # who observes _dlq.order.created (null = loss accepted)
          atomic_with_db: false             # commit+publish must be atomic? true → outbox (Issue 28)
          compensation: null                # compensating event if the chain rolls back (saga)
      rpc_links: []                         # every request() call, each with timeout + on_timeout
```

#### Features are black boxes — the plan is their contract

An agent-written plugin is a black box: nobody reviews its internals, so the
plan must pin down everything observable from outside — the route it serves
(request in, response out), the events it publishes (exact payload fields),
the events it consumes (the keys it reads), and the tables it touches (`db:`).
The feature's unit test proves **that contract**, not the implementation:
mock every injected tool, drive the input, assert the output, the DB effects
on the declared tables, and the published payloads. A feature may only read or
write tables its own domain owns — data crosses domains as events, never as
shared tables.

#### Two failure planes

Every failure in a flow lives on one of two planes, and they are planned
differently:

- **Business failures are facts, not exceptions.** A declined payment or an
  out-of-stock item is caught *inside* the handler and published as an event
  (`payment.declined`), which the plan models like any other event — with a
  payload model, consumers, and its own flow if it triggers reactions. The
  feature's unit test covers these outcomes.
- **Infrastructure failures escape to the bus** — the handler raises, the
  process dies, the DB is down. The bus contract makes these enumerable:
  retries → DLQ → (optionally) compensation. The `links:` checklist below is
  where each one is decided, and the flow's `sad_path_test` is where the
  decision is proven.

If a "failure" is a business outcome, model it as an event; never plan
business logic through the DLQ.

#### The three crash points

"What if the process dies?" is not open-ended either. A link crosses exactly
three gaps where a crash has a distinct consequence, and each gap has one
field that decides it:

| Crash point | What happens without a decision | The field that decides it |
|---|---|---|
| Between DB commit and `publish()` | The event never existed — downstream never learns | `atomic_with_db: true` → Transactional Outbox (Issue 28) |
| Event in flight, process dies | `in_process` driver loses it silently on restart | flow `durability: durable` → requires a durable driver (`sqlite`, `redis_streams`) |
| Mid-handler crash | Durable transports re-deliver → the handler runs twice | `idempotent: true` + its `idempotency_test` |

Crash *tests* split cleanly between transport and flow: redelivery itself is
proven once, generically, by the transport's kill-and-reboot suite
(`tests/tools/test_sqlite_driver.py`) — no feature ever writes a kill test.
What each flow must prove is its side of the bargain: **idempotency**. The
`idempotency_test` delivers the same envelope twice to the consumer (same
mocks as its unit test, still milliseconds) and asserts the final state and
side effects are those of a single delivery.

#### Sad paths are enumerable, not open-ended

In this architecture the failure modes of a chain are finite, because the bus
contract defines them. Each `links:` entry answers the full checklist **at
plan time**, before a line of code exists:

| Field | The question it answers | What forgetting to answer it costs |
|---|---|---|
| `retries` / `backoff` | How many re-deliveries before giving up? | Transient failures become final |
| `idempotent` | Can the handler run twice safely? | Duplicates on every retry / redelivery |
| `idempotency_test` | Where is the double-delivery proof? | "Idempotent" stays a claim, and at-least-once delivery rests on it |
| `dlq_watcher` | Who consumes `_dlq.<event>` after final failure? | Silent event loss (`null` makes the loss *explicit and accepted*) |
| `atomic_with_db` | Does losing the event between DB commit and publish break the business? | The case for the Transactional Outbox (Roadmap Issue 28) |
| `compensation` | If a downstream link fails for good, what event undoes the upstream work? | No saga path — partial state forever |

At the flow level, `durability` answers the remaining crash point (may
in-flight events die with the process?), and `sad_path_test` proves the
declared behavior: it forces the consumer to fail (a mock that raises) and
asserts the decided outcome in the causal tree. No new helper is needed —
`_dlq.<event>` is published *inside* the failing delivery's context, so it
appears as a child of the event that failed, and the same `assert_chain`
works: `assert_chain(tree, ["order.created", "_dlq.order.created"])`.

**RPC is a different contract with one failure mode: timeout.** `request()`
calls do not ride the retry/DLQ machinery — the caller blocks for an answer.
Every one of them is declared in `rpc_links`, each answering what the caller
does when no answer comes:

```yaml
rpc_links:
  - request: user.validate
    caller: CreateOrderPlugin
    timeout: 5
    on_timeout: "respond 503 to the client, create nothing"
```

Two failure modes need no per-chain decision because the system already
handles them observably: a subscriber auto-unsubscribed after 5 consecutive
final failures publishes `system.subscriber.dropped` (alerting belongs to a
system-wide watcher, not to each plan), and expired TTLs simply drop delivery.

#### Plan validity rules (mechanically checked before dispatch)

A plan is valid iff:

1. No two features share a `file`, a `route`, or a `plugin` name — and none
   collides with a route or plugin already live in the system.
2. No two migrations declare the same table, and no migration declares a table
   another domain already owns.
3. Every `consumes.event` has at least one `publishes.event` in the plan (or
   already exists in the live system — check `AI_CONTEXT.md` / `/system/events`).
4. Every key in `consumes.requires` exists in the corresponding publisher's
   `payload`.
5. Every feature has a `test`.
6. Every `publishes` entry names its payload `model` — the Pydantic class the
   publisher plugin defines inline (`GET /system/events/schemas` serves the
   resulting catalog).
7. Every flow lists ALL its consumed events as `links`, each with the sad-path
   checklist answered, and ALL its `request()` calls as `rpc_links`, each with
   `timeout` and `on_timeout`.
8. Every flow has an `e2e_test` that triggers the happy path and asserts the
   real causal chain against `/system/traces/tree`. The helper
   `tests/helpers/trace_chains.py` makes it a one-liner:
   `assert_chain(build_tree(bus.get_trace_history()), ["order.created", "order.notified"])`.
9. `idempotent: true` is mandatory where `retries > 0` **or** the flow is
   `durable` (durable transports re-deliver after a crash even with zero
   retries), and every idempotent link names its `idempotency_test`.
10. A non-null `dlq_watcher` resolves to a consumer of `_dlq.<event>` — in the
    plan or already live. A watcher that nothing implements is a dead string.
11. A non-null `compensation` names an event that some feature in the plan
    publishes AND at least one feature consumes — a saga with no undoer is
    partial state with extra steps.
12. Every flow where any link declares `retries > 0`, a `dlq_watcher`, or a
    `compensation` has a `sad_path_test`.
13. A `durable` flow requires a durable transport at deployment
    (`EVENT_BUS_DRIVER=sqlite` or `redis_streams`) — advisory: the validator
    warns when the live driver is `in_process`.
14. Every table in a feature's `db:` contract is owned by that feature's own
    domain (declared in `phase_0` or already present in
    `domains/{domain}/migrations/`). Cross-domain table access is forbidden —
    data crosses domains as events.

These rules are executable, not aspirational: **`POST /system/plan/validate`**
takes the plan (YAML or JSON) and returns `errors` (the plan is invalid) and
`warnings` (advisory, e.g. rule 13). The orchestrator runs it before
dispatching any agent; an invalid plan is a task-allocation error — fix the
plan, never patch it in code.

### Phase 2 — Execution (parallel, all at once)

The **orchestrator agent** receives two artifacts: the **full plan** and the
freshly regenerated **`AI_CONTEXT.md`**. It validates the plan
(`POST /system/plan/validate` against the system booted in phase 0)
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
Phase 1 (contract)   plan = namespace + failure-mode reservation
                     (validated by POST /system/plan/validate)
Phase 2 (parallel)   orchestrator + N agents → 1 plugin + 1 test each
Phase 3 (verify)     boot linters + full test suite
```

Plan assigns → agents execute → linters verify. With those three layers,
"N agents without collisions" is not an aspiration — it is a property of the
system.
