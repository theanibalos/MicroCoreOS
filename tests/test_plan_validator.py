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
    "engine": "sqlite",          # declared because phase_0 has migrations (rule 2)
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


# ── Rule 15: checklist covers every declared task (advisory) ─────────────

def check_with_checklist(plan_dict, checklist):
    return PlanValidator(Plan(**plan_dict), LiveSnapshot(),
                         checklist=checklist).validate()


def test_rule15_full_coverage_is_silent():
    checklist = "\n".join(f"- [ ] `{path}`" for path in [
        "orders/001_create_orders.sql",
        "domains/orders/models/order.py",
        "domains/orders/plugins/create_order_plugin.py",
        "tests/test_create_order.py",
        "domains/orders/plugins/order_notifier_plugin.py",
        "tests/test_order_notifier.py",
        "tests/test_order_lifecycle_chain.py",
        "tests/test_order_lifecycle_dlq.py",
    ])
    result = check_with_checklist(plan_copy(), checklist)
    assert rule_hits(result, 15, "WARNING") == []


def test_rule15_missing_task_warns_but_stays_valid():
    checklist = "- [ ] `domains/orders/plugins/create_order_plugin.py`"
    result = check_with_checklist(plan_copy(), checklist)
    warnings = rule_hits(result, 15, "WARNING")
    assert any("order_notifier_plugin.py" in w.detail for w in warnings)
    assert result.valid  # advisory only — never invalidates the plan


def test_rule15_basename_match_counts_as_covered():
    # the checklist may use different path roots — basenames still match
    checklist = "- [ ] Task P1: create_order_plugin.py and test_create_order.py"
    result = check_with_checklist(plan_copy(), checklist)
    flagged = [w.detail for w in rule_hits(result, 15, "WARNING")]
    assert not any("create_order_plugin.py" in d or
                   "'tests/test_create_order.py'" in d for d in flagged)


def test_rule15_unrelated_checklist_is_skipped():
    checklist = "- [ ] `domains/billing/plugins/invoice_plugin.py`"
    result = check_with_checklist(plan_copy(), checklist)
    assert rule_hits(result, 15, "WARNING") == []


def test_rule15_no_checklist_is_skipped():
    assert rule_hits(check(plan_copy()), 15, "WARNING") == []


# ── Endpoint: input parsing and schema errors ────────────────────────────

def make_plugin():
    container = MagicMock()
    container.registry.get_domain_metadata.return_value = {}
    plugin = PlanValidatorPlugin(container=container, http=MagicMock(), logger=MagicMock())
    plugin._live_snapshot = lambda: LiveSnapshot()
    plugin._read_checklist = lambda: None  # hermetic: ignore the repo's real checklist
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


@pytest.mark.anyio
async def test_endpoint_reads_active_checklist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "active_plan.md").write_text(
        "- [ ] `domains/orders/plugins/create_order_plugin.py`",
        encoding="utf-8",
    )
    container = MagicMock()
    container.registry.get_domain_metadata.return_value = {}
    plugin = PlanValidatorPlugin(container=container, http=MagicMock(),
                                 logger=MagicMock())
    plugin._live_snapshot = lambda: LiveSnapshot()
    result = await plugin.validate_plan({"plan": plan_copy()})
    assert any(w["rule"] == 15 for w in result["data"]["warnings"])


# --- YAML the plan authors actually copy ------------------------------------
# Every {param} route and Optional[...] type is a flow-mapping parse error when
# unquoted. These two tests keep a broken example from ever teaching the pattern
# again, and keep the parse error pointing at the offending line.

@pytest.mark.anyio
async def test_endpoint_accepts_yaml_with_param_route_and_optional():
    yaml_doc = """
plan:
  domain: tweets
  features:
    - plugin: GetTweetPlugin
      file: domains/tweets/plugins/get_tweet_plugin.py
      route: { method: GET, path: "/tweets/{tweet_id}" }
      publishes:
        - event: tweet.read
          model: TweetReadPayload
          payload: { id: int, avatar_url: "Optional[str]" }
      test: tests/test_get_tweet.py
"""
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan_yaml": yaml_doc})
    assert result["success"] is True
    assert result["data"]["valid"] is True


@pytest.mark.anyio
async def test_endpoint_yaml_error_reports_position():
    yaml_doc = "plan:\n  domain: tweets\n  x: { path: /tweets/{tweet_id} }\n"
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan_yaml": yaml_doc})
    assert result["success"] is False
    assert "line 3" in result["error"]
    assert "column" in result["error"]


