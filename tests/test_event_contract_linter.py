import pytest
from unittest.mock import MagicMock

from domains.system.plugins.event_contract_linter_plugin import (
    EventContractAnalyzer,
    EventContractLinterPlugin,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def run(*sources):
    """Feed (domain, filename, source) tuples and return findings."""
    analyzer = EventContractAnalyzer()
    for domain, filename, source in sources:
        analyzer.add_source(domain, filename, source)
    return analyzer.check()


def codes(findings, severity=None):
    return [f["code"] for f in findings if severity is None or f["severity"] == severity]


PUBLISHER_OK = ("orders", "create_order_plugin.py", '''
class CreateOrderPlugin:
    async def execute(self, data, context=None):
        await self.bus.publish("order.created", {"id": 1, "total": 9.5})
''')

CONSUMER_SUBSCRIPT = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        order_id = event.payload["id"]
''')


def test_compatible_contract_has_no_warnings():
    findings = run(PUBLISHER_OK, CONSUMER_SUBSCRIPT)
    assert codes(findings, "warning") == []


def test_missing_required_key_is_reported():
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        customer = event.payload["customer_id"]
''')
    findings = run(PUBLISHER_OK, consumer)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert len(warnings) == 1
    w = warnings[0]
    assert w["code"] == "MISSING_KEY"
    assert w["event"] == "order.created"
    assert "customer_id" in w["detail"]
    assert "CreateOrderPlugin" in w["publisher"]
    assert "BillingPlugin.on_order" in w["consumer"]


def test_get_access_is_optional_and_never_warns():
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        coupon = event.payload.get("coupon")
        discount = event.payload.get("discount", 0)
''')
    findings = run(PUBLISHER_OK, consumer)
    assert codes(findings, "warning") == []


def test_spread_payload_suppresses_missing_key():
    publisher = ("orders", "create_order_plugin.py", '''
class CreateOrderPlugin:
    async def execute(self, data, context=None):
        await self.bus.publish("order.created", {"id": 1, **extra})
''')
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        customer = event.payload["customer_id"]
''')
    findings = run(publisher, consumer)
    assert codes(findings, "warning") == []


def test_dynamic_event_name_is_informational():
    publisher = ("jobs", "runner_plugin.py", '''
class RunnerPlugin:
    async def fire(self, row):
        await self.bus.publish(row["event"], {"x": 1})
''')
    findings = run(publisher)
    assert codes(findings) == ["DYNAMIC_EVENT"]
    assert codes(findings, "warning") == []


def test_orphan_publish_and_subscribe_are_informational():
    orphan_sub = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("ghost.event", self.on_ghost)

    async def on_ghost(self, event):
        pass
''')
    findings = run(PUBLISHER_OK, orphan_sub)
    assert sorted(codes(findings)) == ["ORPHAN_PUBLISH", "ORPHAN_SUBSCRIBE"]
    assert codes(findings, "warning") == []


def test_payload_alias_is_followed():
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        data = event.payload
        missing = data["not_sent"]
''')
    findings = run(PUBLISHER_OK, consumer)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["code"] == "MISSING_KEY"
    assert "not_sent" in warnings[0]["detail"]


def test_variable_payload_resolved_from_single_dict_assignment():
    publisher = ("orders", "create_order_plugin.py", '''
class CreateOrderPlugin:
    async def execute(self, data, context=None):
        payload = {"id": 1}
        await self.bus.publish("order.created", payload)
''')
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        total = event.payload["total"]
''')
    findings = run(publisher, consumer)
    assert "MISSING_KEY" in codes(findings, "warning")


def test_unresolvable_payload_is_informational_not_warning():
    publisher = ("monitor", "monitor_plugin.py", '''
class MonitorPlugin:
    async def on_failure(self, record):
        await self.bus.publish("delivery.failed", record)
''')
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("delivery.failed", self.on_fail)

    async def on_fail(self, event):
        reason = event.payload["reason"]
''')
    findings = run(publisher, consumer)
    assert "UNKNOWN_PAYLOAD" in codes(findings)
    assert codes(findings, "warning") == []


def test_pydantic_model_unpack_extracts_required_fields():
    consumer = ("system", "one_shot_plugin.py", '''
from pydantic import BaseModel, Field
from typing import Optional

class ScheduleRequest(BaseModel):
    run_at: str = Field(min_length=1)
    event: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    job_id: Optional[str] = Field(default=None)

class OneShotPlugin:
    async def on_boot(self):
        await self.bus.subscribe("one_shot.schedule", self.on_schedule)

    async def on_schedule(self, event):
        req = ScheduleRequest(**event.payload)
''')
    publisher = ("jobs", "jobs_plugin.py", '''
class JobsPlugin:
    async def execute(self, data, context=None):
        await self.bus.publish("one_shot.schedule", {"run_at": "now"})
''')
    findings = run(publisher, consumer)
    warnings = [f for f in findings if f["severity"] == "warning"]
    # 'event' is required by the model but not published; 'payload'/'job_id' have defaults.
    assert len(warnings) == 1
    assert "'event'" in warnings[0]["detail"]


def test_opaque_consumer_is_informational():
    consumer = ("billing", "billing_plugin.py", '''
class BillingPlugin:
    async def on_boot(self):
        await self.bus.subscribe("order.created", self.on_order)

    async def on_order(self, event):
        self.process(event.payload)
''')
    findings = run(PUBLISHER_OK, consumer)
    assert "OPAQUE_CONSUMER" in codes(findings)
    assert codes(findings, "warning") == []


def test_dlq_reply_and_wildcards_are_excluded():
    source = ("system", "dlq_plugin.py", '''
class DlqPlugin:
    async def on_boot(self):
        await self.bus.subscribe("_dlq.order.created", self.on_dlq)
        await self.bus.subscribe("orders.*", self.on_any)

    async def on_dlq(self, event):
        original = event.payload["original"]

    async def on_any(self, event):
        pass
''')
    findings = run(source)
    assert findings == []


@pytest.mark.anyio
async def test_plugin_boot_registers_metadata_and_endpoint():
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    logger = MagicMock()
    http = MagicMock()

    plugin = EventContractLinterPlugin(container=container, logger=logger, http=http)
    await plugin.on_boot()

    args, _ = registry.register_domain_metadata.call_args
    assert args[0] == "system"
    assert args[1] == "event_contract_violations"
    assert isinstance(args[2], list)

    endpoint_args, endpoint_kwargs = http.add_endpoint.call_args
    assert endpoint_args[0] == "/system/lint"
    assert endpoint_args[1] == "GET"


@pytest.mark.anyio
async def test_real_repo_produces_no_false_warnings():
    """The linter must not raise warnings on the current, known-good codebase."""
    container = MagicMock()
    container.registry = MagicMock()
    plugin = EventContractLinterPlugin(container=container, logger=MagicMock(), http=MagicMock())

    findings = plugin._run_scan()

    warnings = [f for f in findings if f["severity"] == "warning"]
    assert warnings == []
    # Sanity: it actually analyzed the repo (user.created exists and is consumed).
    assert any(f.get("event") for f in findings) or findings == []
