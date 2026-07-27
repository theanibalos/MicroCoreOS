"""Domain isolation: no cross-domain imports, no hardcoded tool imports.

One of the linters split out of the former ArchitectureLinterPlugin (one rule
per plugin, like domains/system/): each has its own dependencies, its own
status in the registry, and can fail without taking the others down.

Registry key: devtools/arch_violations (read by GET /system/lint).
"""

import ast
from microcoreos import BasePlugin
from domains.devtools.lint.plugin_sources import iter_plugin_files


class DomainIsolationLinterPlugin(BasePlugin):
    """
    AST scan over domains/*/plugins/*.py looking for the two imports that
    break the architecture:

    - `domains.OTHER_DOMAIN...` — domains talk through the event bus, never by
      importing each other. Same-domain imports (the domain's own models/) and
      `microcoreos` are fine.
    - `tools....` — plugins receive tools by injection; importing one hardcodes
      an implementation and kills the swap (docs/ELASTIC_DEPLOYMENT.md).
    """

    def __init__(self, container, logger):
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        violations = self._perform_scan()
        if violations:
            self.registry.register_domain_metadata("devtools", "arch_violations", violations)
            for v in violations:
                self.logger.warning(f"[DomainIsolationLinter] {v}")
        else:
            self.logger.info("[DomainIsolationLinter] Domain isolation verified. No violations found.")

    def _perform_scan(self) -> list[str]:
        violations = []
        for domain, filepath in iter_plugin_files():
            violations.extend(self._scan_file(domain, filepath))
        return violations

    def _scan_file(self, domain: str, filepath: str) -> list[str]:
        violations = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                # 1. Detect 'import domains.X' or 'from domains.X import ...'
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if self._is_illegal_import(domain, alias.name):
                            violations.append(f"Illegal cross-domain import in {filepath}: {alias.name}")

                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:  # Absolute import
                        if self._is_illegal_import(domain, node.module):
                            violations.append(f"Illegal cross-domain import in {filepath}: from {node.module}")
                        elif node.module.startswith("tools."):
                            violations.append(f"Illegal hardcoded tool import in {filepath}: from {node.module}")

        except Exception as e:
            violations.append(f"Error linting {filepath}: {e}")

        return violations

    def _is_illegal_import(self, current_domain: str, target_module: str) -> bool:
        """
        An import is illegal if it points to 'domains.X' where X != current_domain.
        Imports from 'microcoreos' and internal domain modules are allowed.
        """
        parts = target_module.split('.')
        if len(parts) >= 2 and parts[0] == "domains":
            target_domain = parts[1]
            return target_domain != current_domain
        return False
