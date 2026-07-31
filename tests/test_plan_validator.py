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


# ── Rule 0: the shipped template is not a plan ──────────────────────────────
#
# The template is a VALID plan — that is what makes it a useful example, and
# exactly why nothing else can tell it apart from a real one. Two consecutive
# sessions read the untouched `plans/active_plan.yaml`, found a well-formed
# plan for the example domain, and built THAT; the second did so after being
# told in its prompt to build something else.

def test_template_flag_is_an_error():
    plan = plan_copy()
    plan["template"] = True
    result = check(plan)
    assert not result.valid
    assert rule_hits(result, 0)
    assert "template" in result.errors[0].detail


def test_template_flag_short_circuits_every_other_rule():
    """One unambiguous error, not a wall of findings about someone else's domain."""
    plan = plan_copy()
    plan["template"] = True
    plan["features"][0]["test"] = ""          # would be a rule 5 error
    result = check(plan)
    assert [e.rule for e in result.errors] == [0]


def test_a_real_plan_needs_no_template_key():
    assert check(plan_copy()).valid           # VALID_PLAN never sets it


def test_template_checklist_is_an_error():
    """An all-[x] template checklist proves nothing: its paths are placeholders."""
    result = PlanValidator(
        Plan(**plan_copy()), LiveSnapshot(),
        checklist="<!-- template: true -->\n- [ ] Task D1: ...",
    ).validate()
    assert not result.valid
    assert rule_hits(result, 0)
    assert "checklist" in result.errors[0].detail


def test_the_shipped_template_files_are_actually_marked():
    """The rule is only worth having if the files it targets carry the marker."""
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    with open("plans/active_plan.yaml", encoding="utf-8") as f:
        plan_yaml = f.read()
    with open("plans/active_plan.md", encoding="utf-8") as f:
        checklist = f.read()

    result, error = validate_yaml(plan_yaml, checklist=checklist)
    assert error is None
    assert not result.valid and rule_hits(result, 0)

    # ...and the example it teaches must itself be a valid plan, or the
    # template is teaching a plan that would be rejected.
    edited = "\n".join(
        line for line in plan_yaml.splitlines()
        if not line.strip().startswith("template: true")
    )
    result, error = validate_yaml(edited, checklist=checklist.replace(
        "<!-- template: true -->", ""))
    assert error is None
    assert result.valid, result.errors


# ── `fix:` — the corrected YAML, not a description of it ────────────────────

def test_rule5_fix_names_the_missing_test_file():
    plan = plan_copy()
    plan["features"][0]["test"] = ""
    fix = rule_hits(check(plan), 5)[0].fix
    assert "tests/test_create_order.py" in fix


def test_rule6_fix_spells_the_payload_model():
    plan = plan_copy()
    plan["features"][0]["publishes"][0]["model"] = ""
    fix = rule_hits(check(plan), 6)[0].fix
    assert "model: OrderCreatedPayload" in fix


def test_rule7_fix_is_a_pasteable_flow_link():
    plan = plan_copy()
    plan["flows"] = []
    fix = rule_hits(check(plan), 7)[0].fix
    assert "links:" in fix
    assert "consumes: order.created" in fix
    assert "consumer: OrderNotifierPlugin" in fix


def test_rule8_fix_names_an_e2e_test_path():
    plan = plan_copy()
    plan["flows"][0]["e2e_test"] = ""
    assert "e2e_test: tests/" in rule_hits(check(plan), 8)[0].fix


def test_empty_route_error_explains_that_a_consumer_omits_the_key():
    """`route: {}` is not "no route" — it is a route missing method and path."""
    from domains.devtools.plugins.plan_validator_plugin import (
        offline_snapshot, run_validation,
    )
    plan = plan_copy()
    plan["features"][1]["route"] = {}
    result = run_validation(plan, LiveSnapshot())
    assert not result.valid
    assert any("OMIT the key" in (e.fix or "") for e in result.errors)


def test_unknown_consumes_keys_carry_the_requires_form():
    """`model:`/`payload:` under consumes: is the publisher's shape, copied."""
    from domains.devtools.plugins.plan_validator_plugin import run_validation

    plan = plan_copy()
    plan["features"][1]["consumes"][0]["model"] = "OrderCreatedPayload"
    result = run_validation(plan, LiveSnapshot())
    fixes = [w.fix for w in result.warnings if w.rule == 0 and w.fix]
    assert any("requires: [id, total]" in f for f in fixes)


