import pytest
from unittest.mock import MagicMock
from domains.devtools.plugins.architecture_linter_plugin import ArchitectureLinterPlugin
from core.base_tool import BaseTool

class MockDriftTool(BaseTool):
    @property
    def name(self): return "drift_tool"
    async def setup(self): pass
    def get_interface_description(self):
        return "This tool has documented_method"
    
    def documented_method(self): pass
    def undocumented_method(self): pass

@pytest.mark.anyio
async def test_arch_linter_detects_drift():
    # 1. Setup Container with a tool that has drift
    mock_container = MagicMock()
    mock_registry = MagicMock()
    mock_container.registry = mock_registry
    
    tool = MockDriftTool()
    mock_container.get_raw_tools.return_value = [tool]
    
    mock_logger = MagicMock()
    
    # 2. Initialize Plugin
    plugin = ArchitectureLinterPlugin(container=mock_container, logger=mock_logger, http=MagicMock())
    
    # 3. Perform drift check
    warnings = plugin._check_tool_drift()

    # 4. Assertions
    assert any("'undocumented_method'" in w for w in warnings)
    assert not any("'documented_method'" in w for w in warnings)
    
    # Verify registry was updated with WARNING
    mock_registry.update_tool_status.assert_called_with(
        "drift_tool",
        "WARNING",
        "Documentation drift: missing 'undocumented_method'"
    )


@pytest.mark.anyio
async def test_on_boot_registers_route_collision_hook():
    """Wiring check: on_boot() must hand its collision check to the http
    tool as a pre-mount hook (register_pre_mount_hook), since add_endpoint
    only buffers and the full picture is only available once every plugin's
    on_boot() has run."""
    mock_container = MagicMock()
    mock_container.registry = MagicMock()
    mock_container.get_raw_tools.return_value = []
    mock_http = MagicMock()

    plugin = ArchitectureLinterPlugin(container=mock_container, logger=MagicMock(), http=mock_http)
    await plugin.on_boot()

    mock_http.register_pre_mount_hook.assert_called_once_with(plugin._check_route_collisions)


@pytest.mark.anyio
async def test_real_repo_has_no_isolation_violations():
    """CI gate: domain isolation over the actual codebase must be clean.

    Runs the same scan the linter performs at boot (cross-domain imports,
    hardcoded tool imports) against the real domains/ tree. A violation here
    fails the suite — and therefore CI — instead of only warning at boot.
    """
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    violations = plugin._perform_scan()
    assert violations == []


@pytest.mark.anyio
async def test_real_repo_has_no_duplicate_tables():
    """CI gate: table ownership over the actual codebase must be clean.

    Runs the same scan the linter performs at boot (CREATE TABLE names across
    domains/*/migrations/*.sql) against the real domains/ tree. A duplicate
    table declared by more than one domain here fails the suite instead of
    only warning at boot.
    """
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    warnings = plugin._check_table_ownership()
    assert warnings == []


@pytest.mark.anyio
async def test_arch_linter_detects_table_collision(tmp_path, monkeypatch):
    # Two domains declaring the same table name.
    domain_a = tmp_path / "domains" / "domain_a" / "migrations"
    domain_b = tmp_path / "domains" / "domain_b" / "migrations"
    domain_a.mkdir(parents=True)
    domain_b.mkdir(parents=True)
    (domain_a / "001_create_widgets.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);"
    )
    (domain_b / "001_create_widgets.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);"
    )

    monkeypatch.chdir(tmp_path)
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    warnings = plugin._check_table_ownership()

    assert len(warnings) == 1
    assert "widgets" in warnings[0]
    assert "domain_a" in warnings[0]
    assert "domain_b" in warnings[0]


@pytest.mark.anyio
async def test_arch_linter_no_table_collision(tmp_path, monkeypatch):
    # Two domains declaring different tables — no collision.
    domain_a = tmp_path / "domains" / "domain_a" / "migrations"
    domain_b = tmp_path / "domains" / "domain_b" / "migrations"
    domain_a.mkdir(parents=True)
    domain_b.mkdir(parents=True)
    (domain_a / "001_create_widgets.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);"
    )
    (domain_b / "001_create_gadgets.sql").write_text(
        "CREATE TABLE IF NOT EXISTS gadgets (id INTEGER PRIMARY KEY);"
    )

    monkeypatch.chdir(tmp_path)
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    warnings = plugin._check_table_ownership()

    assert warnings == []


def _make_endpoint(method, path, owner):
    return {"method": method, "path": path, "owner": owner}


def test_arch_linter_detects_route_collision():
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    mock_registry = MagicMock()
    plugin.registry = mock_registry

    endpoints = [
        _make_endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _make_endpoint("GET", "/users/me", "billing.AccountPlugin"),
    ]
    plugin._check_route_collisions(endpoints)

    mock_registry.register_domain_metadata.assert_called_once()
    args, _ = mock_registry.register_domain_metadata.call_args
    domain, key, collisions = args
    assert domain == "devtools"
    assert key == "route_collisions"
    assert len(collisions) == 1
    assert "GET /users/me" in collisions[0]
    assert "users.ProfilePlugin" in collisions[0]
    assert "billing.AccountPlugin" in collisions[0]


def test_arch_linter_no_route_collision():
    plugin = ArchitectureLinterPlugin(container=MagicMock(), logger=MagicMock(), http=MagicMock())
    mock_registry = MagicMock()
    plugin.registry = mock_registry

    endpoints = [
        _make_endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _make_endpoint("POST", "/users/me", "users.ProfilePlugin"),
        _make_endpoint("GET", "/billing/invoice", "billing.AccountPlugin"),
    ]
    plugin._check_route_collisions(endpoints)

    mock_registry.register_domain_metadata.assert_not_called()
