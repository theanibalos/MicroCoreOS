"""Field-constraint divergence: the same field validated differently by sibling plugins.

ROADMAP Issue 37, scope 2 only ("request/response fields → compare within a
domain"). Scopes 1 (event payload keys, fleet-wide) and 3 (opt-in cross-domain
names) are NOT implemented here — see the issue for why each needs its own
comparison rule.


The tool-side equivalent already existed (tool_doc_drift_linter_plugin: a tool's
methods vs its documented contract). This is the plugin-side one: a domain's
plugins each declare their own request schema, so the SAME field ends up with
its own `Field(...)` constraints in several files. That duplication is
deliberate (a request schema is a per-feature projection, not a shared model) —
what was missing is anything that notices when the copies stop agreeing.

Nothing detects it today: `password` accepting 8 characters on create and 6 on
update is not a crash, not a failing test, and not visible in any review that
looks at one file at a time. It is just two rules where the product has one.

Advisory only, like every devtools linter: divergence CAN be legitimate (a
search endpoint may accept a shorter term than a create endpoint). The warning
says "these disagree, confirm it is on purpose", never "this is wrong".

RECORDING THE CONFIRMATION
──────────────────────────
"Confirm it is on purpose" needs somewhere to put the answer, or the warning is
permanent and the linter gets tuned out — the way every advisory tool dies. A
declaration can say it diverges deliberately, in the file that owns it:

    password: str = Field(
        min_length=1,
        json_schema_extra={"divergence_ok": "login checks the hash, not the length"},
    )

`json_schema_extra` is real Pydantic, not a private convention, so the reason
also travels into the OpenAPI schema. A waived declaration drops OUT of the
comparison: the remaining ones are still compared against each other, so
waiving login does not blind the linter to create-vs-update disagreeing. The
reason string is required and must be non-empty — a bare silence is exactly
what this is meant to prevent.

Registry key: devtools/field_divergence_warnings (read by GET /system/lint).
"""

import ast
import os
from microcoreos import BasePlugin
from domains.devtools.lint.plugin_sources import iter_plugin_files

# Pydantic Field(...) keywords worth comparing: the ones that encode a business
# rule. Cosmetic keywords (description, examples, alias) are excluded — they
# differ per endpoint by design and would drown the signal in noise.
COMPARED_CONSTRAINTS = (
    "min_length", "max_length", "pattern",
    "ge", "gt", "le", "lt",
    "multiple_of", "max_digits", "decimal_places",
)


class FieldDivergenceLinterPlugin(BasePlugin):
    """AST scan over domains/*/plugins/*.py comparing Field() constraints
    declared for the same field name within one domain."""

    def __init__(self, container, logger):
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        warnings = self._check_field_divergence()
        if warnings:
            self.registry.register_domain_metadata("devtools", "field_divergence_warnings", warnings)
            for w in warnings:
                self.logger.warning(f"[FieldDivergenceLinter] {w}")
        else:
            self.logger.info("[FieldDivergenceLinter] Field constraints verified. No drift found.")

    def _check_field_divergence(self) -> list[str]:
        # domain → field → constraint → value → [locations]
        declared: dict[str, dict[str, dict[str, dict]]] = {}

        for domain, filepath in iter_plugin_files():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception as e:
                self.logger.warning(f"[FieldDivergenceLinter] Could not parse {filepath}: {e}")
                continue

            filename = os.path.basename(filepath)
            for model_name, field, constraint, value in self._iter_constraints(tree):
                location = f"{filename}:{model_name}"
                (
                    declared
                    .setdefault(domain, {})
                    .setdefault(field, {})
                    .setdefault(constraint, {})
                    .setdefault(value, [])
                    .append(location)
                )

        warnings = []
        for domain in sorted(declared):
            for field in sorted(declared[domain]):
                for constraint in sorted(declared[domain][field]):
                    values = declared[domain][field][constraint]
                    if len(values) < 2:
                        continue
                    detail = " and ".join(
                        f"{value!r} ({', '.join(locations)})"
                        for value, locations in sorted(values.items(), key=lambda kv: repr(kv[0]))
                    )
                    warnings.append(
                        f"Field constraint drift in domain '{domain}': "
                        f"'{field}.{constraint}' is declared as {detail} "
                        f"— sibling plugins validate the same field differently."
                    )
        return warnings

    def _iter_constraints(self, tree: ast.Module):
        """Yields (model_name, field_name, constraint, value) for every literal
        constraint in a `field: type = Field(...)` inside a pydantic model."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not self._is_pydantic_model(node):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                    continue
                call = statement.value
                if not isinstance(call, ast.Call) or not self._is_field_call(call):
                    continue
                if self._waiver_reason(call):
                    continue  # deliberate divergence, declared where it happens
                for keyword in call.keywords:
                    if keyword.arg not in COMPARED_CONSTRAINTS:
                        continue
                    try:
                        value = ast.literal_eval(keyword.value)
                    except Exception:
                        continue  # not a literal — nothing to compare, never guess
                    if not isinstance(value, (str, int, float, bool, type(None))):
                        continue  # only scalars are comparable as "the same rule"
                    yield node.name, statement.target.id, keyword.arg, value

    def _waiver_reason(self, call: ast.Call) -> str | None:
        """The reason from `json_schema_extra={"divergence_ok": "..."}`, if any.

        A waiver with an empty or missing reason is NOT honoured: recording why
        is the whole point, and an unexplained silence is the failure mode this
        linter exists to catch.
        """
        for keyword in call.keywords:
            if keyword.arg != "json_schema_extra":
                continue
            try:
                extra = ast.literal_eval(keyword.value)
            except Exception:
                return None                       # not a literal — never guess
            if not isinstance(extra, dict):
                return None
            reason = extra.get("divergence_ok")
            if isinstance(reason, str) and reason.strip():
                return reason
        return None

    def _is_pydantic_model(self, node: ast.ClassDef) -> bool:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "BaseModel":
                return True
            if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                return True
        return False

    def _is_field_call(self, call: ast.Call) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id == "Field"
        if isinstance(call.func, ast.Attribute):
            return call.func.attr == "Field"
        return False
