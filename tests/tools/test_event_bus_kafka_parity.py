"""
Kafka transport — broker parity suite (Issue 22).

Every EventBusDriver must pass the EXACT same suite as the in-process
reference. This module re-runs `test_event_bus_broker_parity`'s test bodies
against a KafkaDriver-backed bus, proving the Kafka extra honours the
contract (retries, DLQ, RPC, TTL, poisoned-handler escalation, backoff).

Skips itself if no broker is reachable:
    docker compose -f dev_infra/docker-compose.yml up -d kafka
"""

import uuid
import pytest

from tools.event_bus.event_bus_tool import EventBusTool
from extras.available_tools.kafka.kafka_driver import (
    KafkaDriver,
    EventBusConnectionError,
)

# Re-use the canonical parity assertions verbatim — importing the test
# functions registers them in THIS module, bound to the kafka `bus` fixture
# below. If a new parity test is added upstream, it is covered here for free.
from tests.tools.test_event_bus_broker_parity import (  # noqa: F401
    test_ttl_expired,
    test_ttl_valid,
    test_retry_then_success,
    test_retries_exhausted_dlq,
    test_backoff_progression,
    test_dlq_loop_protection,
    test_dlq_disabled,
    test_backward_compatibility,
    test_poisoned_escalation,
    test_rpc_unaffected,
    test_delayed_delivery,
    test_capabilities_declared,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_delayed_survives_publisher_death(bus):
    """The native-delay claim: a delayed envelope is KAFKA-persisted, so the
    publisher dying mid-delay does not lose it — a surviving replica's
    scheduler promotes it when due. (The in_bus fallback would lose it: the
    sleeping publish task dies with the process.)"""
    import asyncio
    from tests.helpers.async_wait import wait_until

    survivor = EventBusTool(driver=KafkaDriver())
    await survivor.setup()
    try:
        received = []

        async def on_due(env):
            received.append(env.payload)

        await survivor.subscribe("jobs.due", on_due)
        await bus.publish("jobs.due", {"job": 1}, delay=1)
        await asyncio.sleep(0.2)   # parked broker-side, not yet due
        await bus.shutdown()       # publisher "dies" with the delay pending
        await wait_until(lambda: received == [{"job": 1}], timeout=20)
    finally:
        await survivor.shutdown()


@pytest.fixture
async def bus(monkeypatch):
    # A unique topic prefix per test keeps durable group offsets from leaking
    # state between tests (topics AND group ids carry the prefix).
    monkeypatch.setenv("KAFKA_BUS_TOPIC_PREFIX", f"bus_test_{uuid.uuid4().hex[:12]}.")
    # Single partition: parity tests assert on delivery order across events.
    monkeypatch.setenv("KAFKA_BUS_PARTITIONS", "1")
    b = EventBusTool(driver=KafkaDriver())
    try:
        await b.setup()
    except EventBusConnectionError:
        pytest.skip(
            "Kafka not available — "
            "docker compose -f dev_infra/docker-compose.yml up -d kafka"
        )
    yield b
    await b.shutdown()
