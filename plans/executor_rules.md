# Executor Rules

> This file is the FINAL block of the shared executor prompt prefix
> (`AI_CONTEXT.md` → `active_plan.yaml` → this file → your task line).
> It is byte-identical for every executor in a wave — never edit it mid-wave.

You are an Executor AI. Your only job is the ONE feature named in the final
line of this prompt. Everything you need is already above: `AI_CONTEXT.md`
(the live system) and the plan (your contract). Do not read any other file.
Do not ask questions — the plan already made every decision.

## Deliverable — exactly two files

Your task line names either a **feature** or a **flow's tests**:

- Feature task → 1. the plugin (at the `file:` path your feature declares)
  and 2. its test (at the `test:` path it declares).
- Flow-tests task → 1. the flow's `e2e_test` (trigger the happy path, assert
  the causal chain with `tests/helpers/trace_chains.py`:
  `assert_chain(build_tree(bus.get_trace_history()), [...])`) and 2. its
  `sad_path_test` (force the consumer to fail with a mock that raises, assert
  `_dlq.<event>` appears as a child of the failed event in the same tree).

Nothing else: no migrations, no entity models, no edits to `main.py`, no
touching other domains or other tasks' files.

## Plugin rules

1. **Schemas inline** — request, response AND event payload models at the top
   of the plugin file. Never import them from `models/` or other domains.
2. **DI by parameter name** — `__init__(self, http, db, logger)` receives the
   tools named `http`, `db`, `logger`. Inject exactly the tools your feature
   uses. No hardcoded imports from `tools/`.
3. **Return envelope** — always `{"success": bool, "data": ..., "error": ...}`.
   All values in `data` must be JSON-serializable (`.model_dump()` Pydantic
   instances before returning).
4. **SQL placeholders** — `$1, $2, $3...` (PostgreSQL style), only on tables
   your feature's `db:` contract declares.
5. **Events** — publish exactly the events the plan declares, with a
   `XxxPayload(BaseModel)` defined in THIS file and published via
   `XxxPayload(...).model_dump()` (bare call, no arguments). Consumers never
   import the publisher's model: declare your own model with only the fields
   your `consumes.requires` lists (tolerant reader) and do `Model(**event.payload)`.
6. **Subscribers receive `EventEnvelope`** — access data via `event.payload`.
7. **Safe errors** — never return `str(e)` to the client. Log it, return a
   generic message ("Database error").
8. **Protected route?** If the plan marks it, pass
   `auth_validator=self.auth.validate_token` to `add_endpoint` and check
   ownership via `data["_auth"]["sub"]`.
9. **Always pass `response_model=`** to `add_endpoint`, and `Field(...)`
   constraints on every request field.

## Template

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

class ThingCreatedPayload(BaseModel):
    id: int
    name: str

class CreateThingPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
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
            await self.bus.publish(
                "thing.created", ThingCreatedPayload(id=new_id, name=req.name).model_dump()
            )
            return {"success": True, "data": {"id": new_id, "name": req.name}}
        except Exception as e:
            self.logger.error(f"Failed to create thing: {e}")
            return {"success": False, "error": "Database error"}
```

## Test rules

- **Write the test FIRST, then the plugin.** Derive every assertion from the
  PLAN (route, envelope shape, declared tables, declared payload keys) —
  never from your own implementation. The test is the contract's proof; a
  test that mirrors the code proves nothing.
- Mock exactly the tools your feature's `mocks:` lists
  (`unittest.mock.AsyncMock` / `MagicMock`); run every other injected tool as
  a real in-memory instance (SQLite `:memory:` with your domain's migration
  applied, in-process event bus).
- Prove the black-box contract: input → output envelope, DB effects on the
  declared tables, published payloads with the declared keys.
- One error-path test: force a failure (mock that raises) and assert the
  technical detail does NOT reach the client response.
- Mark async tests with `@pytest.mark.anyio` (add an `anyio_backend`
  fixture returning `"asyncio"`).

When both files are written, stop. Do not run commands, do not summarize the
codebase, do not propose follow-ups.
