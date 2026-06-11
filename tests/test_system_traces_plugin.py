import asyncio
import pytest
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from domains.system.plugins.system_traces_plugin import SystemTracesPlugin
from domains.system.plugins.system_traces_stream_plugin import SystemTracesStreamPlugin

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

async def test_traces_no_duplicates_and_aggregates_subscribers(bus):
    # Register multiple subscribers for the same event
    subscribers_called = []
    async def sub_a(event: EventEnvelope):
        subscribers_called.append("a")
    async def sub_b(event: EventEnvelope):
        subscribers_called.append("b")

    await bus.subscribe("trace.test", sub_a)
    await bus.subscribe("trace.test", sub_b)

    # Publish an event
    await bus.publish("trace.test", {"data": "test"})
    await asyncio.sleep(0.05)  # Let deliveries complete

    # Instantiate traces plugin
    plugin = SystemTracesPlugin(http=None, event_bus=bus)
    
    # Test flat trace list
    flat_res = await plugin.get_flat({})
    assert flat_res["success"] is True
    flat_data = flat_res["data"]
    
    # We should have exactly 1 record for trace.test, not multiple (e.g. not separate published/delivered records)
    test_records = [r for r in flat_data if r["event"] == "trace.test"]
    assert len(test_records) == 1
    
    # The subscribers should be aggregated
    subs = test_records[0]["subscribers"]
    assert "SystemTracesPlugin" in subs[0] or "sub_a" in subs[0]
    assert len(subs) == 2

    # Test tree trace list
    tree_res = await plugin.get_tree({})
    assert tree_res["success"] is True
    tree_data = tree_res["data"]
    test_tree_nodes = [n for n in tree_data if n["event"] == "trace.test"]
    assert len(test_tree_nodes) == 1
    assert len(test_tree_nodes[0]["subscribers"]) == 2

async def test_traces_stream_contains_subscribers(bus):
    # Register a subscriber
    async def sub_c(event: EventEnvelope):
        pass
    await bus.subscribe("stream.test", sub_c)

    class MockHttp:
        def add_sse_endpoint(self, *args, **kwargs):
            pass

    stream_plugin = SystemTracesStreamPlugin(http=MockHttp(), event_bus=bus)
    await stream_plugin.on_boot()

    # Capture the stream output
    records_emitted = []
    async def capture():
        async for msg in stream_plugin._stream({}):
            if "snapshot" in msg:
                continue
            records_emitted.append(msg)
            if len(records_emitted) >= 1:
                break

    # Start capturing in background
    cap_task = asyncio.create_task(capture())
    await asyncio.sleep(0.02)

    # Publish event
    await bus.publish("stream.test", {"hello": "world"})
    await asyncio.sleep(0.05)

    await cap_task

    assert len(records_emitted) == 1
    import json
    data_str = records_emitted[0].replace("data: ", "").strip()
    data = json.loads(data_str)
    
    # Verify node format and presence of subscribers
    assert data["type"] == "node"
    node = data["node"]
    assert node["event"] == "stream.test"
    assert len(node["subscribers"]) == 1
    assert "sub_c" in node["subscribers"][0]
