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
| `bus.publish("x.y", {"id": 1})` (raw dict) | Define `XyPayload(BaseModel)` and publish `XyPayload(id=1).model_dump()` | The publisher owns the event contract; raw dicts are flagged `UNTYPED_PAYLOAD` by `/system/lint` |
| `await asyncio.sleep(0.1)` in a test, then asserting async delivery | `await wait_until(lambda: <condition>)` from `tests/helpers/async_wait.py` | A fixed sleep guesses a duration and flakes under CI CPU contention; polling passes as soon as delivery lands |

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

## 📨 Event Payload Schemas (Schema Registry Readiness)

Every event a plugin publishes has a Pydantic payload model, defined **inline in
the publisher plugin** — same place as its request/response schemas. The
publisher owns the event contract, exactly like a producer registers its schema
in a schema registry.

```python
# ── In the PUBLISHER plugin ─────────────────────────
class OrderCreatedPayload(BaseModel):
    id: int
    user_id: int
    total: float

await self.bus.publish("order.created", OrderCreatedPayload(
    id=order_id, user_id=req.user_id, total=req.total
).model_dump())
```

```python
# ── In a CONSUMER plugin (another domain) ───────────
# Never import the publisher's model (no cross-domain imports).
# Declare ONLY the fields this consumer needs — tolerant reader.
class OrderForBilling(BaseModel):
    id: int
    total: float

async def on_order_created(self, event):
    order = OrderForBilling(**event.payload)  # extra keys are ignored
```

Rules of the pattern:

- **Publish with a bare `.model_dump()`** — no arguments. `exclude_none=True`
  and friends can drop keys at runtime, so the linter refuses to trust them
  (`UNKNOWN_PAYLOAD`).
- **Consumers are tolerant readers**: they re-declare only the fields they
  read. This is not duplication — it is what decouples publisher evolution
  from consumers, and the `EventContractLinterPlugin` statically cross-checks
  that every field a consumer requires exists in every publish site.
- **Raw-dict publishes still work** but are flagged `UNTYPED_PAYLOAD`
  (info, advisory) in `GET /system/lint`.
- **Why**: when the event bus is swapped to Kafka (Roadmap Issue 18), each
  payload model's `model_json_schema()` is the JSON Schema the registry needs —
  the contracts are already written, no plugin changes. `GET /system/events/schemas`
  serves the full catalog (event → JSON Schema) today.

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

Constructor injection makes testing straightforward. In this project, we support and encourage two levels of testing:

### 1. Black-Box Integration Testing (Recommended for DB/State/Events)
To prevent fragile mocks and ensure database queries actually run and pass syntax and dialect checks:
- Do NOT mock `db`, `event_bus`, or `state` tools unless absolutely necessary.
- Use the real `SqliteTool` configured with `:memory:` (fast, self-contained, no external database files needed).
- Apply migrations dynamically to the in-memory database to establish the real schema.
- Assert on the final state of the database and event bus (Black-Box) rather than internal mock call assertions.

Example of a Black-Box Integration Test:
```python
import pytest
from tools.sqlite.sqlite_tool import SqliteTool
from tools.event_bus.event_bus_tool import EventBusTool
from tools.auth.auth_tool import AuthTool
from domains.users.plugins.create_user_plugin import CreateUserPlugin

@pytest.fixture
async def test_env():
    # Setup real db in memory
    db = SqliteTool()
    db._db_path = ":memory:"
    await db.setup()
    
    # Run the migrations needed for this domain
    with open("domains/users/migrations/001_create_users.sql", "r") as f:
        await db.execute(f.read())
        
    bus = EventBusTool()
    await bus.setup()
    
    auth = AuthTool()
    await auth.setup()
    
    yield db, bus, auth
    
    await db.shutdown()
    await bus.shutdown()

@pytest.mark.anyio
async def test_create_user_integration(test_env):
    db, bus, auth = test_env
    plugin = CreateUserPlugin(http=None, db=db, event_bus=bus, logger=None, auth=auth)
    
    # Input
    data = {"name": "John Doe", "email": "john@example.com", "password": "password123"}
    
    # Execute (Black Box)
    result = await plugin.execute(data)
    
    # Output Verification
    assert result["success"] is True
    assert result["data"]["email"] == "john@example.com"
    
    # Database Verification (No Mocks!)
    users = await db.query("SELECT * FROM users WHERE email = $1", ["john@example.com"])
    assert len(users) == 1
    assert users[0]["name"] == "John Doe"
```

### Waiting for Async Delivery (Events, Retries, DLQ)

Never assert right after a fixed `await asyncio.sleep(...)`. A fixed sleep
guesses how long delivery takes; under CI CPU contention the guess loses and
the test flakes. Poll the real condition instead:

```python
from tests.helpers.async_wait import wait_until

await bus.publish("user.created", payload)
await wait_until(lambda: len(received) == 1)  # returns as soon as delivery lands
```

The one legitimate fixed sleep is a **negative check** (asserting that nothing
arrives) — there is no condition to poll for, so a short fixed wait is correct
there.

For asserting a full event chain across domains (flow tests), use the chain
helper in `tests/helpers/trace_chains.py`.

### 2. Isolated Unit Testing (For pure business logic / third-party mocks)
If you only need to verify branch/flow logic or if you have complex external dependencies (e.g., third-party APIs):
- Mock the specific tools using `unittest.mock.AsyncMock` or `MagicMock`.
- Keep assertions focused on inputs/outputs and mock side-effects.

Example:
```python
from unittest.mock import AsyncMock, MagicMock
from domains.users.plugins.create_user_plugin import CreateUserPlugin

@pytest.mark.anyio
async def test_create_user_unit():
    mock_db = AsyncMock(execute=AsyncMock(return_value=42))
    plugin = CreateUserPlugin(
        http=MagicMock(), db=mock_db, event_bus=AsyncMock(),
        logger=MagicMock(), auth=MagicMock(hash_password=AsyncMock(return_value="hashed"))
    )
    result = await plugin.execute({"name": "Test", "email": "a@b.com", "password": "p"})
    assert result["success"] is True
    assert result["data"]["id"] == 42
```
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
-- depends: users/001_create_users.sql
CREATE TABLE IF NOT EXISTS orders (
    id     INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    ...
);
```

This works for same-domain or cross-domain dependencies. The `.sql` extension is optional in the depends value.

---

*`AI_CONTEXT.md` is auto-generated on every boot by the `context_manager` tool. It contains the live inventory of tools and domain models.*
