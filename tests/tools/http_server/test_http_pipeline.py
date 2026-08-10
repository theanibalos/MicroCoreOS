import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi import Request
from starlette.datastructures import Headers
from tools.http_server.pipeline import (
    _serialize,
    _sse_response,
    _process_request,
    _extract_bearer_token,
    _extract_ws_token,
    _extract_client_ip,
)
from tools.http_server.context import HttpContext
from pydantic import BaseModel


class SampleModel(BaseModel):
    name: str
    age: int


def test_serialize_pydantic_and_nested():
    model = SampleModel(name="Alice", age=30)
    res = _serialize({"user": model, "list": [model]})
    assert res == {"user": {"name": "Alice", "age": 30}, "list": [{"name": "Alice", "age": 30}]}


@pytest.mark.anyio
async def test_extract_ws_token_variants():
    # 1. Bearer header
    ws1 = MagicMock()
    ws1.headers = {"Authorization": "Bearer ws_token_123"}
    assert _extract_ws_token(ws1) == "ws_token_123"

    # 2. Query param
    ws2 = MagicMock()
    ws2.headers = {}
    ws2.query_params = {"token": "ws_query_token"}
    assert _extract_ws_token(ws2) == "ws_query_token"

    # 3. Cookie fallback
    ws3 = MagicMock()
    ws3.headers = {}
    ws3.query_params = {}
    ws3.cookies = {"access_token": "ws_cookie_token"}
    assert _extract_ws_token(ws3) == "ws_cookie_token"


@pytest.mark.anyio
async def test_extract_bearer_token_csrf_block():
    req = MagicMock(spec=Request)
    req.headers = Headers({})
    req.cookies = {"access_token": "cookie_jwt"}
    req.method = "POST"

    # Without X-Requested-With header -> CSRF block returns None
    token = _extract_bearer_token(req)
    assert token is None

    # With X-Requested-With header -> Token allowed
    req.headers = Headers({"X-Requested-With": "XMLHttpRequest"})
    token = _extract_bearer_token(req)
    assert token == "cookie_jwt"


def test_extract_client_ip_trust_order():
    # 1. Cf-Connecting-Ip wins even if the other two are also present.
    req = MagicMock(spec=Request)
    req.headers = Headers({
        "Cf-Connecting-Ip": "203.0.113.7",
        "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
    })
    req.client = MagicMock(host="10.0.0.99")
    assert _extract_client_ip(req) == "203.0.113.7"

    # 2. No Cf-Connecting-Ip -> first hop of X-Forwarded-For.
    req = MagicMock(spec=Request)
    req.headers = Headers({"X-Forwarded-For": "198.51.100.1, 10.0.0.1"})
    req.client = MagicMock(host="10.0.0.99")
    assert _extract_client_ip(req) == "198.51.100.1"

    # 3. Neither header -> the direct TCP peer.
    req = MagicMock(spec=Request)
    req.headers = Headers({})
    req.client = MagicMock(host="10.0.0.99")
    assert _extract_client_ip(req) == "10.0.0.99"

    # 4. No signal at all (request.client itself is None) -> None, not a crash.
    req = MagicMock(spec=Request)
    req.headers = Headers({})
    req.client = None
    assert _extract_client_ip(req) is None


@pytest.mark.anyio
async def test_process_request_exposes_client_ip_to_handler():
    req = MagicMock(spec=Request)
    req.query_params = {}
    req.path_params = {}
    req.headers = Headers({"Cf-Connecting-Ip": "203.0.113.7"})
    req.method = "GET"
    req.url.path = "/whoami"
    req.client = MagicMock(host="10.0.0.99")

    seen_ip = {}

    async def handler(data, ctx: HttpContext):
        seen_ip["value"] = ctx.client_ip
        return {"success": True}

    await _process_request(
        request=req,
        body_data=None,
        handler=handler,
        auth_validator=None,
        paused_owners=set(),
    )

    assert seen_ip["value"] == "203.0.113.7"


