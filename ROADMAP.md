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

**Issue 3 — Medium Priority**
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

**Issue 4 — Medium Priority**
**Separate administration port**

Expose the `system` domain (observability) on a separate port (e.g. 8001) isolated from the public API port. The admin port never reaches the outside in production — only accessible from internal network or VPN.

Reference: Spring Boot Actuator pattern. The HTTP tool would need to support a second internal server instance.

Affected endpoints: `GET /system/status`, `GET /system/events`, `GET /system/traces`, `WS /system/events/stream`, `WS /system/logs/stream`.

---

**Issue 5 — Medium Priority**
**WebSocket broadcast via dedicated Queue**

Currently each log or event creates an `asyncio.create_task` that calls `send_text` on every connected WebSocket client. Under high load this competes with the main event loop.

Solution: sinks enqueue into an `asyncio.Queue` and a dedicated worker drains it and broadcasts. The main event loop never blocks due to streaming regardless of log volume.

Affects: `SystemEventsStreamPlugin` and `SystemLogsStreamPlugin`.

---

**Issue 6 — Low Priority**
**Proactive tool health check**

`ToolProxy` detects failures reactively (when an operation raises an exception). Tools that fail silently (e.g. DB stops responding without raising) remain in `OK` state indefinitely.

Solution: a background plugin that calls `db.health_check()` every N seconds and updates the registry. The DB tool already exposes `health_check() -> bool`. The pattern is extensible to any tool that implements the method.

Note: keep outside the core to preserve the blind-kernel principle.

---

**Issue 7 — Low Priority**
**Real-time causal tree via WebSocket**

`GET /system/traces` exposes the causal event tree reconstructed from the in-memory trace log (last 500 events). Add a WebSocket endpoint `WS /system/traces/stream` that emits tree updates in real time as new event chains occur.

Depends on Issue 5 (dedicated Queue) to avoid adding additional overhead to the event loop.

---