def test_repo_yaml_examples_parse():
    """The examples the planner AI copies must themselves be valid YAML."""
    import re
    from pathlib import Path

    yaml_mod = pytest.importorskip("yaml")
    root = Path(__file__).resolve().parent.parent
    sources = [root / "plans" / "active_plan.yaml"]
    docs = [root / "docs" / "PARALLEL_DEVELOPMENT.md",
            *(root / ".agent" / "workflows").glob("*.md")]

    for path in sources:
        yaml_mod.safe_load(path.read_text(encoding="utf-8"))

    blocks = 0
    for path in docs:
        if not path.exists():
            continue
        for block in re.findall(r"```yaml\n(.*?)```", path.read_text(encoding="utf-8"),
                                re.DOTALL):
            blocks += 1
            try:
                yaml_mod.safe_load(block)
            except Exception as e:
                pytest.fail(f"{path.name}: invalid YAML example — {e}")
    assert blocks, "no YAML examples found — the guard would pass vacuously"


# --- shape warnings: the plan that validates because it says nothing ---------

@pytest.mark.anyio
async def test_endpoint_warns_on_unknown_root_key():
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan": {"domain": "t", "feature": [
        {"plugin": "P", "file": "domains/t/plugins/p.py", "test": "tests/p.py"}]}})
    warnings = result["data"]["warnings"]
    assert result["data"]["valid"] is True          # advisory, never a blocker
    assert any(w["rule"] == 0 and "feature" in w["detail"] for w in warnings)
    assert any(w["rule"] == 0 and "nothing to dispatch" in w["detail"]
               for w in warnings)


@pytest.mark.anyio
async def test_endpoint_warns_on_unknown_nested_key():
    plugin = make_plugin()
    plan = plan_copy()
    plan["features"][0]["mock"] = ["db"]            # typo for 'mocks'
    plan["flows"][0]["links"][0]["retry"] = 3       # typo for 'retries'
    result = await plugin.validate_plan({"plan": plan})
    warnings = result["data"]["warnings"]
    assert any(w["where"] == "plan.features[0]" and "'mock'" in w["detail"]
               for w in warnings)
    assert any(w["where"] == "plan.flows[0].links[0]" and "'retry'" in w["detail"]
               for w in warnings)


@pytest.mark.anyio
async def test_valid_plan_has_no_shape_warnings():
    plugin = make_plugin()
    result = await plugin.validate_plan({"plan": plan_copy()})
    assert not [w for w in result["data"]["warnings"] if w["rule"] == 0]


# --- rule 16: the language section (ROADMAP Issue 38) -----------------------

ORDERS_MIGRATION = {
    "file": "orders/001_create_orders.sql",
    "tables": ["orders"],
    "columns": {"orders": {"id": "INTEGER PRIMARY KEY", "user_id": "INT NOT NULL",
                           "total": "FLOAT NOT NULL", "status": "TEXT",
                           "payment_token": "TEXT"}},
}


def language_plan(*entries, migrations=(ORDERS_MIGRATION,)):
    return {"domain": "orders", "phase_0": {"migrations": list(migrations)},
            "language": list(entries)}


def test_rule_16_new_entity_matching_columns_is_valid():
    result = check(language_plan({
        "model": "OrderEntity", "op": "new", "domain": "orders", "table": "orders",
        "fields": {"id": "int?", "user_id": "int", "total": "float", "status": "str"},
        "internal": ["payment_token"],
    }))
    assert result.valid
    assert not [w for w in result.warnings if w.rule == 16]


def test_rule_16_field_naming_no_column_is_an_error():
    result = check(language_plan({
        "model": "OrderEntity", "op": "new", "table": "orders",
        "fields": {"id": "int?", "client_id": "int"},   # column is user_id
    }))
    assert not result.valid
    assert any(e.rule == 16 and "client_id" in e.detail for e in result.errors)


def test_rule_16_type_projection_is_free():
    """roles is TEXT on disk and list[str] in the domain — same NAME, different type."""
    result = check(language_plan(
        {"model": "UserEntity", "op": "new", "table": "users",
         "fields": {"id": "int?", "roles": "list[str]"}},
        migrations=({"file": "users/001.sql", "tables": ["users"],
                     "columns": {"users": {"id": "INTEGER PRIMARY KEY", "roles": "TEXT"}}},),
    ))
    assert result.valid


def test_rule_16_rename_without_breaking_is_an_error():
    result = check(language_plan({
        "model": "OrderEntity", "op": "rename_field", "from": "client_id",
        "to": "user_id", "affects": ["GET /orders"], "reason": "the domain says user",
    }))
    assert not result.valid
    assert any(e.rule == 16 and "breaking: true" in e.detail for e in result.errors)


def test_rule_16_rename_with_breaking_is_valid():
    result = check(language_plan({
        "model": "OrderEntity", "op": "rename_field", "from": "client_id",
        "to": "user_id", "breaking": True, "affects": ["GET /orders", "POST /orders"],
        "reason": "the domain says user, never client",
    }))
    assert result.valid


