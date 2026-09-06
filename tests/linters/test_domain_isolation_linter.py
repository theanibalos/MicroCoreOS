import pytest
from unittest.mock import MagicMock

from microcoreos_dev.lint.checkers.isolation import check_domain_isolation
from domains.devtools.plugins.system_lint_plugin import SystemLintPlugin


def test_real_repo_has_no_isolation_violations():
    """CI gate: domain isolation over the actual codebase must be clean.

    Runs the same scan the linter performs at boot (cross-domain imports,
    hardcoded tool imports) against the real domains/ tree. A violation here
    fails the suite — and therefore CI — instead of only warning at boot.
    """
    assert check_domain_isolation() == []


def test_detects_cross_domain_import(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order_plugin.py").write_text(
        "from domains.users.models.user import UserEntity\n",
        encoding="utf-8",
    )

    findings = check_domain_isolation(root=str(tmp_path))
    violations = [f.message for f in findings]

    assert len(violations) == 1
    assert "Illegal cross-domain import" in violations[0]
    assert "domains.users.models.user" in violations[0]


def test_same_domain_import_is_allowed(tmp_path, monkeypatch):
    """A domain's plugins speak their own domain's vocabulary — that is what
    domains/<domain>/models/ exists for. Only OTHER domains are off limits."""
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "from microcoreos import BasePlugin\n"
        "from domains.users.models.user import DEFAULT_ROLES\n",
        encoding="utf-8",
    )

    assert check_domain_isolation(root=str(tmp_path)) == []


def test_detects_hardcoded_tool_import_from_syntax(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "from tools.sqlite.sqlite_tool import SqliteTool\n"
        "from tools import db\n",
        encoding="utf-8",
    )

    findings = check_domain_isolation(root=str(tmp_path))
    violations = [f.message for f in findings]

    assert len(violations) == 2
    assert all("Illegal hardcoded tool import" in v for v in violations)
    assert any("from tools.sqlite.sqlite_tool" in v for v in violations)
    assert any("from tools" in v for v in violations)


def test_detects_hardcoded_tool_import_statement_syntax(tmp_path, monkeypatch):
    """
    Issue 46: 'import tools.x' and 'import tools.x as alias' must be rejected
    equally alongside 'from tools.x import ...'.
    """
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "import tools.sqlite.sqlite_tool\n"
        "import tools.db as db\n"
        "import tools\n",
        encoding="utf-8",
    )

    findings = check_domain_isolation(root=str(tmp_path))
    violations = [f.message for f in findings]

    assert len(violations) == 3
    assert all("Illegal hardcoded tool import" in v for v in violations)
    assert any("import tools.sqlite.sqlite_tool" in v for v in violations)
    assert any("import tools.db" in v for v in violations)
    assert any("import tools" in v for v in violations)


def test_third_party_and_stdlib_imports_allowed(tmp_path, monkeypatch):
    """
    Standard library (os, json) and third-party libraries (httpx, pydantic)
    are permitted and not treated as tool imports.
    """
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "import os\n"
        "import json\n"
        "import httpx\n"
        "from pydantic import BaseModel\n",
        encoding="utf-8",
    )

    violations = check_domain_isolation(root=str(tmp_path))
    assert violations == []


@pytest.mark.anyio
async def test_on_boot_publishes_violations_to_registry(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order_plugin.py").write_text("import domains.users.models.user\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    plugin = SystemLintPlugin(container=container, logger=MagicMock(), http=MagicMock())

    await plugin.on_boot()

    calls = [
        call.args for call in registry.register_domain_metadata.call_args_list
        if call.args[0] == "devtools" and call.args[1] == "arch_violations"
    ]
    assert len(calls) == 1
    domain, key, violations = calls[0]
    assert (domain, key) == ("devtools", "arch_violations")
    assert len(violations) == 1
