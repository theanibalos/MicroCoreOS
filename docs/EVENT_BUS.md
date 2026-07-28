# Event Bus — Elastic Monolith Architecture

> The event bus is the **only** legitimate channel for inter-domain communication.
> It follows the "Elastic Monolith" pattern: in-process by default, distributed on demand.

---

## Universal Event Contract

MicroCoreOS uses a standardized **Event Envelope** (Pydantic model) for all messages. This ensures compatibility with enterprise brokers like Kafka, RabbitMQ, and SQS without changing plugin code.

### Envelope Fields

| Field | Type | Description |
|---|---|---|
| `id` | str (UUID) | Unique event ID, auto-generated |
| `event` | str | Event name (e.g. `user.created`) |
| `payload` | dict | Business data |
| `emitter` | str | Name of the publishing plugin/tool |
| `timestamp` | datetime (UTC) | Time of creation |
| `parent_id` | str \| None | ID of the triggering event (causality chain) |
| `correlation_id` | str \| None | Used internally for RPC request/response |
| `reply_to` | str \| None | Reply channel name, used internally by `request()` |
| `key` | str \| None | Ordering unit: same-key publishes keep call order, on every driver |
| `priority` | int \| None | Priority level 1–10 (RabbitMQ) |
| `delay` | int \| None | Seconds before delivery |
| `ttl` | float \| None | Time-to-live in seconds (expired events are discarded) |
| `headers` | dict | Arbitrary metadata attached to the envelope |

### Subscriber Signature

**Every subscriber receives an `EventEnvelope`, not a raw dict.**

```python
async def on_user_created(self, event: EventEnvelope) -> None:
    user_id = event.payload.get("id")
    email   = event.payload.get("email")
```

For RPC (`request()`), return a non-None dict:

```python
async def on_user_validate(self, event: EventEnvelope) -> dict:
    exists = await self.db.query_one("SELECT 1 FROM users WHERE email = $1", [event.payload["email"]])
    return {"exists": exists is not None}
```

---

## Public API

### `publish(event_name, data, **kwargs)` — fire and forget

```python
await self.bus.publish("order.shipped", {"order_id": 123})

# With enterprise kwargs:
await self.bus.publish(
    "order.shipped",
    {"order_id": 123},
    key="customer_42",  # strict ordering per customer
    priority=8,
    delay=60            # deliver after 60 seconds
)
```

Non-blocking. Each subscriber runs as an independent `asyncio.Task`.

---

### `subscribe(event_name, callback, group=None, retries=0, backoff=0.5)` — register a handler

```python
# Broadcast — every subscriber receives the event
await self.bus.subscribe("order.placed", self.on_order_placed)

# With Retries — automatic exponential backoff on failure
await self.bus.subscribe("job.heavy", self.handle_job, retries=3, backoff=1.0)
# Wait times: 1.0s, 2.0s, 4.0s before final failure

# Consumer group — only one subscriber in the group receives each event (Round-Robin)
await self.bus.subscribe("job.heavy", self.handle_job, group="workers")
```

Register in `on_boot()`. Both `async def` and `def` handlers are supported. Sync handlers are offloaded to a thread pool.

---

### `unsubscribe(event_name, callback)` — remove a handler

```python
await self.bus.unsubscribe("order.placed", self.on_order_placed)
```

---

### `request(event_name, data, timeout=5)` — async RPC

```python
result = await self.bus.request("user.validate", {"email": "a@b.com"}, timeout=5)
```

Waits for the first subscriber to return a non-`None` dict. Raises `asyncio.TimeoutError` if no response arrives within the timeout.

> **Warning**: `request()` reintroduces coupling. Use only when a response is strictly required.

---

### `get_trace_history()` — last 500 events

Returns `List[TraceRecord]`. Each `TraceRecord` has:
- `record.envelope` — the full `EventEnvelope`
- `record.subscribers` — list of handler names that received it

```python
history = self.bus.get_trace_history()
for r in history:
    print(r.envelope.event, r.envelope.parent_id, r.subscribers)
```