def test_rule_16_breaking_change_without_blast_radius_warns():
    result = check(language_plan({
        "model": "UserEntity", "op": "remove_field", "field": "legacy_code",
        "breaking": True,
    }))
    assert result.valid                              # advisory, not a blocker
    assert any(w.rule == 16 and "affects" in w.detail for w in result.warnings)
    assert any(w.rule == 16 and "reason" in w.detail for w in result.warnings)


def test_rule_16_add_field_must_match_its_column_name():
    result = check(language_plan({
        "model": "OrderEntity", "op": "add_field", "fields": {"note": "str?"},
        "backed_by": "orders.notes",                 # column is 'notes', field is 'note'
    }))
    assert not result.valid
    assert any(e.rule == 16 and "must equal its column" in e.detail
               for e in result.errors)


def test_rule_16_add_field_backed_by_unknown_column_is_an_error():
    result = check(language_plan({
        "model": "OrderEntity", "op": "add_field", "fields": {"phone": "str?"},
        "backed_by": "orders.phone",                 # no such column anywhere
    }))
    assert not result.valid
    assert any(e.rule == 16 and "names no existing column" in e.detail
               for e in result.errors)


def test_rule_16_unknown_table_warns_instead_of_inventing_an_error():
    result = check({"domain": "orders", "language": [{
        "model": "OrderEntity", "op": "new", "table": "orders",
        "fields": {"user_id": "int"}}]})             # no migrations, no live schema
    assert result.valid
    assert any(w.rule == 16 and "cannot be checked" in w.detail
               for w in result.warnings)


def test_rule_16_resolves_against_the_live_schema():
    live = LiveSnapshot(tables={"orders": "orders"},
                        columns={"orders": {"id", "user_id"}})
    result = check({"domain": "orders", "language": [{
        "model": "OrderEntity", "op": "new", "table": "orders",
        "fields": {"user_id": "int", "client_id": "int"}}]}, live=live)
    assert not result.valid
    assert any(e.rule == 16 and "client_id" in e.detail for e in result.errors)


def test_language_from_alias_is_not_an_unknown_key():
    """'from' is a Python keyword, so the field is aliased — both spellings are input."""
    from domains.devtools.plugins.plan_validator_plugin import unknown_plan_keys
    raw = {"domain": "orders", "language": [
        {"model": "OrderEntity", "op": "rename_field", "from": "client_id",
         "to": "user_id", "breaking": True}]}
    assert unknown_plan_keys(raw) == []


def test_column_scanner_reads_real_create_table_bodies():
    """Rule 16 resolves names against columns, so the SQL parse is load-bearing."""
    from domains.devtools.plugins.plan_validator_plugin import _columns_of
    sql = """
    CREATE TABLE IF NOT EXISTS "orders" (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INT NOT NULL,
        total DECIMAL(10, 2) NOT NULL,          -- the comma here is not a separator
        status TEXT DEFAULT 'pending',
        note TEXT DEFAULT '-- not a comment',   /* nor is this */
        PRIMARY KEY (id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE (user_id, status),
        CHECK (total > 0)
    );
    CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
    """
    assert _columns_of(sql, "orders") == {"id", "user_id", "total", "status", "note"}
    assert _columns_of(sql, "users") == {"id", "email"}
    assert _columns_of(sql, "ghost") == set()
    assert _columns_of(sql, "order") == set()      # no prefix confusion with 'orders'


# --- engine: required exactly when there is SQL to write --------------------

def test_engine_declared_with_migrations_is_silent():
    plan = plan_copy()
    plan["engine"] = "sqlite"
    result = check(plan)
    assert result.valid
    assert not rule_hits(result, 2, "WARNING")


def test_migrations_without_engine_warns():
    plan = plan_copy()                                # VALID_PLAN has migrations
    plan.pop("engine", None)
    result = check(plan)
    assert result.valid                               # advisory, not blocking
    assert any("engine" in w.detail for w in rule_hits(result, 2, "WARNING"))


def test_no_migrations_means_no_engine_warning():
    """A feature-only plan writes no SQL, so 'engine' has no reader."""
    result = check({"domain": "orders", "features": [
        {"plugin": "ListOrdersPlugin",
         "file": "domains/orders/plugins/list_orders_plugin.py",
         "test": "tests/test_list_orders.py"}]})
    assert result.valid
    assert not rule_hits(result, 2, "WARNING")


@pytest.mark.anyio
async def test_engine_is_no_longer_an_unknown_key():
    """Every documented example carries `engine:` — the schema must know it."""
    plugin = make_plugin()
    plan = plan_copy()
    plan["engine"] = "sqlite"
    result = await plugin.validate_plan({"plan": plan})
    assert not [w for w in result["data"]["warnings"]
                if w["rule"] == 0 and "engine" in w["detail"]]
