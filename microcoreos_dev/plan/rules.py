"""The plan validity rules — pure: a Plan plus a LiveSnapshot in, violations out.

The executable form of the rules in docs/PARALLEL_DEVELOPMENT.md ("Formal plan
format"). ERRORS mean the plan is invalid — fix the plan, never patch it in
code. WARNINGS are advisory: a durable flow while the live driver is
in_process is worth saying and is not a refusal.

Nothing here does I/O. `scan.py` produces the snapshot, this judges the plan
against it, and `validate_yaml` at the bottom is the seam the CLI calls.
"""
import ast
import os
import re
from typing import Optional

from pydantic import ValidationError

from microcoreos_dev.plan.schema import (
    Plan,
    PlanFeature,
    PlanLanguage,
    PlanViolation,
    ValidatePlanData,
    unknown_plan_keys,
)
from microcoreos_dev.plan.scan import (
    DURABLE_DRIVERS,
    LiveSnapshot,
    offline_snapshot,
)

try:
    import yaml
except ImportError:  # YAML input becomes unavailable; a plan dict still validates
    yaml = None


# ── Naming, for the `fix:` snippets ────────────────────────────────────────
#
# A suggestion the author has to rename before using is a suggestion they have
# to think about, which is the cost the snippet exists to remove. These
# reproduce the repo's own conventions so the emitted YAML is paste-ready.

def _snake(name: str) -> str:
    """'CreateOrderPlugin' / 'Order paid → invoice' -> 'create_order'."""
    name = re.sub(r"Plugin$", "", name.strip())
    name = re.sub(r"[^0-9A-Za-z]+", "_", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"_+", "_", name).strip("_").lower() or "feature"