def test_unknown_flow_steps_key_carries_the_links_form():
    from domains.devtools.plugins.plan_validator_plugin import run_validation

    plan = plan_copy()
    plan["flows"][0]["steps"] = []
    result = run_validation(plan, LiveSnapshot())
    assert any("links:" in (w.fix or "") for w in result.warnings if w.rule == 0)


# ── Offline validation: same rules, no running system ───────────────────────

def test_validate_yaml_reports_a_parse_error_with_its_position():
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    result, error = validate_yaml("plan:\n  features:\n   - a\n  - b\n")
    assert result is None
    assert "not valid YAML" in error


def test_validate_yaml_accepts_the_documented_plan_root_key():
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    result, error = validate_yaml(
        "plan:\n  domain: orders\n  features:\n"
        "    - plugin: ListOrdersPlugin\n"
        "      file: domains/orders/plugins/list_orders_plugin.py\n"
        "      test: tests/test_list_orders.py\n",
        live=LiveSnapshot(),
    )
    assert error is None and result.valid


def test_scan_live_events_reads_publishers_and_subscribers(tmp_path):
    """Offline stand-in for the live bus — without it rule 3 flags every event
    the existing domains already publish."""
    from domains.devtools.plugins.plan_validator_plugin import scan_live_events

    plugins = tmp_path / "domains" / "shop" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "a_plugin.py").write_text(
        "class ShipPlugin:\n"
        "    async def on_boot(self):\n"
        "        await self.bus.subscribe('order.paid', self.on_paid)\n"
        "    async def on_paid(self, event):\n"
        "        await self.bus.publish('order.shipped', {})\n"
    )
    published, subscribers = scan_live_events(str(tmp_path / "domains"))
    assert published == {"order.shipped"}
    assert subscribers == {"order.paid": ["ShipPlugin.on_paid"]}


def test_offline_snapshot_sees_tables_and_routes(tmp_path, monkeypatch):
    from domains.devtools.plugins.plan_validator_plugin import offline_snapshot

    domain = tmp_path / "domains" / "shop"
    (domain / "migrations").mkdir(parents=True)
    (domain / "plugins").mkdir(parents=True)
    (domain / "migrations" / "001.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER);")
    (domain / "plugins" / "list_plugin.py").write_text(
        "class ListPlugin:\n"
        "    async def on_boot(self):\n"
        "        self.http.add_endpoint('/orders', 'GET', self.execute)\n"
    )
    monkeypatch.chdir(tmp_path)
    snapshot = offline_snapshot()
    assert snapshot.tables == {"orders": "shop"}
    assert snapshot.columns["orders"] == {"id", "total"}
    assert "GET /orders" in snapshot.routes


def test_offline_and_endpoint_agree_on_the_same_plan():
    """The CLI must not be a second, drifting implementation of the rules."""
    from domains.devtools.plugins.plan_validator_plugin import (
        run_validation, validate_yaml,
    )
    import yaml as yaml_module

    plan = plan_copy()
    text = yaml_module.safe_dump({"plan": plan})
    offline, error = validate_yaml(text, live=LiveSnapshot())
    direct = run_validation(plan, LiveSnapshot())
    assert error is None
    assert offline.model_dump() == direct.model_dump()


# ── Regression corpus: a plan a real model actually wrote ───────────────────
#
# tests/corpus/qwen_twitter_plan.yaml is byte-exact output from
# Qwen3.6-35B-A3B (IQ2_XXS, thinking off), recovered from its session log.
# Getting it to validate took that session four rounds, and the model resolved
# the schema by reading ~500 lines of this file's source — the one thing the
# reading path exists to prevent. Every defect came from a shape the plan
# template did not show; each one is now answered with the YAML that fixes it.

import pathlib

CORPUS = pathlib.Path(__file__).parent / "corpus" / "qwen_twitter_plan.yaml"


def _corpus() -> str:
    return CORPUS.read_text(encoding="utf-8")


def test_corpus_round1_names_the_constraint_written_as_a_column():
    """YAML reports the line AFTER the keyless one, so the bare scanner error
    pointed at `models:` while the mistake was `UNIQUE(...)` above it."""
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    result, error = validate_yaml(_corpus())
    assert result is None
    assert "UNIQUE(follower_id, following_id)" in error
    assert "table-level constraint" in error
    assert "line 25" in error          # not the reported 26


def test_corpus_round2_names_the_unquoted_path_param():
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    text = "\n".join(l for l in _corpus().splitlines()
                     if "UNIQUE(follower_id" not in l)
    _, error = validate_yaml(text)
    assert "quote any value containing" in error
    assert '"/orders/{order_id}"' in error


