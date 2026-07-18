## 🧩 Plugin Authoring Guide

> Embedded verbatim from `tools/context/authoring_guide.md` on every boot.
> For a wave executor this section IS the rulebook: the canonical executor
> prompt is this manifest → `plans/active_plan.yaml` → ONE task line at the
> end — nothing else.

### Executor contract — exactly two files

Your only job is the ONE feature named in the final line of your prompt.
Everything you need is in this manifest and the plan (your contract). Do not
read any other file. Do not ask questions — the plan already made every
decision.

Your task line names either a **feature** or a **flow's tests**:

- Feature task → 1. the plugin (at the `file:` path your feature declares)
  and 2. its test (at the `test:` path it declares).
- Flow-tests task → 1. the flow's `e2e_test` (trigger the happy path, assert
  the causal chain with `tests/helpers/trace_chains.py`:
  `assert_chain(build_tree(bus.get_trace_history()), [...])`) and 2. its
  `sad_path_test` (force the consumer to fail with a mock that raises, assert
  `_dlq.<event>` appears as a child of the failed event in the same tree).

Nothing else: no migrations, no entity models, no edits to `main.py`, no
touching other domains or other tasks' files. When both files are written,
stop. Do not run commands, do not summarize the codebase, do not propose
follow-ups.

### Plugin rules

1. **Schemas inline** — request, response AND event payload models at the top
   of the plugin file. Never import them from `models/` or other domains.
2. **DI by parameter name** — `__init__(self, http, db, logger)` receives the
   tools named `http`, `db`, `logger`. Inject exactly the tools your feature
   uses. No hardcoded imports from `tools/`.
3. **Return envelope** — `{"success": bool, "data": ..., "error": ...}`:
   `success` always present, `data` on success, `error` on failure. Responses
   serialize AS-IS — `response_model` does NOT backfill omitted keys, so an
   omitted key is simply absent from the JSON. All values in `data` must be
   JSON-serializable (`.model_dump()` Pydantic instances before returning).
4. **SQL placeholders** — `$1, $2, $3...` (PostgreSQL style), only on tables
   your feature's `db:` contract declares.
5. **Events** — publish exactly the events the plan declares, with a
   `XxxPayload(BaseModel)` defined in THIS file and published via
   `XxxPayload(...).model_dump()` (bare call, no arguments). Consumers never
   import the publisher's model: declare your own model with only the fields
   your `consumes.requires` lists (tolerant reader) and do `Model(**event.payload)`.
6. **Subscribers receive the event envelope** — access data via
   `event.payload`. Leave the parameter untyped (no annotation, no import),
   exactly as the subscriber template below shows.
7. **Safe errors** — never return `str(e)` to the client. Log it, return a
   generic message ("Database error").
8. **Protected route?** If the plan marks it, pass
   `auth_validator=self.auth.validate_token` to `add_endpoint` and check
   ownership via `data["_auth"]["sub"]`.
9. **Always pass `response_model=`** to `add_endpoint`, and `Field(...)`
   constraints on every request field.

### Templates — one per deliverable type, copy the one your task matches

Each is a whole file, imports to last line; nothing a feature or flow-tests
task needs is missing from them.

#### Publisher feature (endpoint + event)

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

#### Subscriber feature (pure event consumer)

```python
from pydantic import BaseModel
from core.base_plugin import BasePlugin


# Consumed event, tolerant reader: declare ONLY the fields your feature's
# `consumes.requires` lists — never import the publisher's model.
class ThingCreatedData(BaseModel):
    id: int
    name: str


class ThingAuditedPayload(BaseModel):
    thing_id: int


class ThingAuditPlugin(BasePlugin):
    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        # retries/backoff: exactly what the plan's flow link declares (omit when none)
        await self.bus.subscribe("thing.created", self.on_thing_created)

    async def on_thing_created(self, event) -> None:
        data = ThingCreatedData(**event.payload)
        self.logger.info(f"Audited thing {data.id}")
        await self.bus.publish(
            "thing.audited", ThingAuditedPayload(thing_id=data.id).model_dump()
        )
```

#### Flow tests (e2e chain + sad path — one file with both)

```python
"""Flow tests for <flow-name>: happy-path causal chain + DLQ sad path."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.things.plugins.create_thing_plugin import CreateThingPlugin
from domains.things.plugins.thing_audit_plugin import ThingAuditPlugin
from tools.event_bus.event_bus_tool import EventBusTool
from tests.helpers.async_wait import wait_until
from tests.helpers.trace_chains import build_tree, assert_chain

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()


async def test_happy_path_chain(bus):
    db = AsyncMock()
    db.execute.return_value = 1

    publisher = CreateThingPlugin(http=MagicMock(), db=db, event_bus=bus, logger=MagicMock())
    consumer = ThingAuditPlugin(event_bus=bus, logger=MagicMock())
    await consumer.on_boot()

    await publisher.execute({"name": "widget"})
    await wait_until(lambda: any(r.envelope.event == "thing.audited"
                                 for r in bus.get_trace_history()))

    assert_chain(build_tree(bus.get_trace_history()),
                 ["thing.created", "thing.audited"])


async def test_sad_path_dlq(bus):
    logger = MagicMock()
    consumer = ThingAuditPlugin(event_bus=bus, logger=logger)
    await consumer.on_boot()

    # Force the consumer to fail on every attempt: one injected tool raises.
    logger.info.side_effect = RuntimeError("forced failure")

    await bus.publish("thing.created", {"id": 1, "name": "widget"})
    # Poll for the DLQ event instead of sleeping through retries + backoff.
    await wait_until(lambda: any(r.envelope.event == "_dlq.thing.created"
                                 for r in bus.get_trace_history()))

    # _dlq.<event> is published inside the failing delivery's context, so it
    # appears as a child of the event that failed — same helper asserts it.
    assert_chain(build_tree(bus.get_trace_history()),
                 ["thing.created", "_dlq.thing.created"])
```

### Test rules

- **Write the test FIRST, then the plugin.** Derive every assertion from the
  PLAN (route, envelope shape, declared tables, declared payload keys) —
  never from your own implementation. The test is the contract's proof; a
  test that mirrors the code proves nothing.
- Mock exactly the tools your feature's `mocks:` lists
  (`unittest.mock.AsyncMock` / `MagicMock`); run every other injected tool as
  a real in-memory instance (SQLite `:memory:` with your domain's migration
  applied, in-process event bus).
- Prove the black-box contract: input → output envelope, DB effects on the
  declared tables, published payloads with the declared keys. Assert the keys
  the envelope guarantees (`success`, plus `data` on success / `error` on
  failure); the complementary key may be legitimately absent — use `.get()`
  for it, never a bare `result["key"]`.
- One error-path test: force a failure (mock that raises) and assert the
  technical detail does NOT reach the client response.
- Mark async tests with `@pytest.mark.anyio` (add an `anyio_backend`
  fixture returning `"asyncio"`).
- **Never a fixed `asyncio.sleep()` to wait for async delivery** — it guesses
  a duration and flakes under CI CPU contention. Poll the real condition with
  `wait_until` from `tests.helpers.async_wait` (as in the flow-test template
  above). The one exception is a negative check (asserting nothing arrives),
  where a short fixed sleep is the only option.
