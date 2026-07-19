import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from tools.event_bus.redis_streams_driver import RedisStreamsDriver, EventBusConnectionError
from tests.helpers.async_wait import wait_until

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

# The parity requirement (Issue 22): every transport driver must pass this
# exact suite. The redis variant skips itself if no server is reachable
# (docker compose -f dev_infra/docker-compose.yml up -d redis).
@pytest.fixture(params=["in_process", "redis_streams", "sqlite"])
async def bus(request, monkeypatch, tmp_path):
    if request.param == "redis_streams":
        monkeypatch.setenv("REDIS_DB", "15")  # keep test streams away from dev data
        b = EventBusTool(driver=RedisStreamsDriver())
        try:
            await b.setup()
        except EventBusConnectionError:
            pytest.skip("Redis not available — docker compose -f dev_infra/docker-compose.yml up -d redis")
        # Durable groups persist between runs: start each test hermetic.
        await b._driver._redis.flushdb()
    elif request.param == "sqlite":
        from tools.event_bus.sqlite_driver import SQLiteDriver
        monkeypatch.setenv("EVENT_BUS_SQLITE_PATH", str(tmp_path / "bus_queue.db"))
        b = EventBusTool(driver=SQLiteDriver())
        await b.setup()
    else:
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

    def _delivered():
        return any(n.kind == "delivered" and n.envelope.payload.get("msg") == "expired"
                    for n in bus.get_trace_history())
    await wait_until(_delivered)

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
    await wait_until(lambda: handler.called)

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
    await wait_until(lambda: calls >= 3)

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
    await wait_until(lambda: fail_listener.called)

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

    class _AsyncioRecorder:
        """asyncio stand-in for event_bus_tool's namespace ONLY: records the
        retry-loop sleeps without sleeping. Patching asyncio.sleep itself
        would mutate the SHARED asyncio module and leak into drivers and
        their client libraries (e.g. Kafka group heartbeats sleep too)."""
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay):
            recorded_sleeps.append(delay)

    with patch("tools.event_bus.event_bus_tool.asyncio", _AsyncioRecorder()):
        await bus.subscribe("test.backoff", always_fail, retries=3, backoff=0.5)
        await bus.publish("test.backoff", {"msg": "backoff"})
        await wait_until(lambda: len(recorded_sleeps) >= 3)

        # Expected sleeps: 0.5 * 2^0 = 0.5, 0.5 * 2^1 = 1.0, 0.5 * 2^2 = 2.0
        assert recorded_sleeps == [0.5, 1.0, 2.0]

async def test_dlq_loop_protection(bus):
    async def always_fail(env):
        raise ValueError("Fail")

    # Subscriber to a DLQ event that also fails
    await bus.subscribe("_dlq.some_event", always_fail)
    
    await bus.publish("_dlq.some_event", {"msg": "bad"})

    def _delivered():
        return any(n.kind == "delivered" and n.envelope.payload.get("msg") == "bad"
                    for n in bus.get_trace_history())
    await wait_until(_delivered)

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

        def _delivered():
            return any(n.kind == "delivered" and n.envelope.payload.get("msg") == "no_dlq"
                        for n in bus.get_trace_history())
        await wait_until(_delivered)

        history = bus.get_trace_history()
        dlq_event = next((n for n in history if n.envelope.event == "_dlq.test.no_dlq"), None)
        assert dlq_event is None

async def test_backward_compatibility(bus):
    handler = AsyncMock()
    await bus.subscribe("test.compat", handler) # No retries/backoff
    
    await bus.publish("test.compat", {"msg": "ok"})
    await wait_until(lambda: handler.called)

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
    
    def _delivered(msg):
        return lambda: any(
            n.kind == "delivered" and n.envelope.payload.get("msg") == msg
            for n in bus.get_trace_history()
        )

    # 1st failure
    await bus.publish("test.poison", {"msg": "1"})
    await wait_until(_delivered("1"))
    assert "test.poison" in bus.get_subscribers()

    # 2nd failure -> should unsubscribe
    await bus.publish("test.poison", {"msg": "2"})
    await wait_until(lambda: "test.poison" not in bus.get_subscribers())
    assert "test.poison" not in bus.get_subscribers()

async def test_rpc_unaffected(bus):
    async def handler(env):
        return {"res": "pong"}

    await bus.subscribe("ping", handler, retries=1)

    res = await bus.request("ping", {"msg": "ping"})
    assert res == {"res": "pong"}

async def test_delayed_delivery(bus):
    """delay=n holds delivery for ~n seconds — never early, always eventually.

    The UPPER bound is contractual too: it catches a driver that sleeps the
    delay itself while leaving the default in_bus claim (the Bus would sleep
    AGAIN — a double-delay bug the lower bound alone would never see)."""
    handler = AsyncMock()
    await bus.subscribe("test.delayed", handler)

    start = asyncio.get_running_loop().time()
    await bus.publish("test.delayed", {"msg": "later"}, delay=2)

    await asyncio.sleep(0.8)
    handler.assert_not_called()  # parked (broker-side or Bus fallback), not early

    await wait_until(lambda: handler.called, timeout=10)
    elapsed = asyncio.get_running_loop().time() - start
    assert 1.9 <= elapsed < 3.5, f"delay=2 delivered at {elapsed:.2f}s"

async def test_capabilities_declared(bus):
    """Issue 30: every driver claims its semantics, and the manifest shows them."""
    caps = bus._driver.capabilities
    assert set(caps) >= {"delay", "retries", "dlq"}
    assert all(v in ("native", "in_bus") for v in caps.values())

    desc = bus.get_interface_description()
    assert bus._driver.__class__.__name__ in desc  # ACTIVE TRANSPORT line

def test_public_contract_frozen():
    """The Bus semantic contract is CLOSED (Issue 36 admission rule).

    A new public method here means a new universal semantic that EVERY driver
    must honor forever. That is a ROADMAP decision, not a code change: new
    capabilities enter as plugin-layer compositions or driver capability
    claims. If you consciously extend the contract, update this set in the
    same commit as the ROADMAP issue that justifies it."""
    public = {n for n in dir(EventBusTool) if not n.startswith("_")}
    assert public == {
        # BaseTool lifecycle
        "name", "setup", "get_interface_description", "on_boot_complete",
        "on_instrument", "shutdown",
        # The Bus semantic contract
        "subscribe", "unsubscribe", "publish", "request",
        # Observability
        "get_trace_history", "get_subscribers", "add_listener",
        "add_failure_listener", "SUBSCRIBER_DROPPED_EVENT",
    }