---

### `get_subscribers()` — current subscription map

```python
subs = self.bus.get_subscribers()
# {"user.created": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"]}
```

---

### `add_listener(callback)` — real-time event sink

Called synchronously on every `publish()` with a flat dict record. Keep it fast.

```python
def my_sink(record: dict) -> None:
    # record keys: id, event, emitter, payload, payload_keys, subscribers, timestamp, parent_id, ...
    asyncio.create_task(self._broadcast(record))

self.bus.add_listener(my_sink)
```

Used by: `SystemEventsStreamPlugin`, `SystemTracesStreamPlugin`.

---

### `add_failure_listener(callback)` — subscriber failure sink

Called synchronously when a subscriber raises. Record shape:

```python
{"event": "email.send", "event_id": "uuid", "subscriber": "SmtpPlugin.on_email_send", "error": "..."}
```

Used by: `EventDeliveryMonitorPlugin` to publish `event.delivery.failed`.

---

## Failure Handling

### Dead-Letter Queue (DLQ)

When a delivery exhausts all retries, the bus automatically publishes a failure event to `_dlq.<original_event>`.

- **Payload**: Includes the original envelope, subscriber identity, error message, and attempt count.
- **Loop Protection**: `_dlq.*` and `_reply.*` events are never dead-lettered.
- **Global Switch**: Controlled by `EVENT_BUS_DLQ_ENABLED=true` env var.

