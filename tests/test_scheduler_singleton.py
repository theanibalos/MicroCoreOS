"""
Issue 19 — Scheduler singleton + jobs vía bus.

Con N réplicas, el scheduler dispararía cada job N veces. El patrón:
- SCHEDULER_ENABLED=true solo en la réplica "beat"; en las workers los jobs
  se registran (mismo código en todas) pero no disparan.
- El job publica un evento al bus; los workers lo consumen con semántica de
  grupos → exactamente un worker de la flota lo ejecuta.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from tools.scheduler.scheduler_tool import SchedulerTool
from tools.event_bus.event_bus_tool import EventBusTool

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_scheduler(enabled: bool, monkeypatch) -> SchedulerTool:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true" if enabled else "false")
    tool = SchedulerTool()
    tool.setup()
    return tool


async def test_worker_replica_registers_but_never_starts(monkeypatch):
    """SCHEDULER_ENABLED=false: los plugins registran igual, nada dispara."""
    scheduler = await _make_scheduler(enabled=False, monkeypatch=monkeypatch)

    fired = []
    scheduler.add_job("* * * * *", lambda: fired.append(1), job_id="nightly")
    await scheduler.on_boot_complete(None)

    assert scheduler._scheduler.running is False
    # El job quedó registrado (mismo código que en la réplica beat)...
    assert [j["id"] for j in scheduler.list_jobs()] == ["nightly"]
    # ...pero sin scheduler corriendo no hay próximo disparo.
    assert scheduler.list_jobs()[0]["next_run"] is None
    scheduler.shutdown()


async def test_beat_replica_starts(monkeypatch):
    scheduler = await _make_scheduler(enabled=True, monkeypatch=monkeypatch)
    scheduler.add_job("* * * * *", lambda: None, job_id="nightly")
    await scheduler.on_boot_complete(None)

    assert scheduler._scheduler.running is True
    assert scheduler.list_jobs()[0]["next_run"] is not None
    scheduler.shutdown()


async def test_stable_job_id_prevents_duplicates_on_hot_reload(monkeypatch):
    """Los cron no necesitan persistencia: en cada boot el scheduler nace vacío y
    los plugins re-registran. El id estable protege el caso restante: un plugin
    re-registrando con el scheduler YA corriendo (hot-reload) no duplica."""
    scheduler = await _make_scheduler(enabled=True, monkeypatch=monkeypatch)
    scheduler.add_job("0 3 * * *", lambda: None, job_id="nightly_report")
    await scheduler.on_boot_complete(None)

    scheduler.add_job("0 3 * * *", lambda: None, job_id="nightly_report")  # hot-reload
    assert len(scheduler.list_jobs()) == 1
    scheduler.shutdown()


async def test_job_publishes_event_and_one_worker_executes(monkeypatch):
    """El patrón completo: el job del beat publica al bus; el worker lo consume.
    (La garantía exactamente-uno entre réplicas la cubre el driver distribuido:
    tests/tools/test_redis_streams_driver.py::test_group_exactly_one_consumer_across_instances)
    """
    scheduler = await _make_scheduler(enabled=True, monkeypatch=monkeypatch)
    bus = EventBusTool()
    await bus.setup()

    executed = []

    async def run_report(env):
        executed.append(env.payload)

    await bus.subscribe("jobs.nightly_report.due", run_report)

    async def emit_due():
        await bus.publish("jobs.nightly_report.due", {"requested_by": "beat"})

    run_at = datetime.now(timezone.utc) + timedelta(seconds=0.2)
    scheduler.add_one_shot(run_at, emit_due, job_id="fire_now")
    await scheduler.on_boot_complete(None)

    await asyncio.sleep(0.6)

    assert executed == [{"requested_by": "beat"}]
    scheduler.shutdown()
    await bus.shutdown()
