import pytest
from unittest.mock import AsyncMock, MagicMock
from domains.users.plugins.create_user_plugin import CreateUserPlugin

@pytest.mark.anyio
async def test_create_user_success():
    # 1. Setup Mock Tools
    mock_db = AsyncMock()
    mock_db.execute.return_value = 123  # Mocked user ID
    
    mock_bus = AsyncMock()
    mock_auth = MagicMock()
    # auth.hash_password is async (bcrypt runs in a thread)
    mock_auth.hash_password = AsyncMock(return_value="hashed_password_123")
    
    mock_logger = MagicMock()
    mock_http = MagicMock()

    # 2. Initialize Plugin with Mocks
    plugin = CreateUserPlugin(
        http=mock_http,
        db=mock_db,
        event_bus=mock_bus,
        logger=mock_logger,
        auth=mock_auth
    )

    # 3. Simulate Request Data
    test_data = {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "securepassword123"
    }

    # 4. Execute Plugin Logic
    result = await plugin.execute(test_data)

    # 5. Assertions
    assert result["success"] is True
    assert result["data"]["id"] == 123
    assert result["data"]["name"] == "John Doe"
    assert result["data"]["roles"] == ["user"]
    
    # Verify DB was called correctly
    mock_db.execute.assert_called_once()
    sql_arg = mock_db.execute.call_args[0][0]
    assert "INSERT INTO users" in sql_arg
    assert "roles" in sql_arg
    
    # Verify Event was published
    mock_bus.publish.assert_called_once_with(
        "user.created", 
        {"id": 123, "email": "john@example.com", "roles": ["user"]}
    )
    
    # Verify Auth was used
    mock_auth.hash_password.assert_called_once_with("securepassword123")

@pytest.mark.anyio
async def test_create_user_failure():
    # Setup Mock Tools for Failure
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("Database Connection Lost")
    
    mock_logger = MagicMock()
    
    mock_auth = MagicMock()
    mock_auth.hash_password = AsyncMock(return_value="hashed_password_123")

    plugin = CreateUserPlugin(
        http=MagicMock(),
        db=mock_db,
        event_bus=AsyncMock(),
        logger=mock_logger,
        auth=mock_auth
    )

    result = await plugin.execute({"name": "Fail", "email": "fail@test.com", "password": "password123"})

    assert result["success"] is False
    assert "error" in result
    # Safe error: raw exception must NOT be exposed to the client
    assert "Database Connection Lost" not in result["error"]
    assert result["error"] == "Could not create user"

    # Verify the real error was logged server-side
    mock_logger.error.assert_called_once()
