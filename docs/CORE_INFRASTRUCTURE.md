# Core Infrastructure — Complete Reference

> These are the internals that operate automatically. Understanding them helps when building
> tools, debugging unexpected behavior, or extending the framework.

---

## Kernel

**File**: `core/kernel.py`

The Kernel auto-discovers and boots everything. `main.py` never changes — it only instantiates and starts the Kernel.

### Boot sequence

```
1. Tools registered manually in main.py → Container.register()
2. Kernel.boot()
   a. setup() called on each tool (connections, env vars)
   b. Plugins discovered: domains/*/plugins/*.py
   c. Plugin dependencies resolved by __init__ parameter names
   d. on_boot() called on each plugin (register routes, subscribe to events)
   e. on_boot_complete(container) called on each tool (all tools ready)
   f. on_boot_complete() called on each plugin (post-boot tasks)
3. Server is live
```

### Plugin dependency resolution

The Kernel inspects each plugin's `__init__` signature and resolves parameters by name against the tool registry:

```python
class MyPlugin(BasePlugin):
    def __init__(self, db, http, event_bus):
        # Kernel finds tools named "db", "http", "event_bus" and injects them
```

If a required tool is not found, the plugin is marked `DEAD` and skipped. This is intentional — plugins fail individually, not the whole system.

**Special parameter: `container`**

A plugin can request the `Container` instance directly by declaring a `container` parameter. The Kernel handles this as a special case before looking up tools:

```python
class MyAdvancedPlugin(BasePlugin):
    def __init__(self, container):
        self.container = container

    async def on_boot(self):
        raw_tools = self.container.get_raw_tools()  # bypasses ToolProxy
```

This is for advanced use only. Normal plugins should always use named tool injection. The only legitimate use case is system introspection tools that need access to all tool instances.

**Optional parameters with defaults**

If a parameter has a default value and the matching tool is not found, the default is used instead of marking the plugin DEAD:

```python
class MyPlugin(BasePlugin):
    def __init__(self, db, cache=None):
        # if no tool named "cache" exists, self.cache = None
        self.db = db
        self.cache = cache
```

**Parallel tool setup**

All tools run `setup()` in parallel via `asyncio.gather()`. Tools are independent by design (no tool imports another), so this is safe. Consequence: if your tool's `setup()` depends on another tool being ready, that is an architectural violation.

### Sync/async transparency

Plugins can use `def` or `async def` interchangeably:

```python
def on_boot(self):           # sync — offloaded to asyncio.to_thread()
    self.http.add_endpoint(...)

async def on_boot(self):     # async — awaited directly
    await self.bus.subscribe(...)
```

The Kernel's `_call_maybe_async()` handles both cases. CPU-heavy work in a sync method does not block the event loop.

---

## Container

**File**: `core/container.py`

The Container holds all tool instances wrapped in `ToolProxy`. It is the single source of truth for tool access.

### ToolProxy — what wraps every tool call

Every tool method call goes through `ToolProxy`, which adds three things automatically:

1. **Timing**: `time.perf_counter()` measures `duration_ms` with microsecond precision
2. **Status tracking**: on exception, the tool is marked `DEAD` in the Registry. On subsequent success, marked `OK` with message "Recovered from transient failure"
3. **OTel span**: if a span factory is registered (TelemetryTool does this), a span wraps the call

None of this requires any code in the tool or plugin.

### Metrics buffer

Every tool call emits a metric record to a circular buffer:

```python
{
    "tool": "db",
    "method": "execute",
    "duration_ms": 12.375,
    "success": True,
    "timestamp": 1742834523.123456
}
```

Buffer holds last **1000 records**. Older records are discarded automatically.

Access via `registry.get_metrics()` or real-time via `registry.add_metrics_sink(callback)`.

The sink is called **synchronously** on every tool call. Keep it fast. To do async work from a sync sink:

```python
def _on_metric(self, record: dict) -> None:
    if record["duration_ms"] > 500:
        asyncio.create_task(self.bus.publish("alert.slow_tool", record))
```

