import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope

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

async def test_ttl_expired(bus):
    handler = AsyncMock()
    await bus.subscribe("test.event", handler)
    
    # Fake an old timestamp
    old_ts = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    # Simulate the arrival of an old envelope directly to the driver
    envelope = EventEnvelope(
        event="test.event",
        payload={"msg": "expired"},
        emitter="test",
        timestamp=old_ts,
        ttl=0.001
    )
    await bus._driver.publish(envelope)
    await asyncio.sleep(0.1) # Wait for tasks
    
    handler.assert_not_called()
    
    # Check trace
    history = bus.get_trace_history()
    # Find the delivered node for this subscriber
    delivered_node = next(n for n in history if n.kind == "delivered" and n.envelope.payload.get("msg") == "expired")
    assert delivered_node.success is False
    assert delivered_node.error == "ttl_expired"
    assert delivered_node.attempts == 0

async def test_ttl_valid(bus):
    handler = AsyncMock()
    await bus.subscribe("test.event", handler)
    
    await bus.publish("test.event", {"msg": "valid"}, ttl=60)
    await asyncio.sleep(0.1)
    
    handler.assert_called_once()
    
    history = bus.get_trace_history()
    delivered_node = next(n for n in history if n.kind == "delivered")
    assert delivered_node.success is True

async def test_retry_then_success(bus):
    calls = 0
    async def failing_handler(env):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("Fail")
        return {"ok": True}

    await bus.subscribe("test.event", failing_handler, retries=3, backoff=0.01)
    
    # Failure listener mock
    fail_listener = MagicMock()
    bus.add_failure_listener(fail_listener)
    
    await bus.publish("test.event", {"msg": "retry"})
    await asyncio.sleep(0.2)
    
    assert calls == 3
    fail_listener.assert_not_called()
    assert bus._consecutive_failures.get("anonymous", 0) == 0 # Should be reset
    
    history = bus.get_trace_history()
    delivered_node = next(n for n in history if n.kind == "delivered" and n.envelope.payload.get("msg") == "retry")
    assert delivered_node.attempts == 3
    assert delivered_node.success is True

async def test_retries_exhausted_dlq(bus):
    async def always_fail(env):
        raise ValueError("Permanent Fail")

    await bus.subscribe("test.fail", always_fail, retries=2, backoff=0.01)
    
    fail_listener = MagicMock()
    bus.add_failure_listener(fail_listener)
    
    # To see DLQ event in trace, we need a subscriber for it or just check trace log
    # The DLQ event itself will be in history if published
    
    await bus.publish("test.fail", {"msg": "to_dlq"})
    await asyncio.sleep(0.2)
    
    # 1 attempt + 2 retries = 3 calls
    fail_listener.assert_called_once()
    
    history = bus.get_trace_history()
    # Should see _dlq.test.fail in history
    dlq_event = next((n for n in history if n.envelope.event == "_dlq.test.fail"), None)
    assert dlq_event is not None
    assert dlq_event.envelope.payload["attempts"] == 3
    assert dlq_event.envelope.payload["error"] == "Permanent Fail"
    assert dlq_event.envelope.payload["original"]["payload"]["msg"] == "to_dlq"

async def test_backoff_progression(bus):
    async def always_fail(env):
        raise ValueError("Fail")

    recorded_sleeps = []
    original_sleep = asyncio.sleep

    async def mock_sleep(delay):
        if delay == 0.1: # From test
            await original_sleep(delay)
        else:
            recorded_sleeps.append(delay)

    with patch("tools.event_bus.event_bus_tool.asyncio.sleep", side_effect=mock_sleep):
        await bus.subscribe("test.backoff", always_fail, retries=3, backoff=0.5)
        await bus.publish("test.backoff", {"msg": "backoff"})
        await asyncio.sleep(0.1)
        
        # Expected sleeps: 0.5 * 2^0 = 0.5, 0.5 * 2^1 = 1.0, 0.5 * 2^2 = 2.0
        assert recorded_sleeps == [0.5, 1.0, 2.0]

async def test_dlq_loop_protection(bus):
    async def always_fail(env):
        raise ValueError("Fail")

    # Subscriber to a DLQ event that also fails
    await bus.subscribe("_dlq.some_event", always_fail)
    
    await bus.publish("_dlq.some_event", {"msg": "bad"})
    await asyncio.sleep(0.1)
    
    history = bus.get_trace_history()
    # There should NOT be a _dlq._dlq.some_event
    dlq_of_dlq = next((n for n in history if n.envelope.event == "_dlq._dlq.some_event"), None)
    assert dlq_of_dlq is None

async def test_dlq_disabled(bus):
    async def always_fail(env):
        raise ValueError("Fail")

    with patch.dict("os.environ", {"EVENT_BUS_DLQ_ENABLED": "false"}):
        await bus.subscribe("test.no_dlq", always_fail)
        await bus.publish("test.no_dlq", {"msg": "no_dlq"})
        await asyncio.sleep(0.1)
        
        history = bus.get_trace_history()
        dlq_event = next((n for n in history if n.envelope.event == "_dlq.test.no_dlq"), None)
        assert dlq_event is None

async def test_backward_compatibility(bus):
    handler = AsyncMock()
    await bus.subscribe("test.compat", handler) # No retries/backoff
    
    await bus.publish("test.compat", {"msg": "ok"})
    await asyncio.sleep(0.1)
    
    handler.assert_called_once()
    
    history = bus.get_trace_history()
    delivered_node = next(n for n in history if n.kind == "delivered" and n.envelope.payload.get("msg") == "ok")
    assert delivered_node.attempts == 1

async def test_poisoned_escalation(bus):
    # Reduce max failures for test speed
    bus._MAX_CONSECUTIVE_FAILURES = 2
    
    async def always_fail(env):
        raise ValueError("Fail")

    await bus.subscribe("test.poison", always_fail)
    
    # 1st failure
    await bus.publish("test.poison", {"msg": "1"})
    await asyncio.sleep(0.1)
    assert "test.poison" in bus.get_subscribers()
    
    # 2nd failure -> should unsubscribe
    await bus.publish("test.poison", {"msg": "2"})
    await asyncio.sleep(0.1)
    assert "test.poison" not in bus.get_subscribers()

async def test_rpc_unaffected(bus):
    async def handler(env):
        return {"res": "pong"}
    
    await bus.subscribe("ping", handler, retries=1)
    
    res = await bus.request("ping", {"msg": "ping"})
    assert res == {"res": "pong"}
