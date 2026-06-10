import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from core.context import current_identity_var
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from tools.http_server.http_server_tool import HttpServerTool, HttpContext

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend(): return "asyncio"

@pytest.fixture
def http_tool():
    return HttpServerTool()

@pytest.fixture
async def client(http_tool):
    async with AsyncClient(transport=ASGITransport(app=http_tool.app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()

async def test_csrf_protection_with_cookies(http_tool, client):
    """
    Verify that mutation methods (POST, PUT, DELETE) require X-Requested-With 
    if a cookie is used for authentication.
    """
    def mock_validator(token):
        if token == "secret-session":
            return {"user": "juan"}
        return None

    async def handler(data, context):
        return {"success": True}

    http_tool.add_endpoint("/update", "POST", handler, auth_validator=mock_validator)
    http_tool._register_all_endpoints()

    # 1. Attempt with cookie but MISSING X-Requested-With (Should Fail/Block)
    client.cookies.set("access_token", "secret-session")
    resp = await client.post("/update")
    assert resp.status_code == 401
    assert "Missing authorization token" in resp.json()["error"]

    # 2. Attempt with cookie AND X-Requested-With (Should Pass)
    resp = await client.post("/update", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 3. Attempt with Bearer Token (Should Pass even without X-Requested-With)
    client.cookies.clear()
    resp = await client.post("/update", headers={"Authorization": "Bearer secret-session"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

async def test_safe_cookie_defaults(http_tool, client):
    """
    Verify that cookies have secure defaults (HttpOnly, Secure, SameSite).
    """
    async def handler(data, context: HttpContext):
        context.set_cookie("session", "data")
        return {"success": True}

    http_tool.add_endpoint("/login", "POST", handler)
    http_tool._register_all_endpoints()

    resp = await client.post("/login")
    cookie_header = resp.headers.get("set-cookie", "")

    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()

# ── EventBus Security Tests ──────────────────────────────────────────────

async def test_event_bus_emitter_protection(bus):
    """
    Verify that EventBusTool.publish ignores manual 'emitter' overrides.
    """
    captured_envelope = None

    async def subscriber(envelope: EventEnvelope):
        nonlocal captured_envelope
        captured_envelope = envelope

    await bus.subscribe("test.event", subscriber)

    # Set context identity
    token = current_identity_var.set("AuthorizedPlugin")
    try:
        # Attempt to spoof identity
        await bus.publish("test.event", {"msg": "hello"}, emitter="SYSTEM_ADMIN")

        # Give a small time for safe_execute task to run
        await asyncio.sleep(0.05)

        assert captured_envelope is not None
        assert captured_envelope.emitter == "AuthorizedPlugin"
        assert captured_envelope.emitter != "SYSTEM_ADMIN"
    finally:
        current_identity_var.reset(token)
