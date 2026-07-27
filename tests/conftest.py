"""
Shared fixtures for the whole test suite.
"""

import pytest


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
