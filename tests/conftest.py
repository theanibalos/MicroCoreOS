"""
Shared fixtures for the whole test suite.
"""

import inspect
from pathlib import Path

import pytest

from tests.helpers.active_db import active_db as _active_db


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
    tests/tools/test_sqlite_driver.py::test_driver_selected_by_env_var),
    those tests would share, and leave behind, the real root-level file:
    state leaks between runs and even between unrelated tests in the same
    run (see EventBusTool._MAX_CONSECUTIVE_FAILURES bookkeeping on the
    "boom" event in test_event_bus_tool.py, which broke on a dirty queue).

    Point every test at its own tmp_path file by default. Tests that need
    the file's actual location — to reopen it directly and assert on rows,
    e.g. tests/tools/test_sqlite_driver.py's local `queue_path` fixture —
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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    """
    marker = request.node.get_closest_marker("migrations")
    dirs = [_PROJECT_ROOT / "domains" / d / "migrations" for d in (marker.args if marker else ())]
    missing = [str(d) for d in dirs if not d.is_dir()]
    assert not missing, f"@pytest.mark.migrations names domains with no migrations/: {missing}"

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
    from tools.auth.auth_tool import AuthTool
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
