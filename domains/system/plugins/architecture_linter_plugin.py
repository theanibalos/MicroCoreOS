import ast
import os
import asyncio
from core.base_plugin import BasePlugin


class ArchitectureLinterPlugin(BasePlugin):
    """
    Enforces architectural rules by scanning plugin files using AST.
    Detects illegal imports:
    - Cross-domain imports (domains communicate ONLY via EventBus).
    - Hardcoded tool imports (tools MUST be injected via DI).
    
    Reports violations to the Registry and Logs.
    """

    def __init__(self, registry, logger):
        self.registry = registry
        self.logger = logger

    async def on_boot(self):
        # Perform initial scan
        violations = self._perform_scan()
        if violations:
            self.registry.register_domain_metadata("system", "arch_violations", violations)
            for v in violations:
                self.logger.warning(f"[ArchLinter] {v}")
        else:
            self.logger.info("[ArchLinter] Domain isolation verified. No violations found.")

    def _perform_scan(self) -> list[str]:
        violations = []
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return []

        for domain in os.listdir(domains_dir):
            plugins_dir = os.path.join(domains_dir, domain, "plugins")
            if not os.path.isdir(plugins_dir):
                continue
            
            for filename in os.listdir(plugins_dir):
                if not filename.endswith(".py"):
                    continue
                
                filepath = os.path.join(plugins_dir, filename)
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
                    if node.level == 0 and node.module: # Absolute import
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
        Imports from 'core' and internal domain modules are allowed.
        """
        parts = target_module.split('.')
        if len(parts) >= 2 and parts[0] == "domains":
            target_domain = parts[1]
            return target_domain != current_domain
        return False
