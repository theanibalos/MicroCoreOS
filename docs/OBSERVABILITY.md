# Observability — The Living System

> Building an external dashboard? The exact JSON shapes and SSE framing of
> every endpoint below are specified in [OBSERVABILITY_API.md](OBSERVABILITY_API.md).

> MicroCoreOS is designed to be introspectable by default.
> It provides real-time metrics, traces, and event history.

---

## Native Pydantic Traceability

The system uses **Event Envelopes** (Pydantic models) to track causality across the entire kernel.

### Trace Records
The event bus maintains a history of `TraceRecord` objects. Each record captures:
1. **The Envelope**: Full metadata (id, parent_id, emitter, timestamp, key, priority, delay).
2. **The Subscribers**: A list of handler names that successfully received the event.

### Causal Trees
Causality is preserved via the `parent_id` field. You can retrieve the current state of the system through these endpoints:
- **`GET /system/traces/tree`**: Returns a hierarchical JSON representing the causality of all events in memory.
- **`GET /system/traces/flat`**: Returns a chronological list of events.

---

## Real-Time Streams (SSE)

The system provides Server-Sent Events (SSE) for real-time monitoring:
- **`GET /system/events/stream`**: A live feed of every event envelope as it passes through the bus.
- **`GET /system/logs/stream`**: A live feed of system logs attributed to the emitting plugin.

---

## Metrics and Topology

### System Events
The **`GET /system/events`** endpoint provides a snapshot of the system's "Event Topology":
- Who publishes what.
- Who subscribes to what.
- How many times each event has fired.

### Tool Metrics
The **`GET /system/metrics`** endpoint returns performance data for every tool call (latency, success/failure). This is powered by the `ToolProxy` which auto-instruments all infrastructure calls.

---

## OpenTelemetry Integration

When `OTEL_ENABLED=true`, MicroCoreOS automatically exports spans to any OTLP-compatible collector (Jaeger, Zipkin, Honeycomb).

- **Auto-instrumentation**: Every tool call (DB queries, Cache hits, Event publishes) gets a span automatically via `ToolProxy`.
- **HTTP spans**: `HttpServerTool` instruments FastAPI with `FastAPIInstrumentor` (requires `opentelemetry-instrumentation-fastapi`). Adds per-request spans with method, route, status code, and latency.
- **Causality (intra-process)**: The Event Bus propagates `parent_id` through `EventEnvelope`, building causal trees of events within the same process. This is not OTel trace propagation — it is a separate, native mechanism queryable at `/system/traces/tree`.

> OTel trace ID propagation across process boundaries via the Event Bus is not currently implemented. For distributed tracing, use the standard W3C `traceparent` header on HTTP calls between services.
