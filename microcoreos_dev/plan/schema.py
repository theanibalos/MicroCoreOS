"""The formal plan format (v3) — the shape `plans/active_plan.yaml` must have.

Vocabulary only: what a plan may say, and which keys no field claims. The rules
that judge a plan live in `rules.py`; what the repo on disk already occupies
lives in `scan.py`.
"""
from typing import Optional, Literal, get_args
from pydantic import BaseModel, ConfigDict, Field


class PlanRoute(BaseModel):
    method: str
    path: str


class PlanMigration(BaseModel):
    file: str
    tables: list[str] = []
    # table -> {column_name: "SQL type + constraints"} — the plan must carry the
    # full schema so phase 0 can be written from the plan alone (no improvisation)
    columns: dict[str, dict[str, str]] = {}


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
    # Named `tools:` because that is what it is — the tools this plugin's
    # __init__ takes, in order, since DI is by parameter name. It was `mocks:`,
    # which reads as "what the test stands in for", and that reading is why the
    # shipped template listed only the interesting two while the example
    # plugin's constructor took four: nobody mocks a logger for its own sake.
    # An incomplete list cannot construct the plugin, so a test written from
    # the plan alone fails on TypeError. `mocks:` stays accepted forever —
    # every plan already written uses it.
    tools: list[str] = Field(default_factory=list, alias="mocks")
    test: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


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


class PlanLanguage(BaseModel):
    """One amendment to a domain's ubiquitous language (ROADMAP Issue 38).

    The entity model is VOCABULARY, not a mirror of the table: storage and
    language are allowed to differ in TYPE (`roles` is TEXT on disk and
    list[str] in the domain) and a column may be absent from the language
    entirely (`password_hash` never leaves the system — that is `internal:`).
    What they may NOT differ in is the NAME, which is what rule 16 enforces.
    """
    model: str
    op: Literal["new", "add_field", "rename_field", "remove_field"]
    domain: Optional[str] = None
    table: Optional[str] = None            # op=new: the table backing the entity
    fields: dict[str, str] = {}            # op=new / add_field: name -> domain type
    internal: list[str] = []               # columns deliberately NOT in the language
    backed_by: Optional[str] = None        # op=add_field: "table.column"
    from_field: Optional[str] = Field(default=None, alias="from")   # op=rename_field
    to: Optional[str] = None               # op=rename_field
    field: Optional[str] = None            # op=remove_field
    breaking: bool = False                 # MANDATORY on rename/remove
    affects: list[str] = []                # endpoints that speak the old name
    reason: str = ""

    model_config = ConfigDict(populate_by_name=True)


class Plan(BaseModel):
    # The shipped plans/active_plan.yaml carries `template: true`, and rule 0
    # refuses to validate a plan that still does. It is a schema field rather
    # than a comment because a comment cannot fail: two sessions in a row read
    # the untouched template, found a syntactically perfect plan for the
    # example `catalog` domain, and built THAT — one of them after being told
    # in the prompt to build something else. Deleting this line is the act of
    # saying "this plan is mine".
    template: bool = False
    domain: Optional[str] = None
    # Which SQL dialect the migrations target. Informative — migrations run
    # verbatim (AGENTS.md rule 8) — but it is the ONLY thing telling the phase 0
    # author whether a PK is "INTEGER PRIMARY KEY" or "SERIAL PRIMARY KEY".
    # Meaningless without migrations, which is why it is optional here and
    # required by rule 2 exactly when phase_0 declares any.
    engine: Optional[str] = None
    phase_0: PlanPhase0 = PlanPhase0()
    language: list[PlanLanguage] = []
    features: list[PlanFeature] = []
    flows: list[PlanFlow] = []

# Unknown keys are IGNORED by the schema on purpose — a plan may carry the
# orchestrator's own annotations (budget, owner, priority). But a typo lands in
# that same bucket: 'feature:' instead of 'features:' validates a plan that
# declares nothing. Ignored, therefore, but never silently.

def _model_at(annotation):
    """The BaseModel class inside T, Optional[T] or list[T] — None if there is none."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        found = _model_at(arg)
        if found is not None:
            return found
    return None


def unknown_plan_keys(raw, model=Plan, where="plan") -> list[tuple[str, str]]:
    """(where, key) for every key of the raw plan that no schema field claims."""
    found: list[tuple[str, str]] = []
    if not isinstance(raw, dict):
        return found
    # a field may be reachable by its alias ('from' is a Python keyword, so
    # PlanLanguage spells it from_field) — both names are legitimate input
    by_name = dict(model.model_fields)
    by_name.update({f.alias: f for f in model.model_fields.values() if f.alias})
    for key, value in raw.items():
        field = by_name.get(key)
        if field is None:
            found.append((where, key))
            continue
        nested = _model_at(field.annotation)
        if nested is None:
            continue
        label = f"{where}.{key}"
        if isinstance(value, list):
            for index, item in enumerate(value):
                found.extend(unknown_plan_keys(item, nested, f"{label}[{index}]"))
        else:
            found.extend(unknown_plan_keys(value, nested, label))
    return found


class PlanViolation(BaseModel):
    rule: int
    severity: str                     # ERROR | WARNING
    where: str = ""
    detail: str
    # The YAML that fixes it, when the rule knows. Prose describing a shape is
    # not the same affordance as the shape: the validator already knows exactly
    # what is missing, and a reader that can copy does not have to derive.
    # Every avoidable round in the observed planning session was a shape the
    # author had to infer — `requires:` vs `payload:`, `links:` vs `steps:`.
    fix: Optional[str] = None


class ValidatePlanData(BaseModel):
    valid: bool
    errors: list[PlanViolation] = []
    warnings: list[PlanViolation] = []
