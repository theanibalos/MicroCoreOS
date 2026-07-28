import asyncio
import threading

import pytest
from microcoreos import current_event_id_var
from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from tests.helpers.async_wait import wait_until

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend(): return "asyncio"

async def test_subscribe_publish(event_bus):
    received = []
    async def handler(event: EventEnvelope):
        received.append(event.payload)

    await event_bus.subscribe("user.created", handler)
    await event_bus.publish("user.created", {"id": 1})
    await wait_until(lambda: len(received) >= 1)
    assert received == [{"id": 1}]

async def test_envelope_metadata(event_bus):
    received = []
    async def handler(event: EventEnvelope):
        received.append(event)

    await event_bus.subscribe("meta.test", handler)
    await event_bus.publish("meta.test", {"x": 1})
    await wait_until(lambda: len(received) >= 1)

    env = received[0]
    assert env.event == "meta.test"
    assert env.payload == {"x": 1}
    assert env.id is not None
    assert env.timestamp is not None

async def test_request_response(event_bus):
    async def handler(event: EventEnvelope):
        return {"ok": True, "echo": event.payload["msg"]}

    await event_bus.subscribe("validate", handler)
    result = await event_bus.request("validate", {"msg": "hello"})
    assert result == {"ok": True, "echo": "hello"}

async def test_system_wide_observation_via_listener(event_bus):
    """There is no wildcard subscription: system-wide observation is
    add_listener's job (publish-side sink, zero transport cost)."""
    received = []
    event_bus.add_listener(lambda record: received.append(record["event"]))
    await event_bus.publish("a", {})
    await event_bus.publish("b", {})
    await wait_until(lambda: "a" in received and "b" in received)

async def test_causality_chain(event_bus):
    async def parent_handler(event: EventEnvelope):
        await event_bus.publish("child", {"p": event.id})

    await event_bus.subscribe("parent", parent_handler)
    await event_bus.publish("parent", {})
    await wait_until(lambda: any(r.envelope.event == "child" for r in event_bus.get_trace_history()))

    history = event_bus.get_trace_history()
    parent_rec = next(r for r in history if r.envelope.event == "parent")
    child_rec = next(r for r in history if r.envelope.event == "child")
    assert child_rec.envelope.parent_id == parent_rec.envelope.id

async def test_dead_subscriber_auto_unsubscribe(event_bus):
    calls = []
    async def flaky(event: EventEnvelope):
        calls.append(1)
        raise RuntimeError("always fails")

    await event_bus.subscribe("boom", flaky)

    for _ in range(EventBusTool._MAX_CONSECUTIVE_FAILURES):
        await event_bus.publish("boom", {})

    await wait_until(lambda: "boom" not in event_bus.get_subscribers())

    # After max failures, the handler must be gone — bus must not deadlock
    before = len(calls)
    await event_bus.publish("boom", {})
    await asyncio.sleep(0.05)  # negative check: no new calls should ever arrive
    assert len(calls) == before  # no new calls — handler was removed

async def test_auto_unsubscribe_publishes_dropped_event(event_bus):
    dropped = []
    async def on_dropped(event: EventEnvelope):
        dropped.append(event)

    async def flaky(event: EventEnvelope):
        raise RuntimeError("always fails")

    await event_bus.subscribe(EventBusTool.SUBSCRIBER_DROPPED_EVENT, on_dropped)
    await event_bus.subscribe("boom", flaky)

    for _ in range(EventBusTool._MAX_CONSECUTIVE_FAILURES):
        await event_bus.publish("boom", {})
    await wait_until(lambda: len(dropped) >= 1)

    assert len(dropped) == 1
    payload = dropped[0].payload
    assert payload["event"] == "boom"
    assert "flaky" in payload["subscriber"]
    assert payload["error"] == "always fails"
    assert payload["consecutive_failures"] == EventBusTool._MAX_CONSECUTIVE_FAILURES