def _corpus_parsable() -> str:
    """The corpus past both YAML errors — where the RULES start applying."""
    import re

    text = "\n".join(l for l in _corpus().splitlines()
                     if "UNIQUE(follower_id" not in l)
    return re.sub(r"path: (/[^ }]*\{[^ }]*\})", r'path: "\1"', text)


def test_corpus_round3_explains_that_a_consumer_omits_route():
    """`route: {}` was the model's way of saying "no route". It is a route
    missing its required method and path."""
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    result, error = validate_yaml(_corpus_parsable())
    assert error is None
    assert not result.valid
    assert any(e.where.endswith(("route.method", "route.path")) for e in result.errors)
    assert any("OMIT the key" in (e.fix or "") for e in result.errors)


def test_corpus_round4_catches_both_shapes_copied_from_publishes():
    """`consumes:` with `model:`/`payload:`, and `flows:` with `steps:` — both
    land in the unknown-key bucket, so the plan validates while declaring
    nothing. Each now carries the form that replaces it."""
    from domains.devtools.plugins.plan_validator_plugin import validate_yaml

    result, _ = validate_yaml(_corpus_parsable().replace("      route: {}\n", ""))
    fixes = [w.fix for w in result.warnings if w.rule == 0 and w.fix]
    assert any("requires: [id, total]" in f for f in fixes)      # consumes
    assert any("links:" in f for f in fixes)                     # flows
    # ...and the consumption with no link is a hard error, with a pasteable link
    rule7 = rule_hits(result, 7)
    assert rule7 and "consumer: NotificationPlugin" in rule7[0].fix


def test_the_corpus_is_the_real_thing_not_a_rewrite():
    """If someone 'tidies' the fixture, it stops being evidence."""
    text = _corpus()
    assert "domain: twitter" in text
    assert "UNIQUE(follower_id, following_id)" in text
    assert "route: {}" in text
    assert "steps:" in text
    assert "model: PostCreatedPayload" in text   # under consumes:, wrongly


# ── Rule 17: the plan must be proportional to its request ───────────────────

def test_rule17_is_silent_at_the_documented_calibration():
    """3 CRUDs plus an event chain is the reference, not a ceiling to approach."""
    plan = plan_copy()
    assert not rule_hits(check(plan), 17, "WARNING")


def test_rule17_warns_when_one_domain_swallows_the_wave():
    plan = plan_copy()
    template = plan["features"][0]
    for n in range(7):
        extra = copy.deepcopy(template)
        extra.update(plugin=f"Extra{n}Plugin",
                     file=f"domains/orders/plugins/extra{n}_plugin.py",
                     route={"method": "GET", "path": f"/extra{n}"},
                     publishes=[], test=f"tests/test_extra{n}.py")
        plan["features"].append(extra)

    warnings = rule_hits(check(plan), 17, "WARNING")

    assert warnings and "9 features in one domain" in warnings[0].detail
    assert "9 executors" in warnings[0].detail        # the cost, not a scolding
    assert "split it" in warnings[0].fix


def test_rule17_never_blocks():
    """Advisory: an oversized plan may still be the right plan."""
    plan = plan_copy()
    for n in range(9):
        extra = copy.deepcopy(plan["features"][0])
        extra.update(plugin=f"Extra{n}Plugin",
                     file=f"domains/orders/plugins/extra{n}_plugin.py",
                     route={"method": "GET", "path": f"/extra{n}"},
                     publishes=[], test=f"tests/test_extra{n}.py")
        plan["features"].append(extra)
    assert check(plan).valid


def test_rule17_counts_per_domain_not_per_plan():
    """A cross-domain plan spreads its features; that is not over-planning."""
    plan = plan_copy()
    for n in range(6):
        extra = copy.deepcopy(plan["features"][0])
        extra.update(plugin=f"Extra{n}Plugin",
                     file=f"domains/billing/plugins/extra{n}_plugin.py",
                     route={"method": "GET", "path": f"/extra{n}"},
                     publishes=[], db=None, test=f"tests/test_extra{n}.py")
        plan["features"].append(extra)
    assert not rule_hits(check(plan), 17, "WARNING")


# ── The three keys a real planner invented ─────────────────────────────────
#
# Observed, not imagined: a Qwen3.6 run against this very schema produced
# `constraints:` under a migration, and `params:`/`protected:` on features.
# All three name something real; none of them is a plan field, so each landed
# in the unknown-key bucket and was silently not validated.