**Provoking a DLQ deliberately (chaos testing)**: this is about a *live*
subscriber whose handler keeps failing — not a process crash (that gap is
the Transactional Outbox's, Issue 28) and not a paused subscriber
(`chaos/off {plugin}` just accumulates a durable backlog with zero retries
and zero DLQ — it drains in full on resume, nothing was ever attempted). To
force `_dlq.<event>` deterministically, use `chaos/tool {mode:"down"}` on a
dependency the handler calls — every call fails, so the first event that
passes through exhausts its retries immediately. `mode:"flaky", rate` is for
realistic noise, not for demonstrating DLQ on demand: a delivery only
reaches DLQ if *every* attempt fails, so with `retries: N` the probability
per event is `rate^(N+1)` (e.g. `retries: 3, rate: 0.3` → ≈0.8% per event —
seeing zero DLQ entries over a handful of requests is the expected outcome,
not a sign anything is broken).

### Auto-unsubscribe after 5 consecutive FINAL failures

If the same subscriber reaches **5 consecutive final failures** (after all retries are exhausted), the bus permanently removes it from all subscriptions. Each failure is logged as:
`[EventBus] 💥 Final failure in {subscriber}: {error} ({count}/5)`

The counter resets on any successful execution. This prevents a broken subscriber from accumulating errors forever.

The drop is never silent: the bus publishes **`system.subscriber.dropped`** with payload
`{event, subscriber, error, consecutive_failures}`. Its `parent_id` is the event that
caused the final failure, so the drop appears chained in `/system/traces/tree`. Subscribe
to it for alerting (a dropped subscriber of `system.subscriber.dropped` itself does not
re-trigger it — loop-guarded).

**To avoid it for external services** — catch exceptions inside the subscriber and never let them escape to the bus:

```python
async def on_order_placed(self, event: EventEnvelope) -> None:
    result = await self.stripe_tool.charge(event.payload["amount"])
    if not result["success"]:
        await self.bus.publish("payment.failed", event.payload)
```

---

## Causality Tracking

The bus automatically propagates context vars into each subscriber's execution context:
- `current_event_id_var` → ID of the triggering event (becomes `parent_id` of any event published inside a subscriber)
- `current_identity_var` → `"PluginClass.method_name"` (attributed automatically to logger calls)

No manual work required. Causal chains build themselves.

---

## Driver Pattern (The "Elastic" Part)

The `EventBusTool` decouples the brain (logic, tracing) from the transport via the `EventBusDriver` interface.

| Driver | Status | Use Case |
|---|---|---|
| `InProcessDriver` | Built-in | Default. Fast, local memory. Simulates groups and delays. |
| `RedisStreamsDriver` | Built-in | Distributed transport across replicas. Activate with `EVENT_BUS_DRIVER=redis_streams`. |
| `SQLiteDriver` | Built-in | Durable local queue without a broker. Activate with `EVENT_BUS_DRIVER=sqlite`. |
| `RabbitMQDriver` | Extra | AMQP transport. Ships in `extras/available_tools/rabbitmq/` — drop into `tools/event_bus/` and set `EVENT_BUS_DRIVER=rabbitmq`. |
| `KafkaDriver` | Extra | Kafka transport (partition-key ordering, consumer groups). Ships in `extras/available_tools/kafka/` — drop into `tools/event_bus/` and set `EVENT_BUS_DRIVER=kafka`. |

### RedisStreamsDriver (distributed mode)

Set `EVENT_BUS_DRIVER=redis_streams` (plus the `REDIS_*` env vars if Redis is not on localhost) and start N replicas pointing at the same Redis — zero code changes:

- Each event maps to a capped stream (`bus:user.created`).
- `subscribe(..., group="workers")` becomes a real Redis consumer group: each message is delivered to exactly **one** consumer across the whole fleet (the Issue 19 scheduler pattern).
- Without `group=`, every subscriber in every replica receives every event (broadcast), matching in-process semantics.
- Retries, backoff, DLQ, RPC and tracing keep working untouched — they live in the Bus, not the transport.

To use a custom driver, instantiate `EventBusTool(driver=MyDriver())` and register it. Plugins remain 100% unaffected because they only interact with `EventBusTool`'s public API. Every driver MUST pass the parity suite (`tests/tools/test_event_bus_broker_parity.py`), which runs parametrized over all built-in transports.

### Capability claims (Issue 30)

Each driver declares how it implements Bus semantics via `capabilities`:

```python
capabilities = {"delay": "native", "retries": "in_bus", "dlq": "in_bus"}
```

- `native` — the broker persists it: **crash-safe**. All durable/distributed drivers (SQLite, Redis Streams, RabbitMQ, Kafka) claim `delay: native`: a delayed event is parked broker-side immediately, so the publisher dying mid-delay does not lose it.
- `in_bus` — the Bus runs the universal software fallback in this process' memory. This is the default (and all `InProcessDriver` has). `retries`/`dlq` are `in_bus` everywhere by design — they are already crash-safe because drivers ack only after the handler and its retries finish.

The active driver and its claims appear in the SYSTEM MANIFEST (`get_interface_description()`'s `ACTIVE TRANSPORT` line), so plugin authors can see whether `delay=` is crash-safe on the mounted transport.

---

## Anti-Patterns

**Event loop:**
```python
# Plugin A publishes "inventory.check" → Plugin B publishes "order.created" → Plugin A → infinite loop
```

**Using events as function calls:**
```python
# Wrong — use request() if you need a response, not publish()
await self.bus.publish("user.get_by_id", {"id": 42})
# You can't get the result back from publish()
```

**Naming commands instead of facts:**
```python
# Wrong — commands imply a single owner
send.email  /  process.payment  /  user.create

# Right — facts can have multiple independent reactors
email.sent  /  payment.processed  /  user.created
```

**`event.delivery.failed` loop protection**: `EventDeliveryMonitorPlugin` explicitly suppresses re-publishing when the failing event was itself `event.delivery.failed`.

### Why there is no wildcard subscription

`subscribe("*")` was removed on purpose (2026-07-19). System-wide observation has two proper homes, neither of which needs the bus to fan out every event twice:

- **In-process (monolith)**: `add_listener()` / `add_failure_listener()` — publish-side sinks with zero transport cost. This is how the event stream viewer, traces stream and delivery monitor already work.
- **Distributed (audit/event-store)**: the broker's own tooling — an external consumer reading the topics/streams directly (e.g. Kafka Connect), without going through the Bus at all.

Removing it also removed the firehose double-write every distributed driver paid on every publish.
