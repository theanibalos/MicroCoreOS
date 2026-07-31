---
description: Create a complete new domain with entity, migration, and CRUD plugins
---

# New Domain Workflow

Creates a full domain from scratch: entity model, SQL migration, and one plugin per use case.

> Planning levels: single features on an existing domain → [feature-plan.md](feature-plan.md) ·
> one new domain → this workflow · several domains / cross-domain chains →
> [multi-domain-plan.md](multi-domain-plan.md) · new infrastructure → [new-tool.md](new-tool.md).

## Before you plan — read these two, in this order

1. **`plans/active_plan.yaml`** — the file you are about to overwrite. It ships
   as a worked example of all three feature shapes. It **is** the format, not a
   description of one, and it is the cheapest way to have it.
2. **`AI_CONTEXT.md`**, down to `## 🧩 Plugin Authoring Guide` — the tables,
   models, routes and events that already exist. Inherit their names exactly.

Then write to **`plans/active_plan.yaml`** — that exact path, overwriting it —
and run `microcoreos plan validate` until it reports zero errors. Errors carry
the YAML that fixes them: paste it.

**Write the file before you ask anything.** Checking in is fine — planning
often is a conversation — but never *instead of* writing: a plan that exists
only as prose in your reply is a plan the next phase cannot read, and the run
may not be interactive at all. So write the YAML, validate it, and then raise
whatever you wanted to raise; the operator answers against a real file instead
of a description. Where a detail is genuinely undecidable, take what the
existing vocabulary implies, put it in the YAML, and flag it in a comment.

`docs/PARALLEL_DEVELOPMENT.md` § Phase 1 holds the rules behind the format.
Read it when a validator error is unclear, not before — and never reach for
plugin source under `domains/`, `tools/` or `extras/` to infer the shape. A
planner that did produced a plan with every field renamed.

## Prerequisites

Both files above. Nothing else: the plugin template lives in `AI_CONTEXT.md`
§ Plugin Authoring Guide, generated on every boot, and the rules are the 13
Non-Negotiable Rules in `AGENTS.md`.

## Steps

### 0. Plan the domain first

Write the plan of `docs/PARALLEL_DEVELOPMENT.md` ("Formal plan format") scoped
to this domain: `phase_0` (its migrations + models, with table ownership AND
every table's `columns:` — name, SQL type, constraints; steps 2-3 below are
written from this, never invented), `features` (one per plugin, every
published event with its payload `model` and fields, plus the `db:`
persistence contract), and — ONLY if any plugin publishes or consumes events —
`flows` (durability, happy path + the sad-path checklist per link — including
the `atomic_with_db` outbox question — and the declared `idempotency_test` /
`sad_path_test` files). A pure-CRUD domain has no `flows` section at all; a
domain whose delete cascades through one event has exactly one flow.
Validate with `microcoreos plan validate` before writing code (offline — the
endpoint form is the same rules against a running system). Build in that
order — tools first if any, then migrations + models, then plugins with their
events. Nothing below this line should require a decision the plan did not
already make. Expected size for a CRUD domain with one event chain: ~80-120
lines of YAML, one pass.

### 1. Create the domain folder structure

```bash
// turbo
mkdir -p domains/{name}/models domains/{name}/migrations domains/{name}/plugins
```

Create `domains/{name}/__init__.py`:
```python
# Auto-discovered by the Kernel. No manual registration needed.
```

### 2. Create the Entity model

File: `domains/{name}/models/{name}.py`

This file contains ONE thing: the Pydantic model that mirrors the database table exactly.

```python
from pydantic import BaseModel

class {Name}Entity(BaseModel):
    id: int | None = None
    # Add fields that match the DB columns exactly
    # Use the DB column names (e.g. password_hash, not password)
```

### 3. Create the SQL migration

File: `domains/{name}/migrations/001_create_{name}_table.sql`

Write raw SQL that creates the table. Use `$1, $2...` placeholders in queries (PostgreSQL-style, auto-converted for SQLite).

```sql
CREATE TABLE IF NOT EXISTS {name}s (
    id SERIAL PRIMARY KEY,
    -- columns matching the entity model
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4. Create plugins (1 file = 1 use case)

One plugin file per operation in `domains/{name}/plugins/`. The template — with
request, response and event-payload schemas inline, and the rules that go with
them — is `AI_CONTEXT.md` § **Plugin Authoring Guide**, regenerated on every
boot and already inside every executor prompt. A fourth copy lived here.

The one thing that is this workflow's own decision: which operations exist.
A CRUD domain is create / get_all / get_by_id / update / delete, one file each,
each declared in the plan before any of them is written.

### 5. Verify

```bash
// turbo
uv run main.py   # or: microcoreos (if you installed the package)
```

Check that:
- Migration ran successfully (look for `[Migration] ✅` in logs)
- Endpoints appear in the Swagger UI at `http://localhost:5000/docs`
- `GET /system/lint` has no warnings and no `UNTYPED_PAYLOAD` for your events
- `GET /system/events/schemas` lists every event the plan declared
- `AI_CONTEXT.md` was regenerated with the new domain — **done when it matches the plan**
- `microcoreos schema` shows the new tables with the columns the plan declared

### 6. Generate tests

Create `tests/test_{name}_plugin.py` with one test per plugin. Mock exactly
the tools the plan's `mocks:` field lists; run the rest as real in-memory
instances (`INSTRUCTIONS_FOR_AI.md` § Testing). Example with everything
mocked (`mocks: [http, db, event_bus, logger]`):

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from domains.{name}.plugins.create_{name}_plugin import Create{Name}Plugin

@pytest.mark.anyio
async def test_create_{name}_success():
    plugin = Create{Name}Plugin(
        http=MagicMock(),
        db=AsyncMock(return_value=1),
        event_bus=AsyncMock(),
        logger=MagicMock(),
    )
    result = await plugin.execute({"field1": "value", "field2": 42})
    assert result["success"] is True
    assert result["data"]["id"] == 1

@pytest.mark.anyio
async def test_create_{name}_db_error():
    plugin = Create{Name}Plugin(
        http=MagicMock(),
        db=AsyncMock(side_effect=Exception("DB down")),
        event_bus=AsyncMock(),
        logger=MagicMock(),
    )
    result = await plugin.execute({"field1": "value", "field2": 42})
    assert result["success"] is False
    assert "DB down" not in result["error"]  # Safe Errors: technical detail never reaches the client
```

Run with `uv run -m pytest tests/test_{name}_plugin.py`.
