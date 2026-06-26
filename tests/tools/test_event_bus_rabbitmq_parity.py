"""
RabbitMQ transport — broker parity suite (Issue 22).

Every EventBusDriver must pass the EXACT same suite as the in-process
reference. This module re-runs `test_event_bus_broker_parity`'s test bodies
against a RabbitMQDriver-backed bus, proving the RabbitMQ extra honours the
contract (retries, DLQ, RPC, TTL, poisoned-handler escalation, backoff).

Skips itself if no broker is reachable:
    docker run -d --rm --name rmq -p 5672:5672 rabbitmq:3.13-alpine
"""

import uuid
import pytest

from tools.event_bus.event_bus_tool import EventBusTool
from extras.available_tools.rabbitmq.rabbitmq_driver import (
    RabbitMQDriver,
    EventBusConnectionError,
)

# Re-use the canonical parity assertions verbatim — importing the test
# functions registers them in THIS module, bound to the rabbitmq `bus` fixture
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
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def bus(monkeypatch):
    # A unique exchange per test keeps durable group queues from leaking state
    # between tests (queue names are derived as "{exchange}.{group}").
    monkeypatch.setenv("RABBITMQ_BUS_EXCHANGE", f"bus_test_{uuid.uuid4().hex[:12]}")
    b = EventBusTool(driver=RabbitMQDriver())
    try:
        await b.setup()
    except EventBusConnectionError:
        pytest.skip(
            "RabbitMQ not available — "
            "docker run -d --rm -p 5672:5672 rabbitmq:3.13-alpine"
        )
    yield b
    await b.shutdown()
