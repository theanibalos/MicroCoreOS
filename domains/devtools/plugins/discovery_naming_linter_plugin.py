"""Discovery naming: a tool or plugin class must live in a file the Kernel reads.

The Kernel narrows discovery by filename (core/kernel.py::_load_modules_from_dir):
only `*_tool.py` under tools/ and `*_plugin.py` under domains/ are imported.
That is deliberate — importing every .py would pull in optional drivers whose
broker library may not be installed, reporting a boot error for a transport
nobody selected — but it trades one failure mode for another: a class in a
misnamed file is not an error, it is simply never found. The system boots
"fine" and the tool is missing.

This linter is the other half of that trade. A misnamed file is cheap to find
here and expensive to find at runtime, where the only symptom is a plugin
reporting `Missing tools: x` from a domain nobody touched.

Registry key: devtools/discovery_naming_violations (read by GET /system/lint).
"""

import ast
from core.base_plugin import BasePlugin
from domains.devtools.lint.plugin_sources import iter_source_files

# base class → the filename suffix that makes the Kernel import it.
DISCOVERY_RULES = {"BaseTool": "_tool.py", "BasePlugin": "_plugin.py"}


class DiscoveryNamingLinterPlugin(BasePlugin):
    """
    AST scan over tools/, domains/ and extras/ for classes the Kernel is meant
    to discover but cannot, because their file is named wrong.

    Detection is by DIRECT base class name (`class X(BaseTool)`) — the repo
    convention everywhere, including extras/. A tool subclassing another tool
    would be missed; that is not a case this codebase has, and reading it out
    of the AST alone is not possible without importing, which is exactly what
    the naming rule exists to avoid.

    extras/ is scanned too: those files are activated by moving them into
    tools/ or domains/ (docs/ELASTIC_DEPLOYMENT.md), so a name that is wrong
    there is a bug that only detonates on the day someone swaps it in.
    """

    def __init__(self, container, logger):
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        violations = self._perform_scan()
        if violations:
            self.registry.register_domain_metadata(
                "devtools", "discovery_naming_violations", violations
            )
            for v in violations:
                self.logger.warning(f"[DiscoveryNamingLinter] {v}")
        else:
            self.logger.info(
                "[DiscoveryNamingLinter] Every tool and plugin class is in a discoverable file."
            )

    def _perform_scan(self) -> list[str]:
        violations = []
        for filepath in iter_source_files("tools", "domains", "extras"):
            violations.extend(self._scan_file(filepath))
        return violations

    def _scan_file(self, filepath: str) -> list[str]:
        violations = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    # `class X(BaseTool)` and `class X(core.base_tool.BaseTool)`
                    base_name = base.id if isinstance(base, ast.Name) else (
                        base.attr if isinstance(base, ast.Attribute) else None
                    )
                    suffix = DISCOVERY_RULES.get(base_name)
                    if suffix and not filepath.endswith(suffix):
                        violations.append(
                            f"{node.name}({base_name}) in {filepath} is invisible to the "
                            f"Kernel: discovery only imports files ending in '{suffix}'."
                        )

        except Exception as e:
            violations.append(f"Error linting {filepath}: {e}")

        return violations
