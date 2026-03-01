**Issue 1 — High Priority**
**Domain-level AI_CONTEXT.md**

Each domain should have an auto-generated or manual `AI_CONTEXT.md` that gives the AI all the context it needs in 10 lines:

```
# Domain: profiles
## Tables: profiles, links
## Endpoints: POST/GET/PUT/DELETE /profiles, POST /profiles/{id}/links
## Events emitted: profile.created, profile.updated
## Events consumed: none
## Dependencies: db, http, logger, auth, event_bus
```

This eliminates the need to read code to understand a domain. The AI reads this file first and knows exactly what exists, what it can use, and what events flow in and out.

---

**Issue 2 — Medium Priority**
**Plugin scaffold / template**

Add an explicit CRUD template to `SKILL.md` or `INSTRUCTIONS_FOR_AI.md` that the AI copies and adapts in seconds:

```python
# Template: CRUD Plugin
# Copy this, replace ENTITY_NAME, and you're done.
class Create__EntityName__Plugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/__entity__", "POST", self.execute,
            tags=["__EntityName__"], request_model=Create__EntityName__Request
        )

    async def execute(self, data: dict, context=None):
        try:
            req = Create__EntityName__Request(**data)
            new_id = await self.db.execute(
                "INSERT INTO __entity__s (field1) VALUES ($1) RETURNING id",
                [req.field1]
            )
            return {"success": True, "data": {"id": new_id}}
        except Exception as e:
            self.logger.error(f"Failed: {e}")
            return {"success": False, "error": str(e)}
```

The `/new-domain` workflow already does something similar but this makes it more explicit and copy-paste ready.

---

**Issue 3 — Medium Priority**
**Standardized validation pattern**

Currently each plugin validates differently. Pydantic with Field validators should be the official standard across all plugins:

```python
from pydantic import BaseModel, Field

class CreateProfileRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern="^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
```

Document this in `SKILL.md` and `INSTRUCTIONS_FOR_AI.md` as the only accepted pattern. Prevents inconsistencies across plugins and makes validation errors automatic via FastAPI.

---

**Issue 4 — Medium Priority**
**Unified error response format**

Currently each plugin returns errors differently. Standardize across all plugins:

```python
# Standard error format
return {"success": False, "error": "Profile not found", "code": "PROFILE_NOT_FOUND"}

# With status code via context
context.set_status(404)
return {"success": False, "error": "Profile not found", "code": "PROFILE_NOT_FOUND"}
```

Optionally add a helper to the http tool:
```python
return self.http.error(404, "PROFILE_NOT_FOUND", "Profile not found")
```

Document the standard error codes per domain in `AI_CONTEXT.md`.

---
