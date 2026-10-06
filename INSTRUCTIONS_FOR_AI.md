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
| `if "UNIQUE" in str(e):` (deciding by the error's text) | `if getattr(e, "kind", None) == "unique_violation":` | Each engine words its errors differently; the db tool classifies them into a closed vocabulary so the branch survives a tool swap |
| `bus.publish("x.y", {"id": 1})` (raw dict) | Define `XyPayload(BaseModel)` and publish `XyPayload(id=1).model_dump()` | The publisher owns the event contract; raw dicts are flagged `UNTYPED_PAYLOAD` by `/system/lint` |
| `await asyncio.sleep(0.1)` in a test, then asserting async delivery | `await wait_until(lambda: <condition>)` from `tests/helpers/async_wait.py` | A fixed sleep guesses a duration and flakes under CI CPU contention; polling passes as soon as delivery lands |

---

## ⚠️ The rules

The **Non-Negotiable Rules** in `AGENTS.md`, there and nowhere else. Never
restate them here, and never cite them with a count: a rival copy, or a number
that another file has to keep in step, is one more thing that can disagree with
the list an agent is standing in front of.

Event bus capabilities (`ttl`, `retries`, `backoff`, DLQ) are in `AI_CONTEXT.md`
§ Tool: `event_bus`, generated from the tool itself so they cannot drift.

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

`AI_CONTEXT.md` § **Plugin Authoring Guide** — one complete template per
deliverable type, regenerated on every boot from `tools/context/authoring_guide.md` and
already inside every executor prompt. Never copy it here: the generated one
is the only one that tracks the code.

If you are writing a plugin you are an executor: nothing in this file is for you.

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

**Location**: `tools/{name}/{name}_tool.py`, with its own tests in
`tools/{name}/tests/`, named `{name}_tool_test.py` — NEVER `test_{name}_tool.py`,
which the Kernel would import at boot. They travel with the tool when it is installed or swapped.
**Rule**: Stateless, isolated, self-documented. Use `EventBusDriver` pattern for new transport layers.

### The Parity Rule (Contract over Implementation)
Any replacement tool (e.g., swapping SQLite for PostgreSQL, or In-Memory State
for Redis) MUST pass the **Parity Suite** of the reference implementation it
replaces. This ensures that plugins remain infrastructure-blind and behavior
is consistent across backends.

**Framework-maintainer references (not shipped in generated applications):**
- `tests/tools/state/test_state_parity.py`: Verifies that `RedisStateTool` behaves
  exactly like the default in-memory `StateTool`.
- `tests/tools/event_bus/test_event_bus_broker_parity.py`: Parametrized suite that
  runs against both the local driver and `RedisStreamsDriver`.

**Health contract (optional, only for tools with an external backend)**:
If the tool talks to an external service (DB, S3, broker...), make its
connection-error class inherit `ToolUnavailableError` so ToolProxy marks it
DEAD on the first infrastructure failure:

```python
from microcoreos import BaseTool, ToolUnavailableError

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

### Which level? One rule

**Mock the input and the output. Use the real tool the moment you assert persistence.**

| What the test asserts | Level | Why |
|---|---|---|
| Returned dict, branch logic, error paths | **Mock** (level 2) | Nothing durable is being claimed; a real DB adds setup and no confidence |
| Rows in a table, state after a swap, an event a consumer actually received | **Real tool** (level 1) | The claim IS the persisted state — see below |

The reason the second row is not negotiable: a mocked `db` lets you assert
*"`execute` was called with this SQL string"*. That verifies the plugin talks
to a contract; it does **not** verify the SQL works against the schema. A
typo'd column, a `NOT NULL` the migration declares and the INSERT never fills,
a type SQLite accepts and PostgreSQL rejects — every one of those passes a
mocked test and fails in production. Once you assert on a table, you need the
table.

A plugin that both validates and writes is not a dilemma: test the validation
branches with mocks and the write with the real tool. They are different tests.

**Most plugin tests here are mocked, and that is correct** — the majority of
plugins are input → output. Reach for level 1 when the subject is the durable
effect, not by default.

**What mocks cannot catch, and what covers it.** A mocked test verifies the
plugin against a contract the test itself declares, so if a tool's real API
drifts the mock keeps passing. That gap is closed elsewhere, not by your test:
the `ToolDocDriftLinter` (boot + `/system/lint`) compares each tool's
documented interface against its implementation, and the parity suites
(`tests/tools/state/test_state_parity.py`,
`tests/tools/event_bus/test_event_bus_broker_parity.py`) hold swappable tools to one
behaviour. Those parity suites live in the framework repository, not in a
scaffolded application's `tests/`. They cover their declared cases, not every
SQL construct or every integration path. Plugin tests must still verify their
own persistence and HTTP security behavior.

### Ask for tools the way the plugin does

A plugin never builds a tool: it names one in `__init__` and the Kernel hands
it over. pytest injects by parameter name too, so **a test uses the same
vocabulary**. The generated root `conftest.py` provides `db`, `event_bus`,
`auth`, `state`, `config`, `mock_logger` and `mock_state`, plus `anyio_backend`.
Inject `mock_logger` as the plugin's `logger` argument; do not assume a real
`logger` fixture exists in generated applications. The framework's own
conftest has a different fixture set.

For a complete application example, see **Black-Box Integration Testing** below.
No tool imports, manual setup/teardown or hand-built schema are needed.
Framework maintainers can additionally consult
`tests/core/test_plugin_di_fixtures.py`; that file is not shipped to applications.

- `@pytest.mark.migrations("users", "system")` applies those domains' real
  migration files. **No marker = a real but empty database**, which is what a
  test that never touches a table wants.
- The `db` fixture resolves the **active** db tool, so these tests keep working
  after a PostgreSQL swap instead of dying at collection on a hardcoded import.
- Fixtures drive setup/shutdown tolerating sync OR async, exactly as the Kernel
  does — `LoggerTool.shutdown()` is sync, `SqliteTool.shutdown()` is not.
- Need something these do not give you? Declare your own fixture with that
  name; a local one always overrides the shared one.

### Deliberate constraint divergence

The `FieldDivergenceLinter` warns when sibling plugins in a domain validate the
same field differently. When that is on purpose, record it where it happens —
do not leave the warning standing:

```python
password: str = Field(
    min_length=1,
    json_schema_extra={"divergence_ok": "login verifies against the hash"},
)
```

The reason is required (an empty one is ignored), and the waived declaration
drops out of the comparison — the others are still compared with each other.

**Prefabs — read these before hand-rolling setup:**

| Helper | For |
|---|---|
| `tests/helpers/mock_db.py` | `async with db.transaction()` — a bare `AsyncMock` crashes there. `TxMock` / `FailingTxMock` |
| `tests/helpers/active_db.py` | A real DB tool with the domain's real migrations applied |
| `tests/helpers/async_wait.py` | `wait_until(...)` instead of a fixed sleep. Pass `describe=` so a rare timeout reports the observed state, not `<lambda at 0x...>` |
| `tests/helpers/trace_chains.py` | Asserting a full event chain across domains |

### 1. Black-Box Integration Testing (For DB/State/Event Effects)

Use real fixtures when asserting persisted rows, state or actual event delivery.
The `db` fixture selects the active backend and the migrations marker applies
real domain migrations through its runner. Do not hardcode SQLite, set private
DB attributes, or pass a whole migration file to `db.execute()`.

Complete example for a generated application **after `microcoreos add auth`**,
with the generated root `conftest.py` and its dependencies installed. Save at
the `test:` path declared by the plan (for example,
`tests/domains/users/test_create_user_plugin.py`):

```python
from unittest.mock import MagicMock

import pytest

from domains.users.plugins.create_user_plugin import CreateUserPlugin

pytestmark = pytest.mark.anyio


@pytest.mark.migrations("users")
async def test_create_user_persists(db, event_bus, auth, mock_logger):
    plugin = CreateUserPlugin(
        http=MagicMock(), db=db, event_bus=event_bus,
        auth=auth, logger=mock_logger,
    )
    result = await plugin.execute({
        "name": "Ana", "email": "a@b.com", "password": "secret123",
    })
    assert result["success"] is True
    rows = await db.query(
        "SELECT name, email, password_hash FROM users WHERE email = $1",
        ["a@b.com"],
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "Ana"
    assert await auth.verify_password("secret123", rows[0]["password_hash"])
```

This tests persistence, not HTTP middleware. Authentication, cookie/CSRF
behavior and HTTP status codes need tests through the registered HTTP endpoint;
calling `plugin.execute()` directly bypasses that pipeline.

### Waiting for Async Delivery (Events, Retries, DLQ)

Never assert right after a fixed `await asyncio.sleep(...)`. A fixed sleep
guesses how long delivery takes; under CI CPU contention the guess loses and
the test flakes. Poll the real condition instead:

```python
from tests.helpers.async_wait import wait_for_dlq, wait_until

await bus.publish("user.created", payload)
await wait_until(lambda: len(received) == 1)  # returns as soon as delivery lands
```

For **DLQ events** always use `wait_for_dlq(bus, "user.created")`, never plain
`wait_until` and never a hand-picked timeout: the DLQ only fires after retries
exhaust their exponential backoff, which can exceed `wait_until`'s default
timeout — the helper derives its deadline from the retries/backoff the
subscribers declared.

The one legitimate fixed sleep is a **negative check** (asserting that nothing
arrives) — there is no condition to poll for, so a short fixed wait is correct
there.

For asserting a full event chain across domains (flow tests), use the chain
helper in `tests/helpers/trace_chains.py`.

### 2. Isolated Unit Testing (For pure business logic / third-party mocks)
If you only need to verify branch/flow logic or if you have complex external dependencies (e.g., third-party APIs):
- Mock the specific tools using `unittest.mock.AsyncMock` or `MagicMock`.
- Keep assertions focused on inputs/outputs and mock side-effects.
- Any method the plugin uses as `async with` must be overridden with
  `MagicMock` — a bare `AsyncMock` yields a coroutine there and crashes. For
  `db.transaction()` use the prefab helpers:
  `db.transaction = MagicMock(return_value=TxMock())` (happy path) or
  `FailingTxMock()` (sad path), from `tests.helpers.mock_db`.

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

```bash
microcoreos add postgres
```

One command does all three acts: installs the optional dependency, moves the
source out of `extras/` into `tools/` (and `domains/` for a pair), and appends
the extra's settings to `.env` without overwriting values already there. Run
`microcoreos add` with no argument to list what is available.

For a replacement, **also move the previous implementation outside `tools/`**
before booting. `microcoreos add postgres` does not remove SQLite: keep exactly
one active tool with the `db` name. Preserve its source and database for rollback.
Review every migration and plugin SQL statement for the target engine before
switching; see `docs/ELASTIC_DEPLOYMENT.md`, Stage 1.

Manual equivalent (run from the project root, with no server running):

```bash
uv add 'microcoreos[postgres]'                     # 1. the library
mkdir -p retired_tools
mv tools/sqlite retired_tools/                    # preserve, outside discovery
mv extras/available_tools/postgresql tools/        # 2. the replacement source
# 3. set PG_HOST, PG_PORT, PG_USER, PG_PASSWORD and PG_DATABASE in .env
```

Set these variables to your actual PostgreSQL connection settings; the tool
does not read `DATABASE_URL`. Retiring SQLite does not migrate its data.

Skipping step 1 does not fail quietly — the Kernel reports a load error for
that file at boot (`No module named 'asyncpg'`). Skipping step 2 does nothing
at all: the Kernel only discovers what is under `tools/` and `domains/`.

| Extra | Package step | Folder step |
|---|---|---|
| **PostgreSQL** — replaces `db`; retire SQLite and set `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE` | `uv add 'microcoreos[postgres]'` | `mv extras/available_tools/postgresql tools/` |
| **Redis State** — swaps in-memory `state` for a distributed one | `uv add 'microcoreos[redis]'` | `mv extras/available_tools/redis_state tools/` |
| **S3** — object storage, private bucket + presigned URLs | `uv add 'microcoreos[s3]'` | `mv extras/available_tools/s3 tools/` |
| **Scheduler** — cron + in-memory one-shots | `uv add 'microcoreos[scheduler]'` | `mv extras/available_tools/scheduler tools/` |
| **Chaos** — resilience testing (tool + its domain) | none | `mv extras/available_tools/chaos tools/` and `mv extras/available_domains/chaos domains/` |

**Event Bus drivers** install by dropping the `*_driver.py` into
`tools/event_bus/` and setting `EVENT_BUS_DRIVER`: `kafka`
(`uv add 'microcoreos[kafka]'`), `rabbitmq` (`[rabbitmq]`). Redis Streams and
the durable SQLite driver already ship in `tools/event_bus/` — Redis Streams
still needs `uv add 'microcoreos[redis]'`.

**Domains that need a tool.** A plugin cannot exist without its tool, so a
domain extra always requires its tool extra first. `extras/available_domains/scheduler/`
(durable one-shots, the `scheduler.one_shot.*` bus API) needs the scheduler
tool installed by both steps above; without it the boot says
`Plugin scheduler.DurableOneShotsPlugin aborted: Missing tools: scheduler`.

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
