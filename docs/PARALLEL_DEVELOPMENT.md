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

> **Authoring order**: the plan (Phase 1) is written and validated FIRST;
> Phase 0 is then *built from it*, mechanically. Phases are numbered by build
> order — nothing is built before the plan exists.

### Phase 0 — Foundation (serial, before any feature)

The schema and infrastructure are shared contracts. They are fully **declared
in the plan** (`phase_0:` section, every table with its `columns`) and
**built first**, serially, by one author — then frozen:

1. **Tools**, only if the plan requires new infrastructure. Tools are the one
   legitimate place for shared logic — if two features would need the same
   code, it is either duplicated (small) or promoted to a tool
   (infrastructure). A NEW tool is written 1:1 from the plan's `contract:`
   (method signatures + return shape) the same way migrations are written from
   `columns:` — never inventing a method. The declaration is a handoff, not a
   second source of truth: once the phase 0 boot regenerates `AI_CONTEXT.md`,
   the tool's real interface is what the wave reads and the plan's `contract:`
   has done its job. A REPLACEMENT tool declares no `contract:` — the reference
   tool's header spec already is the contract (see
   `.agent/workflows/new-tool.md`, case B).
2. **Migrations** (`domains/{domain}/migrations/*.sql`) together with their
   **models** (`domains/{domain}/models/`), written 1:1 from the plan's
   `columns:` — never inventing a field. One author for the migrations
   (sequential numbering), `-- depends:` where ordering matters.