async def test_dropped_event_subscriber_drop_does_not_retrigger(event_bus):
    # A failing subscriber OF the dropped event must not re-trigger it (loop guard).
    max_fails = EventBusTool._MAX_CONSECUTIVE_FAILURES

    async def broken_monitor(event: EventEnvelope):
        raise RuntimeError("monitor down")

    def make_flaky():
        async def flaky(event: EventEnvelope):
            raise RuntimeError("always fails")
        return flaky

    await event_bus.subscribe(EventBusTool.SUBSCRIBER_DROPPED_EVENT, broken_monitor)

    def _delivered_count(event_name):
        return sum(1 for r in event_bus.get_trace_history()
                    if r.kind == "delivered" and r.envelope.event == event_name)

    # Drop N distinct subscribers -> N dropped events -> broken_monitor fails
    # on each of them and is itself dropped on the Nth. The guard must prevent
    # a further dropped event about broken_monitor (no self-reference).
    for i in range(max_fails):
        event_name = f"boom.{i}"
        await event_bus.subscribe(event_name, make_flaky())
        for attempt in range(max_fails):
            await event_bus.publish(event_name, {})
            await wait_until(lambda: _delivered_count(event_name) > attempt)
        await wait_until(lambda: event_name not in event_bus.get_subscribers())

    def _published_dropped():
        return [
            r for r in event_bus.get_trace_history()
            if r.kind == "published" and r.envelope.event == EventBusTool.SUBSCRIBER_DROPPED_EVENT
        ]
    # Dropping the last flaky subscriber cascades into broken_monitor's own
    # (fire-and-forget) delivery — wait for that cascade to settle too.
    await wait_until(lambda: len(_published_dropped()) >= max_fails)

    published_dropped = _published_dropped()
    # One per flaky subscriber; broken_monitor's own drop is guarded and silent.
    assert len(published_dropped) == max_fails
    assert all(
        "broken_monitor" not in r.envelope.payload["subscriber"]
        for r in published_dropped
    )


async def test_a_sync_subscriber_runs_off_the_event_loop(event_bus):
    """
    A plain `def` handler is delivered too — on a worker thread, because a
    blocking subscriber on the loop stalls every other delivery in the process.

    This branch shipped untested: replacing the raise inside it with an
    exception left the whole suite green. It is also the bus's only tie to
    starlette, so anything that changes how it dispatches needs a test that
    notices.
    """
    seen = []
    loop_thread = threading.current_thread().ident

    def handler(event: EventEnvelope):        # deliberately NOT async
        seen.append((event.payload, threading.current_thread().ident))

    await event_bus.subscribe("sync.work", handler)
    await event_bus.publish("sync.work", {"n": 1})
    await wait_until(lambda: seen, describe=lambda: {"seen": seen})

    payload, ran_on = seen[0]
    assert payload == {"n": 1}
    assert ran_on != loop_thread, "a sync subscriber must not run on the event loop"


async def test_a_sync_subscriber_carries_the_event_context(event_bus):
    """
    The bus stamps `current_event_id_var` around delivery, and a thread hop
    loses context vars unless the dispatcher copies the context. Handlers read
    these — losing them silently unstamps every log line and trace a sync
    subscriber produces.
    """
    seen = []

    def handler(event: EventEnvelope):
        seen.append(current_event_id_var.get())

    await event_bus.subscribe("sync.ctx", handler)
    await event_bus.publish("sync.ctx", {})
    await wait_until(lambda: seen, describe=lambda: {"seen": seen})

    assert seen[0] is not None, "the event id did not survive the thread hop"


async def test_publishes_arrive_in_call_order(event_bus):
    """
    `publish()` returns before the message reaches the transport — that is the
    decoupling mandate and it stays. What must NOT leak out of it is the order:
    three publishes in a row raced each other to the driver, and a durable
    queue then stored, and delivered, whatever order the threads won in.

    Twenty rather than three: the race window is per hand-off, so a longer run
    is far more likely to catch a regression than the three-message case that
    took months to show up once.
    """
    seen = []

    async def handler(event: EventEnvelope):
        seen.append(event.payload["n"])

    await event_bus.subscribe("order.seq", handler)
    for n in range(20):
        await event_bus.publish("order.seq", {"n": n})

    await wait_until(lambda: len(seen) == 20, describe=lambda: {"seen": seen})
    assert seen == list(range(20)), f"out of order: {seen}"


async def test_ordering_is_per_key_not_global(event_bus):
    """
    The guarantee is the one every broker makes — Kafka per partition, SQS FIFO
    per MessageGroupId — and this pins its shape: each key's own sequence is
    ordered, while nothing is promised ACROSS keys, because promising that
    would mean serializing every publish in the process.
    """
    seen = []

    async def handler(event: EventEnvelope):
        seen.append((event.key, event.payload["n"]))

    await event_bus.subscribe("order.keyed", handler)
    for n in range(10):
        await event_bus.publish("order.keyed", {"n": n}, key="a")
        await event_bus.publish("order.keyed", {"n": n}, key="b")

    await wait_until(lambda: len(seen) == 20, describe=lambda: {"seen": seen})
    for key in ("a", "b"):
        assert [n for k, n in seen if k == key] == list(range(10)), \
            f"key {key!r} out of order: {seen}"
