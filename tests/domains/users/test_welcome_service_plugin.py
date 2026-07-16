"""Black-box tests for WelcomeServicePlugin (event consumer, tolerant reader)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from domains.users.plugins.welcome_service_plugin import WelcomeServicePlugin
from tools.event_bus.event_bus_tool import EventBusTool

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()


async def test_user_created_triggers_welcome_notify_sent(bus):
    received = []

    async def on_notify(event):
        received.append(event.payload)

    await bus.subscribe("welcome.notify.sent", on_notify)

    plugin = WelcomeServicePlugin(event_bus=bus, logger=MagicMock())
    await plugin.on_boot()

    # Extra keys prove the tolerant reader: the consumer only declares the
    # fields it needs and must ignore the rest of the publisher's payload.
    await bus.publish(
        "user.created",
        {"id": 7, "email": "ana@example.com", "roles": ["user"], "extra_field": "ignored"},
    )
    await asyncio.sleep(0.02)

    assert received == [{"user_id": 7, "email": "ana@example.com"}]