Tasks 1 and 2 are independent at write time — disjoint files, neither reads
the other (plugins compose tools; migrations don't) — so they can be two
agents, in any order or in parallel. The one hard ordering rule is the boot:

3. **Boot once** (`uv run main.py`, or `microcoreos` if you installed the
   package), only after EVERYTHING above is written.
   This regenerates `AI_CONTEXT.md` with the real tables, models and tool
   interfaces — the ground truth every wave agent receives (a tool missing at
   boot means a tool missing from every executor's prefix). Only then do
   features begin.

### Phase 1 — The Plan (the contract — authored before anything is built)

The plan is the namespace-reservation step. It allocates, per feature, every
name that lives in a global namespace, so nothing is left to improvisation:

- **migrations** (phase 0, with the tables they own AND every column with its
  SQL type — the phase 0 author writes the `.sql` files from the plan alone,
  never inventing a schema)
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

**One YAML rule, and it bites every real plan:** inside a flow-style mapping
(`{ ... }`), any value containing `{` or `[` must be quoted — `path:
"/orders/{order_id}"`, `note: "Optional[str]"`. Unquoted, the brace opens a
nested mapping and the whole document fails to parse. Every REST plan has
`{param}` routes, so this is the rule, not the exception.

```yaml
plan:
  domain: orders
  engine: sqlite                            # REQUIRED when phase_0 declares migrations, OMIT otherwise — its only
                                            # reader is the phase 0 author, who writes engine-specific SQL from it
                                            # (migrations run verbatim, see AGENTS.md rule 8)
  phase_0:
    migrations:
      - file: orders/001_create_orders.sql
        tables: [orders]                    # table ownership is declared here
        columns:                            # FULL schema — phase 0 is written from this, nothing is improvised
          orders:
            id: "INTEGER PRIMARY KEY"       # auto-increment PK spelling is engine-specific — match the declared engine
            user_id: "INT NOT NULL"
            total: "FLOAT NOT NULL"
            status: "TEXT DEFAULT 'pending'"
            created_at: "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    models:
      - domains/orders/models/order.py      # entity mirrors the columns above 1:1
    tools:                                  # new infra tools, only if needed (usually [])
      - name: payments                      # the DI injection key — the contract name
        file: tools/payments/payments_tool.py
        contract:                           # signatures + return shape ONLY — the phase 0 author
                                            # writes the tool from this, never inventing a method
                                            # (same rule as columns: for migrations)
          - "await pay(user_id: int, amount: float, note: str) -> {success, charge_id}"
          - "await refund(charge_id: str, order_id: int, note: str) -> {success}"
        infra_errors: true                  # external backend -> connection-error class inherits ToolUnavailableError

  language:                                 # OMIT unless the plan touches the domain's vocabulary
    - model: OrderEntity                    # the ubiquitous language, NOT a mirror of the table
      domain: orders
      op: new                               # new | add_field | rename_field | remove_field
      table: orders                         # the table that backs it
      fields: { id: "int?", user_id: int, total: float, status: str }
      internal: [payment_token]             # columns deliberately NOT in the language

  features:
    - plugin: CreateOrderPlugin
      file: domains/orders/plugins/create_order_plugin.py
      function: "Create an order and announce it"
      route: { method: POST, path: /orders }   # a path with {params} MUST be quoted: "/orders/{order_id}"
      db: { writes: [orders], reads: [] }   # persistence contract — only tables this domain owns
      publishes:
        - event: order.created
          model: OrderCreatedPayload        # Pydantic payload model, inline in the plugin
          payload: { id: int, user_id: int, total: float, note: "Optional[str]" }
      consumes: []
      tools: [http, db, event_bus, logger]  # EVERY tool THIS __init__ takes, in
                                            # order. Not a fixed list: the pure
                                            # consumer below names neither http
                                            # nor logger
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
      tools: [event_bus, logger]
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

#### Plan sizing — the plan must be proportional to the request

The schema above is the *maximum*, not the norm. Every section that would be
empty is **omitted**, never filled with nulls:

- **No new tables?** Omit `phase_0` entirely (that is the mini-plan of
  `.agent/workflows/feature-plan.md`).
- **No events published or consumed?** Omit `flows` entirely. A pure CRUD
  endpoint is one `features:` entry of ~10 lines — route, `db:` contract,
  `tools`, `test` — and nothing else.
- **One event chain?** That is ONE flow with its links — e.g. "deleting a user
  deletes everything they own" is `DELETE /users/{id} → user.deleted →
  cleanup consumers`, a single flow even if three domains consume it.
- **`rpc_links`, `dlq_watcher`, `compensation`** only appear when the plan
  actually uses `request()`, watches a DLQ, or runs a saga. Absent fields
  already have correct defaults.

Calibration reference: **a domain with 3 CRUD plugins and one event chain is a
plan of roughly 80–120 lines of YAML, written in one pass.** If a plan is an
order of magnitude larger than its request, the planning is wrong, not the
request.

The planner's reading set is fixed and small: `AI_CONTEXT.md` (live inventory)
plus this document. The plan pins down everything observable from outside, so
the planner **never reads `domains/`, `tools/` or `tests/` source** — if a
fact seems to require reading code, it belongs in `AI_CONTEXT.md` or
`GET /system/events/schemas`, not in the plan.

#### Features are black boxes — the plan is their contract

An agent-written plugin is a black box: what decides whether it stands is its
contract and its test, not a reading of its internals. A feature that fails
the contract is deleted and rebuilt by a fresh executor (Phase 3 —
Reconstruct), which is why nobody has to read it: repairing someone else's
generated code line by line costs more than regenerating it, and the agent
that got it wrong the first time is not the one you ask to fix it. So the
plan must pin down everything observable from outside — the route it serves
(request in, response out), the events it publishes (exact payload fields),
the events it consumes (the keys it reads), and the tables it touches (`db:`).
The feature's test proves **that contract**, not the implementation: drive
the input, assert the output, the DB effects on the declared tables, and the
published payloads. The plan's `tools:` field decides the level per feature:
tools listed there are mocked (`AsyncMock`/`MagicMock`); tools NOT listed run
as real in-memory instances (`db` as SQLite `:memory:` with the domain's
migrations applied, `event_bus` in-process) — the black-box style of
`INSTRUCTIONS_FOR_AI.md` § Testing. Assert real effects wherever a real tool
runs; assert mock calls only for what the plan mocked. A feature may only read or
write tables its own domain owns — data crosses domains as events, never as
shared tables.

**"Nobody has to read it" is not "nobody may read it."** Two things get read
as a matter of course, and neither is a violation: reconstruction that keeps
producing the same failure means the contract is wrong rather than the code,
and diagnosing that means opening the file; and an engine swap runs a pass
over every plugin query by hand (`ELASTIC_DEPLOYMENT.md` § Stage 1, step 3 —
*"Reading is required"*). What holds during the wave is narrower and is about
isolation, not permission: an executor never sees another feature's source,
because a fresh context per executor is what keeps the shared prefix
byte-stable and stops one agent's implementation from anchoring the next
(`plans/README.md` § Step 4).

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
(`tests/tools/sqlite/test_sqlite_driver.py`) — no feature ever writes a kill test.
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
   another domain already owns. Advisory: every declared table should list its
   `columns` — the validator warns when one doesn't, because phase 0 cannot be
   written from such a plan without improvising a schema.
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
15. Advisory: every task path the plan declares (feature `file:` + `test:`,
    flow `e2e_test`/`sad_path_test`, phase 0 migrations/models/tools) appears
    in the execution checklist (`plans/active_plan.md`). A task missing from
    the checklist is never dispatched and never noticed — the checklist
    reaches all-`[x]` with the feature silently absent. Matching is by path
    or basename (no coupling to the checklist's format), and the whole check
    skips itself when the on-disk checklist shares zero paths with the plan
    being validated (it belongs to a different plan, e.g. a draft).

16. **The `language:` section holds up** (ROADMAP Issue 38). The entity model
    is the domain's ubiquitous language, not a mirror of the table, so the two
    are allowed to differ in TYPE (`roles` is `TEXT` on disk and `list[str]` in
    the domain) and a column may be absent from the language entirely
    (`password_hash` never leaves the system — that is what `internal:`
    records). They may NOT differ in NAME: every declared field must resolve to
    a real column, in this plan's `phase_0.migrations.columns` or in the live
    schema. A vocabulary field with nothing behind it is an error, not a style
    issue. And `rename_field` / `remove_field` without `breaking: true` is an
    error — they are breaking changes to a public API, and `affects:` writes
    the blast radius down. When neither the plan nor the live system knows the
    table, the rule warns that it cannot check rather than inventing an error.

Above the 18 rules sits **rule 0, the shape of the document itself**. The
schema ignores keys it does not know, and a typo lands in exactly that bucket:
`feature:` instead of `features:` yields a plan that declares nothing and
therefore satisfies every rule below. Rule 0 warns on any unknown key (with its
path, e.g. `plan.flows[0].links[0]`) and on any plan with neither features,
migrations nor language. Warnings rather than errors, because the validator
cannot tell a typo from a key deliberately added by a tool upstream — but
neither passes unseen.

These rules are executable, not aspirational: **`microcoreos plan validate`**
runs them offline and returns `errors` (the plan is invalid) and `warnings`
(advisory, e.g. rule 13); where a rule knows the shape that fixes it, the
error carries that YAML. The orchestrator runs it before dispatching any agent;
an invalid plan is a task-allocation error — fix the plan, never patch it in
code.

There is no server-side form and nothing to boot first. The one thing a disk
scan cannot see is **live subscribers** — a `dlq_watcher` or a compensation
consumer that exists only at runtime — and `plan validate` says so in its own
output rather than sending you somewhere else for it.

### Phase 2 — Execution (parallel, all at once)

The **orchestrator agent** receives two artifacts: the **full plan** and the
freshly regenerated **`AI_CONTEXT.md`**. It validates the plan
(`microcoreos plan validate`)
and dispatches ALL features in a single wave — one agent per feature, each
producing exactly two files: its plugin and its test.

**Canonical executor prompt — shared prefix first, task last.** Every agent
receives the same byte-identical preamble, in this exact order:

1. `AI_CONTEXT.md` (frozen since the phase 0 boot — it embeds the executor
   rules and templates as its "Plugin Authoring Guide" section)
2. The full plan (`plans/active_plan.yaml`)

and ONE per-agent line at the very end: *"Implement feature `<PluginName>`
from the plan above."* Two artifacts plus one line — nothing else. Agents never open the plan or `AI_CONTEXT.md`
themselves. Because the preamble is byte-identical, any engine with prefix
caching — a local model's KV cache, Anthropic/OpenAI prompt caching, vLLM —
processes the shared block **once** and reuses it for every agent in the
wave. Never insert per-agent content before or inside the shared block: a
single differing byte breaks the reuse for everything after it. On an engine
with no prefix caching, fall back to pasting only the feature's slice plus
the `AI_CONTEXT.md` sections for the tools it injects.

**Dispatch order is a hard rule, not a suggestion — first alone, then the
rest.** A cache entry being written is not yet readable, so N simultaneous
cold requests ALL pay the full prefix; the whole saving requires the first
agent to start responding before any sibling is sent. This is easy to break
without noticing when the dispatch mechanism is a tool that accepts several
calls in one turn (e.g. issuing N parallel subagent invocations in a single
message): sending all N together from the start is exactly the simultaneous-cold
case, regardless of how identical the prefix is. Dispatch the first agent
alone, wait for it to begin responding, THEN dispatch the remaining N-1 —
together is fine at that point, even in one message. This rule is about the
*order* of dispatch; it does not require observing or measuring the cache in
real time to follow it correctly. If you do want to confirm cache-hits
happened, most agent harnesses don't expose `cache_control`/`usage` per
request directly, but each agent's own transcript (wherever the harness logs
it) carries the real `cache_creation_input_tokens`/`cache_read_input_tokens`
per turn and can be read after the fact — that's a verification step, not a
prerequisite for dispatching correctly.

**Executors are dispatched write-only, scoped to their two files.** "Agents
never open the plan or `AI_CONTEXT.md` themselves" is a property of the
dispatch, not an instruction to obey: an executor receives file-writing
capability ONLY — no read, no search, no shell — and the write capability is
scoped to exactly the two paths its plan entry declares (`file:` + `test:`
for a feature; `e2e_test` + `sad_path_test` for flow tests). The plan is a
namespace reservation, so the dispatch can enforce it mechanically: "no
migrations, no edits to `main.py`, no touching other tasks' files" stops
being a rule and becomes a property. A model with information-seeking tools
available will use them under any residual uncertainty, and will guess paths
when the file it seeks does not exist; removing the capability removes the
whole failure class, the same way disjoint file ownership removes collisions.

**One complete template per deliverable type.** Write-only dispatch is only
safe because the prefix is self-sufficient by construction: for every
deliverable type the plan can assign (publisher feature, subscriber feature,
flow tests), `AI_CONTEXT.md` § "Plugin Authoring Guide" carries one complete,
copy-pasteable template — whole file, imports to last line (embedded at boot
by the context tool from `tools/context/authoring_guide.md`, its single
source). A rule that names a symbol
without a template showing its exact usage manufactures uncertainty a
write-only agent can no longer resolve by reading. Litmus test for the
prefix: a competent developer with NO repository access must be able to
write both files from it alone.

"Parallel" here means **logical independence** (zero coordination, any order
works), not simultaneity. Token cost is identical sequential or simultaneous
(with a warm cache); simultaneity only buys wall-clock time, and only on
hosted APIs. On a local single-GPU engine, run the wave **sequentially on one
slot** — llama.cpp/Ollama KV caches are per-slot, so parallel slots do NOT
share the prefix, while consecutive requests on one slot reuse it fully (and
the GPU was the bottleneck anyway).

No agent needs to see another agent's output; the plan already told each one
which events it may publish (with exact payloads) and which it consumes.

Flow-level tests are wave tasks too: dispatch **one extra executor per flow**
with the same canonical prefix and the final line *"Implement the flow tests
for flow `<name>` from the plan above"* — its two files are the flow's
`e2e_test` and `sad_path_test`, which collide with no feature's files.
(The `idempotency_test` is NOT a separate task: it lives inside the consumer
feature's test file, written by that feature's executor.)

Within one executor, the test is written BEFORE the plugin, with every
assertion derived from the plan — never from the implementation
(`AI_CONTEXT.md` § Plugin Authoring Guide). For critical features, escalate to **independent
derivation**: split the feature into two executors — one writes only the test
(from the plan), the other only the plugin (from the plan) — their files never
collide because the plan declares both paths, and `pytest` arbitrates. If both
agents misread the plan the same way it won't catch it, but it catches every
divergent misreading at the cost of one extra dispatch (~a cache read).

Never assign two agents to the same feature — evolution of an existing feature
is one task for one agent, not two.

**Never boot the system mid-wave.** `AI_CONTEXT.md` and the plan are frozen
for the entire wave: the plan creates no tools or tables after phase 0, so
there is nothing to regenerate. The next boot is the phase 3 integration boot,
after every agent has finished. (This also keeps every agent's prompt prefix
byte-stable — maximum cache reuse across the wave.)

### Phase 3 — Integration boot (the safety net)

Boot the system with all features merged. The linters verify that reality
matches the rules — advisory by design (they warn, never block; a hard gate
belongs in CI via tests):

- **Architecture linters** (devtools, one rule per plugin) — domain isolation
  and no hardcoded tool imports, tool documentation drift, table ownership,
  route collisions, and field-constraint divergence between sibling plugins.
- **EventContractLinterPlugin** — every key a consumer requires is present in
  every statically known publish site.
- All of them report to `GET /system/lint`.

Then run the whole suite: every feature brought its tests, so the integration
proof is `uv run -m pytest`.

**Who tests the tests?** A complacent unit test (one that mirrors its own
plugin's bug) is not alone: the event-contract linter cross-checks publisher
payloads against consumer requirements statically, the flow's e2e/sad-path
tests were written by a DIFFERENT agent against the plan, and the final gate
compares the booted reality against the contract (`AI_CONTEXT.md` == plan).
A wrong plugin ships only if all four layers miss it. For measured rigor on
critical domains, add mutation testing (e.g. `mutmut`, scoped to
`domains/{domain}`): inject deliberate bugs into the plugin and count how
many the tests kill — a test that kills no mutants is decorative.

## Summary

```
Phase 1 (contract)   plan = namespace + schema + failure-mode reservation
                     (authored FIRST, validated by `microcoreos plan validate`)
Phase 0 (serial)     built FROM the plan: tools + migrations + models
                     → boot → AI_CONTEXT.md
Phase 2 (parallel)   orchestrator + N agents → 1 plugin + 1 test each
Phase 3 (verify)     boot linters + full test suite
```

Plan assigns → agents execute → linters verify. With those three layers,
"N agents without collisions" is not an aspiration — it is a property of the
system.
