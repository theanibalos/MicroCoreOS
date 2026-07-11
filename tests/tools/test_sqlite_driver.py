"""
Durability of the SQLite driver (Issue 31).

The parity suite (test_event_bus_broker_parity.py) proves the driver behaves
like the in-process one within a single run. These tests prove what the
in-process driver CANNOT do: in-flight work surviving a process death —
simulated as instance shutdown + a fresh instance on the same queue file.
"""

import asyncio
import sqlite3
import pytest

from tools.event_bus.event_bus_tool import EventBusTool
from tools.event_bus.sqlite_driver import SQLiteDriver

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def queue_path(tmp_path, monkeypatch):
    path = tmp_path / "bus_queue.db"
    monkeypatch.setenv("EVENT_BUS_SQLITE_PATH", str(path))
    return path


async def make_bus() -> EventBusTool:
    b = EventBusTool(driver=SQLiteDriver())
    await b.setup()
    return b


def make_handler(received: list):
    """Same qualname on every call → both instances derive the SAME durable
    group, exactly like two runs of the same plugin code."""
    async def on_event(env):
        received.append(env.payload)
    return on_event


async def test_pending_delay_survives_restart(queue_path):
    """A delayed event outlives the process that published it."""
    seen_a, seen_b = [], []

    bus_a = await make_bus()
    await bus_a.subscribe("jobs.due", make_handler(seen_a))
    await bus_a.publish("jobs.due", {"job": 42}, delay=1)
    await asyncio.sleep(0.2)          # staged, not yet due
    await bus_a.shutdown()            # "process dies" with the delay pending
    assert seen_a == []

    bus_b = await make_bus()          # "reboot"
    await bus_b.subscribe("jobs.due", make_handler(seen_b))
    await asyncio.sleep(1.2)          # due time passes in the new life
    await bus_b.shutdown()
    assert seen_b == [{"job": 42}]


async def test_crash_mid_handler_redelivers_on_reboot(queue_path):
    """A row claimed by a dying process is reset and redelivered at boot."""
    started = asyncio.Event()
    seen_b = []

    def make_hanging():
        async def on_event(env):
            started.set()
            await asyncio.sleep(3600)  # handler never finishes = crash window
        return on_event

    def make_recorder():
        async def on_event(env):       # same qualname? No — see note below.
            seen_b.append(env.payload)
        return on_event

    # Both factories must yield the SAME derived group: use one factory name.
    # We instead subscribe B with an explicit group equal to A's derived one.
    bus_a = await make_bus()
    hanging = make_hanging()
    await bus_a.subscribe("orders.created", hanging, group="workers")
    await bus_a.publish("orders.created", {"id": 7})
    await asyncio.wait_for(started.wait(), timeout=2)  # claimed, in-handler
    await bus_a.shutdown()             # dies mid-handler: row stays 'processing'

    bus_b = await make_bus()           # boot resets processing → pending
    await bus_b.subscribe("orders.created", make_recorder(), group="workers")
    await asyncio.sleep(0.3)
    await bus_b.shutdown()
    assert seen_b == [{"id": 7}]       # redelivered exactly as published


async def test_backlog_accumulates_while_consumer_is_away(queue_path):
    """A registered group queues events published while no consumer runs
    (same semantics as a durable Redis/Rabbit group)."""
    seen_a, seen_b = [], []

    bus_a = await make_bus()
    await bus_a.subscribe("audit.log", make_handler(seen_a), group="auditors")
    await asyncio.sleep(0.1)
    await bus_a.shutdown()

    bus_pub = await make_bus()         # publisher-only life: no consumer
    await bus_pub.publish("audit.log", {"n": 1})
    await bus_pub.publish("audit.log", {"n": 2})
    await asyncio.sleep(0.2)
    await bus_pub.shutdown()

    bus_b = await make_bus()
    await bus_b.subscribe("audit.log", make_handler(seen_b), group="auditors")
    await asyncio.sleep(0.3)
    await bus_b.shutdown()
    assert seen_b == [{"n": 1}, {"n": 2}]  # drained in publish order


async def test_broadcasts_and_replies_are_never_persisted(queue_path):
    """Ephemeral subscriptions (wildcards, RPC replies) leave no rows behind."""
    seen = []

    bus_a = await make_bus()
    await bus_a.subscribe("*", make_handler(seen))          # broadcast
    await bus_a.publish("cache.invalidate", {"k": "x"})
    await asyncio.sleep(0.2)
    await bus_a.shutdown()
    assert seen == [{"k": "x"}]        # delivered live...

    rows = sqlite3.connect(queue_path).execute(
        "SELECT COUNT(*) FROM deliveries").fetchone()[0]
    assert rows == 0                   # ...but nothing survives on disk


async def test_competing_consumers_share_the_group_exactly_once(queue_path):
    """Two callbacks on one group: every event goes to exactly one of them."""
    seen_1, seen_2 = [], []

    bus = await make_bus()
    await bus.subscribe("work.todo", make_handler(seen_1), group="pool")
    await bus.subscribe("work.todo", make_handler(seen_2), group="pool")
    for n in range(4):
        await bus.publish("work.todo", {"n": n})
    await asyncio.sleep(0.4)
    await bus.shutdown()

    all_seen = seen_1 + seen_2
    assert sorted(p["n"] for p in all_seen) == [0, 1, 2, 3]  # no loss, no dupes


async def test_driver_selected_by_env_var(queue_path, monkeypatch):
    """EVENT_BUS_DRIVER=sqlite installs via generic driver discovery."""
    monkeypatch.setenv("EVENT_BUS_DRIVER", "sqlite")
    bus = EventBusTool()
    assert type(bus._driver).__name__ == "SQLiteDriver"
