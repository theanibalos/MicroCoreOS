"""Black-box tests for DeleteUserPlugin (ownership + user.deleted event)."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.delete_user_plugin import DeleteUserPlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_plugin(db, event_bus):
    return DeleteUserPlugin(
        http=MagicMock(), db=db, event_bus=event_bus, logger=MagicMock(), auth=MagicMock()
    )


async def seed_user(db):
    return await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", "ana@example.com", "hashed", json.dumps(["user"])],
    )


@pytest.mark.migrations("users")
async def test_user_deletes_own_account_and_event_is_published(db, event_bus):
    user_id = await seed_user(db)
    received = []

    async def on_deleted(event):
        received.append(event.payload)

    await event_bus.subscribe("user.deleted", on_deleted)
    plugin = make_plugin(db, event_bus)

    result = await plugin.execute({"user_id": str(user_id), "_auth": {"sub": str(user_id)}})

    assert result["success"] is True
    row = await db.query_one("SELECT id FROM users WHERE id = $1", [user_id])
    assert row is None

    await asyncio.sleep(0.01)
    assert received == [{"id": user_id}]


@pytest.mark.migrations("users")
async def test_deleting_someone_else_is_forbidden(db, event_bus):
    user_id = await seed_user(db)
    plugin = make_plugin(db, event_bus)
    context = MagicMock()

    result = await plugin.execute(
        {"user_id": str(user_id), "_auth": {"sub": "777"}}, context
    )

    assert result["success"] is False
    assert result["error"] == "Forbidden"
    context.set_status.assert_called_once_with(403)
    row = await db.query_one("SELECT id FROM users WHERE id = $1", [user_id])
    assert row is not None  # still there


@pytest.mark.migrations("users")
async def test_unknown_user_returns_not_found(db, event_bus):
    plugin = make_plugin(db, event_bus)

    result = await plugin.execute({"user_id": "9999", "_auth": {"sub": "9999"}})

    assert result["success"] is False
    assert result["error"] == "User not found"


async def test_db_failure_never_leaks_technical_detail(event_bus):
    broken_db = AsyncMock()
    broken_db.execute.side_effect = Exception("secret: table structure leaked")
    plugin = make_plugin(broken_db, event_bus)

    result = await plugin.execute({"user_id": "1", "_auth": {"sub": "1"}})

    assert result["success"] is False
    assert result["error"] == "Could not delete user"
    assert "secret" not in result["error"]
