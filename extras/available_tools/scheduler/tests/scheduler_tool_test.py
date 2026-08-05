import asyncio
import pytest
from datetime import datetime, timedelta, timezone


# This test ships inside the tool's own folder, so it runs from either
# location: extras/available_tools/ before `microcoreos add`, tools/ after.
try:
    from tools.scheduler.scheduler_tool import (
        SchedulerTool,
    )
except ModuleNotFoundError:
    from extras.available_tools.scheduler.scheduler_tool import (
        SchedulerTool,
    )

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def tool():
    t = SchedulerTool()
    t.setup()
    await t.on_boot_complete(None)
    yield t
    t.shutdown()

async def test_add_job_returns_string_id(tool):
    job_id = tool.add_job("* * * * *", lambda: None)
    assert isinstance(job_id, str) and job_id

async def test_add_job_same_id_no_duplicate(tool):
    tool.add_job("* * * * *", lambda: None, job_id="stable")
    tool.add_job("* * * * *", lambda: None, job_id="stable")
    ids = [j["id"] for j in tool.list_jobs() if j["id"] == "stable"]
    assert len(ids) == 1

async def test_list_jobs_contains_registered_job(tool):
    job_id = tool.add_job("* * * * *", lambda: None, job_id="listed")
    jobs = tool.list_jobs()
    assert any(j["id"] == job_id for j in jobs)

async def test_remove_job_returns_true_and_removes(tool):
    job_id = tool.add_job("* * * * *", lambda: None)
    assert tool.remove_job(job_id) is True
    assert not any(j["id"] == job_id for j in tool.list_jobs())

async def test_remove_job_nonexistent_returns_false(tool):
    assert tool.remove_job("does-not-exist") is False

async def test_add_one_shot_returns_job_id(tool):
    run_at = datetime.now(timezone.utc) + timedelta(hours=1)
    job_id = tool.add_one_shot(run_at, lambda: None)
    assert isinstance(job_id, str) and job_id
    jobs = tool.list_jobs()
    assert any(j["id"] == job_id for j in jobs)

async def test_one_shot_job_executes_callback(tool):
    executed = []

    def callback():
        executed.append(True)

    soon = datetime.now(timezone.utc) + timedelta(milliseconds=200)
    tool.add_one_shot(soon, callback)

    await asyncio.sleep(1.5)

    assert len(executed) == 1

async def test_async_one_shot_job_executes_callback(tool):
    executed = []

    async def async_callback():
        executed.append(True)

    soon = datetime.now(timezone.utc) + timedelta(milliseconds=200)
    tool.add_one_shot(soon, async_callback)

    await asyncio.sleep(1.5)

    assert len(executed) == 1

async def test_list_jobs_entry_structure(tool):
    tool.add_job("* * * * *", lambda: None, job_id="struct_test")
    jobs = tool.list_jobs()
    entry = next(j for j in jobs if j["id"] == "struct_test")
    assert "id" in entry
    assert "next_run" in entry
    assert "trigger" in entry
    assert isinstance(entry["id"], str)
    assert isinstance(entry["trigger"], str)
    assert entry["next_run"] is None or isinstance(entry["next_run"], str)

# ─── add_interval_job ────────────────────────────────────────────────────────

async def test_add_interval_job_returns_string_id(tool):
    job_id = tool.add_interval_job(1.0, lambda: None)
    assert isinstance(job_id, str) and job_id

async def test_interval_job_fires_repeatedly_below_one_minute(tool):
    """The reason this method exists: a 5-field cron cannot go under a minute."""
    fired = []
    tool.add_interval_job(0.05, lambda: fired.append(1), job_id="fast")

    await asyncio.sleep(0.35)

    assert len(fired) >= 3, f"expected repeated sub-minute firing, got {len(fired)}"

async def test_async_interval_job_executes_callback(tool):
    fired = []

    async def cb():
        fired.append(1)

    tool.add_interval_job(0.05, cb, job_id="async-fast")
    await asyncio.sleep(0.25)

    assert fired

async def test_interval_job_same_id_no_duplicate(tool):
    tool.add_interval_job(1.0, lambda: None, job_id="stable-interval")
    tool.add_interval_job(2.0, lambda: None, job_id="stable-interval")
    ids = [j["id"] for j in tool.list_jobs() if j["id"] == "stable-interval"]
    assert len(ids) == 1

async def test_interval_job_accepts_minutes_and_hours(tool):
    job_id = tool.add_interval_job(0, lambda: None, minutes=90, job_id="every-90m")
    trigger = next(j["trigger"] for j in tool.list_jobs() if j["id"] == job_id)
    assert "1:30:00" in trigger

@pytest.mark.parametrize("kwargs", [
    {"seconds": 0},
    {"seconds": -1},
    {"seconds": 0, "minutes": 0, "hours": 0},
])
async def test_interval_job_rejects_non_positive_interval(tool, kwargs):
    """IntervalTrigger would otherwise pick a default and fire at a rate nobody asked for."""
    with pytest.raises(ValueError, match="must be positive"):
        tool.add_interval_job(callback=lambda: None, **kwargs)

async def test_interval_job_knobs_reach_the_job(tool):
    """max_instances/coalesce/misfire_grace_time are the point of the method."""
    tool.add_interval_job(
        1.0, lambda: None, job_id="tuned",
        max_instances=4, coalesce=False, misfire_grace_time=None,
    )

    job = tool._scheduler.get_job("tuned")
    assert job.max_instances == 4
    assert job.coalesce is False
    assert job.misfire_grace_time is None

async def test_knobs_default_to_apscheduler_behaviour(tool):
    """Defaults are APScheduler's, so existing jobs keep firing as before."""
    tool.add_interval_job(1.0, lambda: None, job_id="plain")

    job = tool._scheduler.get_job("plain")
    assert (job.max_instances, job.coalesce, job.misfire_grace_time) == (1, True, 1)

async def test_overlapping_runs_are_dropped_and_logged(tool, capsys):
    """
    A callback slower than its interval exceeds max_instances=1 and APScheduler
    discards the run without raising. The listener is what makes it visible.
    """
    async def slow():
        await asyncio.sleep(0.5)

    tool.add_interval_job(0.05, slow, job_id="slow-job")
    await asyncio.sleep(0.4)

    out = capsys.readouterr().out
    assert "Run DROPPED" in out
    assert "'slow-job'" in out
    assert "max_instances" in out

async def test_raising_max_instances_stops_the_drops(tool, capsys):
    """The knob has to actually solve the problem the log reports."""
    async def slow():
        await asyncio.sleep(0.2)

    tool.add_interval_job(0.05, slow, job_id="roomy", max_instances=20)
    await asyncio.sleep(0.4)

    assert "Run DROPPED" not in capsys.readouterr().out

async def test_interval_jobs_register_but_do_not_fire_on_worker_replicas(monkeypatch, capsys):
    """SCHEDULER_ENABLED=false: identical plugin code, jobs fire in the beat replica only."""
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    worker = SchedulerTool()
    worker.setup()
    await worker.on_boot_complete(None)

    fired = []
    worker.add_interval_job(0.05, lambda: fired.append(1), job_id="beat-only")

    await asyncio.sleep(0.25)

    assert any(j["id"] == "beat-only" for j in worker.list_jobs())
    assert fired == []
    worker.shutdown()
