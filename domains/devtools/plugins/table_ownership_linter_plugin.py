"""Table ownership: one table, one owning domain (Issue 27).

One of the linters split out of the former ArchitectureLinterPlugin.

Registry key: devtools/table_ownership_warnings (read by GET /system/lint).
"""

import os
import re
from microcoreos import BasePlugin


class TableOwnershipLinterPlugin(BasePlugin):
    """
    Scans domains/*/migrations/*.sql for CREATE TABLE statements and warns when
    the same table name is declared by more than one domain.

    The DB table namespace is global, so the second domain's IF NOT EXISTS
    silently no-ops against the first domain's schema instead of creating its
    own — the second domain then reads and writes columns it never declared.
    """

    def __init__(self, container, logger):
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        table_warnings = self._check_table_ownership()
        if table_warnings:
            self.registry.register_domain_metadata("devtools", "table_ownership_warnings", table_warnings)
            for w in table_warnings:
                self.logger.warning(f"[TableOwnershipLinter] {w}")
        else:
            self.logger.info("[TableOwnershipLinter] Table ownership verified. No duplicate declarations found.")

    def _check_table_ownership(self) -> list[str]:
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
                    self.logger.warning(f"[TableOwnershipLinter] Could not read {filename}: {e}")
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
