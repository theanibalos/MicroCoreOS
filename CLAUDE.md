# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
uv run main.py

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_create_user.py

# Run a single test
uv run pytest tests/test_create_user.py::test_create_user_success

# Start development infrastructure (PostgreSQL)
docker compose -f dev_infra/docker-compose.yml up -d

# Tear down dev infrastructure
docker compose -f dev_infra/docker-compose.yml down
```

## Architecture

MicroCoreOS is an **Atomic Microkernel** where **1 file = 1 feature**. The kernel auto-discovers and wires everything — `main.py` is sacred and must never be modified.

### Core (~6 files, never touch for business logic)

- `core/kernel.py` — Orchestrates boot: discovers `tools/` then `domains/`, resolves plugin dependencies by parameter name. Sync functions are auto-offloaded to `asyncio.to_thread`. The kernel is **blind**: it knows nothing about business logic or domain internals.
- `core/container.py` — Service locator. Wraps tools in `ToolProxy` for automatic async-aware health monitoring. Injects the core registry into tools that expose `_set_core_registry()` at registration time.
- `core/registry.py` — Thread-safe, sharded-lock inventory of all tools and plugins with live status tracking.
- `core/context.py` — `ContextVar`-based identity/event causality tracing (propagated automatically by Kernel and HttpServerTool).
- `core/base_plugin.py` / `core/base_tool.py` — Minimal ABCs. BasePlugin provides only `on_boot()` and `shutdown()` hooks. Plugins define their own handler methods freely.

### Tools (`tools/{name}/{name}_tool.py`)

Stateless infrastructure atoms. **Tools must never import other tools.** Each tool exposes a `name` property that becomes its injection key. Current tools: `http`, `db` (PostgreSQL), `event_bus`, `logger`, `auth`, `state`, `registry`, `config`, `context_manager`, `chaos`.

Tools read their own environment variables with `os.getenv()` — `main.py` calls `load_dotenv()` once on startup.

### Plugins (`domains/{domain}/plugins/{feature}_plugin.py`)

One file per feature. The kernel resolves constructor parameters by name to inject tools. A plugin requests `db` by naming its parameter `db` — no decorators, no manual wiring.

**Plugin lifecycle:**
1. `__init__(self, tool_a, tool_b)` — DI only, save as `self.x`. No logic.
2. `on_boot()` — Register HTTP endpoints and event subscriptions.
3. `execute(data, context=None)` — Business logic (or any named handler method).
4. `shutdown()` — Optional cleanup.

**Tool lifecycle:**
1. `setup()` — Allocate resources (DB connections, read env vars).
2. `on_boot_complete(container)` — Post-boot orchestration (all tools are ready, can call `container.get('name')`).
3. `shutdown()` — Cleanup.

### Dependency Injection

The kernel reads plugin `__init__` parameter names and matches them to registered tool `name` properties. To request the `http` tool, name the parameter `http`. Type hints via `TYPE_CHECKING` are purely for IDE support and do not affect injection.

## Plugin Pattern

Register `self.execute` directly as the HTTP handler — no intermediate `handler()` method needed:

```python
class CreateProductPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute, tags=["Products"], request_model=ProductEntity)
        await self.bus.subscribe("order.confirmed", self.on_order_confirmed)

    async def execute(self, data: dict, context=None) -> dict:
        # HTTP handler: context.set_cookie(), context.set_header(), context.set_status() available
        product_id = await self.db.execute(
            "INSERT INTO products (name) VALUES ($1) RETURNING id", [data["name"]]
        )
        await self.bus.publish("product.created", {"id": product_id})
        return {"success": True, "data": {"id": product_id}}

    async def on_order_confirmed(self, data: dict) -> None:
        # Event subscriber: receives only data dict. Return a dict to participate in request() RPC.
        self.logger.info(f"Order confirmed: {data}")
```

## Critical Rules

1. **Never modify `main.py`** — It only instantiates `Kernel()` and calls `app.boot()`.
2. **No cross-domain imports** — Domains communicate exclusively via `event_bus`.
3. **Tools never import other tools** — Move cross-tool orchestration to a plugin.
4. **No logic in `__init__` or `setup()`** — DI and resource allocation only.
5. **Use `async def` for I/O, `def` for CPU-heavy work** — The kernel auto-threads sync methods.
6. **Never call `time.sleep()` in async code** — Use `await asyncio.sleep()`.
7. **Return format**: Always `{"success": bool, "data": ..., "error": ...}`.

## Creating a New Feature

**Step 1** — Model (`domains/{domain}/models/entity.py`, Pydantic)
**Step 2** — Migration (`domains/{domain}/migrations/NNN_create_table.sql`, raw SQL)
**Step 3** — Plugin (`domains/{domain}/plugins/create_entity_plugin.py`)

The `db` tool auto-runs pending `.sql` migration files sequentially on boot.
PostgreSQL placeholders are `$1, $2, $3` (not `?`).

## Testing Pattern

Mock all tools with `AsyncMock`/`MagicMock` and instantiate the plugin directly. Use `@pytest.mark.anyio` for async tests.

```python
@pytest.mark.anyio
async def test_example():
    plugin = MyPlugin(
        http=MagicMock(),
        db=AsyncMock(),
        event_bus=AsyncMock(),
        logger=MagicMock()
    )
    result = await plugin.execute({"key": "value"})
    assert result["success"] is True
```

## AI_CONTEXT.md

Auto-generated on every boot by the `context_manager` tool. Contains the live inventory of all tools (with exact method signatures) and active domain models. **Read this file before implementing anything** — it is the authoritative reference for what tools are available and how to call them.
