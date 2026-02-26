# 🤖 AI Agent Implementation Guide

> **Reading order**: `AI_CONTEXT.md` (live inventory) → this file (rules + templates) → `workflows/` (step-by-step tasks).

## ⚠️ CRITICAL RULES (DO NOT IGNORE)

1. **`main.py` is sacred** — Never modify. It only boots the Kernel.
2. **No hardcoded imports** — Plugins request tools by `__init__` parameter name matching the tool's `name` property.
3. **No framework patterns** — No Routers, Controllers, or Services. Only Tools (infrastructure) and Plugins (business logic).
4. **No cross-domain imports** — Domains communicate exclusively via `event_bus`.
5. **Tools never import other tools** — Move cross-tool orchestration to a plugin.
6. **No logic in `__init__` or `setup()`** — DI and resource allocation only.
7. **`async def` for I/O, `def` for CPU** — Kernel auto-threads sync methods. Never `time.sleep()` in async.
8. **Return format**: Always `{"success": bool, "data": ..., "error": ...}`.
9. **Runner**: Always use `uv run main.py` / `uv run pytest`.

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

*Domains MUST NOT import from each other.*

### Entity vs Request Schema — where each lives

| What | Where |
|---|---|
| `<Name>Entity` — DB mirror | `domains/{name}/models/{name}.py` — only changes when the DB table changes |
| Request/Response schema | **Top of the plugin file** that owns it — never in `models/` |

**Why:** Each plugin is self-contained. An AI reads entity + its plugin, nothing else. Multiple AI agents work in parallel without conflicts.

### The AI-Driven Build Sequence

1. **Model** → `domains/{name}/models/{name}.py` (Pydantic entity mirroring the DB table)
2. **Migration** → `domains/{name}/migrations/001_create_{name}.sql` (Raw SQL, `$1, $2...` placeholders)
3. **Plugins** → One file per use case in `domains/{name}/plugins/`

> The `db` tool auto-runs pending `.sql` migration files on boot.

---

## ⚡ New Plugin

**Location**: `domains/{domain}/plugins/{feature}_plugin.py`  
**Rule**: 1 File = 1 Feature. Schema defined inline.

```python
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin

# ── Request schema lives HERE, not in models/ ──────────────
class CreateProductRequest(BaseModel):
    name: str
    price: float

class CreateProductPlugin(BasePlugin):
    def __init__(self, logger, event_bus, http, db):
        # 1. DI Phase — save tools, no logic
        self.logger = logger
        self.bus = event_bus
        self.http = http
        self.db = db

    async def on_boot(self):
        # 2. Registration Phase
        self.http.add_endpoint(
            path="/products",
            method="POST",
            handler=self.execute,
            tags=["Products"],
            request_model=CreateProductRequest
        )
        await self.bus.subscribe("order.created", self.on_order_created)

    async def execute(self, data: dict, context=None):
        # 3. Action Phase — context has set_cookie(), set_header(), set_status()
        try:
            req = CreateProductRequest(**data)
            product_id = await self.db.execute(
                "INSERT INTO products (name, price) VALUES ($1, $2) RETURNING id",
                [req.name, req.price]
            )
            await self.bus.publish("product.created", {"id": product_id})
            return {"success": True, "data": {"id": product_id}}
        except Exception as e:
            self.logger.error(f"Failed to create product: {e}")
            return {"success": False, "error": str(e)}

    async def on_order_created(self, data: dict) -> None:
        # Event subscriber — only data dict, no context.
        # Return a dict to participate in request() RPC.
        self.logger.info(f"Order received: {data}")
```

> **Hybrid Power**: `async def` for I/O. `def` for CPU-heavy work — Kernel auto-offloads to thread pool.

---

## 🔧 New Tool

**Location**: `tools/{name}/{name}_tool.py`  
**Rule**: Stateless, isolated, self-documented.

```python
from core.base_tool import BaseTool

class MyServiceTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_service"

    def setup(self):
        # Resource allocation: connections, env vars
        print("[MyService] Initializing...")

    def get_interface_description(self) -> str:
        # AI-readable manual — exact signatures
        return """
        My Service Tool (my_service):
        - PURPOSE: What it does.
        - CAPABILITIES:
            - do_something(arg1, arg2): What this method does.
        """

    def on_boot_complete(self, container):
        # Optional: all tools ready, can call container.get('name')
        pass

    def shutdown(self):
        # Cleanup: close connections, stop threads
        pass
```

---

## 🔄 Lifecycle

### Tool: `setup()` → `on_boot_complete(container)` → `shutdown()`
### Plugin: `__init__(tools)` → `on_boot()` → handler methods → `shutdown()`

---

## 🧪 Testing

Mock all tools, instantiate the plugin directly:

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

---

## 📂 Reference Gallery

- **CRUD + Events**: [create_user_plugin.py](domains/users/plugins/create_user_plugin.py)
- **Protected endpoint (JWT)**: [get_me_plugin.py](domains/users/plugins/get_me_plugin.py)
- **Auth flow**: [login_plugin.py](domains/users/plugins/login_plugin.py)

---
*`AI_CONTEXT.md` is auto-generated on every boot by the `context_manager` tool. It contains the live inventory of tools and domain models.*
