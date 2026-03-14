# Roadmap

---

## High Priority

**Issue 1 — ✅ Domain-level AI_CONTEXT.md**

Each domain should have an auto-generated or manual `AI_CONTEXT.md` that gives the AI all the context it needs in 10 lines:

```
# Domain: profiles
## Tables: profiles, links
## Endpoints: POST/GET/PUT/DELETE /profiles, POST /profiles/{id}/links
## Events emitted: profile.created, profile.updated
## Events consumed: none
## Dependencies: db, http, logger, auth, event_bus
```

This eliminates the need to read code to understand a domain. The AI reads this file first and knows exactly what exists, what it can use, and what events flow in and out.

---

## Medium Priority

**Issue 2 — Standardized validation pattern**

Currently each plugin validates differently. Pydantic with Field validators should be the official standard across all plugins:

```python
from pydantic import BaseModel, Field

class CreateProfileRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern="^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
```

Document this in `INSTRUCTIONS_FOR_AI.md` as the only accepted pattern. Prevents inconsistencies across plugins and makes validation errors automatic via FastAPI.

---

**Issue 3 — Unified error response format**

Currently each plugin returns errors differently. Standardize across all plugins:

```python
context.set_status(404)
return {"success": False, "error": "Profile not found", "code": "PROFILE_NOT_FOUND"}
```

Optionally add a helper to the http tool:
```python
return self.http.error(404, "PROFILE_NOT_FOUND", "Profile not found")
```

Document the standard error codes per domain in `AI_CONTEXT.md`.

---

**Issue 4 — Separate administration port**

Expose the `system` domain (observability) on a separate port (e.g. 8001) isolated from the public API port. The admin port never reaches the outside in production — only accessible from internal network or VPN.

Reference: Spring Boot Actuator pattern. The HTTP tool would need to support a second internal server instance.

Affected endpoints: `GET /system/status`, `GET /system/traces`, `GET /system/events`, `GET /system/events/stream` (SSE), `GET /system/logs/stream` (SSE).

---

**Issue 5 — Event contract validation / linter**

Currently there is no contract between event publishers and subscribers. A plugin can publish `user.created` with `{id, email}` while the subscriber expects `{user_id, email}` — the system boots without errors and fails silently at runtime.

Options to explore:
- **Static linter**: analyzes plugin code before boot and cross-references published vs subscribed event schemas. No runtime overhead.
- **Registry-based declaration**: plugins declare in `on_boot` what events they emit and with what schema. The registry cross-references on boot and raises early if there is a mismatch.
- **Bus-level validation**: `subscribe()` accepts an optional Pydantic model; the bus validates the payload before dispatching.

Key tension: the event bus is intentionally decoupled. Adding event schemas introduces coupling between publisher and subscriber — exactly what the bus is designed to avoid. The right balance needs to be found.

---

## Optional / Exploratory

**Issue 10 — Migrate HttpServerTool from FastAPI to pure Starlette**

FastAPI is already a thin wrapper over Starlette. Most imports in `http_server_tool.py` are Starlette classes re-exported by FastAPI (`Request`, `WebSocket`, `JSONResponse`, `StreamingResponse`, `StaticFiles`, `CORSMiddleware`, `run_in_threadpool`). What is exclusively FastAPI is minimal: the app object, `Depends()` for GET query params, `response_model`/`tags` in `add_api_route`, and the auto-generated docs at `/docs`.

**Motivation:** simplify the tool by removing the `__signature__` hack in `_register_endpoint` (which exists solely to make FastAPI generate correct OpenAPI docs), and align the framework with its long-term identity.

**Trade-off:** auto-generated docs at `/docs` are lost.

**Mitigation — Issue 10b — Optional `OpenApiPlugin`:**

A plugin that lazily generates the OpenAPI 3.0 spec on the first request to `/openapi.json` and serves Swagger UI at `/docs` pointing to that endpoint. `HttpServerTool` exposes `get_registered_routes()` with the metadata accumulated in `_pending_endpoints`. The plugin is fully optional — if absent, no docs are served. Can be excluded in production without any other changes.

Follows the 1 file = 1 feature principle.

---

## Low Priority

**Issue 6 — Proactive tool health check**

`ToolProxy` detects failures reactively (when an operation raises an exception). Tools that fail silently (e.g. DB stops responding without raising) remain in `OK` state indefinitely.

Solution: a background plugin that calls `db.health_check()` every N seconds and updates the registry. The DB tool already exposes `health_check() -> bool`. The pattern is extensible to any tool that implements the method.

Note: keep outside the core to preserve the blind-kernel principle.

---

**Issue 7 — Tool call duration tracking via ToolProxy**

`ToolProxy` already intercepts every tool method call. Adding timing there gives duration metrics for every `db.execute()`, `event_bus.publish()`, and any other tool call automatically — zero changes to plugins or tools.

Two levels of detail to consider:

- **ToolProxy timing** — captures duration per tool method call. Sufficient for 80% of use cases. No external dependencies. Data can be exposed via a new `GET /system/metrics` endpoint or fed into the existing logger sink.
- **OTel driver-level connectors** (`opentelemetry-instrumentation-asyncpg`, etc.) — captures SQL query text, parameters, DB name, etc. Requires OTel (see Issue 9).

Recommendation: implement ToolProxy timing first as a standalone feature. OTel connectors are additive on top when Issue 9 is tackled.

```python
start = time.perf_counter()
result = await attr(*args, **kwargs)
duration_ms = (time.perf_counter() - start) * 1000
# emit to a registered metrics sink (same pattern as logger sinks)
```

---

**Issue 8 — ✅ Real-time causal tree via SSE**

`GET /system/traces/stream` — implemented in `domains/system/plugins/system_traces_stream_plugin.py`.

On connect sends a `snapshot` with the full current tree. Each new event emits a `node` message with `parent_id` so the client appends it to the correct place in the tree without rebuilding.

---

**Issue 9 — OpenTelemetry integration**

Add distributed tracing via OpenTelemetry without coupling the core to any specific library.

Agreed design:

- **`tools/telemetry/telemetry_tool.py`** — bootstraps the global `TracerProvider` via env vars (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_ENABLED`). Falls back to console exporter in development. Exposes `get_tracer(scope)` for plugins that want custom spans.
- **`ToolProxy` span factory** — proxy delegates span creation to a registrable `span_factory` callable. No OTel imports in the core. `TelemetryTool.setup()` registers the factory. `proxy_traced = False` on verbose tools (logger, telemetry itself).
- **`BaseTool.on_instrument(tracer_provider)`** — optional hook for each tool to instrument its own underlying framework (FastAPI, asyncpg, etc.). Keeps framework-specific instrumentation inside the tool that owns the framework.
- **`TelemetryTool.on_boot_complete`** — iterates all tools and calls `on_instrument`. The kernel must invoke this hook directly on tool instances (bypassing the proxy) to avoid marking tools as DEAD on instrumentation failure.
- **`HttpServerTool.on_instrument`** — calls `FastAPIInstrumentor.instrument_app(self.app)`. If the HTTP tool is swapped for Flask/Django, only this method changes.

What is gained over the existing causality system (`/system/traces`):
- Real HTTP span with method, path, status code, and latency as the trace root
- Tool call durations via the proxy
- Export to external platforms: Jaeger, Grafana Tempo, Datadog, etc.
- Cross-service distributed tracing via `traceparent` header propagation

Depends on Issue 7 (ToolProxy timing) as a prerequisite.
