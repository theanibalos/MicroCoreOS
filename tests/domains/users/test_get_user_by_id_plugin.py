"""Black-box tests for GetUserByIdPlugin."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from extras.available_domains.users.plugins.get_user_by_id_plugin import GetUserByIdPlugin


# The users domain is an extra now; the marker resolves it under
# extras/available_domains/ without this file naming a path.
pytestmark = [pytest.mark.anyio, pytest.mark.migrations("users")]


@pytest.fixture
def anyio_backend():
    return "asyncio"




def make_plugin(db):
    return GetUserByIdPlugin(http=MagicMock(), db=db, logger=MagicMock(), auth=MagicMock())


async def test_returns_user_by_path_param(db):
    user_id = await db.execute(
        "INSERT INTO users (name, email, password_hash, roles) VALUES ($1, $2, $3, $4) RETURNING id",
        ["Ana", "ana@example.com", "hashed", json.dumps(["user"])],
    )
    plugin = make_plugin(db)

    result = await plugin.execute({"user_id": str(user_id)})

    assert result["success"] is True
    assert result["data"] == {"id": user_id, "name": "Ana", "email": "ana@example.com"}


async def test_unknown_id_returns_not_found(db):
    plugin = make_plugin(db)

    result = await plugin.execute({"user_id": "9999"})

    assert result["success"] is False
    assert result["error"] == "User not found"


async def test_missing_user_id_is_rejected(db):
    plugin = make_plugin(db)

    result = await plugin.execute({})

    assert result["success"] is False
    assert result["error"] == "Missing user_id"


async def test_db_failure_never_leaks_technical_detail():
    broken_db = AsyncMock()
    broken_db.query_one.side_effect = Exception("secret: connection string leaked")
    plugin = make_plugin(broken_db)

    result = await plugin.execute({"user_id": "1"})

    assert result["success"] is False
    assert result["error"] == "Could not fetch user"
    assert "secret" not in result["error"]
