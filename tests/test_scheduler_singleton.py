"""
Issue 19 — Scheduler singleton + jobs via the bus.

With N replicas, the scheduler would fire every job N times. The pattern:
- SCHEDULER_ENABLED=true only in the "beat" replica; in workers the jobs
  register (same code everywhere) but never fire.
- The job publishes an event to the bus; workers consume it with group
  semantics → exactly one worker across the fleet executes it.
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
    """SCHEDULER_ENABLED=false: plugins still register, nothing fires."""
    scheduler = await _make_scheduler(enabled=False, monkeypatch=monkeypatch)

    fired = []
    scheduler.add_job("* * * * *", lambda: fired.append(1), job_id="nightly")
    await scheduler.on_boot_complete(None)

    assert scheduler._scheduler.running is False
    # The job got registered (same code as in the beat replica)...
    assert [j["id"] for j in scheduler.list_jobs()] == ["nightly"]
    # ...but with no scheduler running there is no next fire time.
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
    """Cron jobs need no persistence: on every boot the scheduler starts empty
    and plugins re-register. The stable id covers the remaining case: a plugin
    re-registering while the scheduler is ALREADY running (hot-reload) does
    not duplicate."""
    scheduler = await _make_scheduler(enabled=True, monkeypatch=monkeypatch)
    scheduler.add_job("0 3 * * *", lambda: None, job_id="nightly_report")
    await scheduler.on_boot_complete(None)

    scheduler.add_job("0 3 * * *", lambda: None, job_id="nightly_report")  # hot-reload
    assert len(scheduler.list_jobs()) == 1
    scheduler.shutdown()


async def test_job_publishes_event_and_one_worker_executes(monkeypatch):
    """The full pattern: the beat job publishes to the bus; the worker consumes.
    (The exactly-one guarantee across replicas is covered by the distributed
    driver: tests/tools/test_redis_streams_driver.py::test_group_exactly_one_consumer_across_instances)
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
