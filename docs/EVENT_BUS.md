# Event Bus — Complete Reference

> The event bus is the **only** legitimate channel for inter-domain communication.
> Direct imports between domains are forbidden.

---

## How It Works

`publish()` is non-blocking. It creates one independent `asyncio.Task` per subscriber and returns immediately. The caller never waits for subscribers to finish.

```
await bus.publish("user.created", {"id": 42})
  → task A: EmailPlugin.on_user_created    ┐
  → task B: NotificationPlugin.on_user_    ├─ run concurrently, publisher is already gone
  → task C: SmsPlugin.on_user_created      ┘
```

This means:
- **Subscribers do not block each other.** If SmsPlugin is slow, EmailPlugin is unaffected.
- **The publisher does not know what happens next.** It fires and forgets.
- **Order of execution is not guaranteed.** Do not rely on subscriber execution order.

---

## Public API

### `publish(event_name, data)` — fire and forget

```python
await self.bus.publish("order.placed", {"order_id": 99, "total": 49.99})
```

Returns immediately. All subscribers run in background tasks.

---

### `subscribe(event_name, callback)` — register a handler

```python
await self.bus.subscribe("order.placed", self.on_order_placed)
```

Register in `on_boot()`. The callback receives only `data: dict` — no `context`.

Both `async def` and `def` handlers are supported. Sync handlers are automatically offloaded to a thread pool and do not block the event loop:

```python
def on_user_created(self, data: dict) -> None:
    # sync — safe, runs in thread pool
    self.send_sync_notification(data["email"])
```

**Wildcard subscription** — observability only, no RPC participation:

```python
await self.bus.subscribe("*", self.monitor_all)
```

Wildcard subscribers receive every event but their return value is ignored in `request()`.

---

### `unsubscribe(event_name, callback)` — remove a handler

```python
await self.bus.unsubscribe("order.placed", self.on_order_placed)
```

Safe to call even if the callback is not registered.

---

### `request(event_name, data, timeout=5)` — async RPC

```python
result = await self.bus.request("user.validate", {"email": "a@b.com"}, timeout=5)
```

Waits for the **first** subscriber to return a non-`None` dict. Raises `asyncio.TimeoutError` if no response arrives within the timeout.

The responding subscriber must return a value:

```python
async def on_user_validate(self, data: dict) -> dict:
    exists = await self.db.query_one("SELECT 1 FROM users WHERE email = $1", [data["email"]])
    return {"exists": exists is not None}
```

> **Warning**: `request()` reintroduces coupling. Use only when a response is strictly required (e.g., validation before proceeding). Avoid for side effects.

---

### `get_trace_history()` — last 500 events

```python
history = self.bus.get_trace_history()
```

Returns a list of records (newest appended last). Each record:

```python
{
    "id": "uuid",
    "parent_id": "uuid | None",   # which event triggered this one
    "event": "user.created",
    "emitter": "CreateUserPlugin.execute",
    "subscribers": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"],
    "payload_keys": ["id", "email"],
    "timestamp": 1742834523.1
}
```

`parent_id` is set automatically from the `current_event_id_var` ContextVar at the moment of publish. If plugin A handles `user.created` and inside publishes `email.send`, the `email.send` record will have `parent_id` pointing to the `user.created` record — no manual work required.

---

### `get_subscribers()` — current subscription map

```python
subs = self.bus.get_subscribers()
# {"user.created": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"]}
```

Live snapshot. Changes immediately when plugins subscribe or unsubscribe.

---

### `add_listener(callback)` — real-time event sink

Called synchronously on every `publish()`, after the trace record is written and before tasks are created. Receives the full trace record.

```python
def my_sink(record: dict) -> None:
    # record = {id, parent_id, event, emitter, subscribers, payload_keys, timestamp}
    pass

self.bus.add_listener(my_sink)
```

**Keep it fast.** This runs in the publish hot path. If you need async work, schedule a task:

