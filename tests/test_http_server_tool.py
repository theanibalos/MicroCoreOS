import os

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


# ─── mount_static ────────────────────────────────────────────────────────────

@pytest.fixture
def ui_dir(tmp_path):
    """A UI build directory holding the kind of files that leak from one."""
    d = tmp_path / "ui"
    (d / ".git").mkdir(parents=True)
    (d / "sub").mkdir()
    (d / "index.html").write_text("<h1>home</h1>")
    (d / "app.js").write_text("console.log('hi')")
    (d / "sub" / "index.html").write_text("<h1>sub</h1>")
    (d / ".env").write_text("SECRET_KEY=hunter2")
    (d / ".git" / "config").write_text("url=git@private")
    (d / "app.js.map").write_text('{"sources":["/home/me/src/secret.ts"]}')
    (d / "backup.sql").write_text("INSERT INTO users")
    (d / "notes.md").write_text("staging password is hunter2")
    (d / "Dockerfile").write_text("FROM python")
    return str(d)


def _mount(tool, *args, **kwargs):
    """mount_static + the boot step that applies buffered mounts."""
    tool.mount_static(*args, **kwargs)
    tool._register_all_static_mounts()


async def test_mount_static_serves_allowed_files(tool, client, ui_dir):
    _mount(tool, "/static", ui_dir)

    resp = await client.get("/static/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


async def test_mount_static_html_serves_index_for_directory(tool, client, ui_dir):
    """A UI mounted at "/" is only usable if the mount root resolves to index.html."""
    _mount(tool, "/ui", ui_dir, html=True)

    resp = await client.get("/ui/")
    assert resp.status_code == 200
    assert "<h1>home</h1>" in resp.text

    resp = await client.get("/ui/sub/")
    assert resp.status_code == 200
    assert "<h1>sub</h1>" in resp.text


async def test_mount_static_defaults_to_no_index_resolution(tool, client, ui_dir):
    """html defaults to False, leaving 404 semantics unchanged for asset mounts."""
    _mount(tool, "/assets", ui_dir)

    assert (await client.get("/assets/")).status_code == 404


# ─── mount_static: nothing leaks ─────────────────────────────────────────────

SENSITIVE = [
    "/static/.env",
    "/static/.git/config",
    "/static/app.js.map",
    "/static/backup.sql",
    "/static/notes.md",
    "/static/Dockerfile",
]


@pytest.mark.parametrize("url", SENSITIVE)
async def test_undeclared_files_are_not_served(tool, client, ui_dir, url):
    """Deny by default: anything outside the allowed extensions is unreachable."""
    _mount(tool, "/static", ui_dir)

    resp = await client.get(url)
    assert resp.status_code == 404, f"{url} leaked: {resp.text[:80]}"
    for secret in ("hunter2", "git@private", "secret.ts", "INSERT INTO"):
        assert secret not in resp.text


@pytest.mark.parametrize("url", SENSITIVE)
async def test_undeclared_files_stay_blocked_in_html_mode(tool, client, ui_dir, url):
    """html=True must not widen what is reachable, only how misses render."""
    _mount(tool, "/static", ui_dir, html=True)

    resp = await client.get(url)
    assert resp.status_code == 404, f"{url} leaked: {resp.text[:80]}"


async def test_narrowed_allowlist_blocks_otherwise_default_types(tool, client, ui_dir):
    """A declared set replaces the default rather than adding to it."""
    _mount(tool, "/static", ui_dir, allow_extensions={"html"})

    assert (await client.get("/static/index.html")).status_code == 200
    assert (await client.get("/static/app.js")).status_code == 404


async def test_wildcard_opts_out_of_the_allowlist_but_not_dotfiles(tool, client, ui_dir):
    """The wildcard is the documented escape hatch; dotfiles stay refused regardless."""
    _mount(tool, "/static", ui_dir, allow_extensions="*")

    assert (await client.get("/static/backup.sql")).status_code == 200
    assert (await client.get("/static/.env")).status_code == 404


async def test_well_known_is_reachable_despite_having_no_extension(tool, client, tmp_path):
    """ACME renewals need '.well-known/', and its challenge tokens are extensionless."""
    d = tmp_path / "pub"
    (d / ".well-known" / "acme-challenge").mkdir(parents=True)
    (d / ".well-known" / "acme-challenge" / "TOKEN123").write_text("proof")
    _mount(tool, "/static", str(d))

    resp = await client.get("/static/.well-known/acme-challenge/TOKEN123")
    assert resp.status_code == 200
    assert resp.text == "proof"


async def test_nothing_outside_the_directory_is_reachable(tool, client, ui_dir, tmp_path):
    """Traversal and symlink escape: we rely on Starlette confining lookups."""
    secret = tmp_path / "outside.txt"
    secret.write_text("TOP SECRET")
    os.symlink(str(secret), os.path.join(ui_dir, "leak.txt"))
    os.symlink(str(secret), os.path.join(ui_dir, "leak.js"))
    _mount(tool, "/static", ui_dir)

    for url in [
        "/static/../outside.txt",
        "/static/%2e%2e%2foutside.txt",
        "/static/sub/../../outside.txt",
        "/static/leak.txt",
        "/static/leak.js",
    ]:
        resp = await client.get(url)
        assert resp.status_code == 404, f"{url} leaked"
        assert "TOP SECRET" not in resp.text


async def test_blocked_and_missing_files_are_indistinguishable(tool, client, ui_dir):
    """A different status or body for blocked files would confirm they exist."""
    _mount(tool, "/static", ui_dir)

    blocked = await client.get("/static/.env")
    missing = await client.get("/static/does-not-exist.env")

    assert blocked.status_code == missing.status_code == 404
    assert blocked.text == missing.text


# ─── mount_static: ordering and validation ───────────────────────────────────

async def test_root_mount_does_not_shadow_api_routes(tool, client, ui_dir):
    """
    A Mount matches its whole subtree and Starlette matches in registration
    order, so mounts are applied after endpoints. Mounting "/" earlier 404s
    the entire API.
    """
    async def handler(data, context):
        return {"success": True, "data": "API"}

    tool.add_endpoint("/api/ping", "GET", handler)
    tool.mount_static("/", ui_dir, html=True)

    tool._register_all_endpoints()      # boot order, as in on_boot_complete()
    tool._register_all_static_mounts()

    api = await client.get("/api/ping")
    assert api.status_code == 200
    assert api.json()["data"] == "API"

    assert "<h1>home</h1>" in (await client.get("/")).text


def test_mount_static_raises_on_missing_directory(tool, tmp_path):
    """A silent no-op is indistinguishable from a wrong mount path at request time."""
    with pytest.raises(ValueError, match="directory not found"):
        tool.mount_static("/static", str(tmp_path / "does_not_exist"))


def test_mount_static_raises_when_path_is_a_file(tool, tmp_path):
    """isdir, not exists: a file is not a mountable directory."""
    f = tmp_path / "index.html"
    f.write_text("<h1>home</h1>")

    with pytest.raises(ValueError, match="directory not found"):
        tool.mount_static("/static", str(f))
