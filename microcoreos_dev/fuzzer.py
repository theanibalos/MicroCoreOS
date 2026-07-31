"""Plan fuzzer — feeds microcoreos_dev.plan plans that are wrong on purpose,
in-process, and checks it answers what it should.

This used to attack POST /system/plan/validate over HTTP (`uv run main.py`
had to be listening first). That endpoint is gone — an endpoint validating
plans next to the user's business was the point of the split
(docs/DEV_PACKAGE_SPLIT.md). The rules were always pure; only the live
snapshot needed a running system, and neither pass below carries live state,
so this calls run_validation/validate_yaml directly: no server, no urllib,
no port, and an iteration that used to cost a round-trip now costs a
function call.

Two passes, because they answer different questions:

  MUTATIONS  Take a plan known to be valid, apply ONE named damage, and assert
             the expected rule fires. The oracle is the damage itself: we know
             what breaking `retries` should cost, so silence is a bug. This is
             what catches a rule that stopped firing.

  FUZZ       Throw structurally broken documents at it — wrong types, absurd
             nesting, truncated YAML, huge strings. There is no oracle for the
             verdict here, only for the CRASH: every input must come back as a
             structured answer, never an unhandled exception and never a
             stack trace. This is what catches the validator dying on input
             it did not imagine.

Usage:
  uv run python microcoreos_dev/fuzzer.py                    # both passes
  uv run python microcoreos_dev/fuzzer.py --fuzz-only --iterations 500
"""
import argparse
import copy
import json
import random
import string
import sys

from microcoreos_dev.plan import LiveSnapshot, run_validation, validate_yaml

VALID_PLAN = {
    "domain": "orders",
    "phase_0": {"migrations": [{
        "file": "orders/001_create_orders.sql",
        "tables": ["orders"],
        "columns": {"orders": {"id": "INTEGER PRIMARY KEY", "user_id": "INT NOT NULL",
                               "total": "FLOAT NOT NULL"}},
    }]},
    "language": [{
        "model": "OrderEntity", "op": "new", "table": "orders",
        "fields": {"id": "int?", "user_id": "int", "total": "float"},
    }],
    "features": [
        {"plugin": "CreateOrderPlugin",
         "file": "domains/orders/plugins/create_order_plugin.py",
         "route": {"method": "POST", "path": "/orders"},
         "db": {"writes": ["orders"], "reads": []},
         "publishes": [{"event": "order.created", "model": "OrderCreatedPayload",
                        "payload": {"id": "int", "user_id": "int"}}],
         "test": "tests/test_create_order.py"},
        {"plugin": "OrderNotifierPlugin",
         "file": "domains/orders/plugins/order_notifier_plugin.py",
         "consumes": [{"event": "order.created", "requires": ["id", "user_id"]}],
         "test": "tests/test_order_notifier.py"},
    ],
    "flows": [{
        "name": "order-lifecycle",
        "e2e_test": "tests/test_order_chain.py",
        "sad_path_test": "tests/test_order_dlq.py",
        "links": [{"consumes": "order.created", "consumer": "OrderNotifierPlugin",
                   "retries": 3, "idempotent": True,
                   "idempotency_test": "tests/test_order_notifier.py::test_twice"}],
    }],
}


# ── Mutations: (name, damage, expected rule, expected severity) ─────────────

def _dup_route(plan):
    plan["features"][1]["route"] = {"method": "POST", "path": "/orders"}

def _steal_table(plan):
    plan["phase_0"]["migrations"].append(
        {"file": "billing/002.sql", "tables": ["orders"]})

def _ghost_event(plan):
    plan["features"][1]["consumes"][0]["event"] = "order.ghost"
    plan["flows"][0]["links"][0]["consumes"] = "order.ghost"

def _missing_key(plan):
    plan["features"][1]["consumes"][0]["requires"] = ["id", "email"]

def _drop_test(plan):
    plan["features"][0]["test"] = None

def _drop_payload_model(plan):
    plan["features"][0]["publishes"][0]["model"] = None

def _retries_without_idempotency(plan):
    plan["flows"][0]["links"][0]["idempotent"] = False

def _idempotent_without_proof(plan):
    plan["flows"][0]["links"][0]["idempotency_test"] = None

def _cross_domain_write(plan):
    plan["features"][0]["db"]["writes"] = ["invoices"]

def _language_renames_a_column(plan):
    plan["language"][0]["fields"]["client_id"] = "int"

def _language_breaking_change_unmarked(plan):
    plan["language"].append({"model": "OrderEntity", "op": "rename_field",
                             "from": "client_id", "to": "user_id"})

def _typo_retries(plan):
    link = plan["flows"][0]["links"][0]
    link["retry"] = link.pop("retries")

def _typo_features(plan):
    plan["feature"] = plan.pop("features")

MUTATIONS = [
    ("duplicate route",                 _dup_route,                     1,  "ERROR"),
    ("table owned twice",               _steal_table,                   2,  "ERROR"),
    ("consumes an event nobody emits",  _ghost_event,                   3,  "ERROR"),
    ("requires a key not in payload",   _missing_key,                   4,  "ERROR"),
    ("feature without a test",          _drop_test,                     5,  "ERROR"),
    ("published event without model",   _drop_payload_model,            6,  "ERROR"),
    ("retries without idempotency",     _retries_without_idempotency,   9,  "ERROR"),
    ("idempotent without proof",        _idempotent_without_proof,      9,  "ERROR"),
    ("writes another domain's table",   _cross_domain_write,            14, "ERROR"),
    ("language field with no column",   _language_renames_a_column,     16, "ERROR"),
    ("breaking change unmarked",        _language_breaking_change_unmarked, 16, "ERROR"),
    ("typo: retry (silent downgrade)",  _typo_retries,                  0,  "WARNING"),
    ("typo: feature (empty plan)",      _typo_features,                 0,  "WARNING"),
]


