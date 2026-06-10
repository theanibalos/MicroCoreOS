"""
Issue 19 (pendiente menor) — Persistencia de one-shots.

add_one_shot(callback) del scheduler tool es efímero por diseño (un callable
no sobrevive un reinicio, y un tool nunca usa otros tools). La durabilidad se
compone en la capa de plugins: DurableOneShotsPlugin (dominio system) persiste
(run_at, event, payload) en la tabla scheduler_one_shots y un cron — que solo
dispara en la réplica beat — publica los vencidos al bus.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.system.plugins.durable_one_shots_plugin import DurableOneShotsPlugin
from tools.sqlite.sqlite_tool import SqliteTool
from tools.event_bus.event_bus_tool import EventBusTool

pytestmark = pytest.mark.anyio

MIGRATION = (
    Path(__file__).parent.parent / "domains/system/migrations/001_scheduler_one_shots.sql"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _SchedulerStub:
    """El cron real dispara a minuto cerrado — los tests llaman publish_due()
    directo. El stub solo registra que el plugin agendó su cron en on_boot."""

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
    await tool.execute(MIGRATION.read_text())  # la migración real del dominio
    yield tool
    await tool.shutdown()


@pytest.fixture
async def bus():
    tool = EventBusTool()
    await tool.setup()
    yield tool
    await tool.shutdown()


async def _make_plugin(db, bus) -> DurableOneShotsPlugin:
    plugin = DurableOneShotsPlugin(
        db=db, event_bus=bus, scheduler=_SchedulerStub(), logger=MagicMock()
    )
    await plugin.on_boot()
    return plugin


async def test_registers_cron_and_subscriptions(db, bus):
    plugin = await _make_plugin(db, bus)
    assert plugin.scheduler.jobs == [
        {"cron": "* * * * *", "job_id": "system_durable_one_shots"}
    ]
    subs = bus.get_subscribers()
    assert "system.one_shot.schedule" in subs
    assert "system.one_shot.cancel" in subs


async def test_schedule_via_bus_and_fire_when_due(db, bus):
    plugin = await _make_plugin(db, bus)

    received = []

    async def on_due(env):
        received.append(env.payload)

    await bus.subscribe("jobs.welcome.due", on_due)

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    res = await bus.request(
        "system.one_shot.schedule",
        {"run_at": past, "event": "jobs.welcome.due", "payload": {"user_id": 42}},
    )
    assert res["success"] is True and res["data"]["job_id"]

    await bus.request(
        "system.one_shot.schedule",
        {"run_at": future, "event": "jobs.welcome.due", "payload": {"user_id": 99}},
    )

    await plugin.publish_due()  # el tick del cron
    await asyncio.sleep(0.1)

    # Dispara solo el vencido; el futuro sigue pendiente en la tabla.
    assert received == [{"user_id": 42}]
    rows = await db.query("SELECT job_id FROM scheduler_one_shots")
    assert len(rows) == 1

    # Un segundo tick no re-dispara (la fila se borró al publicar).
    await plugin.publish_due()
    await asyncio.sleep(0.1)
    assert received == [{"user_id": 42}]


async def test_survives_restart(db, bus):
    """El escenario del Issue 19: la réplica beat muere antes de disparar.
    La fila persiste y una instancia NUEVA del plugin (misma DB) la dispara."""
    first = await _make_plugin(db, bus)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await bus.request(
        "system.one_shot.schedule",
        {"run_at": past, "event": "jobs.report.due", "payload": {"id": 7}, "job_id": "rep"},
    )
    del first  # "muere" sin haber corrido su cron

    received = []

    async def on_due(env):
        received.append(env.payload)

    await bus.subscribe("jobs.report.due", on_due)

    second = DurableOneShotsPlugin(
        db=db, event_bus=bus, scheduler=_SchedulerStub(), logger=MagicMock()
    )
    await second.publish_due()
    await asyncio.sleep(0.1)

    assert received == [{"id": 7}]


async def test_cancel_pending_one_shot(db, bus):
    await _make_plugin(db, bus)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = await bus.request(
        "system.one_shot.schedule",
        {"run_at": future, "event": "jobs.x.due", "job_id": "c1"},
    )
    assert res["success"] is True

    res = await bus.request("system.one_shot.cancel", {"job_id": "c1"})
    assert res == {"success": True, "data": {"removed": True}}

    res = await bus.request("system.one_shot.cancel", {"job_id": "c1"})
    assert res == {"success": True, "data": {"removed": False}}  # ya no estaba


async def test_stable_job_id_replaces_pending(db, bus):
    await _make_plugin(db, bus)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    for v in (1, 2):
        await bus.request(
            "system.one_shot.schedule",
            {"run_at": future, "event": "jobs.a.due", "payload": {"v": v}, "job_id": "stable"},
        )
    rows = await db.query("SELECT payload FROM scheduler_one_shots")
    assert len(rows) == 1
    assert '"v": 2' in rows[0]["payload"]


async def test_invalid_request_returns_safe_error(db, bus):
    await _make_plugin(db, bus)
    res = await bus.request(
        "system.one_shot.schedule", {"run_at": "not-a-date", "event": "jobs.x.due"}
    )
    assert res == {"success": False, "error": "Invalid schedule request"}

    res = await bus.request("system.one_shot.schedule", {"event": ""})
    assert res["success"] is False
