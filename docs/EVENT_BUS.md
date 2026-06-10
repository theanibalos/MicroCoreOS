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
| `key` | str \| None | Partition key for ordered delivery (Kafka/SQS) |
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

Waits for the first non-wildcard subscriber to return a non-`None` dict. Raises `asyncio.TimeoutError` if no response arrives within the timeout.

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
- **Loop Protection**: Wildcards and `_dlq.*` events are never dead-lettered.
- **Global Switch**: Controlled by `EVENT_BUS_DLQ_ENABLED=true` env var.

### Auto-unsubscribe after 5 consecutive FINAL failures

If the same subscriber reaches **5 consecutive final failures** (after all retries are exhausted), the bus permanently removes it from all subscriptions. Each failure is logged as:
`[EventBus] 💥 Final failure in {subscriber}: {error} ({count}/5)`

The counter resets on any successful execution. This prevents a broken subscriber from accumulating errors forever.

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
| `RabbitMQDriver` | Not included | Would add AMQP support. Implement `EventBusDriver` interface. |
| `KafkaDriver` | Not included | Would add streaming and replayability. Implement `EventBusDriver` interface. |

To use a custom driver, instantiate `EventBusTool(driver=MyDriver())` and register it. Plugins remain 100% unaffected because they only interact with `EventBusTool`'s public API.

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
