import pytest
from httpx import AsyncClient, ASGITransport
from tools.http_server.http_server_tool import HttpServerTool
from unittest.mock import AsyncMock
from pydantic import BaseModel

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

async def test_http_path_param_merging_with_body():
    """
    Verify that path parameters ({id}) are correctly merged
    even when there is a JSON body and a Pydantic model is used.
    """
    server = HttpServerTool()
    # Mock a plugin
    handler = AsyncMock(return_value={"success": True})
    
    # Add endpoint with path param
    # Use request_model to force the Pydantic parsing branch
    class Item(BaseModel):
        name: str

    server.add_endpoint(
        path="/items/{item_id}",
        method="POST",
        handler=handler,
        request_model=Item
    )
    
    server._register_all_endpoints()

    # HttpServerTool uses server.app (FastAPI)
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        response = await ac.post("/items/42", json={"name": "test_item"})
    
    assert response.status_code == 200
    # The handler must have received both item_id and name
    called_data = handler.call_args[0][0]
    assert called_data["item_id"] == "42"
    assert called_data["name"] == "test_item"
