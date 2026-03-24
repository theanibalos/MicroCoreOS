# HTTP Server — Complete Reference

> Tool injection key: `http`
> Backed by FastAPI + Uvicorn.

---

## Handler Signature

```python
async def execute(self, data: dict, context: HttpContext) -> dict:
```

`data` is a **flat merge** of path params + query params + request body. All in one dict, no nesting.

`context` provides response controls: `set_status()`, `set_header()`, `set_cookie()`.

---

## Endpoints

### `add_endpoint(path, method, handler, ...)`

Registers a REST endpoint. Must be called in `on_boot()`.

```python
self.http.add_endpoint(
    path="/users/{user_id}",
    method="GET",
    handler=self.execute,
    tags=["Users"],
    request_model=GetUserRequest,       # optional — Pydantic model for body/query validation
    response_model=GetUserResponse,     # required — generates OpenAPI docs
    auth_validator=self.validate_token, # optional — JWT guard
)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | FastAPI path, supports `{param}` syntax |
| `method` | `str` | `"GET"`, `"POST"`, `"PUT"`, `"DELETE"`, `"PATCH"` |
| `handler` | `callable` | Plugin method to call |
| `tags` | `list[str]` | OpenAPI tag grouping |
| `request_model` | `BaseModel` | Pydantic model for input validation |
| `response_model` | `BaseModel` | Pydantic model for output schema |
| `auth_validator` | `async callable` | `async fn(token: str) -> dict \| None` |

**Auth validator**: receives the Bearer token, returns the decoded payload or `None`. If `None`, the request is rejected with 401. The payload is injected into `data["_auth"]`.

```python
async def validate_token(self, token: str) -> dict | None:
    return self.auth.validate_token(token)

async def execute(self, data: dict, context=None):
    user_id = data["_auth"]["sub"]  # from JWT payload
```

**Path parameters** are extracted from `{param}` segments and merged into `data`:

```python
# Path: /users/{user_id}
# Request: GET /users/42
# data["user_id"] == "42"
```

**Automatic route ordering**: endpoints are buffered during `on_boot()` and registered in `on_boot_complete()`. Static routes (e.g., `/users/me`) are always registered before parameterized routes (e.g., `/users/{id}`). You do not need to control registration order.

**Validation errors**: on Pydantic validation failure (422), the response includes ALL validation errors at once, not just the first:

```json
{
  "detail": "Validation failed",
  "errors": [
    {"loc": ["body", "email"], "msg": "value is not a valid email address"},
    {"loc": ["body", "name"], "msg": "String should have at least 1 character"}
  ]
}
```

---

### `add_sse_endpoint(path, generator, tags=None, auth_validator=None)`

Server-Sent Events endpoint. Clients connect once and receive a stream of messages.

```python
self.http.add_sse_endpoint(
    "/my/stream",
    generator=self._stream,
    tags=["MyDomain"],
)

async def _stream(self, data: dict):
    import json
    while True:
        record = await self._queue.get()
        yield f"data: {json.dumps(record)}\n\n"
```

The generator is an async generator. Client disconnect is detected automatically — the `finally` block of the generator runs for cleanup:

```python
async def _stream(self, data: dict):
    queue = asyncio.Queue(maxsize=200)
    self._queues.add(queue)
    try:
        while True:
            record = await queue.get()
            yield f"data: {json.dumps(record)}\n\n"
    finally:
        self._queues.discard(queue)  # cleanup on disconnect
```

**Slow consumers**: if a queue fills up (`maxsize=200`), new records are dropped silently. This prevents memory growth from slow or stalled clients.

---

### `add_ws_endpoint(path, on_connect, on_disconnect=None)`

WebSocket endpoint.

```python
self.http.add_ws_endpoint(
    "/ws/chat",
    on_connect=self.on_connect,
    on_disconnect=self.on_disconnect,
)