@pytest.mark.anyio
async def test_process_request_redirect_response():
    req = MagicMock(spec=Request)
    req.query_params = {}
    req.path_params = {}
    req.headers = Headers({})
    req.method = "GET"
    req.url.path = "/redirect-test"

    async def redirect_handler(data, ctx: HttpContext):
        ctx.redirect("/login")
        ctx.set_header("X-Custom", "123")
        ctx.set_cookie("session", "abc")
        return {}

    response = await _process_request(
        request=req,
        body_data=None,
        handler=redirect_handler,
        auth_validator=None,
        paused_owners=set(),
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert response.headers["X-Custom"] == "123"


@pytest.mark.anyio
async def test_sse_response_auth_and_stream():
    req = MagicMock(spec=Request)
    req.query_params = {"channel": "news"}
    req.path_params = {}
    req.headers = Headers({"Authorization": "Bearer sse_token"})
    req.is_disconnected = AsyncMock(side_effect=[False, False, True])

    async def sse_gen(data):
        assert data["_auth"] == {"sub": "user1"}
        yield "event: update\ndata: {}\n\n"

    async def auth_val(token):
        assert token == "sse_token"
        return {"sub": "user1"}

    response = await _sse_response(req, sse_gen, auth_val)
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"


@pytest.mark.anyio
async def test_sse_response_auth_failures_and_sync_validator():
    req = MagicMock(spec=Request)
    req.headers = Headers({})
    req.cookies = {}

    # 1. Missing token -> 401
    res1 = await _sse_response(req, None, auth_validator=lambda t: True)
    assert res1.status_code == 401

    # 2. Invalid token with sync validator -> 401
    req.headers = Headers({"Authorization": "Bearer invalid"})
    res2 = await _sse_response(req, None, auth_validator=lambda t: None)
    assert res2.status_code == 401

    # 3. Valid token with sync validator
    req.headers = Headers({"Authorization": "Bearer valid"})
    req.query_params = {}
    req.path_params = {}
    req.is_disconnected = AsyncMock(side_effect=[False, True])

    def sync_val(token):
        return {"sub": "sync_user"}

    async def sse_gen(data):
        yield "data: ok\n\n"

    res3 = await _sse_response(req, sse_gen, auth_validator=sync_val)
    assert res3.status_code == 200


@pytest.mark.anyio
async def test_process_request_paused_owner_503():
    req = MagicMock(spec=Request)
    req.query_params = {}
    req.path_params = {}
    req.headers = Headers({})
    req.method = "POST"
    req.url.path = "/test"

    async def my_handler(data, ctx):
        return {"success": True}

    # Pass paused_owners matching handler name
    res = await _process_request(
        request=req,
        body_data=None,
        handler=my_handler,
        auth_validator=None,
        paused_owners={"my_handler"},
    )
    assert res.status_code == 503


@pytest.mark.anyio
async def test_process_request_auto_400_and_sync_auth():
    req = MagicMock(spec=Request)
    req.query_params = {}
    req.path_params = {}
    req.headers = Headers({"Authorization": "Bearer token123"})
    req.method = "POST"
    req.url.path = "/test"

    def sync_auth(token):
        return {"sub": "user_sync"}

    async def failing_handler(data, ctx):
        assert data["_auth"] == {"sub": "user_sync"}
        return {"success": False, "error": "validation failed"}

    res = await _process_request(
        request=req,
        body_data=None,
        handler=failing_handler,
        auth_validator=sync_auth,
        paused_owners=set(),
    )
    assert res.status_code == 400


@pytest.mark.anyio
async def test_process_request_manual_form_extraction():
    req = MagicMock(spec=Request)
    req.query_params = {}
    req.path_params = {}
    req.headers = Headers({"Content-Type": "application/x-www-form-urlencoded"})
    req.method = "POST"
    req.url.path = "/form"

    mock_field = MagicMock()
    del mock_field.filename  # not a file
    mock_field.__str__ = lambda self: "john"

    req.form = AsyncMock(return_value={"username": "john"})

    captured = {}
    async def handler(data, ctx):
        captured.update(data)
        return {"success": True}

    res = await _process_request(
        request=req,
        body_data=None,
        handler=handler,
        auth_validator=None,
        paused_owners=set(),
    )
    assert res.status_code == 200
    assert captured.get("username") == "john"