def _payload_model_name(event: str) -> str:
    """'order.paid' -> 'OrderPaidPayload' (AGENTS.md rule 10's spelling)."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", event) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) + "Payload"


# ── The validator (pure — no I/O, fully testable) ──────────────────────────

class PlanValidator:
    def __init__(self, plan: Plan, live: LiveSnapshot,
                 checklist: Optional[str] = None):
        self.plan = plan
        self.live = live
        self.checklist = checklist
        self.errors: list[PlanViolation] = []
        self.warnings: list[PlanViolation] = []
        # event -> list of payload dicts declared by in-plan publishers
        self.plan_payloads: dict[str, list[dict]] = {}
        for feature in plan.features:
            for pub in feature.publishes:
                self.plan_payloads.setdefault(pub.event, []).append(pub.payload)

    def validate(self) -> ValidatePlanData:
        if self._rule_0_still_the_template():
            # Stop here on purpose. Every other rule would now report on the
            # example domain, and a wall of green against a plan that is not
            # yours is worse than no answer: it is a confident wrong one.
            return ValidatePlanData(valid=False, errors=self.errors,
                                    warnings=self.warnings)
        self._rule_0_plan_declares_work()
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
        self._rule_15_checklist_coverage()
        self._rule_16_language()
        self._rule_17_plan_sizing()
        self._rule_18_declared_test_nodes()
        return ValidatePlanData(
            valid=not self.errors, errors=self.errors, warnings=self.warnings
        )

    # rule 0 — the plan is still the shipped template. The template is a VALID
    #          plan (that is what makes it a useful example), so nothing else
    #          here can tell it apart from a real one — and an agent asked for
    #          feature X will happily build the template's example domain
    #          instead, reporting success, because the file it was told to read
    #          said to.
    TEMPLATE_CHECKLIST_MARKER = "<!-- template: true -->"

    def _rule_0_still_the_template(self) -> bool:
        if self.plan.template:
            self._error(
                0, "plan",
                "this is still the shipped template (`template: true`). Write "
                "the real plan at plans/active_plan.yaml — that exact path is "
                "the only one the pipeline executes.",
                fix="plan:\n  # delete the `template: true` line\n  domain: <your-domain>",
            )
            return True
        if self.checklist and self.TEMPLATE_CHECKLIST_MARKER in self.checklist:
            self._error(
                0, "plans/active_plan.md",
                "the execution checklist is still the shipped template — its "
                "tasks name placeholder paths, so it can reach all-[x] while "
                "every real feature is missing.",
                fix="Replace the checklist with one task per `file:` and "
                    "`test:` the plan declares,\nthen delete the "
                    f"`{self.TEMPLATE_CHECKLIST_MARKER}` marker line.",
            )
            return True
        return False

    # rule 0 — shape: a plan with nothing to dispatch validates perfectly against
    #          all 15 rules, which is exactly what a mistyped key looks like
    def _rule_0_plan_declares_work(self):
        if not self.plan.features and not self.plan.phase_0.migrations \
                and not self.plan.language:
            self._warn(0, "plan",
                       "declares no features and no migrations — nothing to "
                       "dispatch (check for a mistyped key, e.g. 'feature:')")

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
        # Same defect class as a table without columns, one level up: without
        # columns the phase 0 author invents the fields, without an engine they
        # invent the dialect. Silent when there are no migrations — there is no
        # SQL to write, so the field has no reader.
        if self.plan.phase_0.migrations and not self.plan.engine:
            self._warn(2, "phase_0",
                       "migrations are declared without an 'engine' — the SQL "
                       "dialect (auto-increment PK spelling, types) is left to "
                       "the phase 0 author to guess")
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
                if table not in migration.columns:
                    self._warn(2, migration.file,
                               f"table '{table}' declares no columns — phase 0 "
                               f"cannot be written from this plan alone")

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
                self._error(
                    5, feature.plugin, "feature has no 'test' file declared",
                    fix=f"- plugin: {feature.plugin}\n"
                        f"  test: tests/test_{_snake(feature.plugin)}.py",
                )

    # rule 6 — every publish names its payload model
    def _rule_6_payload_models(self):
        for feature in self.plan.features:
            for pub in feature.publishes:
                if not pub.model:
                    self._error(
                        6, feature.plugin,
                        f"published event '{pub.event}' names no payload model",
                        fix=f"publishes:\n  - event: {pub.event}\n"
                            f"    model: {_payload_model_name(pub.event)}\n"
                            f"    payload: {{ id: int }}   # the keys the event carries",
                    )

    # rule 7 — every (event, consumer) consumption appears as a flow link,
    #          and every declared rpc_link answers timeout + on_timeout
    def _rule_7_links_cover_consumptions(self):
        linked = {(link.consumes, link.consumer)
                  for flow in self.plan.flows for link in flow.links}
        for feature in self.plan.features:
            for consume in feature.consumes:
                if (consume.event, feature.plugin) not in linked:
                    self._error(
                        7, feature.plugin,
                        f"consumption of '{consume.event}' appears in no "
                        f"flow's links — its sad path is undecided",
                        fix="flows:\n"
                            f"  - name: \"{consume.event} → {feature.plugin}\"\n"
                            "    durability: ephemeral\n"
                            f"    e2e_test: tests/test_{_snake(feature.plugin)}_chain.py\n"
                            "    links:\n"
                            f"      - consumes: {consume.event}\n"
                            f"        consumer: {feature.plugin}\n"
                            "        retries: 0            # >0 also requires "
                            "idempotent + idempotency_test + sad_path_test",
                    )
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
                self._error(
                    8, flow.name, "flow has no 'e2e_test' declared",
                    fix=f"- name: \"{flow.name}\"\n"
                        f"  e2e_test: tests/test_{_snake(flow.name)}_chain.py",
                )

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

    # rule 15 — advisory: every task the plan declares appears in the execution
    #           checklist. A task missing from the checklist is never dispatched
    #           and never noticed: the checklist reaches all-[x] and the feature
    #           silently does not exist.
    def _rule_15_checklist_coverage(self):
        if not self.checklist:
            return
        declared: list[tuple[str, str]] = []
        for feature in self.plan.features:
            declared.append((feature.plugin, feature.file))
            if feature.test:
                declared.append((feature.plugin, feature.test))
        for flow in self.plan.flows:
            for path in (flow.e2e_test, flow.sad_path_test):
                if path:
                    declared.append((flow.name, path))
        for migration in self.plan.phase_0.migrations:
            declared.append((migration.file, migration.file))
        for path in self.plan.phase_0.models + self.plan.phase_0.tools:
            declared.append((path, path))

        def covered(path: str) -> bool:
            # substring match, path or basename — no coupling to the
            # checklist's markdown format or its choice of path roots
            return path in self.checklist or os.path.basename(path) in self.checklist

        # Auto-detect: a checklist sharing zero paths with this plan belongs to
        # a different plan (e.g. validating a draft) — cross-checking it would
        # be pure noise.
        if not any(covered(path) for _, path in declared):
            return
        for where, path in declared:
            if not covered(path):
                self._warn(15, where,
                           f"declared path '{path}' appears nowhere in the "
                           f"execution checklist — the task would never be "
                           f"dispatched")

    # rule 16 — the language section (ROADMAP Issue 38):
    #   a) every declared field resolves to a real column — a vocabulary field
    #      with nothing behind it is an error, not a style issue
    #   b) a model field's name equals its column's name (projections of TYPE
    #      are free, projections of NAME are not)
    #   c) rename_field / remove_field without breaking: true is an error — a
    #      breaking change to a public API stops being silent
    def _rule_16_language(self):
        for entry in self.plan.language:
            where = f"{entry.model} ({entry.op})"
            if entry.op == "new":
                self._language_new(entry, where)
            elif entry.op == "add_field":
                self._language_add_field(entry, where)
            else:                                    # rename_field | remove_field
                self._language_breaking(entry, where)

    def _known_columns(self, table: str) -> Optional[set[str]]:
        """Every column of `table`, from this plan's migrations or the live
        system. None when nothing on either side knows the table — the
        validator cannot arbitrate what it cannot see, so it says so instead
        of inventing an error."""
        declared: set[str] = set()
        found = False
        for migration in self.plan.phase_0.migrations:
            if table in migration.columns:
                declared.update(migration.columns[table])
                found = True
            elif table in migration.tables:
                found = True                         # declared, columns omitted (rule 2 warns)
        live = self.live.columns.get(table)
        if live:
            declared.update(live)
            found = True
        return declared if found else None

    def _language_new(self, entry: PlanLanguage, where: str):
        if not entry.table:
            self._error(16, where, "op 'new' must declare the table backing the entity")
            return
        columns = self._known_columns(entry.table)
        if columns is None:
            self._warn(16, where,
                       f"table '{entry.table}' is neither live nor declared in this "
                       f"plan's phase_0 — the vocabulary cannot be checked against it")
            return
        if not columns:
            return                                   # table declared without columns
        for name in entry.fields:
            if name not in columns:
                self._error(16, where,
                            f"field '{name}' names no column of '{entry.table}' "
                            f"(a name is not a projection: rename the field or "
                            f"the column, never both apart)")
        for column in entry.internal:
            if column not in columns:
                self._warn(16, where,
                           f"internal column '{column}' does not exist in "
                           f"'{entry.table}' — nothing is being excluded")

    def _language_add_field(self, entry: PlanLanguage, where: str):
        if not entry.fields:
            self._error(16, where, "op 'add_field' declares no fields")
            return
        if not entry.backed_by:
            self._error(16, where,
                        "op 'add_field' must declare backed_by: 'table.column'")
            return
        if "." not in entry.backed_by:
            self._error(16, where,
                        f"backed_by '{entry.backed_by}' must be 'table.column'")
            return
        table, column = entry.backed_by.rsplit(".", 1)
        if len(entry.fields) > 1:
            self._error(16, where,
                        "op 'add_field' declares one field per entry — a single "
                        "backed_by cannot name the column of several fields")
            return
        if column not in entry.fields:
            self._error(16, where,
                        f"field '{next(iter(entry.fields))}' is backed by column "
                        f"'{column}' — a model field's name must equal its column's")
        known = self._known_columns(table)
        if known is None:
            self._warn(16, where,
                       f"table '{table}' is neither live nor declared in this plan's "
                       f"phase_0 — backed_by cannot be checked")
        elif known and column not in known:
            self._error(16, where,
                        f"backed_by '{entry.backed_by}' names no existing column — "
                        f"declare it in this plan's phase_0 migrations or fix the name")

    def _language_breaking(self, entry: PlanLanguage, where: str):
        if entry.op == "rename_field" and not (entry.from_field and entry.to):
            self._error(16, where, "op 'rename_field' must declare 'from' and 'to'")
        if entry.op == "remove_field" and not entry.field:
            self._error(16, where, "op 'remove_field' must declare 'field'")
        if not entry.breaking:
            self._error(16, where,
                        f"'{entry.op}' is a breaking change to a public API and "
                        f"must declare breaking: true")
        if not entry.affects:
            self._warn(16, where,
                       f"'{entry.op}' declares no 'affects' — the blast radius of "
                       f"a breaking change should be written down")
        if not entry.reason:
            self._warn(16, where, f"'{entry.op}' declares no 'reason'")

    # rule 17 — advisory: a plan must be proportional to its request
    #   (docs/PARALLEL_DEVELOPMENT.md → "Plan sizing"). The calibration there is
    #   explicit: a domain with 3 CRUD plugins and one event chain is one pass.
    #   Every feature is one executor — a fresh conversation, and on a local
    #   engine the wave runs sequentially — so an oversized plan is not a style
    #   problem, it is the whole budget. A vague request ("build me a twitter")
    #   is exactly what produces one, and the planner is the only one who can
    #   still cut it: past this point the cost is paid per feature, by everyone.
    CALIBRATION_FEATURES = 6          # comfortably above the documented 3 + 1

    def _rule_17_plan_sizing(self):
        by_domain: dict[str, int] = {}
        for feature in self.plan.features:
            domain = self._feature_domain(feature)
            if domain:
                by_domain[domain] = by_domain.get(domain, 0) + 1
        for domain, count in sorted(by_domain.items()):
            if count > self.CALIBRATION_FEATURES:
                self._warn(
                    17, domain,
                    f"{count} features in one domain — the calibration is 3 CRUDs "
                    f"plus one event chain in a single pass. This dispatches "
                    f"{count} executors, each a fresh conversation (sequential on "
                    f"a local engine).",
                    fix="Cut it to the features the request actually named, or "
                        "split it:\nship the first wave, run it green, then plan "
                        "the next one against the\nmanifest it produced — which "
                        "is a smaller and better-informed plan.",
                )

    # rule 18 — a declared test that names a `::node` must contain that node
    #
    # Rules 5, 8 and 9 check only that a test is DECLARED, which is all they
    # can do while the plan is fresh and nothing is built. That leaves a hole
    # at the other end: once the wave has run, a plan may declare
    # `tests/x.py::test_double_delivery` while the executor wrote x.py without  lint:no-path
    # that function. Then `plan validate` is green, `pytest` is green — it
    # never selects a node that does not exist — and the property the plan
    # promised is neither implemented nor tested. Three checks pass and the
    # contract is unmet. Found by building a whole plan end to end.
    #
    # Silent while the file is absent: that is phase 2 not having run yet, not
    # a defect. Only a file that EXISTS without its declared node is an error.
    def _rule_18_declared_test_nodes(self):
        for path, where, why in self._declared_test_nodes():
            file_part, _, node = path.partition("::")
            if not node or not os.path.isfile(file_part):
                continue
            found = self._test_nodes_in(file_part)
            if found is None:  # unparseable — not this rule's business
                continue
            if node.split("::")[-1] not in found:
                self._error(
                    18, where,
                    f"{why} declares '{path}' but {file_part} defines no "
                    f"'{node}' — pytest silently selects nothing, so this "
                    f"property is unproven",
                    fix=f"Add it to {file_part}:\n\n"
                        f"async def {node.split('::')[-1]}():\n"
                        f"    ...  # deliver the same event twice, assert the "
                        f"effect happened once",
                )

    def _declared_test_nodes(self):
        """(declared path, where, what declared it) for every test in the plan."""
        for flow in self.plan.flows:
            for attr, label in (("e2e_test", "e2e_test"),
                                ("sad_path_test", "sad_path_test")):
                if getattr(flow, attr, None):
                    yield getattr(flow, attr), flow.name, label
            for link in flow.links:
                if link.idempotency_test:
                    yield (link.idempotency_test, flow.name,
                           f"link '{link.consumes}' → {link.consumer} "
                           f"idempotency_test")
        for feature in self.plan.features:
            if feature.test:
                yield feature.test, feature.plugin, "test"

    @staticmethod
    def _test_nodes_in(path: str) -> Optional[set[str]]:
        """Every function and class name defined in a test file, or None."""
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except (OSError, SyntaxError):
            return None
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
        return names

    @staticmethod
    def _feature_domain(feature: PlanFeature) -> Optional[str]:
        parts = feature.file.split("/")
        if len(parts) >= 4 and parts[0] == "domains" and parts[2] == "plugins":
            return parts[1]
        return None

    def _error(self, rule: int, where: str, detail: str, fix: Optional[str] = None):
        self.errors.append(PlanViolation(rule=rule, severity="ERROR",
                                         where=where, detail=detail, fix=fix))

    def _warn(self, rule: int, where: str, detail: str, fix: Optional[str] = None):
        self.warnings.append(PlanViolation(rule=rule, severity="WARNING",
                                           where=where, detail=detail, fix=fix))


# ── Entry points ───────────────────────────────────────────────────────────

# The two shapes the observed planning session guessed wrong, both of which
# land in the "unknown key" bucket — ignored by the schema, so the plan
# validates while declaring nothing.
UNKNOWN_KEY_FIXES = {
    "consumes.model": "consumes:\n  - event: order.paid\n    requires: [id, total]"
                      "\n# `model:`/`payload:` belong to publishes:. A consumer "
                      "is a tolerant reader —\n# it names only the keys it reads.",
    "consumes.payload": "consumes:\n  - event: order.paid\n    requires: [id, total]"
                        "\n# `payload:` belongs to publishes:. A consumer names "
                        "only the keys it reads.",
    "flows.steps": "flows:\n  - name: \"…\"\n    e2e_test: tests/test_….py\n"
                   "    links:\n      - consumes: order.paid\n"
                   "        consumer: SendInvoicePlugin\n"
                   "# A flow is `links:`, not `steps:` — a link is where the sad "
                   "path is decided.",
    # The next three were invented by a real planner run against this schema.
    # Each names something real; none of them is a plan field.
    "migrations.constraints": "columns:\n  follows:\n    follower_id: \"INTEGER NOT NULL\"\n"
                              "# Table-level constraints (UNIQUE, FOREIGN KEY, CHECK) are not\n"
                              "# plan fields at all — write them in the .sql file. The validator\n"
                              "# reads them back from there.",
    "features.params": "route: { method: GET, path: \"/users/{user_id}/posts\" }\n"
                       "# Path parameters are part of `path:` — quoted, because of the braces.\n"
                       "# There is no separate `params:` key.",
    "features.protected": "# Auth is not a plan field. The plugin passes\n"
                          "#   auth_validator=self.auth.validate_token\n"
                          "# to add_endpoint, and declares `auth` among its mocks:\n"
                          "mocks: [db, auth]",
}


def _unknown_key_fix(where: str, key: str) -> Optional[str]:
    """`plan.features[7].consumes[0]` + `model` -> the consumes fix."""
    section = re.sub(r"\[\d+\]", "", where).split(".")[-1]
    return UNKNOWN_KEY_FIXES.get(f"{section}.{key}")


ROUTE_FIX = (
    "# A pure event consumer has no route. OMIT the key entirely:\n"
    "- plugin: RecordAuditEntryPlugin\n"
    "  file: domains/audit/plugins/record_audit_entry_plugin.py\n"
    "  consumes:\n    - event: user.created\n      requires: [id]\n"
    "# `route: {}` is not \"no route\" — it is a route missing method and path."
)


# Above this many schema errors, the format itself is wrong — not fields in it.
# Set well clear of a plan with a few genuine mistakes: the observed wholesale
# case produced 19.
WHOLESALE_SCHEMA_ERRORS = 8


def run_validation(plan_dict: dict, live: LiveSnapshot,
                   checklist: Optional[str] = None) -> ValidatePlanData:
    """Schema check, then the rules, then the unknown-key report."""
    try:
        plan = Plan(**plan_dict)
    except ValidationError as e:
        errors = [
            PlanViolation(
                rule=0, severity="ERROR",
                where=".".join(str(loc) for loc in err["loc"]),
                detail=err["msg"],
                fix=ROUTE_FIX if "route" in [str(x) for x in err["loc"]] else None,
            )
            for err in e.errors()
        ]
        # Many schema errors at once is a different failure from a few: the
        # author is not making mistakes inside the format, they are writing a
        # different format. Answering that with a list of twenty field errors
        # invites twenty patches; naming the worked example ends it in one. A
        # real planner run produced `name/description/version` at the root with
        # `phase_0` as a list — every field wrong, and nothing saying so.
        if len(errors) >= WHOLESALE_SCHEMA_ERRORS:
            errors.insert(0, PlanViolation(
                rule=0, severity="ERROR", where="plan",
                detail=f"{len(errors)} schema errors — this is not the plan "
                       f"format. Do not patch them one by one.",
                fix="Read plans/active_plan.yaml as it ships: a worked example "
                    "of all three\nfeature shapes, with the rules behind it in "
                    "docs/PARALLEL_DEVELOPMENT.md § Phase 1.\nStart from that "
                    "shape and fill it with your domain.",
            ))
        return ValidatePlanData(valid=False, errors=errors)

    result = PlanValidator(plan, live, checklist=checklist).validate()
    # prepended: a dropped key explains every downstream violation
    result.warnings[:0] = [
        PlanViolation(rule=0, severity="WARNING", where=where,
                      detail=f"unknown key '{key}' — ignored by the schema, so "
                             f"anything under it is not validated",
                      fix=_unknown_key_fix(where, key))
        for where, key in unknown_plan_keys(plan_dict)
    ]
    return result


def _constraint_line_hint(text: str, mark) -> str:
    """`UNIQUE(a, b)` under `columns:` — a SQL constraint written as a column.

    `columns:` maps a column NAME to its SQL, so a table-level constraint has
    no key and YAML fails with a bare "could not find expected ':'" — accurate
    about the syntax, silent about the mistake. Naming it costs one line and
    saves the round that was spent staring at the file. Driven by what the
    offending line actually says, never a guess.

    Searched BACKWARDS from the mark: the scanner reports where it noticed the
    problem, which is the token AFTER the keyless line. On the plan that
    prompted this, the error read "line 26" and the constraint was on line 25.
    """
    if mark is None:
        return ""
    lines = text.splitlines()
    keywords = {"UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "CONSTRAINT",
                "INDEX", "KEY"}
    seen = 0
    for index in range(min(mark.line, len(lines) - 1), -1, -1):
        line = lines[index].strip()
        if not line or line.startswith("#"):
            continue
        if line.split("(")[0].split()[0].strip().upper() in keywords and ":" not in line:
            return (f" — line {index + 1}, `{line}`, is a table-level "
                    "constraint, and `columns:` maps a column NAME to its SQL. "
                    "Write constraints in the .sql file; the validator reads "
                    "them back from there")
        seen += 1
        if seen > 3:        # the culprit is adjacent, or this is another bug
            return ""
    return ""


def parse_plan_yaml(text: str):
    """(plan_dict, error). The error names a position in the CALLER's document."""
    if yaml is None:
        return None, "YAML support unavailable — send the plan as JSON in 'plan'"
    try:
        loaded = yaml.safe_load(text)
    except Exception as e:
        # e.problem/e.problem_mark instead of str(e): precise about the caller's
        # document without leaking anything of ours (security rule 1).
        mark = getattr(e, "problem_mark", None)
        where = (f" at line {mark.line + 1}, column {mark.column + 1}"
                 if mark is not None else "")
        problem = getattr(e, "problem", None) or "could not be parsed"
        hint = ""
        if "{" in problem or "[" in problem:
            hint = (" — inside a flow mapping, quote any value containing '{' or"
                    " '[', e.g. path: \"/orders/{order_id}\"")
        else:
            hint = _constraint_line_hint(text, mark)
        return None, f"plan_yaml is not valid YAML: {problem}{where}{hint}"
    if not isinstance(loaded, dict):
        return None, "plan_yaml does not parse to a mapping"
    if set(loaded.keys()) == {"plan"} and isinstance(loaded["plan"], dict):
        loaded = loaded["plan"]
    return loaded, None
def validate_yaml(text: str, checklist: Optional[str] = None,
                  live: Optional[LiveSnapshot] = None):
    """(ValidatePlanData, None) or (None, parse error). The CLI's entry point."""
    plan_dict, error = parse_plan_yaml(text)
    if error:
        return None, error
    return run_validation(plan_dict, live or offline_snapshot(), checklist), None
