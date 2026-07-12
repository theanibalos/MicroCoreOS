"""
POST /system/plan/validate — the executable form of the 14 plan validity
rules in docs/PARALLEL_DEVELOPMENT.md ("Formal plan format").

The orchestrator sends the formal plan (YAML or JSON) BEFORE dispatching any
agent; the response separates ERRORS (the plan is invalid — fix the plan,
never patch it in code) from WARNINGS (advisory, e.g. a durable flow while
the live driver is in_process).

Cross-checks against the live system reuse the sanctioned introspection
precedents: routes via AST scan of plugin sources (ContextTool pattern),
tables via domains/*/migrations/*.sql, published events via the registry
metadata the EventContractLinterPlugin records at boot, live subscribers via
the event bus.
"""
import ast
import os
import re
from typing import Optional, Literal
from pydantic import BaseModel, ValidationError
from core.base_plugin import BasePlugin

try:
    import yaml
except ImportError:  # YAML input becomes unavailable; JSON still works
    yaml = None


# ── Plan schema (format v3) ────────────────────────────────────────────────

class PlanRoute(BaseModel):
    method: str
    path: str


class PlanMigration(BaseModel):
    file: str
    tables: list[str] = []


class PlanPhase0(BaseModel):
    migrations: list[PlanMigration] = []
    models: list[str] = []
    tools: list[str] = []


class PlanDbContract(BaseModel):
    reads: list[str] = []
    writes: list[str] = []


class PlanPublish(BaseModel):
    event: str
    model: Optional[str] = None
    payload: dict = {}


class PlanConsume(BaseModel):
    event: str
    requires: list[str] = []


class PlanFeature(BaseModel):
    plugin: str
    file: str
    function: str = ""
    route: Optional[PlanRoute] = None
    db: Optional[PlanDbContract] = None
    publishes: list[PlanPublish] = []
    consumes: list[PlanConsume] = []
    mocks: list[str] = []
    test: Optional[str] = None


class PlanLink(BaseModel):
    consumes: str
    consumer: str
    retries: int = 0
    backoff: float = 0.5
    idempotent: bool = False
    idempotency_test: Optional[str] = None
    dlq_watcher: Optional[str] = None
    atomic_with_db: bool = False
    compensation: Optional[str] = None


class PlanRpcLink(BaseModel):
    request: str
    caller: str = ""
    timeout: Optional[float] = None
    on_timeout: Optional[str] = None


class PlanFlow(BaseModel):
    name: str
    durability: Literal["ephemeral", "durable"] = "ephemeral"
    happy_path: str = ""
    e2e_test: Optional[str] = None
    sad_path_test: Optional[str] = None
    links: list[PlanLink] = []
    rpc_links: list[PlanRpcLink] = []


class Plan(BaseModel):
    domain: Optional[str] = None
    phase_0: PlanPhase0 = PlanPhase0()
    features: list[PlanFeature] = []
    flows: list[PlanFlow] = []


# ── Request / response schemas ─────────────────────────────────────────────

class ValidatePlanRequest(BaseModel):
    plan: Optional[dict] = None       # the plan as JSON (with or without the "plan:" root key)
    plan_yaml: Optional[str] = None   # or the raw YAML document


class PlanViolation(BaseModel):
    rule: int
    severity: str                     # ERROR | WARNING
    where: str = ""
    detail: str


class ValidatePlanData(BaseModel):
    valid: bool
    errors: list[PlanViolation] = []
    warnings: list[PlanViolation] = []


class ValidatePlanResponse(BaseModel):
    success: bool
    data: Optional[ValidatePlanData] = None
    error: Optional[str] = None


# ── Live system snapshot ───────────────────────────────────────────────────

DURABLE_DRIVERS = {"sqlite", "redis_streams", "rabbitmq", "kafka"}

CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)", re.IGNORECASE
)


class LiveSnapshot:
    """What the running system (and the repo on disk) already occupies."""

    def __init__(self, routes=None, tables=None, events=None, subscribers=None,
                 driver="in_process"):
        self.routes: dict[str, str] = routes or {}         # "METHOD /path" -> source file
        self.tables: dict[str, str] = tables or {}         # table -> owning domain
        self.events: set[str] = events or set()            # events published live
        self.subscribers: dict[str, list] = subscribers or {}  # event -> handler names
        self.driver: str = driver


