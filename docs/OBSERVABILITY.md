# Observability — Complete Reference

> Audience: Frontend monitoring dashboard developers and plugin authors.

---

## Overview

MicroCoreOS has three active observability layers:

| Layer | What it captures | Storage |
|-------|-----------------|---------|
| **Event Bus trace** | Every event fired, who received it, causal parent→child chain | In-memory, last 500 events |
| **Metrics buffer** | Duration of every tool method call (ms) | In-memory, last 1000 records |
| **OpenTelemetry** | Distributed spans exportable to Jaeger/DataDog | Configurable via env var |

---

## 1. Request Timing

### Tool call level (always active)

Every call to any tool method is timed automatically by `ToolProxy` with `time.perf_counter()` (microsecond precision):

```json
{
  "tool": "db",
  "method": "execute",
  "duration_ms": 42.375,
  "success": true,
  "timestamp": 1742834523.123456
}
```

Buffer holds the last 1000 records (circular). Access via `registry.get_metrics()` or `GET /system/metrics`.

### HTTP request level (requires OpenTelemetry)

Total request duration (wall clock from request received to response sent) is only available with:

```bash
OTEL_ENABLED=true
uv add opentelemetry-instrumentation-fastapi
```

Without OTel, there is no single timer for the full HTTP handler. Tool-level metrics cover what happens inside the handler but not network and serialization overhead.

---

## 2. Tool Call Metrics

### `GET /system/metrics` — snapshot of last 1000 records

Returns all records sorted newest first:

```json
{
  "success": true,
  "data": [
    { "tool": "db", "method": "execute", "duration_ms": 12.375, "success": true, "timestamp": 1742834523.1 },
    { "tool": "event_bus", "method": "publish", "duration_ms": 0.041, "success": true, "timestamp": 1742834523.0 }
  ]
}
```

Covers every tool method call: `db.query`, `event_bus.publish`, `auth.create_token`, etc.

### `GET /system/metrics/stream` — SSE, one message per tool call

```
data: {"tool": "db", "method": "execute", "duration_ms": 12.375, "success": true, "timestamp": 1742834523.1}
```

Useful for live performance dashboards. Slow consumers drop records silently (queue cap: 200).

### What metrics do NOT cover

- Total HTTP request duration — requires OTel
- Individual SQL query text or parameters
- Operations inside a tool that don't call a tracked public method

---

## 3. Event Causal Tree

Every event carries an `id` and a `parent_id`. When plugin B handles `user.created` and publishes `email.send` inside that handler, `email.send` automatically gets `parent_id` pointing to `user.created`. No manual work required — the ContextVar propagates through asyncio tasks.

### `GET /system/traces/flat` — chronological list

```json
[
  {
    "id": "abc-123",
    "parent_id": null,
    "event": "user.created",
    "emitter": "CreateUserPlugin.execute",
    "subscribers": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"],
    "payload_keys": ["user_id", "email"],
    "timestamp": 1742834523.1
  },
  {
    "id": "def-456",
    "parent_id": "abc-123",
    "event": "email.send",
    "emitter": "EmailPlugin.on_user_created",
    "subscribers": ["SmtpPlugin.send"],
    "payload_keys": ["to", "subject"],
    "timestamp": 1742834523.4
  }
]
```

### `GET /system/traces/tree` — hierarchical parent→child

```json
[
  {
    "id": "abc-123",
    "parent_id": null,
    "event": "user.created",
    "emitter": "CreateUserPlugin.execute",
    "subscribers": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"],
    "payload_keys": ["user_id", "email"],
    "timestamp": 1742834523.1,
    "children": [
      {
        "id": "def-456",
        "parent_id": "abc-123",
        "event": "email.send",
        "emitter": "EmailPlugin.on_user_created",
        "subscribers": ["SmtpPlugin.send"],
        "payload_keys": ["to", "subject"],
        "timestamp": 1742834523.4,
        "children": []
      }
    ]
  }
]
```

---

## 4. Failure Detection in Event Chains

`EventDeliveryMonitorPlugin` (active by default) hooks into the EventBus failure sink. When any subscriber raises an exception, it publishes `event.delivery.failed`:

```json
{
  "event": "email.send",
  "event_id": "def-456",
  "subscriber": "SmtpPlugin.send",
  "error": "Connection refused"
}
```

This event appears in the trace tree as a child of the failed event, inheriting the same `parent_id` context. The tree looks like:

```
user.created
  └─ email.send  (failed)
       └─ event.delivery.failed
```

After 5 consecutive failures, the subscriber is automatically unsubscribed. See `EVENT_BUS.md` for the full failure handling spec.

### Marking nodes red/green in the frontend

The trace node itself has no `failed` field. The frontend must cross-reference:

1. For each `event.delivery.failed` node, its payload contains `event_id`
2. Find the trace node with `id == event_id`
3. In that node's `subscribers` list, mark the `subscriber` field as failed

Everything else in `subscribers` that has no matching failure record processed successfully (silence = success).

---

## 5. Real-Time Streams (SSE)

All streams are Server-Sent Events. Connect once, receive indefinitely.

### `GET /system/events/stream` — flat event stream

One message per event as it fires:

