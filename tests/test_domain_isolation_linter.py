import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.domain_isolation_linter_plugin import DomainIsolationLinterPlugin


def make_plugin():
    container = MagicMock()
    container.registry = MagicMock()
    return DomainIsolationLinterPlugin(container=container, logger=MagicMock())


@pytest.mark.anyio
async def test_real_repo_has_no_isolation_violations():
    """CI gate: domain isolation over the actual codebase must be clean.

    Runs the same scan the linter performs at boot (cross-domain imports,
    hardcoded tool imports) against the real domains/ tree. A violation here
    fails the suite — and therefore CI — instead of only warning at boot.
    """
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_detects_cross_domain_import(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order_plugin.py").write_text(
        "from domains.users.models.user import UserEntity\n"
    )

    monkeypatch.chdir(tmp_path)
    violations = make_plugin()._perform_scan()

    assert len(violations) == 1
    assert "Illegal cross-domain import" in violations[0]
    assert "domains.users.models.user" in violations[0]


@pytest.mark.anyio
async def test_same_domain_import_is_allowed(tmp_path, monkeypatch):
    """A domain's plugins speak their own domain's vocabulary — that is what
    domains/<domain>/models/ exists for. Only OTHER domains are off limits."""
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "from microcoreos import BasePlugin\n"
        "from domains.users.models.user import DEFAULT_ROLES\n"
    )

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_detects_hardcoded_tool_import(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "users" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "create_user_plugin.py").write_text(
        "from tools.sqlite.sqlite_tool import SqliteTool\n"
    )

    monkeypatch.chdir(tmp_path)
    violations = make_plugin()._perform_scan()

    assert len(violations) == 1
    assert "Illegal hardcoded tool import" in violations[0]


@pytest.mark.anyio
async def test_on_boot_publishes_violations_to_registry(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order_plugin.py").write_text("import domains.users.models.user\n")

    monkeypatch.chdir(tmp_path)
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    plugin = DomainIsolationLinterPlugin(container=container, logger=MagicMock())

    await plugin.on_boot()

    registry.register_domain_metadata.assert_called_once()
    domain, key, violations = registry.register_domain_metadata.call_args[0]
    assert (domain, key) == ("devtools", "arch_violations")
    assert len(violations) == 1
