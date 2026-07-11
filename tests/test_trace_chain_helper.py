import asyncio
import pytest

from tools.event_bus.event_bus_tool import EventBusTool, EventEnvelope
from tests.helpers.trace_chains import build_tree, find_chain, assert_chain

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


def node(event, children=None):
    return {"id": event, "parent_id": None, "event": event, "children": children or []}


def test_find_chain_matches_direct_causal_path():
    forest = [node("a", [node("b", [node("c")])])]
    assert find_chain(forest, ["a", "b", "c"])
    assert find_chain(forest, ["b", "c"])  # may start mid-tree
    assert find_chain(forest, ["c"])


def test_find_chain_rejects_gaps_and_wrong_order():
    forest = [node("a", [node("b", [node("c")])])]
    assert not find_chain(forest, ["a", "c"])  # b in between: not a direct path
    assert not find_chain(forest, ["c", "b"])
    assert not find_chain(forest, ["a", "x"])


def test_assert_chain_failure_shows_observed_causality():
    forest = [node("a", [node("b")])]
    with pytest.raises(AssertionError) as exc:
        assert_chain(forest, ["a", "ghost"])
    assert "a -> ghost" in str(exc.value)
    assert "Observed causality" in str(exc.value)


async def test_chain_asserted_against_real_bus_causality(bus):
    """The in-process flavor: a real handler chain, verified via trace history."""

    async def on_created(event: EventEnvelope):
        await bus.publish("order.notified", {"order_id": event.payload["id"]})

    await bus.subscribe("order.created", on_created)
    await bus.publish("order.created", {"id": 7})
    await asyncio.sleep(0.05)

    forest = build_tree(bus.get_trace_history())
    assert_chain(forest, ["order.created", "order.notified"])
    assert not find_chain(forest, ["order.notified", "order.created"])