```json
{
  "id": "abc-123",
  "parent_id": null,
  "event": "user.created",
  "emitter": "CreateUserPlugin.execute",
  "subscribers": ["EmailPlugin.on_user_created"],
  "payload_keys": ["user_id"],
  "timestamp": 1742834523.1
}
```

### `GET /system/traces/stream` — incremental causal tree

On connect, sends the full current tree as a snapshot:

```json
{ "type": "snapshot", "tree": [...] }
```

On every new event, sends the new node:

```json
{ "type": "node", "node": { "id": "...", "parent_id": "...", ... } }
```

Client logic: if `parent_id` exists in the local tree → append as child. If not → new root.

### `GET /system/logs/stream` — live log entries

```json
{
  "level": "INFO",
  "message": "User created: user_id=42",
  "timestamp": "2026-03-24T10:30:45.123456",
  "identity": "CreateUserPlugin.execute"
}
```

`identity` maps directly to the `emitter` field in trace records. Use it to correlate logs with the event that triggered them.

### `GET /system/metrics/stream` — live tool call metrics

```
data: {"tool": "db", "method": "execute", "duration_ms": 12.375, "success": true, "timestamp": ...}
```

---

## 6. System Status

### `GET /system/status`

```json
{
  "success": true,
  "data": {
    "tools": [
      { "name": "db", "status": "OK", "message": null },
      { "name": "event_bus", "status": "OK", "message": null }
    ],
    "plugins": [
      {
        "name": "CreateUserPlugin",
        "domain": "users",
        "status": "RUNNING",
        "error": null,
        "tools": ["db", "event_bus"]
      }
    ]
  }
}
```

Tool statuses: `OK` | `FAIL` | `DEAD`
Plugin statuses: `BOOTING` | `RUNNING` | `READY` | `DEAD`

The `tools` field on each plugin is the list of tool dependencies declared in its `__init__`.

### `GET /system/events` — subscription topology

Static view of all known events, their subscribers, and how many times they have fired:

```json
{
  "success": true,
  "data": {
    "events": [
      {
        "event": "user.created",
        "subscribers": ["EmailPlugin.on_user_created", "SmsPlugin.on_user_created"],
        "last_emitters": ["CreateUserPlugin.execute"],
        "times_fired": 42
      }
    ]
  }
}
```

---

## 7. OpenTelemetry (optional, production)

Activate with environment variables:

```bash
OTEL_ENABLED=true
OTEL_SERVICE_NAME=microcoreos
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

Install dependencies:

```bash
uv add opentelemetry-sdk opentelemetry-exporter-otlp
uv add opentelemetry-instrumentation-fastapi  # for HTTP spans
```

What is instrumented automatically (no plugin changes):
- Every tool method call → span with attributes `tool` and `method`
- HTTP server → spans with HTTP method, route template, status code, full request latency

Useful for: correlating distributed requests, exporting to Grafana/Datadog/Jaeger, getting total request duration.

---

## 8. Frontend Integration Guide

### Recommended architecture for the trace tree

```
1. Connect to GET /system/traces/stream (SSE)
2. On "snapshot" message → render full tree
3. On "node" message → insert into tree by parent_id
4. Track event.delivery.failed nodes separately → annotate parent node's subscriber list
5. On node click, show side panel:
   - subscribers (with failure status)
   - payload_keys
   - timestamp
   - logs from same identity (cross-reference /system/logs/stream by identity field)
   - metrics for tools called during that context (cross-reference /system/metrics/stream)
```

### Capability map

| Need | Status | Endpoint |
|------|--------|----------|
| Tool call duration | ✅ | `GET /system/metrics`, `GET /system/metrics/stream` |
| Total HTTP request duration | ⚙️ Requires OTel | `OTEL_ENABLED=true` + fastapi instrumentation |
| Event causal tree | ✅ | `GET /system/traces/tree` |
| Real-time causal tree | ✅ | `GET /system/traces/stream` (SSE) |
| Which subscribers received an event | ✅ | `subscribers` field on each trace node |
| Detect subscriber failure | ✅ | `event.delivery.failed` with `event_id` cross-reference |
| Mark node red/green | ✅ (client logic) | Cross-reference trace nodes with failure events |
| Tool health status | ✅ | `GET /system/status` |
| Real-time logs | ✅ | `GET /system/logs/stream` (SSE) |
| Event topology | ✅ | `GET /system/events` |

---

## 9. File Reference

| Component | File |
|-----------|------|
| Tool call metrics (source) | `core/container.py` + `tools/system/registry_tool.py` |
| Metrics endpoint | `domains/system/plugins/system_metrics_plugin.py` |
| Event Bus + trace log | `tools/event_bus/event_bus_tool.py` |
| Trace endpoints (flat + tree) | `domains/system/plugins/system_traces_plugin.py` |
| Trace SSE stream | `domains/system/plugins/system_traces_stream_plugin.py` |
| Event SSE stream | `domains/system/plugins/system_events_stream_plugin.py` |
| Log SSE stream | `domains/system/plugins/system_logs_stream_plugin.py` |
| Failure detection | `domains/system/plugins/event_delivery_monitor_plugin.py` |
| System status | `domains/system/plugins/system_status_plugin.py` |
| Event topology | `domains/system/plugins/system_events_plugin.py` |
| ContextVars (causality) | `core/context.py` |