### OTel span factory

TelemetryTool registers a span factory with the Container:

```python
container.register_span_factory(factory)
# factory(tool: str, method: str) → context manager
```

After registration, every subsequent tool call is wrapped in an OTel span. Tools registered before the factory still get timed and tracked — just without spans.

### Raw tool access

`container.get_raw_tools()` bypasses ToolProxy and returns the actual tool instances. Used by TelemetryTool to call `on_instrument()` without risking marking a tool as DEAD if instrumentation fails.

---

## Registry

**File**: `core/registry.py` (internal) + `tools/system/registry_tool.py` (public)

Tracks the live state of all tools and plugins.

### Tool status

| Status | Meaning |
|--------|---------|
| `OK` | Last call succeeded, or health check passed |
| `FAIL` | Health check failed (set by ToolHealthPlugin) |
| `DEAD` | Raised an exception (set by ToolProxy) |

ToolProxy sets `DEAD` reactively when a tool raises. It sets `OK` when the same tool succeeds after being `DEAD` ("recovered from transient failure"). This means a tool that silently stopped responding (e.g., a hung connection) may still show `OK` until the next call fails.

For proactive detection, use `ToolHealthPlugin` — it calls `health_check()` on tools at a configurable interval.

### Plugin status

| Status | Meaning |
|--------|---------|
| `BOOTING` | `__init__` completed, `on_boot()` not yet called |
| `RUNNING` | `on_boot()` completed successfully |
| `READY` | `on_boot_complete()` completed successfully |
| `DEAD` | Failed during boot or a required tool was unavailable |

### `get_system_dump()`

Full live snapshot of the system:

```python
{
    "tools": {
        "db": {"status": "OK", "message": None},
        "event_bus": {"status": "OK", "message": None}
    },
    "plugins": {
        "CreateUserPlugin": {
            "status": "RUNNING",
            "error": None,
            "domain": "users",
            "class": "CreateUserPlugin",
            "dependencies": ["db", "http", "event_bus", "logger"]
        }
    },
    "domains": {...}
}
```

---

## ContextVars

**File**: `core/context.py`

Two `contextvars.ContextVar` instances propagate execution context through async tasks:

### `current_event_id_var`

Set by the EventBus before calling each subscriber. Value: the UUID of the event being dispatched.

Used for:
- `parent_id` in new events published during subscriber execution (automatic causal chain)
- `X-Request-ID` header sets this for HTTP-triggered chains

### `current_identity_var`

Set by the EventBus before calling each subscriber. Value: `"PluginClass.method_name"`.

Used for:
- Logger attribution: every `logger.info()` inside a subscriber is tagged with the plugin name
- EventBus trace records: `emitter` field uses this value

Both vars are **reset in the `finally` block** of each dispatch. They do not leak between subscribers.

---

## Database Tools

### SQLite — undocumented behaviors

**File**: `tools/sqlite/sqlite_tool.py`

**WAL mode**: Write-Ahead Logging is enabled automatically on every connection. This improves concurrent read/write performance and is the recommended mode for production SQLite.

**Foreign keys**: `PRAGMA foreign_keys = ON` is set automatically. SQLite does not enforce foreign keys by default. This enables referential integrity constraints in migration files.

**Placeholder normalization**: `$1, $2, $3...` (PostgreSQL style) are converted to `?` (SQLite native) transparently. This makes SQLite a drop-in replacement for the PostgreSQL tool — plugins never change.

**Migration dependency ordering**: migration files can declare dependencies on other files:

```sql
-- depends: users/001_create_users.sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id)
);
```

The SQLite tool parses these comments and topologically sorts migrations before execution. If two files have no dependency relationship, they run alphabetically. If a circular dependency is detected, falls back to alphabetical order.

---

## Auth Tool

**File**: `tools/auth/auth_tool.py`