def scan_live_routes(domains_dir: str = "domains") -> dict[str, str]:
    """AST scan of every plugin source for add_endpoint(path, method) calls."""
    routes: dict[str, str] = {}
    if not os.path.isdir(domains_dir):
        return routes
    for domain in sorted(os.listdir(domains_dir)):
        plugins_dir = os.path.join(domains_dir, domain, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        for filename in sorted(os.listdir(plugins_dir)):
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(plugins_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr != "add_endpoint":
                    continue
                path, method = None, None
                if len(node.args) >= 2:
                    if isinstance(node.args[0], ast.Constant): path = node.args[0].value
                    if isinstance(node.args[1], ast.Constant): method = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "path" and isinstance(kw.value, ast.Constant): path = kw.value.value
                    if kw.arg == "method" and isinstance(kw.value, ast.Constant): method = kw.value.value
                if path and method:
                    routes[f"{method.upper()} {path}"] = filepath
    return routes


def scan_live_tables(domains_dir: str = "domains") -> dict[str, str]:
    """CREATE TABLE statements in every domain's migrations -> table ownership."""
    tables: dict[str, str] = {}
    if not os.path.isdir(domains_dir):
        return tables
    for domain in sorted(os.listdir(domains_dir)):
        migrations_dir = os.path.join(domains_dir, domain, "migrations")
        if not os.path.isdir(migrations_dir):
            continue
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith(".sql"):
                continue
            try:
                with open(os.path.join(migrations_dir, filename), "r", encoding="utf-8") as f:
                    sql = f.read()
            except Exception:
                continue
            for table in CREATE_TABLE_RE.findall(sql):
                tables.setdefault(table, domain)
    return tables


# ── The validator (pure — no I/O, fully testable) ──────────────────────────

class PlanValidator:
    def __init__(self, plan: Plan, live: LiveSnapshot):
        self.plan = plan
        self.live = live
        self.errors: list[PlanViolation] = []
        self.warnings: list[PlanViolation] = []
        # event -> list of payload dicts declared by in-plan publishers
        self.plan_payloads: dict[str, list[dict]] = {}
        for feature in plan.features:
            for pub in feature.publishes:
                self.plan_payloads.setdefault(pub.event, []).append(pub.payload)

    def validate(self) -> ValidatePlanData:
        self._rule_1_namespace_collisions()
        self._rule_2_table_ownership()
        self._rules_3_4_event_contracts()
        self._rule_5_feature_tests()
        self._rule_6_payload_models()
        self._rule_7_links_cover_consumptions()
        self._rule_8_e2e_tests()
        self._rules_9_12_sad_path_checklist()
        self._rule_13_durability_vs_driver()
        self._rule_14_db_contract_ownership()
        return ValidatePlanData(
            valid=not self.errors, errors=self.errors, warnings=self.warnings
        )

    # rule 1 — no two features share file/route/plugin; no live route collision
    def _rule_1_namespace_collisions(self):
        seen: dict[str, dict[str, str]] = {"file": {}, "route": {}, "plugin": {}}
        for feature in self.plan.features:
            claims = {"file": feature.file, "plugin": feature.plugin}
            if feature.route:
                claims["route"] = f"{feature.route.method.upper()} {feature.route.path}"
            for kind, value in claims.items():
                owner = seen[kind].get(value)
                if owner:
                    self._error(1, feature.plugin,
                                f"{kind} '{value}' already claimed by feature '{owner}'")
                else:
                    seen[kind][value] = feature.plugin
            if self._feature_domain(feature) is None:
                self._error(1, feature.plugin,
                            f"file '{feature.file}' must live in domains/{{domain}}/plugins/")
            route_key = claims.get("route")
            if route_key and route_key in self.live.routes \
                    and self.live.routes[route_key] != feature.file:
                # live collision is advisory: it may be a legitimate evolution
                # of an existing feature that moved files — the boot linter is
                # the hard backstop
                self._warn(1, feature.plugin,
                           f"route '{route_key}' is already served live by "
                           f"{self.live.routes[route_key]}")

    # rule 2 — unique table declarations, in the plan and across live domains
    def _rule_2_table_ownership(self):
        declared: dict[str, str] = {}
        for migration in self.plan.phase_0.migrations:
            domain = migration.file.split("/")[0] if "/" in migration.file else None
            for table in migration.tables:
                if table in declared and declared[table] != migration.file:
                    self._error(2, migration.file,
                                f"table '{table}' already declared by {declared[table]}")
                declared.setdefault(table, migration.file)
                live_owner = self.live.tables.get(table)
                if live_owner and domain and live_owner != domain:
                    self._error(2, migration.file,
                                f"table '{table}' is already owned by domain '{live_owner}'")

    # rule 3 — every consumed event has a publisher (plan or live); events the
    #          bus itself publishes (_dlq.*, system.subscriber.dropped) are exempt
    # rule 4 — every required key exists in every in-plan publisher's payload
    BUS_PUBLISHED = ("_dlq.", "system.subscriber.dropped")

    def _rules_3_4_event_contracts(self):
        for feature in self.plan.features:
            for consume in feature.consumes:
                if consume.event.startswith(self.BUS_PUBLISHED):
                    continue
                publishers = self.plan_payloads.get(consume.event)
                if publishers is None and consume.event not in self.live.events:
                    self._error(3, feature.plugin,
                                f"consumed event '{consume.event}' has no publisher "
                                f"in the plan or the live system")
                    continue
                for payload in publishers or []:
                    missing = [k for k in consume.requires if k not in payload]
                    if missing:
                        self._error(4, feature.plugin,
                                    f"event '{consume.event}' payload lacks required "
                                    f"keys {missing}")

    # rule 5 — every feature has a test
    def _rule_5_feature_tests(self):
        for feature in self.plan.features:
            if not feature.test:
                self._error(5, feature.plugin, "feature has no 'test' file declared")

    # rule 6 — every publish names its payload model
    def _rule_6_payload_models(self):
        for feature in self.plan.features:
            for pub in feature.publishes:
                if not pub.model:
                    self._error(6, feature.plugin,
                                f"published event '{pub.event}' names no payload model")

    # rule 7 — every (event, consumer) consumption appears as a flow link,
    #          and every declared rpc_link answers timeout + on_timeout
    def _rule_7_links_cover_consumptions(self):
        linked = {(link.consumes, link.consumer)
                  for flow in self.plan.flows for link in flow.links}
        for feature in self.plan.features:
            for consume in feature.consumes:
                if (consume.event, feature.plugin) not in linked:
                    self._error(7, feature.plugin,
                                f"consumption of '{consume.event}' appears in no "
                                f"flow's links — its sad path is undecided")
        for flow in self.plan.flows:
            for rpc in flow.rpc_links:
                if rpc.timeout is None or not rpc.on_timeout:
                    self._error(7, flow.name,
                                f"rpc_link '{rpc.request}' must declare timeout "
                                f"and on_timeout")

    # rule 8 — every flow has its e2e chain test
    def _rule_8_e2e_tests(self):
        for flow in self.plan.flows:
            if not flow.e2e_test:
                self._error(8, flow.name, "flow has no 'e2e_test' declared")

    # rule 9  — idempotent where retries > 0 or the flow is durable, with proof
    # rule 10 — a named dlq_watcher must consume _dlq.<event> somewhere
    # rule 11 — a compensation event must be published AND consumed in the plan
    # rule 12 — declared failures require a sad_path_test
    def _rules_9_12_sad_path_checklist(self):
        plan_consumed = {c.event for f in self.plan.features for c in f.consumes}
        for flow in self.plan.flows:
            has_declared_failure = False
            for link in flow.links:
                redelivers = link.retries > 0 or flow.durability == "durable"
                if redelivers and not link.idempotent:
                    self._error(9, flow.name,
                                f"link '{link.consumes}' → {link.consumer} can be "
                                f"re-delivered but is not declared idempotent")
                if link.idempotent and not link.idempotency_test:
                    self._error(9, flow.name,
                                f"link '{link.consumes}' → {link.consumer} declares "
                                f"idempotent: true without an idempotency_test")
                if link.dlq_watcher:
                    dlq_event = f"_dlq.{link.consumes}"
                    in_plan = any(f.plugin == link.dlq_watcher
                                  and any(c.event == dlq_event for c in f.consumes)
                                  for f in self.plan.features)
                    live_handlers = self.live.subscribers.get(dlq_event, [])
                    live = any(h.startswith(f"{link.dlq_watcher}.") for h in live_handlers)
                    if not in_plan and not live:
                        self._error(10, flow.name,
                                    f"dlq_watcher '{link.dlq_watcher}' does not consume "
                                    f"'{dlq_event}' in the plan or the live system")
                if link.compensation:
                    if link.compensation not in self.plan_payloads \
                            and link.compensation not in self.live.events:
                        self._error(11, flow.name,
                                    f"compensation event '{link.compensation}' is "
                                    f"published by no feature")
                    if link.compensation not in plan_consumed \
                            and not self.live.subscribers.get(link.compensation):
                        self._error(11, flow.name,
                                    f"compensation event '{link.compensation}' is "
                                    f"consumed by nothing — a saga with no undoer")
                if link.retries > 0 or link.dlq_watcher or link.compensation:
                    has_declared_failure = True
            if has_declared_failure and not flow.sad_path_test:
                self._error(12, flow.name,
                            "flow declares retries/DLQ/compensation but has no "
                            "sad_path_test")

    # rule 13 — durable flows need a durable transport (advisory)
    def _rule_13_durability_vs_driver(self):
        durable_flows = [f.name for f in self.plan.flows if f.durability == "durable"]
        if durable_flows and self.live.driver not in DURABLE_DRIVERS:
            self._warn(13, ", ".join(durable_flows),
                       f"flow(s) declared durable but the live driver is "
                       f"'{self.live.driver}' — in-flight events die with the "
                       f"process (set EVENT_BUS_DRIVER=sqlite or redis_streams)")

    # rule 14 — a feature's db contract only touches tables its domain owns
    def _rule_14_db_contract_ownership(self):
        plan_ownership: dict[str, str] = {}
        for migration in self.plan.phase_0.migrations:
            domain = migration.file.split("/")[0] if "/" in migration.file else None
            for table in migration.tables:
                if domain:
                    plan_ownership.setdefault(table, domain)
        for feature in self.plan.features:
            if not feature.db:
                continue
            domain = self._feature_domain(feature)
            if domain is None:
                continue  # already reported by rule 1
            for table in feature.db.reads + feature.db.writes:
                owner = plan_ownership.get(table) or self.live.tables.get(table)
                if owner is None:
                    self._error(14, feature.plugin,
                                f"table '{table}' is declared by no migration "
                                f"(plan or live)")
                elif owner != domain:
                    self._error(14, feature.plugin,
                                f"table '{table}' belongs to domain '{owner}' — "
                                f"cross-domain table access is forbidden, "
                                f"communicate via events")

    @staticmethod
    def _feature_domain(feature: PlanFeature) -> Optional[str]:
        parts = feature.file.split("/")
        if len(parts) >= 4 and parts[0] == "domains" and parts[2] == "plugins":
            return parts[1]
        return None

    def _error(self, rule: int, where: str, detail: str):
        self.errors.append(PlanViolation(rule=rule, severity="ERROR",
                                         where=where, detail=detail))

    def _warn(self, rule: int, where: str, detail: str):
        self.warnings.append(PlanViolation(rule=rule, severity="WARNING",
                                           where=where, detail=detail))


# ── The plugin ─────────────────────────────────────────────────────────────

class PlanValidatorPlugin(BasePlugin):
    def __init__(self, container, http, logger):
        self.container = container
        self.registry = container.registry
        self.http = http
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/plan/validate", "POST", self.validate_plan,
            tags=["System"],
            request_model=ValidatePlanRequest,
            response_model=ValidatePlanResponse,
        )

    async def validate_plan(self, data: dict, context=None):
        try:
            plan_dict, parse_error = self._parse_plan_input(data)
            if parse_error:
                return {"success": False, "error": parse_error}
            try:
                plan = Plan(**plan_dict)
            except ValidationError as e:
                schema_errors = [
                    PlanViolation(
                        rule=0, severity="ERROR",
                        where=".".join(str(loc) for loc in err["loc"]),
                        detail=err["msg"],
                    ).model_dump()
                    for err in e.errors()
                ]
                return {"success": True,
                        "data": {"valid": False, "errors": schema_errors,
                                 "warnings": []}}
            result = PlanValidator(plan, self._live_snapshot()).validate()
            return {"success": True, "data": result.model_dump()}
        except Exception as e:
            self.logger.error(f"[PlanValidator] Validation crashed: {e}")
            return {"success": False, "error": "Plan validation failed"}

    def _parse_plan_input(self, data: dict):
        plan_dict = data.get("plan")
        plan_yaml = data.get("plan_yaml")
        if plan_dict is None and plan_yaml:
            if yaml is None:
                return None, "YAML support unavailable — send the plan as JSON in 'plan'"
            try:
                plan_dict = yaml.safe_load(plan_yaml)
            except Exception:
                return None, "plan_yaml is not valid YAML"
        if not isinstance(plan_dict, dict):
            return None, "Provide the plan in 'plan' (JSON) or 'plan_yaml' (YAML)"
        # accept both the bare plan and the documented "plan:" root key
        if set(plan_dict.keys()) == {"plan"} and isinstance(plan_dict["plan"], dict):
            plan_dict = plan_dict["plan"]
        return plan_dict, None

    def _live_snapshot(self) -> LiveSnapshot:
        events: set[str] = set()
        meta = self.registry.get_domain_metadata().get("devtools", {})
        for entry in meta.get("event_payload_models", []):
            events.add(entry["event"])
        subscribers: dict[str, list] = {}
        try:
            bus = self.container.get("event_bus")
            if bus is not None:
                subscribers = bus.get_subscribers()
                events.update(subscribers.keys())
        except Exception as e:
            self.logger.warning(f"[PlanValidator] No event bus snapshot: {e}")
        return LiveSnapshot(
            routes=scan_live_routes(),
            tables=scan_live_tables(),
            events=events,
            subscribers=subscribers,
            driver=os.getenv("EVENT_BUS_DRIVER", "in_process"),
        )
