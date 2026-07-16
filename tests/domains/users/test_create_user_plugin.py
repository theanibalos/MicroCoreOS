"""Black-box tests for CreateUserPlugin.

Real tools: SQLite :memory: with the users migrations, real AuthTool, real
in-process event bus. Only the error-path test mocks `db`.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.create_user_plugin import CreateUserPlugin
from tools.auth.auth_tool import AuthTool
from tools.event_bus.event_bus_tool import EventBusTool
from tools.sqlite.sqlite_tool import SqliteTool

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "domains" / "users" / "migrations"
SECRET = "test-secret-key-32chars-long-ok!"

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


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)
    return AuthTool()


def make_plugin(db, bus, auth):
    return CreateUserPlugin(
        http=MagicMock(), db=db, event_bus=bus, logger=MagicMock(), auth=auth
    )


async def test_create_user_persists_row_and_publishes_event(db, bus, auth):
    received = []

    async def on_created(event):
        received.append(event.payload)

    await bus.subscribe("user.created", on_created)
    plugin = make_plugin(db, bus, auth)

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


async def test_duplicate_email_returns_specific_error(db, bus, auth):
    plugin = make_plugin(db, bus, auth)
    payload = {"name": "Ana", "email": "ana@example.com", "password": "password123"}

    first = await plugin.execute(payload)
    second = await plugin.execute(payload)

    assert first["success"] is True
    assert second["success"] is False
    assert second["error"] == "Email already in use"

    rows = await db.query("SELECT id FROM users WHERE email = $1", ["ana@example.com"])
    assert len(rows) == 1


async def test_db_failure_never_leaks_technical_detail(bus, auth):
    broken_db = AsyncMock()
    broken_db.execute.side_effect = Exception("secret: table structure leaked")
    plugin = make_plugin(broken_db, bus, auth)

    result = await plugin.execute(
        {"name": "Ana", "email": "ana@example.com", "password": "password123"}
    )

    assert result["success"] is False
    assert result["error"] == "Could not create user"
    assert "secret" not in result["error"]
