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
7. **No framework patterns** — No Routers, Controllers, or Services. Only Tools (infrastructure) and Plugins (business logic).
8. **No cross-domain imports** — Domains communicate exclusively via `event_bus`.
9. **CSRF Guard** — HTTP mutations (POST/PUT/DELETE) via cookie auth REQUIRE `X-Requested-With` header.
10. **Secure Cookies** — `context.set_cookie` defaults to `Secure=True`, `HttpOnly=True`, `SameSite=Lax`.
11. **Return format**: Always `{"success": bool, "data": ..., "error": ...}`.

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
            self.logger.error(f"Failed to create product: {e}")
            return {"success": False, "error": "Could not create product"}

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

### The Parity Rule (Contract over Implementation)
Any replacement tool (e.g., swapping SQLite for PostgreSQL, or In-Memory State
for Redis) MUST pass the **Parity Suite** of the reference implementation it
replaces. This ensures that plugins remain infrastructure-blind and behavior
is consistent across backends.

**Canonical examples:**
- `tests/tools/test_state_parity.py`: Verifies that `RedisStateTool` behaves
  exactly like the default in-memory `StateTool`.
- `tests/tools/test_event_bus_broker_parity.py`: Parametrized suite that
  runs against both the local driver and `RedisStreamsDriver`.

**Health contract (optional, only for tools with an external backend)**:
If the tool talks to an external service (DB, S3, broker...), make its
connection-error class inherit `ToolUnavailableError` so ToolProxy marks it
DEAD on the first infrastructure failure:

```python
from core.base_tool import BaseTool, ToolUnavailableError

class RedisError(Exception): ...                                    # business errors
class RedisConnectionError(RedisError, ToolUnavailableError): ...   # infra -> DEAD immediately
```

In-memory/local tools (state, logger, scheduler...) skip this entirely — the
fallback (DEAD after 5 consecutive failures) covers every tool automatically.

---

## 🚦 Rate Limiting Pattern

There is **no `rate_limiter` tool, by design**. Rate limiting splits into two
layers, and neither needs one:

- **Volumetric / anonymous (per-IP, anti-abuse, DDoS)** → belongs to the edge
  (nginx, gateway, CDN), never to the monolith. See the edge section in
  `docs/ELASTIC_DEPLOYMENT.md`.
- **Identity-aware (per-user, per-API-key, per-plan quotas)** → business
  policy, implemented in the plugin with the `state` tool primitive:

```python
async def execute(self, data: dict, context=None):
    attempts = await self.state.increment(
        f"login:{req.email}", namespace="rate_limit", ttl=900  # 15-min window
    )
    if attempts > 5:
        context.set_status(429)
        context.set_header("Retry-After", "900")
        return {"success": False, "error": "Too many attempts. Try again later."}
    # ... normal handling
```

Rules of the pattern:

- **Key by identity** (user id, email, API key) — never by IP (that is the
  edge's job).
- **Fixed window**: `increment()` applies the TTL only when the key is
  created, so the counter resets `ttl` seconds after the first hit. A client
  can burst up to 2× the limit across a window boundary — acceptable for
  quotas and throttles. If a real case ever demands sliding-window precision,
  that is the moment to introduce a tool, not before.
- **`Retry-After`**: the state contract does not expose remaining TTL, so use
  the window size as a conservative upper bound.
- **Distribution is free**: with `RedisStateTool` swapped in
  (`extras/available_tools/redis_state/`), the same code enforces the limit
  across all replicas.

---

## 🔐 User Roles & Authorization Pattern

Roles are **business data**, not infrastructure. The `auth` tool remains
infrastructure-blind (it only handles signing/verifying strings), while the
`users` domain manages the roles.

- **Storage**: roles are a column in the `users` table (JSON array in SQLite).
- **Claims**: `LoginPlugin` fetches roles and includes them in the JWT claims.
- **Consumption**: plugins read `data["_auth"]["roles"]` for general authorization.

### The Hybrid Authorization Rule
For standard operations, trust the claims in the token. For **critical
operations** (financial transactions, privilege escalation, destructive
actions), perform a **fresh check** against the database to catch late
revocations or role changes that happened after the token was issued:

```python
async def execute(self, data: dict, context=None):
    roles = data.get("_auth", {}).get("roles", [])
    
    # 1. Fast check (claims)
    if "admin" not in roles:
        return {"success": False, "error": "Forbidden"}

    # 2. Fresh check (critical ops only)
    user_id = data["_auth"]["sub"]
    user = await self.db.query_one("SELECT roles FROM users WHERE id = $1", [user_id])
    fresh_roles = json.loads(user["roles"])
    if "admin" not in fresh_roles:
         return {"success": False, "error": "Privileges revoked"}
    
    # ... proceed
```

---

## 🧪 Testing
...
---

## 📦 Available Extras

The project includes pre-built tools and domains in the `extras/` folder. These
are not active by default to keep the core lean.

### Activating an Extra
To activate an extra, move its folder to the corresponding core directory
(`tools/` or `domains/`). The Kernel will auto-discover and boot it on the next
restart.

- **PostgreSQL**: Move `extras/available_tools/postgresql/` to `tools/postgresql/`.
  Ensure `DATABASE_URL` is set in `.env`. It will take over the `db` injection
  key if the default `sqlite` tool is removed or if it registers with the same
  name.
- **Redis State**: Move `extras/available_tools/redis_state/` to `tools/redis_state/`
  to swap the in-memory `state` for a distributed one.
- **Chaos Tool/Domain**: Used for resilience testing. Move from `extras/` to
  `tools/` or `domains/` to enable.

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