```python
def my_sink(record: dict) -> None:
    asyncio.create_task(self._do_async_work(record))
```

Used by: `SystemEventsStreamPlugin`, `SystemTracesStreamPlugin`.

---

### `add_failure_listener(callback)` — subscriber failure sink

Called synchronously when a subscriber raises an exception. Receives:

```python
{
    "event": "email.send",
    "event_id": "uuid",          # matches the id in the trace record
    "subscriber": "SmtpPlugin.on_email_send",
    "error": "Connection refused"
}
```

```python
self.bus.add_failure_listener(self._on_failure)
```

Used by: `EventDeliveryMonitorPlugin` to publish `event.delivery.failed`.

---

## Causality Tracking

The bus automatically propagates two ContextVars into each subscriber's execution context:

| ContextVar | Value | Where set |
|-----------|-------|-----------|
| `current_event_id_var` | ID of the triggering event | EventBus, before calling subscriber |
| `current_identity_var` | `"PluginClass.method_name"` | EventBus, before calling subscriber |

Both are reset after the subscriber returns (or raises). This means:

- **Logs are attributed automatically.** The `logger` tool reads `current_identity_var` — every `logger.info()` call inside a subscriber is automatically tagged with the plugin name, no manual effort.
- **Causal chains are automatic.** When a subscriber publishes a new event, `current_event_id_var` is the `parent_id` of that new event — building the causality tree without any code.

---

## Failure Handling

### Per-call failure (single exception)

If a subscriber raises once, the bus:
1. Increments a consecutive failure counter for that subscriber
2. Calls all registered failure listeners synchronously
3. Logs the failure to stdout
4. Continues dispatching to other subscribers (they are unaffected)

The subscriber **stays subscribed**. It will receive the next event normally.

### Auto-unsubscribe after 5 consecutive failures

If the same subscriber fails **5 times in a row** without a single success:

1. The bus removes it from all event subscriptions it had
2. The failure counter is cleared
3. A log message is printed: `[EventBus] 🔇 Auto-unsubscribed dead handler`

**The subscriber does not recover automatically.** It is permanently gone until the process restarts.

**The counter resets on success.** If a subscriber fails 4 times and then succeeds once, the counter goes back to 0 and it stays subscribed.

### Why this exists

Without it, a broken subscriber would be called on every event forever — accumulating error logs, filling the trace buffer with noise, and wasting CPU on tasks guaranteed to fail. Five failures is the threshold between "transient error" and "structurally broken."

### How to avoid it for external services

If a subscriber calls an external API (Stripe, Twilio, etc.), it must catch failures internally and never let them escape to the bus:

```python
async def on_order_placed(self, data: dict) -> None:
    result = await self.stripe_tool.charge(data["amount"])
    if not result["success"]:
        # Handle gracefully — publish a retry event, log, whatever
        await self.bus.publish("payment.failed", data)
        return
    # success path
```

The tool is responsible for its own retries and timeouts. The plugin handles `success: false`. The bus never sees an exception.

---

## Preventing Event Hell

Event hell is when events trigger events that trigger more events in uncontrolled chains, creating loops, ambiguous ownership, and systems that are impossible to reason about.

MicroCoreOS has several hard constraints that prevent this by design:

### 1. No cross-domain imports

Domains cannot import from each other. The only communication channel is `event_bus`. This forces you to think about what events you expose as a public contract.

### 2. `publish()` is fire-and-forget — no return value

You cannot build synchronous chains through `publish()`. If you need a response, use `request()` — and its coupling cost is visible and intentional.

### 3. Wildcard subscriptions are observability-only

`subscribe("*", callback)` receives everything but cannot reply in RPC. This makes system-wide monitoring explicit and separates it from business logic.

### 4. Failure listeners are separate from subscribers

Dead-letter logic (`add_failure_listener`) is a different mechanism from event subscription. You cannot accidentally turn a failure handler into a business logic handler.

### 5. `event.delivery.failed` has infinite-loop protection

