"""Tool documentation drift: every public tool method must be documented.

One of the linters split out of the former ArchitectureLinterPlugin.

Registry key: devtools/drift_warnings (read by GET /system/lint), plus a
WARNING status on the offending tool itself.
"""

import inspect
import re
from core.base_plugin import BasePlugin


class ToolDocDriftLinterPlugin(BasePlugin):
    """
    Introspects every raw tool and checks that each public method appears in
    its get_interface_description().

    Why it matters: that description IS the tool's contract for every agent
    writing plugins. A method that exists but is undocumented might as well not
    exist; a documented method that was renamed sends the agent to write code
    that cannot work.
    """

    # Methods defined in BaseTool or Python internals that shouldn't be documented
    IGNORED_METHODS = {
        "setup", "name", "get_interface_description", "on_boot_complete",
        "on_instrument", "shutdown", "on_boot"
    }

    def __init__(self, container, logger):
        self.container = container
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        drift_warnings = self._check_tool_drift()
        if drift_warnings:
            self.registry.register_domain_metadata("devtools", "drift_warnings", drift_warnings)
            for w in drift_warnings:
                self.logger.warning(f"[ToolDocDriftLinter] {w}")
        else:
            self.logger.info("[ToolDocDriftLinter] Tool documentation verified. No drift found.")

    def _check_tool_drift(self) -> list[str]:
        warnings = []

        for tool in self.container.get_raw_tools():
            desc = tool.get_interface_description()
            missing = []

            # Introspect all methods that don't start with '_'
            for method_name, _ in inspect.getmembers(tool, predicate=inspect.isroutine):
                if method_name.startswith("_") or method_name in self.IGNORED_METHODS:
                    continue

                # Whole-word match: a substring check would let "get" pass
                # because "get_interface" contains it.
                if not re.search(rf"\b{re.escape(method_name)}\b", desc, re.IGNORECASE):
                    missing.append(method_name)
                    warnings.append(
                        f"Tool '{tool.name}' method '{method_name}' is not documented in get_interface_description()"
                    )

            # One registry status per tool, listing every missing method
            # (per-method calls would overwrite each other, keeping only the last).
            if missing:
                self.registry.update_tool_status(
                    tool.name,
                    "WARNING",
                    f"Documentation drift: missing {', '.join(repr(m) for m in missing)}"
                )

        return warnings
