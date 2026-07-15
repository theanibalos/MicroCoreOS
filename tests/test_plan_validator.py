"""
Plan validator — one test per validity rule of docs/PARALLEL_DEVELOPMENT.md,
plus the endpoint's input-parsing paths.

The validator core is pure (PlanValidator + LiveSnapshot), so rule tests run
without infrastructure; endpoint tests mock the live snapshot.
"""
import copy

import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.plan_validator_plugin import (
    LiveSnapshot,
    Plan,
    PlanValidator,
    PlanValidatorPlugin,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


VALID_PLAN = {
    "domain": "orders",
    "phase_0": {
        "migrations": [
            {
                "file": "orders/001_create_orders.sql",
                "tables": ["orders"],
                "columns": {
                    "orders": {
                        "id": "SERIAL PRIMARY KEY",
                        "user_id": "INT NOT NULL",
                        "total": "FLOAT NOT NULL",
                    }
                },
            }
        ],
        "models": ["domains/orders/models/order.py"],
        "tools": [],
    },
    "features": [
        {
            "plugin": "CreateOrderPlugin",
            "file": "domains/orders/plugins/create_order_plugin.py",
            "function": "Create an order and announce it",
            "route": {"method": "POST", "path": "/orders"},
            "db": {"writes": ["orders"], "reads": []},
            "publishes": [
                {
                    "event": "order.created",
                    "model": "OrderCreatedPayload",
                    "payload": {"id": "int", "user_id": "int", "total": "float"},
                }
            ],
            "consumes": [],
            "test": "tests/test_create_order.py",
        },
        {
            "plugin": "OrderNotifierPlugin",
            "file": "domains/orders/plugins/order_notifier_plugin.py",
            "function": "Notify the user when an order is created",
            "route": None,
            "publishes": [
                {
                    "event": "order.notified",
                    "model": "OrderNotifiedPayload",
                    "payload": {"order_id": "int"},
                }
            ],
            "consumes": [{"event": "order.created", "requires": ["id", "user_id"]}],
            "test": "tests/test_order_notifier.py",
        },
    ],
    "flows": [
        {
            "name": "order-lifecycle",
            "durability": "ephemeral",
            "happy_path": "POST /orders -> order.created -> order.notified",
            "e2e_test": "tests/test_order_lifecycle_chain.py",
            "sad_path_test": "tests/test_order_lifecycle_dlq.py",
            "links": [
                {
                    "consumes": "order.created",
                    "consumer": "OrderNotifierPlugin",
                    "retries": 3,
                    "backoff": 1.0,
                    "idempotent": True,
                    "idempotency_test": "tests/test_order_notifier.py::test_delivered_twice",
                    "dlq_watcher": None,
                    "atomic_with_db": False,
                    "compensation": None,
                }
            ],
            "rpc_links": [],
        }
    ],
}


def plan_copy() -> dict:
    return copy.deepcopy(VALID_PLAN)


def check(plan_dict, live=None):
    return PlanValidator(Plan(**plan_dict), live or LiveSnapshot()).validate()


def rule_hits(result, rule, severity="ERROR"):
    pool = result.errors if severity == "ERROR" else result.warnings
    return [v for v in pool if v.rule == rule]


def test_valid_plan_passes():
    result = check(plan_copy())
    assert result.valid, result.errors
    assert result.errors == [] and result.warnings == []


# ── Rule 1: namespace collisions ─────────────────────────────────────────

def test_rule1_duplicate_route():
    plan = plan_copy()
    plan["features"][1]["route"] = {"method": "POST", "path": "/orders"}
    assert rule_hits(check(plan), 1)


def test_rule1_duplicate_file_and_plugin():
    plan = plan_copy()
    plan["features"][1]["file"] = plan["features"][0]["file"]
    plan["features"][1]["plugin"] = plan["features"][0]["plugin"]
    assert len(rule_hits(check(plan), 1)) == 2


def test_rule1_file_outside_domains_layout():
    plan = plan_copy()
    plan["features"][0]["file"] = "plugins/create_order.py"
    assert rule_hits(check(plan), 1)


def test_rule1_live_route_collision_is_warning():
    live = LiveSnapshot(routes={"POST /orders": "domains/legacy/plugins/old.py"})
    result = check(plan_copy(), live)
    assert result.valid  # advisory, not blocking
    assert rule_hits(result, 1, "WARNING")


# ── Rule 2: table ownership ──────────────────────────────────────────────

def test_rule2_duplicate_table_in_plan():
    plan = plan_copy()
    plan["phase_0"]["migrations"].append(
        {"file": "billing/001_create_orders.sql", "tables": ["orders"]}
    )
    assert rule_hits(check(plan), 2)


def test_rule2_table_owned_by_another_domain_live():
    live = LiveSnapshot(tables={"orders": "billing"})
    assert rule_hits(check(plan_copy(), live), 2)


def test_rule2_table_without_columns_warns():
    plan = plan_copy()
    del plan["phase_0"]["migrations"][0]["columns"]
    result = check(plan)
    assert result.valid  # advisory, not blocking
    assert rule_hits(result, 2, severity="WARNING")


# ── Rules 3 & 4: event contracts ─────────────────────────────────────────

def test_rule3_consumed_event_without_publisher():
    plan = plan_copy()
    plan["features"][1]["consumes"][0]["event"] = "order.ghost"
    plan["flows"][0]["links"][0]["consumes"] = "order.ghost"
    assert rule_hits(check(plan), 3)


def test_rule3_live_event_satisfies_consumption():
    plan = plan_copy()
    plan["features"][1]["consumes"][0]["event"] = "user.created"
    plan["features"][1]["consumes"][0]["requires"] = []
    plan["flows"][0]["links"][0]["consumes"] = "user.created"
    result = check(plan, LiveSnapshot(events={"user.created"}))
    assert not rule_hits(result, 3)


def test_rule4_required_key_missing_from_payload():
    plan = plan_copy()
    plan["features"][1]["consumes"][0]["requires"] = ["id", "email"]
    assert rule_hits(check(plan), 4)


# ── Rules 5 & 6: declared tests and payload models ───────────────────────

def test_rule5_feature_without_test():
    plan = plan_copy()
    plan["features"][0]["test"] = None
    assert rule_hits(check(plan), 5)


def test_rule6_publish_without_model():
    plan = plan_copy()
    plan["features"][0]["publishes"][0]["model"] = None
    assert rule_hits(check(plan), 6)


# ── Rule 7: links cover consumptions; rpc checklist ──────────────────────

def test_rule7_consumption_missing_from_flows():
    plan = plan_copy()
    plan["flows"][0]["links"] = []
    plan["flows"][0]["sad_path_test"] = None  # no declared failures left
    assert rule_hits(check(plan), 7)


def test_rule7_rpc_link_without_timeout_decision():
    plan = plan_copy()
    plan["flows"][0]["rpc_links"] = [{"request": "user.validate", "caller": "CreateOrderPlugin"}]
    assert rule_hits(check(plan), 7)


def test_rule7_rpc_link_fully_declared():
    plan = plan_copy()
    plan["flows"][0]["rpc_links"] = [
        {"request": "user.validate", "caller": "CreateOrderPlugin",
         "timeout": 5, "on_timeout": "respond 503, create nothing"}
    ]
    live = LiveSnapshot(events={"user.validate"})
    assert not rule_hits(check(plan, live), 7)


# ── Rule 8: e2e chain test ───────────────────────────────────────────────

def test_rule8_flow_without_e2e_test():
    plan = plan_copy()
    plan["flows"][0]["e2e_test"] = None
    assert rule_hits(check(plan), 8)


# ── Rule 9: idempotency and its proof ────────────────────────────────────

def test_rule9_retries_without_idempotency():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["idempotent"] = False
    plan["flows"][0]["links"][0]["idempotency_test"] = None
    assert rule_hits(check(plan), 9)


def test_rule9_durable_flow_forces_idempotency_even_without_retries():
    plan = plan_copy()
    plan["flows"][0]["durability"] = "durable"
    plan["flows"][0]["links"][0]["retries"] = 0
    plan["flows"][0]["links"][0]["idempotent"] = False
    plan["flows"][0]["links"][0]["idempotency_test"] = None
    plan["flows"][0]["sad_path_test"] = None  # retries=0, no other failure declared
    result = check(plan, LiveSnapshot(driver="sqlite"))
    assert rule_hits(result, 9)


def test_rule9_idempotent_claim_needs_proof():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["idempotency_test"] = None
    assert rule_hits(check(plan), 9)


# ── Rule 10: dlq_watcher must resolve ────────────────────────────────────

def test_rule10_dlq_watcher_unresolved():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["dlq_watcher"] = "GhostWatcherPlugin"
    assert rule_hits(check(plan), 10)


def test_rule10_dlq_watcher_in_plan():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["dlq_watcher"] = "OrderDlqWatcherPlugin"
    plan["features"].append(
        {
            "plugin": "OrderDlqWatcherPlugin",
            "file": "domains/orders/plugins/order_dlq_watcher_plugin.py",
            "function": "Persist dead-lettered order events for reprocessing",
            "route": None,
            "publishes": [],
            "consumes": [{"event": "_dlq.order.created", "requires": []}],
            "test": "tests/test_order_dlq_watcher.py",
        }
    )
    plan["flows"][0]["links"].append(
        {"consumes": "_dlq.order.created", "consumer": "OrderDlqWatcherPlugin"}
    )
    result = check(plan)
    assert not rule_hits(result, 10)
    # _dlq.* is published by the bus itself — consuming it needs no plan publisher
    assert not rule_hits(result, 3)


def test_rule10_dlq_watcher_live():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["dlq_watcher"] = "LiveWatcherPlugin"
    live = LiveSnapshot(
        subscribers={"_dlq.order.created": ["LiveWatcherPlugin.on_dlq"]}
    )
    assert not rule_hits(check(plan, live), 10)


# ── Rule 11: compensation must be published and consumed ─────────────────

def test_rule11_compensation_not_published():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["compensation"] = "order.rollback"
    assert rule_hits(check(plan), 11)


def test_rule11_compensation_published_and_consumed():
    plan = plan_copy()
    plan["flows"][0]["links"][0]["compensation"] = "order.rollback"
    plan["features"][1]["publishes"].append(
        {"event": "order.rollback", "model": "OrderRollbackPayload",
         "payload": {"id": "int"}}
    )
    plan["features"][0]["consumes"].append({"event": "order.rollback", "requires": ["id"]})
    plan["flows"][0]["links"].append(
        {"consumes": "order.rollback", "consumer": "CreateOrderPlugin"}
    )
    assert not rule_hits(check(plan), 11)


# ── Rule 12: declared failures need a sad-path test ──────────────────────

def test_rule12_retries_without_sad_path_test():
    plan = plan_copy()
    plan["flows"][0]["sad_path_test"] = None
    assert rule_hits(check(plan), 12)


# ── Rule 13: durability vs live driver (advisory) ────────────────────────

def test_rule13_durable_flow_on_ephemeral_driver_warns():
    plan = plan_copy()
    plan["flows"][0]["durability"] = "durable"
    result = check(plan, LiveSnapshot(driver="in_process"))
    assert result.valid  # warning, not error
    assert rule_hits(result, 13, "WARNING")


def test_rule13_durable_flow_on_durable_driver_is_silent():
    plan = plan_copy()
    plan["flows"][0]["durability"] = "durable"
    result = check(plan, LiveSnapshot(driver="sqlite"))
    assert not rule_hits(result, 13, "WARNING")


# ── Rule 14: db contract respects table ownership ────────────────────────

def test_rule14_cross_domain_table_access():
    plan = plan_copy()
    plan["features"][0]["db"]["reads"] = ["users"]
    live = LiveSnapshot(tables={"users": "users"})
    assert rule_hits(check(plan, live), 14)


def test_rule14_table_declared_nowhere():
    plan = plan_copy()
    plan["features"][0]["db"]["writes"] = ["orders", "phantom_table"]
    assert rule_hits(check(plan), 14)


# ── Endpoint: input parsing and schema errors ────────────────────────────

def make_plugin():
    container = MagicMock()
    container.registry.get_domain_metadata.return_value = {}
    plugin = PlanValidatorPlugin(container=container, http=MagicMock(), logger=MagicMock())
    plugin._live_snapshot = lambda: LiveSnapshot()
    return plugin


@pytest.mark.anyio
async def test_endpoint_accepts_json_with_root_key():
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan": {"plan": plan_copy()}})
    assert result["success"] is True
    assert result["data"]["valid"] is True


@pytest.mark.anyio
async def test_endpoint_accepts_yaml():
    yaml_doc = """
plan:
  domain: ping
  features:
    - plugin: PingPlugin
      file: domains/ping/plugins/ping_plugin.py
      route: { method: GET, path: /ping }
      test: tests/test_ping.py
"""
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan_yaml": yaml_doc})
    assert result["success"] is True
    assert result["data"]["valid"] is True


@pytest.mark.anyio
async def test_endpoint_schema_errors_reported_as_rule_zero():
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan": {"features": [{"file": "x.py"}]}})
    assert result["success"] is True
    assert result["data"]["valid"] is False
    assert all(err["rule"] == 0 for err in result["data"]["errors"])


@pytest.mark.anyio
async def test_endpoint_rejects_missing_input():
    plugin = make_plugin()
    result = await plugin.validate_plan({})
    assert result["success"] is False
