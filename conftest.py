"""
Shared fixtures for the whole test suite.

At the repo root, not under `tests/`, because the suite lives in more than one
tree: a tool's own tests ship inside the tool's folder and travel with it
(`tools/{name}/tests/`, or `extras/available_tools/{name}/tests/` until the
extra is installed). A conftest under `tests/` reaches none of them.
"""

import inspect
from pathlib import Path

import pytest

from unittest.mock import AsyncMock, MagicMock
from tests.helpers.active_db import active_db as _active_db


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_event_bus_sqlite_queue(tmp_path, monkeypatch):
    """
    Keep every test off the production event-bus queue file.

    SQLiteDriver (tools/event_bus/sqlite_driver.py) defaults
    EVENT_BUS_SQLITE_PATH to "event_bus_queue.db" at the repo root when the
    var is unset. That default is legitimate production behavior (see the
    driver's module docstring) — but plenty of tests build a bare
    EventBusTool()/SQLiteDriver() without ever pointing it elsewhere. Under
    EVENT_BUS_DRIVER=sqlite (a supported, exercised test mode — see e.g.
    tests/tools/sqlite/test_sqlite_driver.py::test_driver_selected_by_env_var),
    those tests would share, and leave behind, the real root-level file:
    state leaks between runs and even between unrelated tests in the same
    run (see EventBusTool._MAX_CONSECUTIVE_FAILURES bookkeeping on the
    "boom" event in test_event_bus_tool.py, which broke on a dirty queue).

    Point every test at its own tmp_path file by default. Tests that need
    the file's actual location — to reopen it directly and assert on rows,
    e.g. tests/tools/sqlite/test_sqlite_driver.py's local `queue_path` fixture —
    keep declaring their own fixture; autouse fixtures run before
    explicitly requested ones in the same scope, so a test's own override
    always wins over this default.
    """
    monkeypatch.setenv("EVENT_BUS_SQLITE_PATH", str(tmp_path / "event_bus_queue.db"))


# ─── Tools by injection name ──────────────────────────────────────────
#
# A plugin never builds a tool: it names one in `__init__` and the Kernel
# hands it over. These fixtures are the same contract for tests — pytest
# already injects by parameter name, so a test can ask for exactly what the
# plugin under test asks for:
#
#     @pytest.mark.migrations("users")
#     async def test_create_user_persists(db, event_bus, auth, logger):
#         plugin = CreateUserPlugin(http=MagicMock(), db=db,
#                                   event_bus=event_bus, auth=auth, logger=logger)
#         await plugin.execute({"name": "Ana", ...})
#         assert await db.query("SELECT email FROM users") == [...]
#
# The names below MUST match the Kernel's injection keys (`db`, `event_bus`,
# `auth`, ...) — that is the whole point: the test's signature and the
# plugin's signature are the same vocabulary. A test that needs something
# else keeps declaring its own fixture; a local one always overrides these.

_PROJECT_ROOT = Path(__file__).resolve().parent

# A domain's migrations live in `domains/` once materialized and in
# `extras/available_domains/` until then, and the marker should not care which:
# `microcoreos add scheduler` moves the folder without changing a single test.
# `domains/` is searched first so a materialized domain wins over the extra it
# was installed from — the same rule as the ACTIVE db tool below.
_MIGRATION_ROOTS = (
    _PROJECT_ROOT / "domains",
    _PROJECT_ROOT / "extras" / "available_domains",
)


def _migrations_dir(domain: str) -> Path | None:
    for root in _MIGRATION_ROOTS:
        candidate = root / domain / "migrations"
        if candidate.is_dir():
            return candidate
    return None


async def _lifecycle(tool, method: str):
    """
    Run a tool's setup/shutdown tolerating sync OR async — exactly what the
    Kernel does (`microcoreos/kernel.py::_call_maybe_async`).

    `LoggerTool.shutdown()` is sync; `SqliteTool.shutdown()` is not. A fixture
    that assumes one shape breaks on the other, and worse, it would be testing
    tools through a lifecycle the Kernel does not use.
    """
    fn = getattr(tool, method, None)
    if fn is None:
        return
    result = fn()
    if inspect.isawaitable(result):
        await result


