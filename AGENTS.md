# MicroCoreOS — AI Agent & Architecture Guide

This file is the single, absolute entry point for any AI agent (Gemini, Claude, GPT, etc.) working in this codebase. All development must strictly adhere to these principles to maintain the integrity of the Elastic Monolith.

---

## 📖 Reading Path (minimize token usage)

1. **`plans/active_plan.md`** — The checklist for your assigned task (the formal contract lives in `plans/active_plan.yaml`).
2. **`AI_CONTEXT.md`** — Contains the live inventory of active tools (with exact signatures) and domain tables/endpoints. **Read only the tools and tables you need.**
3. **`domains/{domain}/models/{name}.py`** — Entity model (DB mirror). *Advisory: Table structures are already mirrored in AI_CONTEXT.md.*
4. **`INSTRUCTIONS_FOR_AI.md`** — Read ONLY for advanced tasks (building new tools, testing in-depth, or changing kernel internals).

---

## 🧭 Pick the Right Workflow (scale ladder)

Match the request to its workflow BEFORE planning. Over-planning a small
request is a failure mode: **a plan must be proportional to its request**
(see "Plan sizing" in `docs/PARALLEL_DEVELOPMENT.md`).

| Request | Workflow | Expected plan size |
|---|---|---|
| Plugin(s) on an EXISTING domain | `.agent/workflows/feature-plan.md` | Mini-plan, ~10-15 YAML lines per plugin, no `phase_0` |
| ONE new domain (e.g. a few CRUDs) | `.agent/workflows/new-domain.md` | ~80-120 YAML lines, one pass |
| Several domains / cross-domain event chains | `.agent/workflows/multi-domain-plan.md` | Full formal plan |
| New infrastructure tool (or replacement) | `.agent/workflows/new-tool.md` | No YAML plan — contract header + parity suite |

Omit every plan section that would be empty: no new tables → no `phase_0`;
no events → no `flows`. A CRUD-only plan has `features:` and nothing else.

---

## 💻 Commands

```bash
uv run main.py                                          # Run the app (also regenerates AI_CONTEXT.md)
uv run -m pytest                                        # Run all tests (always -m: the pytest binary is not exposed)
uv run -m pytest tests/test_file.py                     # Run a single test
docker compose -f dev_infra/docker-compose.yml up -d    # Start dev infrastructure (PostgreSQL)
```

---

## 🛡️ Non-Negotiable Rules

1. **Never modify `main.py`** — The Kernel auto-discovers everything.
2. **1 file = 1 feature** — Each plugin lives in `domains/{domain}/plugins/{feature}_plugin.py`.
3. **No Framework Abstractions** — No Routers, Controllers, or Services. Only Tools (infrastructure) and Plugins (business logic).
4. **DI by parameter name** — `__init__(self, http, db, logger)` injects tools named `http`, `db`, `logger`. No hardcoded imports.
5. **Schemas inline** — Request, response, and event payload schemas go at the top of the plugin file, never in `models/`.
6. **No cross-domain imports** — Domains communicate ONLY through the `event_bus`.
7. **Return envelope** — `{"success": bool, "data": ..., "error": ...}`: `success` always present, `data` on success, `error` on failure. Responses serialize **as-is** — `response_model` does NOT backfill omitted keys, so an omitted key is absent from the JSON and consumers must never assume it exists.
8. **SQL Placeholders & Verbatim Migrations** — Always `$1, $2, $3...` (PostgreSQL style; SQLite converts internally). Migration SQL runs **verbatim** on the active engine (no dialect translation). Engine-specific SQL is a valid choice — it commits you to that engine; portable SQL (e.g. `CURRENT_TIMESTAMP`, not `NOW()`) keeps the SQLite↔PostgreSQL swap free. Either way, the swap includes a review pass (ELASTIC_DEPLOYMENT.md, Stage 1).
9. **Event Envelope Contract** — Subscribers receive `EventEnvelope` objects, not raw dicts. Access payload data via `event.payload`.
10. **Typed Event Payloads** — Define `XxxPayload(BaseModel)` in the PUBLISHER plugin and publish using `XxxPayload(...).model_dump()` (bare call, no args). Consumers must never import it; they declare their own model with only the fields they read (tolerant reader).
11. **Protected Endpoints**: Pass `auth_validator=self.auth.validate_token` to `add_endpoint` for non-public routes. Check ownership via `data["_auth"]["sub"]` inside the handler.
12. **CSRF Guard & Cookie Security**: HTTP mutations (POST/PUT/DELETE) using cookie auth require the `X-Requested-With` header. Cookies set via `context.set_cookie` default to `Secure=True`, `HttpOnly=True`, `SameSite=Lax`.
13. **Core uses `print()`, not the logger** — Core modules must not depend on the logging tool.

---

## ⚖️ Core Architectural Laws

### The "No Hidden Magic" Rule (Kernel Level)
The Kernel (ToolProxy & Container) is infrastructure-blind:
1. **NO Kernel Retries**: `ToolProxy` is forbidden from automatically retrying failed tool calls. Automatic, blind retries at the kernel level lead to non-idempotent operation duplicates (e.g., double payments, duplicate database records).
2. **Explicit Resilience**: Resilience and idempotency are handled at the Tool level (connection pooling/locks) or Plugin level (business logic retry/compensation).
3. **Reactive Health**: `ToolProxy` marks tools as `DEAD` reactively (immediately if `ToolUnavailableError` is raised, or after 5 consecutive failures). Success resets the status to `OK`.

