"""Black-box tests for WelcomeServicePlugin (event consumer, tolerant reader)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from extras.available_domains.users.plugins.welcome_service_plugin import WelcomeServicePlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_user_created_triggers_welcome_notify_sent(event_bus):
    received = []

    async def on_notify(event):
        received.append(event.payload)

    await event_bus.subscribe("welcome.notify.sent", on_notify)

    plugin = WelcomeServicePlugin(event_bus=event_bus, logger=MagicMock())
    await plugin.on_boot()

    # Extra keys prove the tolerant reader: the consumer only declares the
    # fields it needs and must ignore the rest of the publisher's payload.
    await event_bus.publish(
        "user.created",
        {"id": 7, "email": "ana@example.com", "roles": ["user"], "extra_field": "ignored"},
    )
    await asyncio.sleep(0.02)

    assert received == [{"user_id": 7, "email": "ana@example.com"}]
