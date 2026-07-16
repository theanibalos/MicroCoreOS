"""Black-box tests for LoginPlugin.

Real tools: SQLite :memory: with the users migrations applied, real AuthTool
(hashing + JWT), real in-memory StateTool (throttle window). Only the
error-path test mocks `db` to force a failure.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.users.plugins.login_plugin import LoginPlugin
from tools.auth.auth_tool import AuthTool
from tools.sqlite.sqlite_tool import SqliteTool
from tools.state.state_tool import StateTool

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


@pytest.fixture
def plugin_factory(db, auth):
    def make(db_tool=None):
        return LoginPlugin(
            http=MagicMock(),
            db=db_tool or db,
            auth=auth,
            logger=MagicMock(),
            state=StateTool(),
        )
    return make


async def seed_user(db, auth, email="ana@example.com", password="password123", roles=None):
    password_hash = await auth.hash_password(password)
    return await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", email, password_hash, json.dumps(roles or ["user"])],
    )


async def test_login_returns_valid_token_and_sets_cookie(db, auth, plugin_factory):
    user_id = await seed_user(db, auth)
    plugin = plugin_factory()
    context = MagicMock()

    result = await plugin.execute(
        {"email": "ana@example.com", "password": "password123"}, context
    )

    assert result["success"] is True
    token = result["data"]["token"]
    claims = auth.validate_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["email"] == "ana@example.com"
    assert claims["roles"] == ["user"]

    context.set_cookie.assert_called_once()
    assert context.set_cookie.call_args.args[0] == "access_token"


async def test_token_carries_all_user_roles(db, auth, plugin_factory):
    await seed_user(db, auth, roles=["user", "admin"])
    plugin = plugin_factory()

    result = await plugin.execute({"email": "ana@example.com", "password": "password123"})

    assert result["success"] is True
    claims = auth.validate_token(result["data"]["token"])
    assert claims["roles"] == ["user", "admin"]


async def test_wrong_password_returns_generic_error(db, auth, plugin_factory):
    await seed_user(db, auth)
    plugin = plugin_factory()

    result = await plugin.execute({"email": "ana@example.com", "password": "wrong-pass"})

    assert result["success"] is False
    assert result["error"] == "Invalid email or password"


async def test_unknown_email_returns_same_generic_error(plugin_factory):
    plugin = plugin_factory()

    result = await plugin.execute({"email": "ghost@example.com", "password": "whatever1"})

    # Same message as wrong password: no user enumeration.
    assert result["success"] is False
    assert result["error"] == "Invalid email or password"


async def test_throttled_after_max_failed_attempts(db, auth, plugin_factory):
    await seed_user(db, auth)
    plugin = plugin_factory()
    context = MagicMock()

    for _ in range(LoginPlugin.MAX_ATTEMPTS):
        await plugin.execute({"email": "ana@example.com", "password": "wrong-pass"})

    # Even the CORRECT password is rejected while throttled.
    result = await plugin.execute(
        {"email": "ana@example.com", "password": "password123"}, context
    )

    assert result["success"] is False
    assert result["error"] == "Too many attempts. Try again later."
    context.set_status.assert_called_once_with(429)


async def test_db_failure_never_leaks_technical_detail(plugin_factory):
    broken_db = AsyncMock()
    broken_db.query_one.side_effect = Exception("secret: /var/lib/db path leaked")
    plugin = plugin_factory(db_tool=broken_db)

    result = await plugin.execute({"email": "ana@example.com", "password": "password123"})

    assert result["success"] is False
    assert result["error"] == "Authentication failed"
    assert "secret" not in result["error"]
