import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tools.http_server.http_server_tool import HttpServerTool, HttpContext
from tools.http_server.pipeline import (
    _parse_trusted_proxies,
    _normalize_origin,
    _validate_ws_origin,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ISSUE 48: WEBSOCKET ORIGIN POLICY TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_normalize_origin():
    # Valid normalizations
    assert _normalize_origin("http://example.com") == "http://example.com"
    assert _normalize_origin("http://example.com:80") == "http://example.com"
    assert _normalize_origin("https://example.com:443") == "https://example.com"
    assert _normalize_origin("http://localhost:3000/") == "http://localhost:3000"
    assert _normalize_origin("HTTPS://EXAMPLE.COM:8443") == "https://example.com:8443"
    assert _normalize_origin("ws://chat.example.com") == "ws://chat.example.com"
    assert _normalize_origin("wss://chat.example.com:443") == "wss://chat.example.com"

    # Malformed origins
    with pytest.raises(ValueError):
        _normalize_origin("not-a-valid-origin")
    with pytest.raises(ValueError):
        _normalize_origin("ftp://example.com")


def test_ws_origin_policy_off_by_default():
    tool = HttpServerTool()
    assert tool._ws_origin_policy == "off"

    connected = []
    tool.add_ws_endpoint("/ws", lambda conn: connected.append(1))

    # Any origin or missing origin connects successfully
    with TestClient(tool.app).websocket_connect("/ws", headers={"Origin": "https://untrusted.com"}):
        pass
    assert len(connected) == 1

    with TestClient(tool.app).websocket_connect("/ws"):
        pass
    assert len(connected) == 2


def test_ws_origin_policy_allowlist_allowed_and_rejected():
    tool = HttpServerTool()
    tool._ws_origin_policy = "allowlist"
    tool._ws_allowed_origins = {"https://app.example.com", "http://localhost:5173"}
    tool._ws_allow_missing_origin = False

    called = []
    tool.add_ws_endpoint("/ws", lambda conn: called.append(True))

    client = TestClient(tool.app)

    # 1. Allowed origin passes
    with client.websocket_connect("/ws", headers={"Origin": "https://app.example.com"}):
        pass
    assert len(called) == 1

    # 2. Second allowed origin passes
    with client.websocket_connect("/ws", headers={"Origin": "http://localhost:5173"}):
        pass
    assert len(called) == 2

    # 3. Unlisted origin is rejected with 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"Origin": "https://evil.com"}):
            pass
    assert exc.value.code == 1008
    assert len(called) == 2, "Callback must not be invoked on rejected origin"

    # 4. Substring / suffix attack is rejected
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"Origin": "https://app.example.com.evil.com"}):
            pass
    assert exc.value.code == 1008
    assert len(called) == 2


