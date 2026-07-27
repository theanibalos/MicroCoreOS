"""Black-box tests for CreateUserPlugin.

Real tools: the ACTIVE db tool with the users migrations applied, real
AuthTool, real in-process event bus. Only the error-path test mocks `db`.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.create_user_plugin import CreateUserPlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_plugin(db, event_bus, auth):
    return CreateUserPlugin(
        http=MagicMock(), db=db, event_bus=event_bus, logger=MagicMock(), auth=auth
    )


@pytest.mark.migrations("users")
async def test_create_user_persists_row_and_publishes_event(db, event_bus, auth):
    received = []

    async def on_created(event):
        received.append(event.payload)

    await event_bus.subscribe("user.created", on_created)
    plugin = make_plugin(db, event_bus, auth)

    result = await plugin.execute(
        {"name": "Ana", "email": "ana@example.com", "password": "password123"}
    )

    assert result["success"] is True
    assert result["data"]["email"] == "ana@example.com"
    assert result["data"]["roles"] == ["user"]

    row = await db.query_one("SELECT * FROM users WHERE id = $1", [result["data"]["id"]])
    assert row["name"] == "Ana"
    assert row["email"] == "ana@example.com"
    # Password is stored hashed, never in plain text.
    assert row["password_hash"] != "password123"
    assert await auth.verify_password("password123", row["password_hash"])

    await asyncio.sleep(0.01)
    assert received == [
        {"id": result["data"]["id"], "email": "ana@example.com", "roles": ["user"]}
    ]


@pytest.mark.migrations("users")
async def test_duplicate_email_returns_specific_error(db, event_bus, auth):
    plugin = make_plugin(db, event_bus, auth)
    payload = {"name": "Ana", "email": "ana@example.com", "password": "password123"}

    first = await plugin.execute(payload)
    second = await plugin.execute(payload)

    assert first["success"] is True
    assert second["success"] is False
    assert second["error"] == "Email already in use"

    rows = await db.query("SELECT id FROM users WHERE email = $1", ["ana@example.com"])
    assert len(rows) == 1


async def test_db_failure_never_leaks_technical_detail(event_bus, auth):
    broken_db = AsyncMock()
    broken_db.execute.side_effect = Exception("secret: table structure leaked")
    plugin = make_plugin(broken_db, event_bus, auth)

    result = await plugin.execute(
        {"name": "Ana", "email": "ana@example.com", "password": "password123"}
    )

    assert result["success"] is False
    assert result["error"] == "Could not create user"
    assert "secret" not in result["error"]
