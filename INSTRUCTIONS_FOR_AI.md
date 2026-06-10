# 🤖 AI Agent Implementation Guide — Advanced Reference

> **For building plugins, read `AI_CONTEXT.md` only.** This file is for advanced topics: testing, observability, creating tools, and edge cases.

## ❌ Anti-Patterns (Common AI Mistakes)

These are the most frequent errors. Check these first before writing any code.

| Wrong | Correct | Why |
|-------|---------|-----|
| `async def on_event(self, data):` | `async def on_event(self, event: EventEnvelope):` | Subscribers now receive the full envelope, not raw data |
| `from domains.users.models.user import UserEntity` inside `orders` plugin | Define `OrderData` inline | No cross-domain imports |
| `class CreateUserRequest(BaseModel): name: str` (bare field) | `name: str = Field(min_length=1)` | FastAPI won't validate without constraints |
| `add_endpoint("/users", "POST", self.execute, ...)` without `response_model=` | Always pass `response_model=CreateUserResponse` | No OpenAPI docs generated |
| Logic inside `__init__` | Move to `on_boot()` or `execute()` | `__init__` is DI only |
| `import asyncio; asyncio.run(...)` inside a plugin | `await` or schedule via `scheduler` | Already inside an event loop |
| `?` placeholders in SQL | `$1, $2, $3...` | PostgreSQL-style; SQLite converts automatically |
| Returning the full Entity object (including `password_hash`) | Define a response schema with only the fields you expose | Leaks sensitive data |
| `from tools.http_server.http_server_tool import HttpServerTool` | Use DI: `def __init__(self, http)` | Hardcoded imports break tool swapping |
| Expecting automatic Kernel retries | Handle your own exceptions or use Tool-level resilience | **ToolProxy NO LONGER retries automatically** to prevent duplicates |
| `return {"success": False, "error": str(e)}` | `logger.error(e); return {"success": False, "error": "Generic Message"}` | `str(e)` leaks table names, paths, and internal logic |

---

## ⚠️ CRITICAL RULES (DO NOT IGNORE)

1. **`main.py` is sacred** — Never modify. It only boots the Kernel.
2. **Event Contract** — Subscribers receive `EventEnvelope`. Access data via `event.payload`.
3. **No Hidden Magic** — The Kernel does NOT retry failed tool calls. Idempotency is your responsibility.
4. **Safe Errors** — NEVER return `str(e)` to the client. Return safe, generic messages only.
5. **Event Bus Power** — Leverage `ttl`, `retries`, and `backoff` in `subscribe()` and `publish()`.
6. **DLQ Monitoring** — Final failures go to `_dlq.<event>`. Subscribe to it for error handling.

4. **No framework patterns** — No Routers, Controllers, or Services. Only Tools (infrastructure) and Plugins (business logic).
5. **No cross-domain imports** — Domains communicate exclusively via `event_bus`.
6. **CSRF Guard** — HTTP mutations (POST/PUT/DELETE) via cookie auth REQUIRE `X-Requested-With` header.
7. **Secure Cookies** — `context.set_cookie` defaults to `Secure=True`, `HttpOnly=True`, `SameSite=Lax`.
8. **Return format**: Always `{"success": bool, "data": ..., "error": ...}`.

---

## 🧭 Navigation

| Task | Section |
|---|---|
| New feature on existing domain | [Plugin](#-new-plugin) |
| New functional area from scratch | [Domain](#-new-domain) |
| New infrastructure capability | [Tool](#-new-tool) |

---

## 🧩 New Domain

Folder structure:
```
domains/{name}/
  __init__.py
  models/{name}.py        ← DB Entity only (mirrors the table)
  migrations/001_xxx.sql  ← Raw SQL, auto-executed on boot
  plugins/                ← 1 file = 1 feature
```

---

## ⚡ New Plugin

**Location**: `domains/{domain}/plugins/{feature}_plugin.py`
**Rule**: 1 File = 1 Feature. Schema defined inline.

```python
from typing import Optional
from pydantic import BaseModel, Field
from core.base_plugin import BasePlugin

class CreateProductPlugin(BasePlugin):
    def __init__(self, logger, event_bus, http, db):
        self.logger = logger
        self.bus = event_bus
        self.http = http
        self.db = db

    async def on_boot(self):
        self.http.add_endpoint(
            path="/products", method="POST",
            handler=self.execute,
            tags=["Products"]
        )
        # Leverage built-in retries for event subscribers
        await self.bus.subscribe("order.created", self.on_order_created, retries=3, backoff=1.0)

    async def execute(self, data: dict, context=None):
        try:
            # Action Phase
            # publish is fire-and-forget. Use ttl for expiring messages.
            await self.bus.publish("product.created", {"id": 123}, ttl=3600)
            return {"success": True, "data": {"id": 123}}
        except Exception as e:
            # Kernel won't retry db.execute! Handle idempotency here.
            return {"success": False, "error": str(e)}

    async def on_order_created(self, event) -> None:
        # event is an EventEnvelope
        self.logger.info(f"Order received: {event.payload}")
        # To participate in request() RPC, return a dict
        return {"processed": True}
```

---

## 🔧 New Tool

**Location**: `tools/{name}/{name}_tool.py`
**Rule**: Stateless, isolated, self-documented. Use `EventBusDriver` pattern for new transport layers.

---

## 🧪 Testing

### Event Bus Mocking
When testing plugins, remember they now expect an `EventEnvelope`.

```python
from tools.event_bus.event_bus_tool import EventEnvelope

async def test_plugin_on_event():
    plugin = MyPlugin(bus=AsyncMock())
    mock_event = EventEnvelope(
        event="test.event",
        payload={"key": "value"},
        emitter="TestEmitter"
    )
    await plugin.on_test_event(mock_event)
    # assert ...
```

---

## 📡 Observability Capabilities

### Tool call metrics via `registry`
Every tool call is timed by ToolProxy. Access last 1000 records via `registry.get_metrics()`.

### Native Pydantic Tracing
`event_bus.get_trace_history()` returns `List[TraceRecord]` (last 500 events).
Each `TraceRecord` has:
- `envelope`: The full `EventEnvelope` (metadata + payload).
- `subscribers`: List of names of handlers that received the event.

---

## 🗄️ Swapping the Database Engine
The `db` injection key is the contract. Plugins use `$1, $2...` placeholders. SQLite converts them internally to `?`.

## 🗄️ Migration Dependency Ordering
The kernel **always** applies migrations via topological sort. Without `-- depends:`, the order is the discovery order (alphabetical by domain → alphabetical by filename). When a migration requires another to have run first, declare it on the first comment line:

```sql
-- depends: users/001_create_users_table.sql
CREATE TABLE IF NOT EXISTS orders (
    id     SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    ...
);
```

This works for same-domain or cross-domain dependencies. The `.sql` extension is optional in the depends value.

---

*`AI_CONTEXT.md` is auto-generated on every boot by the `context_manager` tool. It contains the live inventory of tools and domain models.*