# ── Fuzz payloads: no verdict oracle, only "it must not crash" ──────────────

def _rand_text(size):
    return "".join(random.choice(string.printable) for _ in range(size))

def _fuzz_payload():
    kind = random.randrange(8)
    if kind == 0:
        return {"plan_yaml": _rand_text(random.randrange(1, 400))}
    if kind == 1:                                   # truncated YAML
        doc = "plan:\n  features:\n    - plugin: P\n      route: { method: GET"
        return {"plan_yaml": doc}
    if kind == 2:                                   # wrong types everywhere
        return {"plan": {"domain": [1, 2], "features": "not a list",
                         "flows": {"nope": True}, "language": 7}}
    if kind == 3:                                   # deep nesting
        node = {"x": 1}
        for _ in range(200):
            node = {"features": [node]}
        return {"plan": node}
    if kind == 4:                                   # huge strings
        return {"plan": {"domain": "d" * 100_000,
                         "features": [{"plugin": "P", "file": "f" * 10_000}]}}
    if kind == 5:                                   # nulls in every slot
        return {"plan": {"domain": None, "phase_0": None, "features": [None],
                         "flows": [None], "language": [None]}}
    if kind == 6:                                   # YAML that parses to a scalar
        return {"plan_yaml": random.choice(["42", "just a string", "[]", "null", ""])}
    return {"plan": random.choice([[], "string", 42, None, {"plan": {"plan": {}}}])}


def check_plan(payload):
    """(status, body) — the shape the old HTTP endpoint returned, kept so the
    two passes below didn't have to change. `status` is synthetic now: 200 for
    a structured answer (valid or not), 500 for anything this call could not
    turn into one. Malformed top-level shapes (a list where the plan should
    be, a doubly-wrapped {"plan": {"plan": ...}}) are the same input parsing
    the deleted endpoint used to do — reproduced here because nothing else in
    the library does it, and a plan sent by a real caller can still be shaped
    like that.
    """
    try:
        plan_dict, plan_yaml = payload.get("plan"), payload.get("plan_yaml")
        if plan_dict is None and plan_yaml is not None:
            result, error = validate_yaml(plan_yaml, live=LiveSnapshot())
            if error:
                return 200, {"success": False, "error": error}
        else:
            if isinstance(plan_dict, dict) and set(plan_dict.keys()) == {"plan"} \
                    and isinstance(plan_dict["plan"], dict):
                plan_dict = plan_dict["plan"]
            if not isinstance(plan_dict, dict):
                return 200, {"success": False, "error":
                             "Provide the plan in 'plan' (JSON) or 'plan_yaml' (YAML)"}
            result = run_validation(plan_dict, LiveSnapshot())
        return 200, {"success": True, "data": result.model_dump()}
    except Exception as e:
        return 500, {"success": False, "error": f"{type(e).__name__}: {e}"}


def run_mutations():
    print("MUTATIONS — each damage must produce its rule\n")
    baseline_status, baseline = check_plan({"plan": copy.deepcopy(VALID_PLAN)})
    failures = 0
    if baseline_status != 200 or not baseline.get("data", {}).get("valid"):
        print(f"  !! the baseline plan is not valid — fix it first:\n     {baseline}")
        return 1
    print("  ok    baseline plan is valid, no warnings"
          if not baseline["data"]["warnings"] else
          f"  warn  baseline has warnings: {baseline['data']['warnings']}")

    for name, damage, rule, severity in MUTATIONS:
        plan = copy.deepcopy(VALID_PLAN)
        damage(plan)
        status, body = check_plan({"plan": plan})
        if status != 200 or "data" not in body:
            print(f"  FAIL  {name}: status {status} — {body}")
            failures += 1
            continue
        pool = body["data"]["errors"] if severity == "ERROR" else body["data"]["warnings"]
        if any(v["rule"] == rule for v in pool):
            print(f"  ok    {name}  ->  rule {rule} {severity}")
        else:
            print(f"  FAIL  {name}: expected rule {rule} {severity}, got "
                  f"errors={[v['rule'] for v in body['data']['errors']]} "
                  f"warnings={[v['rule'] for v in body['data']['warnings']]}")
            failures += 1
    return failures


def run_fuzz(iterations):
    print(f"\nFUZZ — {iterations} malformed documents, none may crash the validator\n")
    failures = 0
    for index in range(iterations):
        payload = _fuzz_payload()
        status, body = check_plan(payload)
        crashed = status >= 500 or (
            isinstance(body, dict) and body.get("success") is False
            and "Traceback" in str(body.get("error", "")))
        if crashed:
            failures += 1
            print(f"  CRASH on iteration {index}: status {status}\n"
                  f"    payload: {json.dumps(payload)[:300]}\n"
                  f"    body:    {str(body)[:300]}")
    print(f"  {iterations - failures}/{iterations} answered without crashing")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuzz-only", action="store_true")
    parser.add_argument("--mutations-only", action="store_true")
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()

    failures = 0
    if not args.fuzz_only:
        failures += run_mutations()
    if not args.mutations_only:
        failures += run_fuzz(args.iterations)
    print(f"\n{'FAILURES: ' + str(failures) if failures else 'All checks passed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
