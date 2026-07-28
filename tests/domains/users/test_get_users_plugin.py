"""Black-box tests for ListUsersPlugin (pagination)."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from extras.available_domains.users.plugins.get_users_plugin import ListUsersPlugin


# The users domain is an extra now; the marker resolves it under
# extras/available_domains/ without this file naming a path.
pytestmark = [pytest.mark.anyio, pytest.mark.migrations("users")]


@pytest.fixture
def anyio_backend():
    return "asyncio"




def make_plugin(db):
    return ListUsersPlugin(http=MagicMock(), db=db, logger=MagicMock(), auth=MagicMock())


async def seed_users(db, count):
    for i in range(1, count + 1):
        await db.execute(
            "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4)",
            [f"User {i}", f"user{i}@example.com", "hashed", json.dumps(["user"])],
        )


async def test_lists_users_with_limit_and_offset(db):
    await seed_users(db, 3)
    plugin = make_plugin(db)

    result = await plugin.execute({"limit": 2, "offset": 1})

    assert result["success"] is True
    assert result["data"]["limit"] == 2
    assert result["data"]["offset"] == 1
    emails = [u["email"] for u in result["data"]["users"]]
    assert emails == ["user2@example.com", "user3@example.com"]


async def test_empty_table_returns_empty_list(db):
    plugin = make_plugin(db)

    result = await plugin.execute({})

    assert result["success"] is True
    assert result["data"]["users"] == []


async def test_db_failure_returns_500_and_never_leaks():
    broken_db = AsyncMock()
    broken_db.query.side_effect = Exception("secret: SQL structure leaked")
    plugin = make_plugin(broken_db)
    context = MagicMock()

    result = await plugin.execute({}, context)

    assert result["success"] is False
    assert result["error"] == "Internal Server Error"
    assert "secret" not in result["error"]
    context.set_status.assert_called_once_with(500)
