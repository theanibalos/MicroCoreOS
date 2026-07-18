import ast
import os
import re
import inspect
from core.base_plugin import BasePlugin


class ArchitectureLinterPlugin(BasePlugin):
    """
    Enforces architectural rules by scanning plugin files using AST and
    introspecting tools for documentation drift.
    
    Detects:
    - Illegal cross-domain imports.
    - Hardcoded tool imports.
    - Tool methods missing from get_interface_description() (anti-drift).
    """

    def __init__(self, container, logger, http):
        self.container = container
        self.registry = container.registry
        self.logger = logger
        self.http = http

    async def on_boot(self):
        # 1. Domain Isolation Scan
        violations = self._perform_scan()
        if violations:
            self.registry.register_domain_metadata("devtools", "arch_violations", violations)
            for v in violations:
                self.logger.warning(f"[ArchLinter] {v}")
        else:
            self.logger.info("[ArchLinter] Domain isolation verified. No violations found.")

        # 2. Tool Anti-Drift Check
        drift_warnings = self._check_tool_drift()
        if drift_warnings:
            self.registry.register_domain_metadata("devtools", "drift_warnings", drift_warnings)
            for w in drift_warnings:
                self.logger.warning(f"[ArchLinter] {w}")
        else:
            self.logger.info("[ArchLinter] Tool documentation verified. No drift found.")

        # 3. Table Ownership Scan (Issue 27)
        table_warnings = self._check_table_ownership()
        if table_warnings:
            self.registry.register_domain_metadata("devtools", "table_ownership_warnings", table_warnings)
            for w in table_warnings:
                self.logger.warning(f"[ArchLinter] {w}")
        else:
            self.logger.info("[ArchLinter] Table ownership verified. No duplicate declarations found.")

        # 4. Route Collision Check (Issue 26) — deferred: add_endpoint only buffers
        # endpoints, so this must run once every plugin has had a chance to
        # register (http's on_boot_complete, after all plugin on_boot() calls).
        self.http.register_pre_mount_hook(self._check_route_collisions)

    def _check_tool_drift(self) -> list[str]:
        warnings = []
        # Methods defined in BaseTool or Python internals that shouldn't be documented
        IGNORED_METHODS = {
            "setup", "name", "get_interface_description", "on_boot_complete",
            "on_instrument", "shutdown", "on_boot"
        }

        for tool in self.container.get_raw_tools():
            desc = tool.get_interface_description()
            missing = []

            # Introspect all methods that don't start with '_'
            for method_name, _ in inspect.getmembers(tool, predicate=inspect.isroutine):
                if method_name.startswith("_") or method_name in IGNORED_METHODS:
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

    def _check_table_ownership(self) -> list[str]:
        """
        Scans domains/*/migrations/*.sql for CREATE TABLE statements and warns
        when the same table name is declared by more than one domain — the DB
        table namespace is global, so the second domain's IF NOT EXISTS silently
        no-ops against the first domain's schema instead of creating its own.
        """
        table_owners: dict[str, set[str]] = {}
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return []

        for domain in sorted(os.listdir(domains_dir)):
            migrations_dir = os.path.join(domains_dir, domain, "migrations")
            if not os.path.isdir(migrations_dir):
                continue
            for filename in sorted(os.listdir(migrations_dir)):
                if not filename.endswith(".sql"):
                    continue
                try:
                    with open(os.path.join(migrations_dir, filename), "r", encoding="utf-8") as f:
                        sql = f.read()
                except Exception as e:
                    self.logger.warning(f"[ArchLinter] Could not read {filename}: {e}")
                    continue
                for match in re.finditer(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?",
                    sql, re.IGNORECASE,
                ):
                    table_owners.setdefault(match.group(1).lower(), set()).add(domain)

        return [
            f"Table '{table}' is declared by multiple domains: {', '.join(sorted(owners))} "
            f"— the second CREATE TABLE IF NOT EXISTS silently no-ops."
            for table, owners in table_owners.items()
            if len(owners) > 1
        ]

    def _check_route_collisions(self, endpoints: list[dict]) -> None:
        """
        Groups the http tool's buffered endpoints by (method, path). Starlette
        routes to the first match, so more than one plugin registering the same
        route means every registration after the first is silently unreachable.
        Called by the http tool as a pre-mount hook (see register_pre_mount_hook),
        the first point where every plugin's add_endpoint() calls are guaranteed
        to have run. Advisory only — never blocks boot.
        """
        owners_by_route: dict[tuple[str, str], set[str]] = {}
        for ep in endpoints:
            key = (ep["method"].upper(), ep["path"])
            owners_by_route.setdefault(key, set()).add(ep["owner"])

        collisions = [
            f"Route collision: {method} {path} registered by {', '.join(sorted(owners))} "
            f"— only the first match is reachable."
            for (method, path), owners in owners_by_route.items()
            if len(owners) > 1
        ]

        if collisions:
            self.registry.register_domain_metadata("devtools", "route_collisions", collisions)
            for c in collisions:
                self.logger.warning(f"[ArchLinter] {c}")
        else:
            self.logger.info("[ArchLinter] No route collisions found.")
