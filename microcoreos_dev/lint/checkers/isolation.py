"""Domain isolation checker.

AST scan over domains/*/plugins/*.py verifying:
- No cross-domain imports (domains communicate only via the event bus).
- No hardcoded tool imports (plugins receive tools by injection).
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


def _is_illegal_import(current_domain: str, target_module: str) -> bool:
    parts = target_module.split(".")
    if len(parts) >= 2 and parts[0] == "domains":
        target_domain = parts[1]
        return target_domain != current_domain
    return False


def _is_tool_import(module_name: str) -> bool:
    parts = module_name.split(".")
    return bool(parts and parts[0] == "tools")


def check_domain_isolation(
    root: str = ".",
    domains_dir: str = "domains",
) -> list[CheckFinding]:
    """Scan plugins for illegal cross-domain or hardcoded tool imports."""
    findings: list[CheckFinding] = []

    for domain, filepath in _iter_plugin_files(root, domains_dir):
        relpath = os.path.relpath(filepath, root)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_illegal_import(domain, alias.name):
                            findings.append(
                                CheckFinding(
                                    checker="domain_isolation",
                                    code="ILLEGAL_CROSS_DOMAIN_IMPORT",
                                    severity="error",
                                    message=f"Illegal cross-domain import in {relpath}: {alias.name}",
                                    file=relpath,
                                    line=node.lineno,
                                )
                            )
                        elif _is_tool_import(alias.name):
                            findings.append(
                                CheckFinding(
                                    checker="domain_isolation",
                                    code="ILLEGAL_TOOL_IMPORT",
                                    severity="error",
                                    message=f"Illegal hardcoded tool import in {relpath}: import {alias.name}",
                                    file=relpath,
                                    line=node.lineno,
                                )
                            )

                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        if _is_illegal_import(domain, node.module):
                            findings.append(
                                CheckFinding(
                                    checker="domain_isolation",
                                    code="ILLEGAL_CROSS_DOMAIN_IMPORT",
                                    severity="error",
                                    message=f"Illegal cross-domain import in {relpath}: from {node.module}",
                                    file=relpath,
                                    line=node.lineno,
                                )
                            )
                        elif _is_tool_import(node.module):
                            findings.append(
                                CheckFinding(
                                    checker="domain_isolation",
                                    code="ILLEGAL_TOOL_IMPORT",
                                    severity="error",
                                    message=f"Illegal hardcoded tool import in {relpath}: from {node.module}",
                                    file=relpath,
                                    line=node.lineno,
                                )
                            )
        except Exception as e:
            findings.append(
                CheckFinding(
                    checker="domain_isolation",
                    code="ISOLATION_SCAN_ERROR",
                    severity="error",
                    message=f"Error linting {relpath}: {e}",
                    file=relpath,
                )
            )

    return findings
