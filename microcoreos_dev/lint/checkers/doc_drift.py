"""Tool documentation drift checker.

Inspects tool implementations and checks that each public method appears in its
get_interface_description().

Supports both AST-based offline analysis (without importing dependencies)
and live tool instance inspection.
"""

import ast
import inspect
import os
import re
from typing import Optional
from microcoreos_dev.lint.schema import CheckFinding

IGNORED_METHODS = {
    "setup", "name", "get_interface_description", "on_boot_complete",
    "on_instrument", "shutdown", "on_boot",
}


def check_tool_doc_drift(
    root: str = ".",
    tools_dir: str = "tools",
    tools: Optional[list] = None,
) -> list[CheckFinding]:
    """Scan tools for documentation drift."""
    findings: list[CheckFinding] = []

    # 1. Live inspection mode if tool instances are passed
    if tools is not None:
        for tool in tools:
            tool_name = getattr(tool, "name", tool.__class__.__name__)
            desc = tool.get_interface_description() if hasattr(tool, "get_interface_description") else ""
            for method_name, _ in inspect.getmembers(tool, predicate=inspect.isroutine):
                if method_name.startswith("_") or method_name in IGNORED_METHODS:
                    continue
                if not re.search(rf"\b{re.escape(method_name)}\b", desc, re.IGNORECASE):
                    findings.append(
                        CheckFinding(
                            checker="tool_doc_drift",
                            code="TOOL_DOC_DRIFT",
                            severity="warning",
                            message=(
                                f"Tool '{tool_name}' method '{method_name}' is not documented in "
                                f"get_interface_description()"
                            ),
                            file=None,
                        )
                    )
        return findings

    # 2. Offline AST mode
    base_dir = os.path.join(root, tools_dir) if not os.path.isabs(tools_dir) else tools_dir
    if not os.path.isdir(base_dir):
        return findings

    for root_dir, _, files in os.walk(base_dir):
        for filename in sorted(files):
            if not filename.endswith("_tool.py"):
                continue
            filepath = os.path.join(root_dir, filename)
            relpath = os.path.relpath(filepath, root)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=filepath)
            except Exception as e:
                findings.append(
                    CheckFinding(
                        checker="tool_doc_drift",
                        code="TOOL_SCAN_ERROR",
                        severity="warning",
                        message=f"Could not parse {relpath}: {e}",
                        file=relpath,
                    )
                )
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # Class in *_tool.py
                tool_name = node.name
                desc = ""
                methods = []

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == "get_interface_description":
                            for ret in ast.walk(item):
                                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Constant):
                                    if isinstance(ret.value.value, str):
                                        desc = ret.value.value
                        elif not item.name.startswith("_") and item.name not in IGNORED_METHODS:
                            methods.append((item.name, item.lineno))

                if desc:
                    for method_name, lineno in methods:
                        if not re.search(rf"\b{re.escape(method_name)}\b", desc, re.IGNORECASE):
                            findings.append(
                                CheckFinding(
                                    checker="tool_doc_drift",
                                    code="TOOL_DOC_DRIFT",
                                    severity="warning",
                                    message=(
                                        f"Tool '{tool_name}' method '{method_name}' is not documented in "
                                        f"get_interface_description()"
                                    ),
                                    file=relpath,
                                    line=lineno,
                                )
                            )

    return findings