@pytest.mark.parametrize("where, key, expected", [
    ("plan.phase_0.migrations[0]", "constraints", "write them in the .sql file"),
    ("plan.features[2]", "params", "part of `path:`"),
    ("plan.features[3]", "protected", "auth_validator=self.auth.validate_token"),
])
def test_invented_keys_carry_the_real_form(where, key, expected):
    from domains.devtools.plugins.plan_validator_plugin import _unknown_key_fix

    fix = _unknown_key_fix(where, key)
    assert fix and expected in fix


def test_an_unrecognised_key_simply_has_no_fix():
    """The map answers what it has seen; it must not invent guidance."""
    from domains.devtools.plugins.plan_validator_plugin import _unknown_key_fix

    assert _unknown_key_fix("plan.features[0]", "budget") is None


# ── Wholesale schema failure: a different format, not mistakes in this one ───

def test_a_handful_of_schema_errors_stays_field_by_field():
    """Few errors means the author is inside the format and slipped."""
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    plan = plan_copy()
    plan["features"][0].pop("plugin")

    result = run_validation(plan, LiveSnapshot())

    assert not result.valid
    assert not any("not the plan format" in e.detail for e in result.errors)


def test_a_wholesale_mismatch_names_the_worked_example_first():
    """Observed: a planner emitted `name/description/version` at the root with
    `phase_0` as a list. Twenty field errors invite twenty patches; the format
    was simply a different one."""
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    invented = {
        "name": "Twitter Domain",
        "phase_0": [{"file": "domains/x/migrations/001.sql",
                     "tables": [{"name": "tweets", "columns": []}]}],
        "features": [{"name": f"p{n}", "db": "tweets"} for n in range(9)],
    }

    result = run_validation(invented, LiveSnapshot())

    assert not result.valid
    first = result.errors[0]
    assert "not the plan format" in first.detail
    assert "plans/active_plan.yaml" in first.fix
    assert "Do not patch them one by one" in first.detail


# ── rule 18 — a declared `::node` must exist once its file does ────────────
#
# The hole this closes was found by building a whole plan end to end: the plan
# declared `tests/test_note_counter_plugin.py::test_double_delivery_created`,
# the executor wrote the file without that function, and `plan validate`,
# `pytest` and `GET /system/lint` were ALL green while the idempotency the plan
# promised was neither implemented nor tested.

def _plan_with_idempotency_test(nodeid):
    plan = plan_copy()
    plan["flows"] = [{
        "name": "chain",
        "e2e_test": "tests/test_chain.py",
        "sad_path_test": "tests/test_chain_dlq.py",
        "links": [{
            "consumes": plan["features"][0]["publishes"][0]["event"],
            "consumer": plan["features"][-1]["plugin"],
            "retries": 2,
            "idempotent": True,
            "idempotency_test": nodeid,
        }],
    }]
    return plan


def test_rule_18_silent_while_the_test_file_does_not_exist(tmp_path, monkeypatch):
    """Phase 2 has not run yet — that is not a defect."""
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    monkeypatch.chdir(tmp_path)
    plan = _plan_with_idempotency_test("tests/nope.py::test_double_delivery")

    result = run_validation(plan, LiveSnapshot())

    assert not any(e.rule == 18 for e in result.errors)


def test_rule_18_flags_a_file_that_exists_without_the_declared_node(tmp_path, monkeypatch):
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_something_else():\n    pass\n")
    plan = _plan_with_idempotency_test("tests/t.py::test_double_delivery")

    result = run_validation(plan, LiveSnapshot())

    err = next(e for e in result.errors if e.rule == 18)
    assert "test_double_delivery" in err.detail
    assert "pytest silently selects nothing" in err.detail
    assert "async def test_double_delivery():" in err.fix


def test_rule_18_accepts_the_node_once_it_is_written(tmp_path, monkeypatch):
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        "async def test_double_delivery():\n    pass\n"
    )
    plan = _plan_with_idempotency_test("tests/t.py::test_double_delivery")

    result = run_validation(plan, LiveSnapshot())

    assert not any(e.rule == 18 for e in result.errors)


def test_rule_18_ignores_a_plain_path_with_no_node(tmp_path, monkeypatch):
    """`tests/x.py` with no `::` makes no claim about a specific function."""
    from domains.devtools.plugins.plan_validator_plugin import (
        LiveSnapshot, run_validation,
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_x():\n    pass\n")
    plan = _plan_with_idempotency_test("tests/t.py")

    result = run_validation(plan, LiveSnapshot())

    assert not any(e.rule == 18 for e in result.errors)
