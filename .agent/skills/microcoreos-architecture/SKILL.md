---
name: microcoreos-architecture
description: Ensures adherence to MicroCoreOS "Atomic Microkernel" architecture. Use when creating or modifying core, tools, plugins, or domains.
---

# MicroCoreOS Architecture Skill

## Reading Path (minimize token usage)

**To write a plugin**: Read `AI_CONTEXT.md` + the entity model in `domains/{domain}/models/`. Nothing else.
**To create a full domain**: Use the `/new-domain` workflow.
**For edge cases only**: Read `INSTRUCTIONS_FOR_AI.md`.

## Essential Rules

1. **Never modify `main.py`** — Kernel auto-discovers everything.
2. **1 file = 1 feature** — Plugins in `domains/{domain}/plugins/`.
3. **DI by name** — `__init__` parameter names match tool `name` properties.
4. **Entity in models/ = DB mirror only** — Request schemas go inline at the top of the plugin file.
5. **No cross-domain imports** — Use `event_bus` for communication.
6. **Return format**: `{"success": bool, "data": ..., "error": ...}`.
7. **Runner**: Always `uv run`.

## Plugin Template

```python
from pydantic import BaseModel
from core.base_plugin import BasePlugin

class CreateThingRequest(BaseModel):  # schema lives HERE, not in models/
    name: str

class CreateThingPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/things", "POST", self.execute,
                               tags=["Things"], request_model=CreateThingRequest)

    async def execute(self, data: dict, context=None):
        try:
            req = CreateThingRequest(**data)
            new_id = await self.db.execute(
                "INSERT INTO things (name) VALUES ($1) RETURNING id", [req.name]
            )
            return {"success": True, "data": {"id": new_id}}
        except Exception as e:
            self.logger.error(f"Failed: {e}")
            return {"success": False, "error": str(e)}
```

## Pre-commit Checklist

- [ ] `main.py` untouched
- [ ] No cross-domain imports
- [ ] Entity mirrors DB table only — schemas inline in plugin
- [ ] Plugin is a single self-contained file
- [ ] `async def` for I/O, `def` for CPU
- [ ] Ran `uv run main.py` to verify
