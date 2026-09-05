"""Discovery naming checker.

Verifies that every class inheriting BaseTool or BasePlugin lives in a file
matching the discovery convention (*_tool.py, *_plugin.py), and that no test
file uses those suffixes (which would cause the Kernel to import pytest).
"""

import ast
import os
from typing import Iterator
from microcoreos_dev.lint.schema import CheckFinding

DISCOVERY_RULES = {
    "BaseTool": "_tool.py",
    "BasePlugin": "_plugin.py",
}


def _iter_source_files(base_dir: str, *roots: str) -> Iterator[str]:
    for root in roots:
        target = os.path.join(base_dir, root) if not os.path.isabs(root) else root
        if not os.path.isdir(target):
            continue
        for current, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for filename in sorted(files):
                if filename.endswith(".py") and filename != "__init__.py":
                    yield os.path.join(current, filename)


def check_discovery_naming(
    root: str = ".",
    roots: tuple[str, ...] = ("tools", "domains", "extras"),
) -> list[CheckFinding]:
    """Scan sources for discovery naming violations and test collisions."""
    findings: list[CheckFinding] = []

    for filepath in _iter_source_files(root, *roots):
        relpath = os.path.relpath(filepath, root)
        filename = os.path.basename(filepath)

        # 1. Test collision check: test_*.py ending in _tool.py or _plugin.py
        if filename.startswith("test_"):
            for suffix in DISCOVERY_RULES.values():
                if filename.endswith(suffix):
                    stem = filename[len("test_"):-len(".py")]
                    findings.append(
                        CheckFinding(
                            checker="discovery_naming",
                            code="NAMING_TEST_COLLISION",
                            severity="error",
                            message=(
                                f"{relpath} is a test the Kernel will import at boot: it ends in "
                                f"'{suffix}', which is the discovery suffix. Rename it '{stem}_test.py'."
                            ),
                            file=relpath,
                        )
                    )

        # 2. Class inheritance check
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    base_name = base.id if isinstance(base, ast.Name) else (
                        base.attr if isinstance(base, ast.Attribute) else None
                    )
                    suffix = DISCOVERY_RULES.get(base_name)
                    if suffix and not filepath.endswith(suffix):
                        findings.append(
                            CheckFinding(
                                checker="discovery_naming",
                                code="NAMING_MISNAMED_FILE",
                                severity="error",
                                message=(
                                    f"{node.name}({base_name}) in {relpath} is invisible to the "
                                    f"Kernel: discovery only imports files ending in '{suffix}'."
                                ),
                                file=relpath,
                                line=node.lineno,
                            )
                        )
        except Exception as e:
            findings.append(
                CheckFinding(
                    checker="discovery_naming",
                    code="NAMING_SCAN_ERROR",
                    severity="error",
                    message=f"Error linting {relpath}: {e}",
                    file=relpath,
                )
            )

    return findings