def test_ws_origin_missing_origin_handling():
    tool = HttpServerTool()
    tool._ws_origin_policy = "allowlist"
    tool._ws_allowed_origins = {"https://app.example.com"}

    # Policy allow_missing = False (default): missing origin rejected
    tool._ws_allow_missing_origin = False
    called = []
    tool.add_ws_endpoint("/ws1", lambda conn: called.append(1))
    client = TestClient(tool.app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws1"):
            pass
    assert exc.value.code == 1008
    assert called == []

    # Policy allow_missing = True: missing origin accepted (e.g. non-browser clients)
    tool._ws_allow_missing_origin = True
    tool.add_ws_endpoint("/ws2", lambda conn: called.append(2))
    with client.websocket_connect("/ws2"):
        pass
    assert called == [2]


def test_ws_origin_rejects_null_and_malformed_and_multiple():
    ws_mock = MagicMock()
    ws_mock.headers = {"origin": "null"}
    allowed, reason = _validate_ws_origin(ws_mock, policy="allowlist", allowed_origins={"https://example.com"})
    assert not allowed
    assert "null" in reason

    ws_mock.headers = {"origin": "https://example.com, https://evil.com"}
    allowed, reason = _validate_ws_origin(ws_mock, policy="allowlist", allowed_origins={"https://example.com"})
    assert not allowed
    assert "Multiple origins" in reason

    ws_mock.headers = {"origin": "::not-an-origin::"}
    allowed, reason = _validate_ws_origin(ws_mock, policy="allowlist", allowed_origins={"https://example.com"})
    assert not allowed
    assert "Malformed" in reason


def test_ws_origin_rejection_precedes_auth_validator():
    """Origin rejection must happen before auth_validator is invoked."""
    tool = HttpServerTool()
    tool._ws_origin_policy = "allowlist"
    tool._ws_allowed_origins = {"https://app.example.com"}

    auth_validator_called = []
    on_connect_called = []

    def mock_validator(token):
        auth_validator_called.append(token)
        return {"sub": "user1"}

    tool.add_ws_endpoint(
        "/ws",
        on_connect=lambda conn, auth: on_connect_called.append(auth),
        auth_validator=mock_validator,
    )

    client = TestClient(tool.app)

    # Calling from untrusted origin with a valid token
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=my-token", headers={"Origin": "https://untrusted.com"}):
            pass
    assert exc.value.code == 1008
    assert auth_validator_called == [], "Auth validator must not be called when origin is rejected"
    assert on_connect_called == []


@pytest.mark.anyio
async def test_ws_setup_validation(monkeypatch):
    tool = HttpServerTool()

    # Invalid policy
    monkeypatch.setenv("HTTP_WS_ORIGIN_POLICY", "invalid_policy")
    with pytest.raises(ValueError, match="Invalid HTTP_WS_ORIGIN_POLICY"):
        await tool.setup()

    # Allowlist with empty origins
    monkeypatch.setenv("HTTP_WS_ORIGIN_POLICY", "allowlist")
    monkeypatch.setenv("HTTP_WS_ORIGINS", "")
    with pytest.raises(ValueError, match="HTTP_WS_ORIGINS must not be empty"):
        await tool.setup()

    # Allowlist with wildcard origin
    monkeypatch.setenv("HTTP_WS_ORIGINS", "https://app.com, *")
    with pytest.raises(ValueError, match="Wildcard '\\*' is not permitted"):
        await tool.setup()

    # Allowlist with valid configuration
    monkeypatch.setenv("HTTP_WS_ORIGINS", "https://app.example.com, http://localhost:3000")
    monkeypatch.setenv("HTTP_WS_ALLOW_MISSING_ORIGIN", "false")
    await tool.setup()
    assert tool._ws_origin_policy == "allowlist"
    assert "https://app.example.com" in tool._ws_allowed_origins
    assert "http://localhost:3000" in tool._ws_allowed_origins


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRUSTED PROXIES & CLIENT IP RESOLUTION TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.anyio
async def test_trusted_proxies_setup_validation(monkeypatch):
    tool = HttpServerTool()

    # Invalid IP / CIDR
    monkeypatch.setenv("HTTP_TRUSTED_PROXIES", "127.0.0.1, not-a-cidr/99")
    with pytest.raises(ValueError, match="Invalid IP or CIDR in HTTP_TRUSTED_PROXIES"):
        await tool.setup()

    # Invalid Cloudflare boolean
    monkeypatch.setenv("HTTP_TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.setenv("HTTP_TRUST_CLOUDFLARE", "maybe")
    with pytest.raises(ValueError, match="Invalid HTTP_TRUST_CLOUDFLARE"):
        await tool.setup()

    # Valid config with custom IP header
    monkeypatch.setenv("HTTP_CUSTOM_CLIENT_IP_HEADER", "X-Real-IP")
    monkeypatch.setenv("HTTP_TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/8, ::1")
    monkeypatch.setenv("HTTP_WS_ORIGIN_POLICY", "off")
    monkeypatch.delenv("HTTP_TRUST_CLOUDFLARE", raising=False)
    await tool.setup()
    assert tool._custom_ip_header == "X-Real-IP"
    assert len(tool._trusted_proxies) == 3

    # Wildcard config accepts any peer IP
    wildcard_tool = HttpServerTool()
    monkeypatch.setenv("HTTP_TRUSTED_PROXIES", "*")
    await wildcard_tool.setup()
    assert len(wildcard_tool._trusted_proxies) == 2  # 0.0.0.0/0 and ::/0


@pytest.mark.anyio
async def test_trusted_proxies_end_to_end_in_http_server():
    tool = HttpServerTool()
    tool._trusted_proxies = _parse_trusted_proxies("10.0.0.0/8, 127.0.0.1")
    tool._custom_ip_header = "X-Real-IP"

    seen_ip = {}

    async def handler(data, ctx: HttpContext):
        seen_ip["ip"] = ctx.client_ip
        return {"success": True}

    tool.add_endpoint("/ip-check", "GET", handler)
    tool._register_all_endpoints()

    client = TestClient(tool.app)

    # In TestClient, default client.host is "testclient" which is not a valid IP in trusted_proxies
    resp = client.get("/ip-check", headers={"X-Forwarded-For": "198.51.100.1", "X-Real-IP": "198.51.100.2"})
    assert resp.status_code == 200
    # Because 'testclient' is not in trusted_proxies, headers are ignored as spoofing
    assert seen_ip["ip"] == "testclient"