### Environment variables (undocumented)

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_SECRET_KEY` | required | Secret for JWT signing |
| `AUTH_ALGORITHM` | `HS256` | JWT algorithm |
| `AUTH_TOKEN_EXPIRE_MINUTES` | `60` | Token expiry in minutes |

`AUTH_TOKEN_EXPIRE_MINUTES` can be overridden per-token by passing `expires_delta` to `create_token()`.

---

## Telemetry Tool

**File**: `tools/telemetry/telemetry_tool.py`

### No-op tracer

When `OTEL_ENABLED` is `false` or OTel packages are not installed, `get_tracer()` returns a `_NoOpTracer` that returns `contextlib.nullcontext()` for `start_as_current_span()`.

This means plugin code can use the telemetry tool unconditionally:

```python
class MyPlugin(BasePlugin):
    def __init__(self, telemetry, db, http):
        self.telemetry = telemetry

    async def execute(self, data: dict, context=None):
        tracer = self.telemetry.get_tracer("my_plugin")
        with tracer.start_as_current_span("my_operation"):
            # runs normally with or without OTel installed
            result = await self.db.query(...)
```

No `if otel_enabled` guards needed.

### Driver-level instrumentation

Tools can implement `on_instrument(tracer_provider)` to add framework-specific spans:

```python
class MyTool(BaseTool):
    async def on_instrument(self, tracer_provider) -> None:
        # Called by TelemetryTool after boot, bypassing ToolProxy
        # Add spans, instrument frameworks, etc.
        MyFrameworkInstrumentor.instrument(tracer_provider=tracer_provider)
```

The HTTP server tool uses this to instrument FastAPI with `FastAPIInstrumentor`, adding per-request spans with method, route, status code, and latency.

---

## ContextTool — AI_CONTEXT.md Auto-Generation

**File**: `tools/context/context_tool.py`

On `on_boot_complete()`, the ContextTool does two things automatically:

1. **Scans all domain models**: reads every file in `domains/*/models/*.py` and stores its contents in the Registry as domain metadata. This is what `registry.get_domain_metadata()` returns.

2. **Regenerates `AI_CONTEXT.md`**: overwrites the file at the project root with a fresh snapshot of all tools (from their `get_interface_description()`) and all domains (parsed from plugin files using regex to extract HTTP endpoints and published events).

This means `AI_CONTEXT.md` is **computed on every boot**, not handwritten. It reflects the live state of the system. If you add a new plugin with a new endpoint, `AI_CONTEXT.md` updates automatically after the next boot.

**Do not edit `AI_CONTEXT.md` manually** — changes will be overwritten on next boot.

---

## Logger Tool

**File**: `tools/logger/logger_tool.py`

### Sink pattern with identity

```python
def my_sink(level: str, message: str, timestamp: str, identity: str) -> None:
    # identity = "CreateUserPlugin.execute" (from current_identity_var)
    pass

self.logger.add_sink(my_sink)
```

`identity` is always the current plugin/tool context. This enables sinks to attribute logs to specific components without parsing the message.

Used by `SystemLogsStreamPlugin` to broadcast logs to SSE clients.

---

## Health Check Pattern

`ToolHealthPlugin` calls `health_check()` on tools that implement it:

```python
class MyTool(BaseTool):
    async def health_check(self) -> bool:
        try:
            await self._ping()
            return True
        except Exception:
            return False
```

If `health_check()` returns `False`, the Registry marks the tool as `FAIL`. If it raises, the tool is marked `DEAD`.

Configure interval:

```bash
HEALTH_CHECK_INTERVAL=30  # seconds, default: 30
```

Tools that do not implement `health_check()` are skipped by the health checker. Their status is only updated reactively by ToolProxy when a real call fails.

> **Current scope**: The built-in `ToolHealthPlugin` only calls `health_check()` on the `db` tool. All other tools rely on reactive detection by ToolProxy. To monitor additional tools, create a new plugin in the `system` domain that calls `health_check()` on the specific tool and calls `registry.update_tool_status()` with the result.
