"""
Tests for ChaosControlPlugin (ROADMAP Issue 34, extras — never active by
default). Covers the single seam it uses: monkey-patching raw tool methods
via container.get_raw_tools(), with calls still traversing the ToolProxy.

Does NOT touch tools/event_bus/ or tools/http_server/ — this suite proves the
extras plugin composes with the REAL, UNMODIFIED event_bus and http tools.
"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from core.base_tool import BaseTool
from core.container import Container
from tools.event_bus.event_bus_tool import EventBusTool
from tools.http_server.http_server_tool import HttpServerTool
from extras.available_domains.chaos.plugins.chaos_control_plugin import (
    ChaosControlPlugin,
    ChaosToolFaultError,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class LedgerTool(BaseTool):
    """Minimal real tool with one business method to fault."""

    def __init__(self):
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "ledger"

    async def setup(self) -> None:
        pass

    def get_interface_description(self) -> str:
        return "Ledger Tool (ledger): - record(who): appends who to calls."

    async def record(self, who: str) -> dict:
        self.calls.append(who)
        return {"ok": True, "who": who}


@pytest.fixture
def container():
    c = Container()
    c.register(LedgerTool())
    return c


@pytest.fixture
async def bus():
    b = EventBusTool()
    await b.setup()
    yield b
    await b.shutdown()


@pytest.fixture
def chaos(container, bus):
    return ChaosControlPlugin(http=MagicMock(), event_bus=bus, container=container, logger=MagicMock())


# ── mode: down / slow / flaky / off ─────────────────────────────────────────

async def test_tool_down_mode_raises_and_off_restores(container, chaos):
    proxy = container.get("ledger")

    resp = await chaos.set_tool_fault({"name": "ledger", "mode": "down"})
    assert resp["success"] is True

    with pytest.raises(ChaosToolFaultError):
        await proxy.record("x")

    resp = await chaos.set_tool_fault({"name": "ledger", "mode": "off"})
    assert resp["success"] is True

    result = await proxy.record("after-restore")
    assert result == {"ok": True, "who": "after-restore"}


async def test_down_mode_after_cache_warm_still_faults(container, chaos):
    """Regression for the documented ROADMAP deviation: the ToolProxy caches
    a per-method wrapper closure on first access. If that happened BEFORE
    the fault was armed, the fault must still fire on the next call."""
    proxy = container.get("ledger")

    # Warm the ToolProxy's _wrapper_cache BEFORE arming any fault.
    warm = await proxy.record("warmup")
    assert warm == {"ok": True, "who": "warmup"}

    resp = await chaos.set_tool_fault({"name": "ledger", "mode": "down"})
    assert resp["success"] is True

    with pytest.raises(ChaosToolFaultError):
        await proxy.record("should-fail")


async def test_tool_slow_mode_delays_then_passes_through(container, chaos):
    proxy = container.get("ledger")
    resp = await chaos.set_tool_fault({"name": "ledger", "mode": "slow", "seconds": 0.2})
    assert resp["success"] is True

    t0 = time.monotonic()
    result = await proxy.record("slow-call")
    elapsed = time.monotonic() - t0

    assert elapsed >= 0.15
    assert result == {"ok": True, "who": "slow-call"}


async def test_tool_flaky_mode_rate_one_always_fails(container, chaos):
    proxy = container.get("ledger")
    resp = await chaos.set_tool_fault({"name": "ledger", "mode": "flaky", "rate": 1.0})
    assert resp["success"] is True

    with pytest.raises(ChaosToolFaultError):
        await proxy.record("x")


async def test_dependent_plugin_hits_safe_error_path_and_recovers(container, chaos):
    """Simulates a real plugin's try/except Safe-Error pattern (house rule 7):
    NEVER return str(e) — a generic message only."""
    proxy = container.get("ledger")
    await chaos.set_tool_fault({"name": "ledger", "mode": "down"})

    async def dependent_execute():
        try:
            await proxy.record("x")
            return {"success": True}
        except Exception:
            return {"success": False, "error": "Ledger error"}

    result = await dependent_execute()
    assert result == {"success": False, "error": "Ledger error"}

    await chaos.set_tool_fault({"name": "ledger", "mode": "off"})
    result = await dependent_execute()
    assert result == {"success": True}


# ── caller-scoped fail / latency (via the REAL, unmodified event_bus) ──────

class BillingPlugin:
    _identity = "billing.BillingPlugin"

    def __init__(self, ledger):
        self.ledger = ledger

    async def on_event(self, env):
        await self.ledger.record("billing")
        return {"ok": True}


class ShippingPlugin:
    _identity = "shipping.ShippingPlugin"

    def __init__(self, ledger):
        self.ledger = ledger

    async def on_event(self, env):
        await self.ledger.record("shipping")
        return {"ok": True}


async def test_fail_scoped_to_one_plugin_leaves_other_callers_unaffected(container, bus, chaos):
    ledger_proxy = container.get("ledger")
    ledger_raw = container.get_raw_tools()[0]
    billing = BillingPlugin(ledger_proxy)
    shipping = ShippingPlugin(ledger_proxy)

    dlq = []
    async def dlq_handler(env):
        dlq.append(env.payload)
    await bus.subscribe("_dlq.order.created", dlq_handler)

    await bus.subscribe("order.created", billing.on_event, retries=1, backoff=0.01)
    await bus.subscribe("order.created", shipping.on_event, retries=1, backoff=0.01)

    resp = await chaos.set_fail({"plugin": "billing.BillingPlugin", "rate": 1.0})
    assert resp["success"] is True

    await bus.publish("order.created", {"id": 1})
    await asyncio.sleep(0.2)

    # Billing's REAL retry/DLQ machinery reacted to the injected failure —
    # indistinguishable from an organic exception.
    assert len(dlq) == 1
    assert dlq[0]["subscriber"] == "billing.BillingPlugin.on_event"
    assert dlq[0]["attempts"] == 2
    assert "Chaos" in dlq[0]["error"]

    # Shipping (a different caller identity) was never touched.
    assert ledger_raw.calls == ["shipping"]


async def test_fail_reset_stops_affecting_the_scoped_plugin(container, bus, chaos):
    ledger_proxy = container.get("ledger")
    billing = BillingPlugin(ledger_proxy)
    await bus.subscribe("order.created", billing.on_event, retries=0)

    await chaos.set_fail({"plugin": "billing.BillingPlugin", "rate": 1.0})
    resp = await chaos.reset({})
    assert resp["success"] is True

    await bus.publish("order.created", {"id": 2})
    await asyncio.sleep(0.1)

    ledger_raw = container.get_raw_tools()[0]
    assert ledger_raw.calls == ["billing"]


async def test_latency_unscoped_delays_every_caller(container, chaos):
    proxy = container.get("ledger")
    resp = await chaos.set_latency({"tool": "ledger", "seconds": 0.2})
    assert resp["success"] is True

    t0 = time.monotonic()
    await proxy.record("anyone")
    assert time.monotonic() - t0 >= 0.15


async def test_latency_scoped_to_plugin_only(container, bus, chaos):
    ledger_proxy = container.get("ledger")
    billing = BillingPlugin(ledger_proxy)
    shipping = ShippingPlugin(ledger_proxy)
    await bus.subscribe("order.created", billing.on_event)
    await bus.subscribe("order.created", shipping.on_event)

    await chaos.set_latency({"plugin": "billing.BillingPlugin", "tool": "ledger", "seconds": 0.3})

    t0 = time.monotonic()
    await bus.publish("order.created", {"id": 3})
    await asyncio.sleep(0.05)  # shipping (unscoped) should already be done

    ledger_raw = container.get_raw_tools()[0]
    assert "shipping" in ledger_raw.calls
    assert "billing" not in ledger_raw.calls  # still sleeping

    await asyncio.sleep(0.4)
    assert "billing" in ledger_raw.calls
    assert time.monotonic() - t0 >= 0.25


# ── reset / state introspection ─────────────────────────────────────────────

async def test_reset_restores_everything_unconditionally(container, chaos):
    proxy = container.get("ledger")
    await chaos.set_tool_fault({"name": "ledger", "mode": "down"})
    with pytest.raises(ChaosToolFaultError):
        await proxy.record("x")

    resp = await chaos.reset({})
    assert resp["success"] is True
    assert resp["data"]["cleared"] == 1
    assert resp["data"]["restored_tools"] == ["ledger"]

    result = await proxy.record("y")
    assert result == {"ok": True, "who": "y"}

    state = await chaos.get_state({})
    assert state["data"]["faults"] == []
    assert state["data"]["wrapped_tools"] == []


async def test_get_state_reports_armed_faults(container, chaos):
    await chaos.set_tool_fault({"name": "ledger", "mode": "flaky", "rate": 0.3})
    state = await chaos.get_state({})
    assert state["success"] is True
    assert state["data"]["wrapped_tools"] == ["ledger"]
    faults = state["data"]["faults"]
    assert len(faults) == 1
    assert faults[0]["tool"] == "ledger"
    assert faults[0]["source"] == "tool_mode"
    assert faults[0]["mode"] == "flaky"
    assert faults[0]["rate"] == 0.3


async def test_unknown_tool_returns_business_error_not_exception(chaos):
    resp = await chaos.set_tool_fault({"name": "does-not-exist", "mode": "down"})
    assert resp["success"] is False
    assert "does-not-exist" in resp["error"]


# ── full HTTP round trip (real, unmodified HttpServerTool) ─────────────────

async def test_full_http_roundtrip(container):
    http = HttpServerTool()
    bus = MagicMock()
    bus.publish = AsyncMock()
    chaos = ChaosControlPlugin(http=http, event_bus=bus, container=container, logger=MagicMock())
    await chaos.on_boot()
    http._register_all_endpoints()

    async with AsyncClient(transport=ASGITransport(app=http.app), base_url="http://test") as client:
        resp = await client.post("/system/chaos/tool", json={"name": "ledger", "mode": "down"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        proxy = container.get("ledger")
        with pytest.raises(ChaosToolFaultError):
            await proxy.record("x")

        resp = await client.get("/system/chaos")
        assert resp.status_code == 200
        assert resp.json()["data"]["wrapped_tools"] == ["ledger"]

        resp = await client.post("/system/chaos/reset", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["cleared"] == 1

        result = await proxy.record("restored")
        assert result == {"ok": True, "who": "restored"}
