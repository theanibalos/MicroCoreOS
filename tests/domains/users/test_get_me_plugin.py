"""Black-box tests for GetMePlugin (protected endpoint, ownership via _auth)."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.get_me_plugin import GetMePlugin
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


def make_plugin(db):
    return GetMePlugin(http=MagicMock(), db=db, auth=MagicMock(), logger=MagicMock())


async def seed_user(db, email="ana@example.com", roles=None):
    return await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", email, "hashed", json.dumps(roles or ["user", "admin"])],
    )


async def test_returns_own_profile_with_parsed_roles(db):
    user_id = await seed_user(db)
    plugin = make_plugin(db)

    result = await plugin.execute({"_auth": {"sub": str(user_id)}})

    assert result["success"] is True
    assert result["data"] == {
        "id": user_id,
        "name": "Ana",
        "email": "ana@example.com",
        "roles": ["user", "admin"],
    }


async def test_missing_auth_payload_is_unauthorized(db):
    plugin = make_plugin(db)

    result = await plugin.execute({})

    assert result["success"] is False
    assert result["error"] == "Unauthorized"


async def test_deleted_user_with_valid_token(db):
    plugin = make_plugin(db)

    result = await plugin.execute({"_auth": {"sub": "9999"}})

    assert result["success"] is False
    assert result["error"] == "User no longer exists"


async def test_db_failure_never_leaks_technical_detail():
    broken_db = AsyncMock()
    broken_db.query_one.side_effect = Exception("secret: SQL structure leaked")
    plugin = make_plugin(broken_db)

    result = await plugin.execute({"_auth": {"sub": "1"}})

    assert result["success"] is False
    assert result["error"] == "Could not fetch user"
    assert "secret" not in result["error"]
