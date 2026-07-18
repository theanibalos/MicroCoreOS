import pytest
from httpx import AsyncClient, ASGITransport
from tools.http_server.http_server_tool import HttpServerTool, HttpContext

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def tool():
    t = HttpServerTool()
    # No necesitamos setup() completo ni arrancar uvicorn para probar la app de FastAPI
    return t

@pytest.fixture
async def client(tool):
    async with AsyncClient(transport=ASGITransport(app=tool.app), base_url="http://test") as ac:
        yield ac

async def test_data_merging_intent(tool, client):
    """
    The Gateway's intent is to be transparent and merge all input data
    (path, query, body) into a single 'data' dictionary.
    """
    received_data = {}

    async def handler(data, context):
        received_data.update(data)
        return {"success": True}

    tool.add_endpoint("/test/{id}", "POST", handler)
    tool._register_all_endpoints()

    await client.post("/test/42?query_param=val", json={"body_param": "data"})

    assert received_data.get("id") == "42"
    assert received_data.get("query_param") == "val"
    assert received_data.get("body_param") == "data"

async def test_auth_injection_intent(tool, client):
    """
    The security intent is that when a validator is present, it injects
    its result into data['_auth'] automatically.
    """
    async def mock_validator(token):
        if token == "valid-token":
            return {"user_id": 123}
        return None

    async def handler(data, context):
        return {"success": True, "data": {"user": data.get("_auth")}}

    tool.add_endpoint("/secure", "GET", handler, auth_validator=mock_validator)
    tool._register_all_endpoints()

    # Intento sin token
    resp = await client.get("/secure")
    assert resp.status_code == 401
    assert resp.json()["success"] is False

    # Attempt with a valid token
    resp = await client.get("/secure", headers={"Authorization": "Bearer valid-token"})
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["user_id"] == 123

async def test_http_context_manipulation_intent(tool, client):
    """
    The intent of HttpContext is to let the plugin control the
    response (status, headers, cookies) without coupling to FastAPI.
    """
    async def handler(data, context: HttpContext):
        context.set_status(201)
        context.set_header("X-Custom", "Value")
        context.set_cookie("test_cookie", "yum")
        return {"success": True}

    tool.add_endpoint("/context", "GET", handler)
    tool._register_all_endpoints()

    resp = await client.get("/context")
    assert resp.status_code == 201
    assert resp.headers["X-Custom"] == "Value"
    assert "test_cookie=yum" in resp.headers.get("set-cookie", "")

async def test_binary_response_intent(tool, client):
    """
    The intent is that the plugin can return raw data (e.g. images),
    bypassing the standard JSON envelope.
    """
    async def handler(data, context: HttpContext):
        context.set_binary_response(b"raw-data", media_type="text/plain")
        return {"success": True} # Will be ignored by the tool

    tool.add_endpoint("/binary", "GET", handler)
    tool._register_all_endpoints()

    resp = await client.get("/binary")
    assert resp.status_code == 200
    assert resp.content == b"raw-data"
    assert "text/plain" in resp.headers["content-type"]

async def test_unhandled_exception_safety_intent(tool, client):
    """
    The resilience intent is that plugin failures do not break the server
    y devuelvan un error 500 consistente al cliente.
    """
    async def handler(data, context):
        raise RuntimeError("Oops!")

    tool.add_endpoint("/fail", "GET", handler)
    tool._register_all_endpoints()

    resp = await client.get("/fail")
    assert resp.status_code == 500
    assert resp.json()["success"] is False
    assert "Internal server error" in resp.json()["error"]


class _FakePlugin:
    """Stand-in for a booted plugin: Kernel stamps `_identity` on real ones."""
    def __init__(self, identity):
        self._identity = identity

    async def handler(self, data, context=None):
        return {"success": True}


def test_pre_mount_hook_receives_owner_per_endpoint(tool):
    """
    Issue 26 support: register_pre_mount_hook must be invoked once, before
    mounting, with every buffered endpoint annotated with the registering
    plugin's identity — this is what the architecture linter's
    route-collision check consumes.
    """
    plugin_a = _FakePlugin("users.ProfilePlugin")
    plugin_b = _FakePlugin("billing.AccountPlugin")

    tool.add_endpoint("/users/me", "GET", plugin_a.handler)
    tool.add_endpoint("/billing/invoice", "GET", plugin_b.handler)

    received = []
    tool.register_pre_mount_hook(received.append)
    tool._run_pre_mount_hooks()

    assert len(received) == 1
    endpoints = received[0]
    by_path = {ep["path"]: ep for ep in endpoints}
    assert by_path["/users/me"]["owner"] == "users.ProfilePlugin"
    assert by_path["/billing/invoice"]["owner"] == "billing.AccountPlugin"
