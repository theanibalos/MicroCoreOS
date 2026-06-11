"""
Regression: times_fired must count publications only.

The bus trace logs one "published" node plus one "delivered" node per
subscriber for every event. SystemEventsPlugin once counted every trace
record as a firing, so an event with N subscribers reported (1 + N) x the
real publish count (e.g. 2 users created -> times_fired 4 with one
subscriber). These tests pin times_fired to the number of publish() calls
regardless of how many subscribers received the event.
"""

import asyncio
import pytest
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from domains.system.plugins.system_events_plugin import SystemEventsPlugin

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend(): return "asyncio"

@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()


def _entry(result: dict, event_name: str) -> dict:
    assert result["success"] is True
    matches = [e for e in result["data"]["events"] if e.event == event_name]
    assert len(matches) == 1
    return matches[0]


async def test_times_fired_counts_publications_not_deliveries(bus):
    async def handler(event: EventEnvelope): pass

    await bus.subscribe("stats.test", handler)
    await bus.publish("stats.test", {"n": 1})
    await bus.publish("stats.test", {"n": 2})
    await asyncio.sleep(0.05)  # let deliveries land in the trace log

    plugin = SystemEventsPlugin(http=None, event_bus=bus)
    entry = _entry(await plugin.execute({}), "stats.test")
    assert entry.times_fired == 2


async def test_times_fired_unaffected_by_subscriber_count(bus):
    async def handler_a(event: EventEnvelope): pass
    async def handler_b(event: EventEnvelope): pass

    await bus.subscribe("stats.fanout", handler_a)
    await bus.subscribe("stats.fanout", handler_b)
    await bus.publish("stats.fanout", {})
    await asyncio.sleep(0.05)

    plugin = SystemEventsPlugin(http=None, event_bus=bus)
    entry = _entry(await plugin.execute({}), "stats.fanout")
    assert entry.times_fired == 1
    assert len(entry.subscribers) == 2
