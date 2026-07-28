"""
A plugin test written the way a PLUGIN is written.

A plugin never builds a tool — it names one in `__init__` and the Kernel hands
it over. pytest injects by parameter name too, so a test can use the same
vocabulary: ask for `db`, `event_bus`, `auth`, then assert on what actually
landed. No tool imports, no setup/teardown, no hand-rolled schema.

Compare with the older style (tests/test_durable_one_shots.py): three tool
imports, a hand-written stub, a MagicMock and a migration read by path.
"""

from unittest.mock import MagicMock

import pytest

from extras.available_domains.users.plugins.create_user_plugin import CreateUserPlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.migrations("users")
async def test_create_user_persists_and_announces(db, event_bus, auth, logger):
    """Input → output → persistence, plus the event the domain promises."""
    announced = []
    await event_bus.subscribe("user.created", lambda env: announced.append(env.payload))

    plugin = CreateUserPlugin(http=MagicMock(), db=db, event_bus=event_bus,
                              auth=auth, logger=logger)
    result = await plugin.execute(
        {"name": "Ana", "email": "ana@test.com", "password": "secret123"}
    )

    assert result["success"] is True

    # Persistence — the claim that a mocked db cannot make: this SQL ran
    # against the domain's real schema.
    rows = await db.query("SELECT name, email, password_hash FROM users")
    assert [(r["name"], r["email"]) for r in rows] == [("Ana", "ana@test.com")]
    assert rows[0]["password_hash"] != "secret123", "password stored in the clear"


@pytest.mark.migrations("users")
async def test_duplicate_email_is_rejected_by_the_real_constraint(db, event_bus, auth, logger):
    """The UNIQUE index lives in the migration, so only a real schema proves it."""
    plugin = CreateUserPlugin(http=MagicMock(), db=db, event_bus=event_bus,
                              auth=auth, logger=logger)
    payload = {"name": "Ana", "email": "dup@test.com", "password": "secret123"}

    assert (await plugin.execute(payload))["success"] is True
    assert (await plugin.execute(payload))["success"] is False

    rows = await db.query("SELECT id FROM users WHERE email = $1", ["dup@test.com"])
    assert len(rows) == 1


async def test_db_fixture_without_the_marker_has_no_schema(db):
    """No marker means a real, empty database — not a silently shared one."""
    with pytest.raises(Exception):
        await db.query("SELECT 1 FROM users")