### Event Bus Mandates
1. **Universal Envelope**: All messages travel inside `EventEnvelope` objects. Emitters publish standard dicts; subscribers receive the full envelope.
2. **Decoupled Publication**: `publish()` is strictly fire-and-forget. Emitters must never know who consumes the event or when.
3. **Idempotency by Design**: Since durable transports re-deliver events after a crash (at-least-once), all event subscribers must be designed as idempotent.

### Security & Integrity
1. **Safe Error Reporting**: Never return raw exception strings (`str(e)`) to the client to prevent leak of paths, SQL structure, or keys. Log technical errors internally; return generic messages ("Database error") to the external client.
2. **Stateless JWT Logout**: By default, logout clears the cookie. JWTs remain valid until expiration. For critical revocation, use the `state` tool as a denylist.

---

## 🔄 Batch Parallel Execution Workflow (Coordinator Guidelines)

The canonical methodology (and its phase numbering) is `docs/PARALLEL_DEVELOPMENT.md`.
This is the coordinator's operational summary:

1. **Phase 1 — The Plan (contract)**: The formal YAML plan lives in `plans/active_plan.yaml`; the execution checklist (all tasks `[ ]`) in `plans/active_plan.md`. Validate with `POST /system/plan/validate` — **zero `errors` before anything else runs**. An invalid plan is fixed in the plan, never patched in code.
2. **Phase 0 — Foundation (Serial)**: Write the tools (if any), then all domain models and SQL migrations sequentially, exactly as the plan's `columns:` declare them. Run `uv run main.py --boot-tool db` to migrate and regenerate `AI_CONTEXT.md`.
3. **Phase 2 — Parallel Write Wave**: Spawn N subagents (one per plugin), each with the **canonical executor prompt**: a byte-identical shared prefix (`AI_CONTEXT.md` → `plans/active_plan.yaml` → `plans/executor_rules.md`, in that order) followed by ONE per-agent line at the end ("Implement feature `<PluginName>` from the plan above"). Subagents never open the plan or `AI_CONTEXT.md` themselves. The identical prefix lets any engine with prefix caching (local KV cache, hosted prompt caching) process the shared block once and reuse it for the whole wave — dispatch the first agent, let it start responding, then fire the rest. Each agent writes exactly two files: its plugin and its unit test.
4. **Phase 3 — Bulk Verification**: Once all subagents finish writing, run the entire test suite in a single execution (`uv run -m pytest`), then boot and check `GET /system/lint`.
5. **Cleanup & Reconstruct**:
   * For passing plugins: Mark their checkbox as `[x]` in `plans/active_plan.md`.
   * For failing plugins: **Delete** the created plugin and unit test files, keep their checkbox as `[ ]`, and spawn a new wave of clean agents to rewrite them from scratch.
   * Repeat until all checkboxes are `[x]`.

---

## ⚡ Minimal Plugin Template

```python
from typing import Optional
from pydantic import BaseModel, Field
from core.base_plugin import BasePlugin

class CreateThingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class ThingData(BaseModel):
    id: int
    name: str

class CreateThingResponse(BaseModel):
    success: bool
    data: Optional[ThingData] = None
    error: Optional[str] = None

class CreateThingPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/things", "POST", self.execute,
                               tags=["Things"], request_model=CreateThingRequest,
                               response_model=CreateThingResponse)

    async def execute(self, data: dict, context=None):
        try:
            req = CreateThingRequest(**data)
            new_id = await self.db.execute(
                "INSERT INTO things (name) VALUES ($1) RETURNING id", [req.name]
            )
            return {"success": True, "data": {"id": new_id, "name": req.name}}
        except Exception as e:
            self.logger.error(f"Failed to create thing: {e}")
            return {"success": False, "error": "Database error"}
```

---

## 🔎 Where to Find Examples

When writing a new feature, read these specific files under demand to copy their syntax:

| Pattern | File |
|---|---|
| **CRUD + Event Bus** | `domains/users/plugins/create_user_plugin.py` |
| **Protected Endpoint (JWT)** | `domains/users/plugins/get_me_plugin.py` |
| **Auth, Cookies & Session** | `domains/users/plugins/login_plugin.py` |
| **Minimal Plugin (No DB)** | `domains/ping/plugins/ping_plugin.py` |
| **Database Migrations** | `domains/users/migrations/001_create_users.sql` |
| **Dynamic Introspection** | `domains/system/plugins/system_status_plugin.py` |
| **Black-Box Integration Tests** | `tests/domains/users/test_login_plugin.py` |

---

## 🔧 Common Infrastructure Operations

When tasked with infrastructure changes, read the specific guide in `docs/ELASTIC_DEPLOYMENT.md`:

| Operation | Guide Section |
|---|---|
| **Swap SQLite to PostgreSQL** | [ELASTIC_DEPLOYMENT.md (Stage 1)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L25-L90) |
| **Swap In-Memory State to Redis** | [ELASTIC_DEPLOYMENT.md (Section 2.1)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L98-L116) |
| **Scale Event Bus to Redis Streams** | [ELASTIC_DEPLOYMENT.md (Section 2.2)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L117-L141) |
| **Disable/Configure Scheduler on Replicas** | [ELASTIC_DEPLOYMENT.md (Section 2.3)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L142-L160) |
| **Production DB Migrations Pipeline** | [ELASTIC_DEPLOYMENT.md (Section 2.4)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L161-L177) |

