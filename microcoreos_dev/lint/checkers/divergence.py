"""Field divergence checker.

Scans domains/*/plugins/*.py comparing Field(...) constraints declared for
the same field name within a single domain. Supports reasoned waivers via
json_schema_extra={"divergence_ok": "reason"}.
"""

import ast
import os
from typing import Iterator, Optional
from microcoreos_dev.lint.schema import CheckFinding

COMPARED_CONSTRAINTS = (
    "min_length", "max_length", "pattern",
    "ge", "gt", "le", "lt",
    "multiple_of", "max_digits", "decimal_places",
)


def _iter_plugin_files(base_dir: str, domains_dirname: str = "domains") -> Iterator[tuple[str, str]]:
    domains_dir = os.path.join(base_dir, domains_dirname)
    if not os.path.isdir(domains_dir):
        return

    for domain in sorted(os.listdir(domains_dir)):
        plugins_dir = os.path.join(domains_dir, domain, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        for filename in sorted(os.listdir(plugins_dir)):
            if filename.endswith(".py"):
                yield domain, os.path.join(plugins_dir, filename)


def _is_pydantic_model(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
    return False


def _is_field_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == "Field"
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "Field"
    return False


def _waiver_reason(call: ast.Call) -> Optional[str]:
    for keyword in call.keywords:
        if keyword.arg != "json_schema_extra":
            continue
        try:
            extra = ast.literal_eval(keyword.value)
        except Exception:
            return None
        if not isinstance(extra, dict):
            return None
        reason = extra.get("divergence_ok")
        if isinstance(reason, str) and reason.strip():
            return reason
    return None


def _iter_constraints(tree: ast.Module):
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_pydantic_model(node):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                continue
            call = statement.value
            if not isinstance(call, ast.Call) or not _is_field_call(call):
                continue
            if _waiver_reason(call):
                continue
            for keyword in call.keywords:
                if keyword.arg not in COMPARED_CONSTRAINTS:
                    continue
                try:
                    value = ast.literal_eval(keyword.value)
                except Exception:
                    continue
                if not isinstance(value, (str, int, float, bool, type(None))):
                    continue
                yield node.name, statement.target.id, keyword.arg, value


def check_field_divergence(
    root: str = ".",
    domains_dir: str = "domains",
) -> list[CheckFinding]:
    """Scan plugins for field constraint divergence within domains."""
    declared: dict[str, dict[str, dict[str, dict]]] = {}
    findings: list[CheckFinding] = []

    for domain, filepath in _iter_plugin_files(root, domains_dir):
        relpath = os.path.relpath(filepath, root)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)
        except Exception as e:
            findings.append(
                CheckFinding(
                    checker="field_divergence",
                    code="FIELD_DIVERGENCE_PARSE_ERROR",
                    severity="warning",
                    message=f"Could not parse {relpath}: {e}",
                    file=relpath,
                )
            )
            continue

        filename = os.path.basename(filepath)
        for model_name, field, constraint, value in _iter_constraints(tree):
            location = f"{filename}:{model_name}"
            (
                declared
                .setdefault(domain, {})
                .setdefault(field, {})
                .setdefault(constraint, {})
                .setdefault(value, [])
                .append(location)
            )

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
                findings.append(
                    CheckFinding(
                        checker="field_divergence",
                        code="FIELD_CONSTRAINT_DIVERGENCE",
                        severity="warning",
                        message=(
                            f"Field constraint drift in domain '{domain}': "
                            f"'{field}.{constraint}' is declared as {detail} "
                            f"— sibling plugins validate the same field differently."
                        ),
                        file=None,
                    )
                )

    return findings
