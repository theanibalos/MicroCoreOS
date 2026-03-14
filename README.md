# MicroCoreOS: The Architecture That Makes AI-Generated Code Maintainable

> The current solution to AI coding mistakes is more context — .cursorrules, CLAUDE.md, skills, system prompts.
> The result: context windows full of instructions instead of code.
>
> MicroCoreOS takes the opposite approach: an architecture where there's only one place to put things.

**1 file = 1 feature.** When AI makes a mistake, you find it in 30 seconds — not 30 minutes reviewing 8 files. The AI reads 2 files (the auto-generated system manifest + the plugin it's working on), follows one pattern, and produces clean, isolated code.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/theanibalos/MicroCoreOS/actions/workflows/ci.yml/badge.svg)](https://github.com/theanibalos/MicroCoreOS/actions)

---

## Quick Start

```bash
git clone https://github.com/theanibalos/MicroCoreOS.git
cd MicroCoreOS
cp .env.example .env
uv run main.py
# Visit http://localhost:5000/docs
```

No configuration needed. SQLite is the default (zero setup). The Kernel discovers all plugins, injects dependencies, runs migrations, and starts the server.

---

## One File = One Feature

This is a complete feature — schema, registration, logic, event publishing:

```python
# domains/products/plugins/create_product_plugin.py

from pydantic import BaseModel, Field
from core.base_plugin import BasePlugin

class CreateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(gt=0)

class CreateProductPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute,
                               tags=["Products"], request_model=CreateProductRequest)

    async def execute(self, data: dict, context=None):
        try:
            req = CreateProductRequest(**data)
            product_id = await self.db.execute(
                "INSERT INTO products (name, price) VALUES ($1, $2) RETURNING id",
                [req.name, req.price]
            )
            await self.bus.publish("product.created", {"id": product_id})
            return {"success": True, "data": {"id": product_id, "name": req.name}}
        except Exception as e:
            self.logger.error(f"Failed: {e}")
            return {"success": False, "error": str(e)}
```

Drop this file in `domains/products/plugins/`, restart, and it works. No `main.py` edits, no route registration, no wiring.

---

## What Makes It Different

### ~340-line kernel. Pure stdlib. No external dependencies in core.

The entire orchestration engine — DI, plugin discovery, tool lifecycle, fault tolerance — uses only Python's standard library.

### DI by parameter name.

```python
def __init__(self, db, http, logger):  # These ARE the injected tools
```

No decorators, no configuration, no container setup. The Kernel inspects your constructor, matches names to tools, done.

### AI_CONTEXT.md regenerates on every boot.

The system scans all tools, plugins, domains, events, and models — then writes a manifest with exact method signatures. Your AI always has current context, regardless of project size.

### Tools are swappable. Plugins don't change.

A Tool is identified by its `name` property. The SQLite tool and the PostgreSQL tool both expose the same API (`query`, `execute`, `transaction`, `health_check`) and both use `$1, $2` placeholders. To switch databases:

1. Change `name = "db"` in the SQLite tool to `name = "sqlite"`
2. Change `name = "postgresql"` in the PostgreSQL tool to `name = "db"`
3. Plugins don't change a single line.

This pattern works for any infrastructure: swap the event bus backend, the HTTP server, the auth mechanism — as long as the new tool has the same `name` and API, plugins keep working.

Additional tools (PostgreSQL, chaos testing) are available in extras/available_tools/. To activate, move them into tools/.

### Fault tolerance is automatic.

Every tool call passes through `ToolProxy`, which catches exceptions, marks failed tools as `DEAD` in the registry, auto-recovers when a subsequent call succeeds, and records timing metrics. If your logging service goes down, your payment processing keeps running.

---

## Built-in Observability (Zero Config)

**Causal Event Tracing** — Every event on the bus carries a `parent_id`. `GET /system/traces/tree` reconstructs the full causal chain. `GET /system/traces/stream` streams it live via SSE.

**Tool Call Metrics** — Every tool method call is automatically timed by ToolProxy. Access via `registry.get_metrics()` or attach a real-time sink.

**OpenTelemetry** (optional) — Set `OTEL_ENABLED=true`. Every tool call gets a span. Export to Jaeger, Grafana Tempo, Datadog. Zero changes to plugins.

---

## Architecture

```
MicroCoreOS/
├── core/                    # ~340 lines total, zero external deps
│   ├── kernel.py           # Discovery, DI, lifecycle
│   ├── container.py        # DI container + ToolProxy
│   ├── registry.py         # Thread-safe runtime state
│   ├── context.py          # ContextVars for causality
│   ├── base_plugin.py      # Plugin contract (15 lines)
│   └── base_tool.py        # Tool contract (23 lines)
├── tools/                   # Stateless, swappable infrastructure
│   ├── http_server/        # FastAPI (REST + WebSocket + SSE)
│   ├── sqlite/             # Default DB — zero config
│   ├── event_bus/          # Pub/Sub + async RPC + causal tracing
│   ├── auth/               # JWT + bcrypt
│   ├── scheduler/          # Cron + one-shot background jobs
│   ├── telemetry/          # OpenTelemetry (optional)
│   └── ...                 # logger, state, config, registry
├── domains/                 # Business logic
│   ├── users/              # Full CRUD + auth + JWT + events
│   ├── system/             # Observability endpoints
│   └── {your_domain}/
└── AI_CONTEXT.md           # Auto-generated on every boot
```

---

## Problems It Addresses

| Problem                                 | Approach                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------ |
| **AI needs too many files for context** | 2 files: `AI_CONTEXT.md` + the plugin.                                         |
| **Coupling between modules**            | Domains communicate via EventBus only, never direct imports.                   |
| **Architecture erodes under pressure**  | Conventions are explicit and easy to spot in review. CI linter on the roadmap. |
| **Merge conflicts on shared files**     | Each feature is its own file. No shared business logic files.                  |
| **One dependency failure cascades**     | ToolProxy contains failures per-tool automatically.                            |
| **Changing databases takes weeks**      | Swap the tool file. Same API, same placeholders.                               |
| **Background errors disappear**         | EventBus watchdog + causality engine.                                          |
| **Slow developer onboarding**           | Read `AI_CONTEXT.md` + one plugin.                                             |
| **Sync/async mixing bugs**              | Kernel auto-detects `def` vs `async def`, offloads sync to thread pool.        |

→ Deep dive: [docs.microcoreos.com/guide/problems](https://docs.microcoreos.com/guide/problems)

---

## Available Tools

| Tool        | Description                                                    |
| ----------- | -------------------------------------------------------------- |
| `http`      | FastAPI gateway — REST, WebSocket, SSE, auto-generated OpenAPI |
| `db`        | SQLite (default) or PostgreSQL — same API, drop-in swap        |
| `event_bus` | Pub/sub + async RPC + causal tracing + failure monitoring      |
| `auth`      | JWT lifecycle + bcrypt password hashing                        |
| `scheduler` | Cron jobs + one-shot tasks (APScheduler)                       |
| `logger`    | Structured logging with sink pattern                           |
| `state`     | Thread-safe in-memory key-value store                          |
| `registry`  | Runtime introspection + metrics + health status                |
| `telemetry` | OpenTelemetry — auto-instruments all tool calls                |
| `config`    | Environment variable validation for plugins                    |

---

## Working with AI

```
> Read AI_CONTEXT.md for available tools.
> Create a plugin in the orders domain that creates an order and publishes order.created.
```

The AI uses `$1, $2` placeholders, registers via `http`, publishes via `event_bus`, places everything in one file.

For full domains: follow `.agent/workflows/new-domain.md`.

---

## Testing

Constructor injection makes mocking straightforward:

```python
@pytest.mark.anyio
async def test_create_user():
    plugin = CreateUserPlugin(
        http=MagicMock(),
        db=AsyncMock(execute=AsyncMock(return_value=42)),
        event_bus=AsyncMock(),
        logger=MagicMock(),
        auth=MagicMock(hash_password=MagicMock(return_value="hashed"))
    )
    result = await plugin.execute({"name": "Test", "email": "a@b.com", "password": "p"})
    assert result["success"] is True
    assert result["data"]["id"] == 42
```

---

## Documentation

Full docs at **[docs.microcoreos.com](https://docs.microcoreos.com)**:
Quick Start · First Plugin Tutorial · Plugin Reference · Tools Reference · Observability · Philosophy

---

## Roadmap

- `uv add microcoreos` — Core as an installable package
- Domain isolation linter — CI enforcement of import rules
- Event contract linter — Static validation of pub/sub schemas
- Official tool packages — `microcoreos-redis`, `microcoreos-postgres`

---

## License

[MIT](LICENSE)

---

**Anibal Fernandez** ([@theanibalos](https://github.com/theanibalos))
