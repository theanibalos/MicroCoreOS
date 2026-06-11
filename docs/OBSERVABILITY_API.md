# Observability API — Data Contract for External Dashboards

Everything an external frontend (dashboard, visualization, "city view") needs
to consume MicroCoreOS observability data. All endpoints live under `/system/*`,
are **public by design** (see `ELASTIC_DEPLOYMENT.md` — protect them at the
edge in production) and follow the standard envelope:

```json
{ "success": true, "data": ..., "error": null }
```

CORS defaults to `*` (`HTTP_CORS_ORIGINS`), so a frontend on another origin
works out of the box in dev. SSE streams are plain `text/event-stream`
consumable with the native `EventSource` API; every message is one line:
`data: <json>\n\n` (no `event:` field, no message ids — on reconnect you start
fresh; the traces stream re-sends a full snapshot).

## Identity formats (read this first)

- **Plugin names** (`/system/status`): `"<domain>.<ClassName>"` — e.g.
  `"users.CreateUserPlugin"`.
- **Subscriber names** (traces, `/system/events`):
  `"<domain>.<ClassName>.<method>"` — e.g.
  `"users.WelcomeServicePlugin.on_user_created"`. The prefix is the plugin's
  registered identity (exactly the `/system/status` name), so mapping a
  subscriber to its plugin is `subscriber.rsplit(".", 1)[0]`. The prefix
  exists so derived consumer groups never collide across domains.
  Non-plugin subscribers (rare: plain functions, internal callbacks) fall
  back to a module-qualified form (`"<module>.<qualname>"`).
- **Emitter** (traces, events): the caller's identity, same scheme as
  subscribers — `"users.CreateUserPlugin.execute"` — or `"system"` when
  published outside any handler context.
- **Timestamps**: epoch seconds as float (UTC), except the logs stream where
  `timestamp` is a preformatted string.
- **Internal events**: names starting with `_reply.` (RPC plumbing) are
  filtered out of traces server-side; the raw `/system/events/stream` does NOT
  filter them — skip `_reply.*` (and optionally `_dlq.*`) client-side.

---

## REST snapshots

### GET /system/status — what exists and how healthy it is

```json
{
  "success": true,
  "data": {
    "tools":   [ { "name": "db", "status": "OK", "message": null } ],
    "plugins": [ {
      "name": "users.CreateUserPlugin",
      "domain": "users",
      "status": "READY",
      "error": null,
      "tools": ["http", "db", "event_bus", "logger", "auth"]
    } ]
  },
  "error": null
}
```

Tool `status`: `OK` | `WARNING` | `DEAD` | `FAIL`. Plugin `status`:
`RUNNING` | `READY` | `DEAD` (with `error` populated). `plugins[].tools` is
the DI dependency list — the edges between a plugin and the tools it uses.

### GET /system/events — event topology + firing stats

```json
{
  "success": true,
  "data": { "events": [ {
    "event": "user.created",
    "subscribers": ["users.WelcomeServicePlugin.on_user_created"],
    "last_emitters": ["users.CreateUserPlugin.execute"],
    "times_fired": 42
  } ] },
  "error": null
}
```

Union of statically-scanned publishes, live subscriptions, and the trace
history — so events appear even before they ever fire (`times_fired: 0`).

### GET /system/metrics — last 1000 tool calls, newest first

```json
{
  "success": true,
  "data": [ {
    "tool": "db",
    "method": "query",
    "duration_ms": 0.412,
    "success": true,
    "timestamp": 1765432100.123
  } ],
  "error": null
}
```

### GET /system/traces/tree — causal event tree (roots newest first)

### GET /system/traces/flat — same nodes, flat, newest first

Node shape (tree nodes additionally have `children: [node, ...]`):

```json
{
  "id": "uuid4",
  "parent_id": "uuid4 | null",
  "event": "user.created",
  "emitter": "users.CreateUserPlugin.execute",
  "subscribers": ["users.WelcomeServicePlugin.on_user_created"],
  "payload_keys": ["id", "email", "roles"],
  "timestamp": 1765432100.123,
  "key": null,
  "priority": null,
  "delay": null
}
```

The ring buffer holds the last 500 records; `parent_id` links events caused
by other events (an event published from inside a handler), which is what
draws the "route" an action travels through the system.

---

## SSE live streams

### GET /system/metrics/stream — one message per tool call

```
data: {"tool":"db","method":"query","duration_ms":0.412,"success":true,"timestamp":1765432100.123}
```

### GET /system/traces/stream — live causal tree

On connect, one snapshot; then one message per new event:

```
data: {"type":"snapshot","tree":[ <node with children>, ... ]}
data: {"type":"node","node":{ <node without children> }}
```

Client logic: render the snapshot tree; on `node`, find the node whose `id`
equals `node.parent_id` and append it as a child — if not found, it is a new
root. `_reply.*` is already filtered server-side.

### GET /system/events/stream — raw firehose (full payloads)

One message per published event — the **full envelope**, payload included
(the only place payloads are exposed; traces only carry `payload_keys`):

```
data: {"id":"uuid4","event":"user.created","payload":{"id":1,"email":"a@b.c"},
       "emitter":"users.CreateUserPlugin.execute","timestamp":1765432100.123,
       "parent_id":null,"correlation_id":null,"reply_to":null,
       "key":null,"priority":null,"delay":null,"ttl":null,"headers":{},
       "kind":"published","payload_keys":["id","email"]}
```

NOT filtered: skip `_reply.*` (and `_dlq.*` if undesired) client-side.

### GET /system/logs/stream — live log records

```
data: {"level":"INFO","message":"User created with ID 7","timestamp":"2026-06-11 12:00:00","identity":"users.CreateUserPlugin"}
```

---

## Failure signals (how a dashboard shows "this is failing")

1. **Tool-level**: `/system/metrics` records carry `success: false` per call;
   `/system/status` flips a tool to `DEAD`/`WARNING` (the proxy's hybrid DEAD
   policy + proactive health checks).
2. **Handler-level**: when a subscriber exhausts its retries, the bus's
   failure sink fires and `EventDeliveryMonitorPlugin` publishes
   **`event.delivery.failed`** with payload
   `{event, event_id, subscriber, error, attempts}` — it arrives on
   `/system/events/stream` like any other event. Counting these per
   `subscriber` gives the failure count of each consumer.
3. **Dead letters**: terminally failed deliveries are also published as
   `_dlq.<original-event>` with the failure detail in the payload.
