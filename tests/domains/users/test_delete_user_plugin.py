"""Black-box tests for DeleteUserPlugin (ownership + user.deleted event)."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.delete_user_plugin import DeleteUserPlugin
from tools.event_bus.event_bus_tool import EventBusTool
from tools.sqlite.sqlite_tool import SqliteTool

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "domains" / "users" / "migrations"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setenv("SQLITE_DB_PATH", ":memory:")
    tool = SqliteTool()
    await tool.setup()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        await tool.execute(migration.read_text())
    yield tool
    await tool.shutdown()


@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()


def make_plugin(db, bus):
    return DeleteUserPlugin(
        http=MagicMock(), db=db, event_bus=bus, logger=MagicMock(), auth=MagicMock()
    )


async def seed_user(db):
    return await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", "ana@example.com", "hashed", json.dumps(["user"])],
    )


async def test_user_deletes_own_account_and_event_is_published(db, bus):
    user_id = await seed_user(db)
    received = []

    async def on_deleted(event):
        received.append(event.payload)

    await bus.subscribe("user.deleted", on_deleted)
    plugin = make_plugin(db, bus)

    result = await plugin.execute({"user_id": str(user_id), "_auth": {"sub": str(user_id)}})

    assert result["success"] is True
    row = await db.query_one("SELECT id FROM users WHERE id = $1", [user_id])
    assert row is None

    await asyncio.sleep(0.01)
    assert received == [{"id": user_id}]


async def test_deleting_someone_else_is_forbidden(db, bus):
    user_id = await seed_user(db)
    plugin = make_plugin(db, bus)
    context = MagicMock()

    result = await plugin.execute(
        {"user_id": str(user_id), "_auth": {"sub": "777"}}, context
    )

    assert result["success"] is False
    assert result["error"] == "Forbidden"
    context.set_status.assert_called_once_with(403)
    row = await db.query_one("SELECT id FROM users WHERE id = $1", [user_id])
    assert row is not None  # still there


async def test_unknown_user_returns_not_found(db, bus):
    plugin = make_plugin(db, bus)

    result = await plugin.execute({"user_id": "9999", "_auth": {"sub": "9999"}})

    assert result["success"] is False
    assert result["error"] == "User not found"


async def test_db_failure_never_leaks_technical_detail(bus):
    broken_db = AsyncMock()
    broken_db.execute.side_effect = Exception("secret: table structure leaked")
    plugin = make_plugin(broken_db, bus)

    result = await plugin.execute({"user_id": "1", "_auth": {"sub": "1"}})

    assert result["success"] is False
    assert result["error"] == "Could not delete user"
    assert "secret" not in result["error"]