`EventDeliveryMonitorPlugin` explicitly guards against publishing `event.delivery.failed` when the original failing event was itself `event.delivery.failed`:

```python
if record.get("event") == "event.delivery.failed":
    # suppress — do not loop
    return
```

### Anti-patterns that lead to event hell

**Loop:**
```python
# Plugin A
async def on_order_created(self, data):
    await self.bus.publish("inventory.check", data)  # → triggers Plugin B

# Plugin B
async def on_inventory_checked(self, data):
    await self.bus.publish("order.created", data)    # ← LOOP
```

**Fan-out explosion:**
```python
# One event triggers 10 events, each triggering 10 more → 100 events
# No visible owner, impossible to debug
```

**Using events as function calls:**
```python
# Wrong: using publish() when you need a response
await self.bus.publish("user.get_by_id", {"id": 42})
# You can't get the result — use request() or direct tool access
```

**Cross-domain data access via events:**
```python
# Wrong: querying another domain's data through events
result = await self.bus.request("users.find", {"id": 42})
user_email = result["email"]
# If you need user data, you need either:
# a) The users domain to push the data in the event payload
# b) Your own copy of the relevant data
```

### Naming convention that helps

Use dot-separated namespaces that read as past tense facts, not commands:

```
# Good — facts that already happened
user.created
order.placed
payment.failed
email.sent

# Bad — commands (implies the event drives behavior imperatively)
user.create
send.email
process.payment
```

Facts are easier to reason about. Multiple plugins can react to `user.created` independently. A command like `send.email` implies a single owner and creates implicit coupling.

---

## What the Trace Records Tell You

Given a `user.created` event dispatched to three subscribers where SmsPlugin fails:

```json
{
  "id": "abc-123",
  "parent_id": null,
  "event": "user.created",
  "emitter": "CreateUserPlugin.execute",
  "subscribers": [
    "EmailPlugin.on_user_created",
    "NotificationPlugin.on_user_created",
    "SmsPlugin.on_user_created"
  ],
  "payload_keys": ["id", "email"],
  "timestamp": 1742834523.1
}
```

After SmsPlugin fails, the failure monitor publishes:

```json
{
  "id": "def-456",
  "parent_id": "abc-123",
  "event": "event.delivery.failed",
  "emitter": "EventDeliveryMonitorPlugin._publish_alert",
  "subscribers": [...],
  "payload_keys": ["event", "event_id", "subscriber", "error"],
  "timestamp": 1742834523.4
}
```

Reading the tree:

| Field | Meaning |
|-------|---------|
| `subscribers: ["EmailPlugin...", "NotificationPlugin...", "SmsPlugin..."]` | All three received the event |
| No `event.delivery.failed` for Email or Notification | They processed it without exception |
| `event.delivery.failed` with `parent_id: "abc-123"` | SmsPlugin crashed during that specific dispatch |
| `error: "Connection refused"` in the payload | The actual exception message |

**Silence means success.** A subscriber that processed an event without exception leaves no additional trace node. Its presence in the `subscribers` array of the parent node is the only record.

**`subscribers: []` means nobody was listening.** The event was published, recorded, and silently dropped. This is not an error at the bus level, but may indicate a misconfigured or dead plugin.

---

## Observability Endpoints (system domain)

| Endpoint | Description |
|----------|-------------|
| `GET /system/events` | Static topology: which events exist, who subscribes |
| `GET /system/traces/flat` | Last 500 events, newest first |
| `GET /system/traces/tree` | Same events as a causal parent→child tree |
| `GET /system/events/stream` | SSE: live event records as they happen |
| `GET /system/traces/stream` | SSE: snapshot on connect + incremental nodes |

The SSE trace stream sends two message types:

```json
// On connect — full current tree
{ "type": "snapshot", "tree": [...] }

// On every new event
{ "type": "node", "node": { "id": "...", "parent_id": "...", ... } }
```

Client logic: if `parent_id` is in your local tree → add as child. If not → new root.