@pytest.fixture
async def db(request, monkeypatch):
    """
    The ACTIVE db tool, with the migrations this test declares:

        @pytest.mark.migrations("users", "system")

    Active, not `SqliteTool` by name — a test that hardcodes the class dies at
    collection after a Postgres swap instead of proving anything about it
    (see tests/helpers/active_db.py). With no marker you get a real, empty
    schema, which is what a test that does not touch tables wants.

    The domain may be materialized or still an extra; see `_migrations_dir`.
    """
    marker = request.node.get_closest_marker("migrations")
    names = marker.args if marker else ()
    resolved = {name: _migrations_dir(name) for name in names}

    missing = [name for name, d in resolved.items() if d is None]
    assert not missing, (
        f"@pytest.mark.migrations names domains with no migrations/ under "
        f"{' or '.join(str(r.relative_to(_PROJECT_ROOT)) for r in _MIGRATION_ROOTS)}: {missing}"
    )
    dirs = list(resolved.values())

    async with _active_db(monkeypatch, *dirs) as tool:
        yield tool


@pytest.fixture
async def event_bus():
    from tools.event_bus.event_bus_tool import EventBusTool
    tool = EventBusTool()
    await _lifecycle(tool, "setup")
    yield tool
    await _lifecycle(tool, "shutdown")


@pytest.fixture
async def auth(monkeypatch):
    try:
        from tools.auth.auth_tool import AuthTool
    except ImportError:
        from extras.available_tools.auth.auth_tool import AuthTool
    # The tool refuses a key under 32 chars — a real rule, not test noise.
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-0123456789abcdefghij")
    tool = AuthTool()
    await _lifecycle(tool, "setup")
    yield tool
    await _lifecycle(tool, "shutdown")


@pytest.fixture
async def state():
    from tools.state.state_tool import StateTool
    tool = StateTool()
    await _lifecycle(tool, "setup")
    yield tool
    await _lifecycle(tool, "shutdown")


@pytest.fixture
async def logger():
    from tools.logger.logger_tool import LoggerTool
    tool = LoggerTool()
    await _lifecycle(tool, "setup")
    yield tool
    await _lifecycle(tool, "shutdown")


@pytest.fixture
async def config():
    from tools.config.config_tool import ConfigTool
    tool = ConfigTool()
    await _lifecycle(tool, "setup")
    yield tool
    await _lifecycle(tool, "shutdown")


@pytest.fixture
def mock_logger():
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    logger.warning = MagicMock()
    return logger


@pytest.fixture
def mock_state():
    """
    Stand-in for the `state` tool, matching its real contract:

    - Every method is async. The tool's public API is async top to bottom
      (`tools/state/state_tool.py`), so a sync fixture dies on the first
      `await self.state.get(...)` with "object is not awaitable".
    - Every method takes `namespace=`, and `set`/`increment` take `ttl=` —
      real call sites pass them by keyword (see the users domain's
      `login_plugin.py` throttle), and a mock without them raises TypeError.
    - `increment` exists and returns the new value.

    `ttl` is accepted and ignored: nothing expires in this fixture. A test
    about expiry wants the real StateTool, not a mock of it.
    """
    store = {}
    state = MagicMock()

    async def _set(key, value, namespace="default", ttl=None):
        store[(namespace, key)] = value

    async def _get(key, default=None, namespace="default"):
        return store.get((namespace, key), default)

    async def _delete(key, namespace="default"):
        store.pop((namespace, key), None)

    async def _has(key, namespace="default"):
        return (namespace, key) in store

    async def _increment(key, amount=1, namespace="default", ttl=None):
        store[(namespace, key)] = store.get((namespace, key), 0) + amount
        return store[(namespace, key)]

    state.set = AsyncMock(side_effect=_set)
    state.get = AsyncMock(side_effect=_get)
    state.delete = AsyncMock(side_effect=_delete)
    state.has = AsyncMock(side_effect=_has)
    state.increment = AsyncMock(side_effect=_increment)
    return state
