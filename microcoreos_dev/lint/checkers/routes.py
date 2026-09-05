"""Route collision checker.

AST scan over domains/*/plugins/*.py looking for duplicate (method, path)
endpoint registrations. Starlette routes to the first match, so duplicate
registrations leave later plugins silently unreachable.
"""

import ast
import os
from typing import Iterator
from microcoreos_dev.lint.schema import CheckFinding


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


def check_route_collisions(
    root: str = ".",
    domains_dir: str = "domains",
) -> list[CheckFinding]:
    """Scan plugins for duplicate route registrations."""
    routes: dict[tuple[str, str], set[str]] = {}
    findings: list[CheckFinding] = []

    for domain, filepath in _iter_plugin_files(root, domains_dir):
        relpath = os.path.relpath(filepath, root)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)
        except Exception as e:
            findings.append(
                CheckFinding(
                    checker="route_collisions",
                    code="ROUTE_SCAN_ERROR",
                    severity="error",
                    message=f"Could not parse {relpath}: {e}",
                    file=relpath,
                )
            )
            continue

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "add_endpoint":
                continue

            path, method = None, None
            # Positional args: add_endpoint(path, method, ...)
            if len(node.args) >= 2:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    path = node.args[0].value
                if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    method = node.args[1].value

            for kw in node.keywords:
                if kw.arg == "path" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    path = kw.value.value
                elif kw.arg == "method" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    method = kw.value.value

            if path and method:
                key = (method.upper(), path)
                routes.setdefault(key, set()).add(relpath)

    for (method, path), owners in sorted(routes.items()):
        if len(owners) > 1:
            sorted_owners = sorted(owners)
            findings.append(
                CheckFinding(
                    checker="route_collisions",
                    code="ROUTE_COLLISION",
                    severity="error",
                    message=(
                        f"Route collision: {method} {path} registered by {', '.join(sorted_owners)} "
                        f"— only the first match is reachable."
                    ),
                    file=sorted_owners[0],
                )
            )

    return findings