async def on_connect(self, websocket):
    await websocket.accept()
    async for message in websocket.iter_text():
        await websocket.send_text(f"echo: {message}")

async def on_disconnect(self, websocket):
    pass
```

---

### `mount_static(path, directory_path)`

Serve static files from a directory.

```python
self.http.mount_static("/static", "domains/frontend/static")
```

---

## HttpContext

The `context` parameter in handlers provides response controls.

```python
async def execute(self, data: dict, context=None):
    if not found:
        context.set_status(404)
        return {"success": False, "error": "Not found"}

    context.set_header("X-Custom", "value")
    context.set_cookie("session", token, httponly=True, samesite="strict")
    return {"success": True, "data": {...}}
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `set_status` | `(code: int)` | Override HTTP status code (default: 200) |
| `set_header` | `(key: str, value: str)` | Add response header |
| `set_cookie` | see below | Set a response cookie |
| `status_code` | `→ int` (property) | Read back the currently set status code |

**`set_cookie` full signature:**

```python
context.set_cookie(
    key: str,
    value: str,
    max_age: int = 3600,     # seconds until expiry
    httponly: bool = True,   # not accessible via JavaScript
    samesite: str = "lax",   # "lax", "strict", or "none"
    secure: bool = False,    # HTTPS only — set True in production
    path: str = "/",
)
```

Defaults are security-conscious: `httponly=True` and `samesite="lax"` out of the box. Set `secure=True` when serving over HTTPS.

---

## Automatic Security Headers

Every HTTP response automatically includes:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

No configuration required. Applied via FastAPI middleware to all routes.

---

## CORS Configuration

Configured via environment variable. No code changes needed.

```bash
# Allow all origins (default — development)
HTTP_CORS_ORIGINS=*

# Restrict to specific origins (production)
HTTP_CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

CORS middleware applies to all routes automatically.

---

## X-Request-ID — Distributed Tracing

When a request arrives with an `X-Request-ID` header, the bus uses that value as the causality ID for all events triggered during that request. Without it, a fresh UUID is generated.

This means: if Service A calls Service B and passes its current event ID as `X-Request-ID`, Service B's entire event chain will be nested under Service A's trace tree as children.

```
# Service A sends:
GET /orders/process
X-Request-ID: abc-123

# Service B's events all have parent_id: "abc-123"
# Both services' traces stitch into one causal tree
```

No plugin code required. The HTTP server sets `current_event_id_var` automatically before calling the handler.

---

## Raw Body Fallback

If `request_model` is not provided, the server attempts to parse the raw JSON body and merges it into `data`. This enables untyped endpoints:

```python
self.http.add_endpoint("/webhook", "POST", self.handle)

async def handle(self, data: dict, context=None):
    payload = data  # raw JSON body merged in
```

Always prefer `request_model` for type safety and OpenAPI documentation.

---

## OpenTelemetry — HTTP Spans

When `OTEL_ENABLED=true` and `opentelemetry-instrumentation-fastapi` is installed, every HTTP request gets a span with:
- HTTP method
- Route template (e.g., `/users/{user_id}`, not the actual path)
- Status code
- Latency (full request duration, wall clock)

```bash
uv add opentelemetry-instrumentation-fastapi
OTEL_ENABLED=true
```

This is the only way to get **total request duration** (handler start to response sent). Tool-level timing via `registry.get_metrics()` covers internal tool calls but not the HTTP layer overhead.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_PORT` | `5000` | Server port |
| `HTTP_HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` for Docker/network access |
| `HTTP_LOG_LEVEL` | `warning` | Uvicorn log level: `debug`, `info`, `warning`, `error`, `critical` |
| `HTTP_CORS_ORIGINS` | `*` | CORS allowed origins (comma-separated or `*`) |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry instrumentation |

> **Docker / container note**: The default host `127.0.0.1` only accepts connections from the same machine. To expose the server outside the container, set `HTTP_HOST=0.0.0.0`.
