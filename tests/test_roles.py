import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from domains.users.plugins.login_plugin import LoginPlugin

@pytest.mark.anyio
async def test_login_includes_roles_in_token():
    # 1. Setup Mock Tools
    mock_db = AsyncMock()
    # Simulate user with admin role
    mock_db.query_one.return_value = {
        "id": 1,
        "password_hash": "hashed_pass",
        "roles": json.dumps(["user", "admin"])
    }
    
    mock_auth = MagicMock()
    mock_auth.verify_password = AsyncMock(return_value=True)
    mock_auth.create_token.return_value = "fake_jwt_token"
    
    mock_state = AsyncMock()
    mock_state.get.return_value = 0 # No throttle
    
    mock_logger = MagicMock()
    mock_http = MagicMock()

    # 2. Initialize Plugin
    plugin = LoginPlugin(
        http=mock_http,
        db=mock_db,
        auth=mock_auth,
        logger=mock_logger,
        state=mock_state
    )

    # 3. Execute
    test_data = {"email": "admin@example.com", "password": "password123"}
    result = await plugin.execute(test_data)

    # 4. Assertions
    assert result["success"] is True
    
    # Verify create_token was called with roles
    mock_auth.create_token.assert_called_once()
    claims = mock_auth.create_token.call_args[0][0]
    assert claims["roles"] == ["user", "admin"]
    assert claims["email"] == "admin@example.com"
    assert claims["sub"] == "1"

@pytest.mark.anyio
async def test_login_default_roles_if_missing():
    mock_db = AsyncMock()
    # Missing roles column or null
    mock_db.query_one.return_value = {
        "id": 2,
        "password_hash": "hashed_pass",
        "roles": None
    }
    
    mock_auth = MagicMock()
    mock_auth.verify_password = AsyncMock(return_value=True)
    
    mock_state = AsyncMock()
    mock_state.get.return_value = 0 # No throttle

    plugin = LoginPlugin(
        http=MagicMock(),
        db=mock_db,
        auth=mock_auth,
        logger=MagicMock(),
        state=mock_state
    )

    result = await plugin.execute({"email": "user@example.com", "password": "password123"})
    assert result["success"] is True

    claims = mock_auth.create_token.call_args[0][0]
    assert claims["roles"] == ["user"]
