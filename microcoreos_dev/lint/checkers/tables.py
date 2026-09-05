"""Table ownership checker.

Scans domains/*/migrations/*.sql for CREATE TABLE statements and warns when
the same table name is declared by more than one domain.
"""

import os
import re
from microcoreos_dev.lint.schema import CheckFinding


def check_table_ownership(
    root: str = ".",
    domains_dir: str = "domains",
) -> list[CheckFinding]:
    """Scan domain migrations for duplicate table declarations."""
    table_owners: dict[str, set[str]] = {}
    findings: list[CheckFinding] = []

    base_dir = os.path.join(root, domains_dir) if not os.path.isabs(domains_dir) else domains_dir
    if not os.path.isdir(base_dir):
        return findings

    for domain in sorted(os.listdir(base_dir)):
        migrations_dir = os.path.join(base_dir, domain, "migrations")
        if not os.path.isdir(migrations_dir):
            continue
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith(".sql"):
                continue
            filepath = os.path.join(migrations_dir, filename)
            relpath = os.path.relpath(filepath, root)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    sql = f.read()
            except Exception as e:
                findings.append(
                    CheckFinding(
                        checker="table_ownership",
                        code="TABLE_SCAN_ERROR",
                        severity="error",
                        message=f"Could not read {relpath}: {e}",
                        file=relpath,
                    )
                )
                continue

            for match in re.finditer(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?",
                sql, re.IGNORECASE,
            ):
                table_owners.setdefault(match.group(1).lower(), set()).add(domain)

    for table, owners in sorted(table_owners.items()):
        if len(owners) > 1:
            sorted_owners = sorted(owners)
            findings.append(
                CheckFinding(
                    checker="table_ownership",
                    code="TABLE_OWNERSHIP_COLLISION",
                    severity="error",
                    message=(
                        f"Table '{table}' is declared by multiple domains: {', '.join(sorted_owners)} "
                        f"— the second CREATE TABLE IF NOT EXISTS silently no-ops."
                    ),
                    file=None,
                )
            )

    return findings
