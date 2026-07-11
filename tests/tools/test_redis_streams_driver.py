"""
Distributed behavior of the Redis Streams driver (Issue 18).

The parity suite (test_event_bus_broker_parity.py) proves the driver behaves
like the in-process one within a single instance. These tests prove what the
in-process driver CANNOT do: two EventBusTool instances (two MicroCoreOS
replicas) sharing transport through the same Redis.

Skips itself if no Redis server is reachable:
    docker compose -f dev_infra/docker-compose.yml up -d redis
"""

import asyncio
import pytest
from tools.event_bus.event_bus_tool import EventBusTool, InProcessDriver
from tools.event_bus.redis_streams_driver import RedisStreamsDriver, EventBusConnectionError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_bus(monkeypatch) -> EventBusTool:
    monkeypatch.setenv("REDIS_DB", "15")
    b = EventBusTool(driver=RedisStreamsDriver())
    try:
        await b.setup()
    except EventBusConnectionError:
        pytest.skip("Redis not available — docker compose -f dev_infra/docker-compose.yml up -d redis")
    return b


@pytest.fixture
async def two_buses(monkeypatch):
    """Two independent EventBusTool instances = two replicas sharing one Redis."""
    bus_a = await _make_bus(monkeypatch)
    bus_b = await _make_bus(monkeypatch)
    # Durable groups persist between runs: start each test hermetic.
    # (Flush BEFORE any subscription so no reader loses its group.)
    await bus_a._driver._redis.flushdb()
    yield bus_a, bus_b
    await bus_a.shutdown()
    await bus_b.shutdown()


async def test_cross_instance_delivery(two_buses):
    """An event published in replica B reaches a subscriber living in replica A."""
    bus_a, bus_b = two_buses
    received = []

    async def handler(env):
        received.append(env.payload)

    await bus_a.subscribe("dist.test", handler)
    await bus_b.publish("dist.test", {"from": "replica_b"})
    await asyncio.sleep(0.3)

    assert received == [{"from": "replica_b"}]


async def test_group_exactly_one_consumer_across_instances(two_buses):
    """The Issue 19 pattern: N workers with group= → each job consumed exactly once."""
    bus_a, bus_b = two_buses
    deliveries_a, deliveries_b = [], []

    async def worker_a(env):
        deliveries_a.append(env.payload["n"])

    async def worker_b(env):
        deliveries_b.append(env.payload["n"])

    await bus_a.subscribe("jobs.report.due", worker_a, group="workers")
    await bus_b.subscribe("jobs.report.due", worker_b, group="workers")

    for n in range(10):
        await bus_a.publish("jobs.report.due", {"n": n})
    await asyncio.sleep(0.5)

    # Every job delivered exactly once across the whole fleet — no duplicates.
    assert sorted(deliveries_a + deliveries_b) == list(range(10))


async def test_distinct_consumers_each_receive(two_buses):
    """Different plugins (different callback identities) each get their own copy."""
    bus_a, bus_b = two_buses
    seen_a, seen_b = [], []

    async def send_notification(env):
        seen_a.append(env.payload["n"])

    async def send_email(env):
        seen_b.append(env.payload["n"])

    await bus_a.subscribe("order.placed", send_notification)
    await bus_b.subscribe("order.placed", send_email)

    await bus_a.publish("order.placed", {"n": 1})
    await asyncio.sleep(0.3)

    assert seen_a == [1]
    assert seen_b == [1]


def _make_video_worker(sink):
    """Same factory in every replica → same callback identity → same auto-group."""
    async def on_video_uploaded(env):
        sink.append(env.payload["n"])
    return on_video_uploaded


async def test_same_plugin_across_replicas_consumes_once(two_buses):
    """The replica case: identical code in N instances → each event processed ONCE.
    No group= needed — the Bus derives it from the callback identity."""
    bus_a, bus_b = two_buses
    sink_a, sink_b = [], []

    await bus_a.subscribe("video.uploaded", _make_video_worker(sink_a))
    await bus_b.subscribe("video.uploaded", _make_video_worker(sink_b))

    for n in range(10):
        await bus_a.publish("video.uploaded", {"n": n})
    await asyncio.sleep(0.5)

    # Every video processed exactly once across the fleet — no duplicates.
    assert sorted(sink_a + sink_b) == list(range(10))


async def test_broadcast_flag_reaches_all_replicas(two_buses):
    """broadcast=True opts out of grouping: instance-local concerns see everything."""
    bus_a, bus_b = two_buses
    sink_a, sink_b = [], []

    await bus_a.subscribe("config.changed", _make_video_worker(sink_a), broadcast=True)
    await bus_b.subscribe("config.changed", _make_video_worker(sink_b), broadcast=True)

    await bus_a.publish("config.changed", {"n": 1})
    await asyncio.sleep(0.3)

    assert sink_a == [1]
    assert sink_b == [1]


async def test_wildcard_across_instances(two_buses):
    """'*' subscribers consume the firehose stream, regardless of who published."""
    bus_a, bus_b = two_buses
    seen = []

    async def auditor(env):
        seen.append(env.event)

    await bus_a.subscribe("*", auditor)
    await bus_b.publish("orders.created", {"id": 1})
    await bus_b.publish("orders.paid", {"id": 1})
    await asyncio.sleep(0.3)

    assert sorted(seen) == ["orders.created", "orders.paid"]


async def test_driver_selected_by_env_var(monkeypatch):
    """EVENT_BUS_DRIVER=redis_streams swaps the transport with zero code changes."""
    monkeypatch.setenv("EVENT_BUS_DRIVER", "redis_streams")
    assert isinstance(EventBusTool()._driver, RedisStreamsDriver)

    monkeypatch.setenv("EVENT_BUS_DRIVER", "in_process")
    assert isinstance(EventBusTool()._driver, InProcessDriver)

    monkeypatch.setenv("EVENT_BUS_DRIVER", "kafka")
    with pytest.raises(ValueError):
        EventBusTool()


async def test_driver_discovery_is_generic_drop_in(monkeypatch):
    """Installing a transport = dropping tools/event_bus/{name}_driver.py in.

    Same swap standard as the db tool: file placement IS the installation —
    no branch in the Bus, no code edit.
    """
    import os
    import tools.event_bus.event_bus_tool as bus_module

    driver_dir = os.path.dirname(os.path.abspath(bus_module.__file__))
    dummy_file = os.path.join(driver_dir, "dummy_driver.py")
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write(
            "from tools.event_bus.event_bus_tool import EventBusDriver\n\n\n"
            "class DummyDriver(EventBusDriver):\n"
            "    pass\n"
        )
    try:
        monkeypatch.setenv("EVENT_BUS_DRIVER", "dummy")
        assert type(EventBusTool()._driver).__name__ == "DummyDriver"
    finally:
        os.remove(dummy_file)
