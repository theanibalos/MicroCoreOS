"""Black-box tests for UpdateUserPlugin (ownership + partial updates)."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.update_user_plugin import UpdateUserPlugin
from tools.auth.auth_tool import AuthTool
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
def auth(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)
    return AuthTool()


def make_plugin(db, auth):
    return UpdateUserPlugin(
        http=MagicMock(), db=db, event_bus=AsyncMock(), logger=MagicMock(), auth=auth
    )


async def seed_user(db, email="ana@example.com"):
    return await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", email, "hashed", json.dumps(["user"])],
    )


async def test_user_updates_own_name_and_email(db, auth):
    user_id = await seed_user(db)
    plugin = make_plugin(db, auth)

    result = await plugin.execute({
        "user_id": str(user_id),
        "_auth": {"sub": str(user_id)},
        "name": "Ana Maria",
        "email": "ana.maria@example.com",
    })

    assert result["success"] is True
    row = await db.query_one("SELECT name, email FROM users WHERE id = $1", [user_id])
    assert row == {"name": "Ana Maria", "email": "ana.maria@example.com"}


async def test_password_update_is_stored_hashed(db, auth):
    user_id = await seed_user(db)
    plugin = make_plugin(db, auth)

    result = await plugin.execute({
        "user_id": str(user_id),
        "_auth": {"sub": str(user_id)},
        "password": "new-password-9",
    })

    assert result["success"] is True
    row = await db.query_one("SELECT password_hash FROM users WHERE id = $1", [user_id])
    assert row["password_hash"] != "new-password-9"
    assert await auth.verify_password("new-password-9", row["password_hash"])


async def test_updating_someone_else_is_forbidden(db, auth):
    user_id = await seed_user(db)
    plugin = make_plugin(db, auth)
    context = MagicMock()

    result = await plugin.execute(
        {"user_id": str(user_id), "_auth": {"sub": "777"}, "name": "Hacked"}, context
    )

    assert result["success"] is False
    assert result["error"] == "Forbidden"
    context.set_status.assert_called_once_with(403)
    row = await db.query_one("SELECT name FROM users WHERE id = $1", [user_id])
    assert row["name"] == "Ana"  # untouched


async def test_no_fields_to_update_is_rejected(db, auth):
    user_id = await seed_user(db)
    plugin = make_plugin(db, auth)

    result = await plugin.execute({"user_id": str(user_id), "_auth": {"sub": str(user_id)}})

    assert result["success"] is False
    assert result["error"] == "No fields to update"


async def test_unknown_user_returns_not_found(db, auth):
    plugin = make_plugin(db, auth)

    result = await plugin.execute(
        {"user_id": "9999", "_auth": {"sub": "9999"}, "name": "Ghost"}
    )

    assert result["success"] is False
    assert result["error"] == "User not found"


async def test_duplicate_email_returns_specific_error(db, auth):
    await seed_user(db, email="taken@example.com")
    user_id = await seed_user(db, email="ana@example.com")
    plugin = make_plugin(db, auth)

    result = await plugin.execute({
        "user_id": str(user_id),
        "_auth": {"sub": str(user_id)},
        "email": "taken@example.com",
    })

    assert result["success"] is False
    assert result["error"] == "Email already in use"


async def test_db_failure_never_leaks_technical_detail(auth):
    broken_db = AsyncMock()
    broken_db.execute.side_effect = Exception("secret: SQL structure leaked")
    plugin = make_plugin(broken_db, auth)

    result = await plugin.execute(
        {"user_id": "1", "_auth": {"sub": "1"}, "name": "Ana"}
    )

    assert result["success"] is False
    assert result["error"] == "Could not update user"
    assert "secret" not in result["error"]
