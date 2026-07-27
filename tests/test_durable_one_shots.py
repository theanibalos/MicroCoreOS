"""
Issue 19 (minor leftover) — One-shot persistence.

The scheduler tool's add_one_shot(callback) is ephemeral by design (a callable
cannot survive a restart, and a tool never uses other tools). Durability is
composed in the plugin layer: DurableOneShotsPlugin (scheduler domain, an extra) persists
(run_at, event, payload) in the scheduler_one_shots table and a cron — firing
only in the beat replica — publishes the due ones to the bus.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from extras.available_domains.scheduler.plugins.durable_one_shots_plugin import DurableOneShotsPlugin
from tools.sqlite.sqlite_tool import SqliteTool

pytestmark = pytest.mark.anyio

MIGRATION = (
    Path(__file__).parent.parent
    / "extras/available_domains/scheduler/migrations/001_scheduler_one_shots.sql"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _SchedulerStub:
    """The real cron fires on the minute — tests call publish_due() directly.
    The stub only records that the plugin scheduled its cron in on_boot."""

    def __init__(self):
        self.jobs = []

    def add_job(self, cron_expr, callback, job_id=None):
        self.jobs.append({"cron": cron_expr, "job_id": job_id})
        return job_id


@pytest.fixture
async def db(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    tool = SqliteTool()
    await tool.setup()
    await tool.execute(MIGRATION.read_text(encoding="utf-8"))  # the domain's real migration
    yield tool
    await tool.shutdown()


async def _make_plugin(db, event_bus) -> DurableOneShotsPlugin:
    plugin = DurableOneShotsPlugin(
        db=db, event_bus=event_bus, scheduler=_SchedulerStub(), logger=MagicMock()
    )
    await plugin.on_boot()
    return plugin


async def test_registers_cron_and_subscriptions(db, event_bus):
    plugin = await _make_plugin(db, event_bus)
    assert plugin.scheduler.jobs == [
        {"cron": "* * * * *", "job_id": "scheduler_durable_one_shots"}
    ]
    subs = event_bus.get_subscribers()
    assert "scheduler.one_shot.schedule" in subs
    assert "scheduler.one_shot.cancel" in subs


async def test_schedule_via_bus_and_fire_when_due(db, event_bus):
    plugin = await _make_plugin(db, event_bus)

    received = []

    async def on_due(env):
        received.append(env.payload)

    await event_bus.subscribe("jobs.welcome.due", on_due)

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    res = await event_bus.request(
        "scheduler.one_shot.schedule",
        {"run_at": past, "event": "jobs.welcome.due", "payload": {"user_id": 42}},
    )
    assert res["success"] is True and res["data"]["job_id"]

    await event_bus.request(
        "scheduler.one_shot.schedule",
        {"run_at": future, "event": "jobs.welcome.due", "payload": {"user_id": 99}},
    )

    await plugin.publish_due()  # the cron tick
    await asyncio.sleep(0.1)

    # Only the due one fires; the future one stays pending in the table.
    assert received == [{"user_id": 42}]
    rows = await db.query("SELECT job_id FROM scheduler_one_shots")
    assert len(rows) == 1

    # A second tick does not re-fire (the row was deleted on publish).
    await plugin.publish_due()
    await asyncio.sleep(0.1)
    assert received == [{"user_id": 42}]


async def test_survives_restart(db, event_bus):
    """The Issue 19 scenario: the beat replica dies before firing.
    The row persists and a NEW plugin instance (same DB) fires it."""
    first = await _make_plugin(db, event_bus)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await event_bus.request(
        "scheduler.one_shot.schedule",
        {"run_at": past, "event": "jobs.report.due", "payload": {"id": 7}, "job_id": "rep"},
    )
    del first  # "dies" without having run its cron

    received = []

    async def on_due(env):
        received.append(env.payload)

    await event_bus.subscribe("jobs.report.due", on_due)

    second = DurableOneShotsPlugin(
        db=db, event_bus=event_bus, scheduler=_SchedulerStub(), logger=MagicMock()
    )
    await second.publish_due()
    await asyncio.sleep(0.1)

    assert received == [{"id": 7}]


async def test_cancel_pending_one_shot(db, event_bus):
    await _make_plugin(db, event_bus)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = await event_bus.request(
        "scheduler.one_shot.schedule",
        {"run_at": future, "event": "jobs.x.due", "job_id": "c1"},
    )
    assert res["success"] is True

    res = await event_bus.request("scheduler.one_shot.cancel", {"job_id": "c1"})
    assert res == {"success": True, "data": {"removed": True}}

    res = await event_bus.request("scheduler.one_shot.cancel", {"job_id": "c1"})
    assert res == {"success": True, "data": {"removed": False}}  # ya no estaba


async def test_stable_job_id_replaces_pending(db, event_bus):
    await _make_plugin(db, event_bus)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    for v in (1, 2):
        await event_bus.request(
            "scheduler.one_shot.schedule",
            {"run_at": future, "event": "jobs.a.due", "payload": {"v": v}, "job_id": "stable"},
        )
    rows = await db.query("SELECT payload FROM scheduler_one_shots")
    assert len(rows) == 1
    assert '"v": 2' in rows[0]["payload"]


async def test_invalid_request_returns_safe_error(db, event_bus):
    await _make_plugin(db, event_bus)
    res = await event_bus.request(
        "scheduler.one_shot.schedule", {"run_at": "not-a-date", "event": "jobs.x.due"}
    )
    assert res == {"success": False, "error": "Invalid schedule request"}

    res = await event_bus.request("scheduler.one_shot.schedule", {"event": ""})
    assert res["success"] is False
