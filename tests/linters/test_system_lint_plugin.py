import pytest
from unittest.mock import MagicMock
from domains.devtools.plugins.system_lint_plugin import SystemLintPlugin


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_system_lint_plugin_on_boot_and_endpoint():
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    logger = MagicMock()
    http = MagicMock()

    plugin = SystemLintPlugin(container=container, logger=logger, http=http)
    await plugin.on_boot()

    # Verify endpoint registration
    http.add_endpoint.assert_called_once()
    args, kwargs = http.add_endpoint.call_args
    assert args[0] == "/system/lint"
    assert args[1] == "GET"
    assert args[2] == plugin.get_lint

    # Verify registry metadata calls
    registered_keys = {
        call.args[1]
        for call in registry.register_domain_metadata.call_args_list
        if call.args[0] == "devtools"
    }
    assert "event_payload_models" in registered_keys
    assert "arch_violations" in registered_keys
    assert "event_contract_violations" in registered_keys
    assert "discovery_naming_violations" in registered_keys
    assert "drift_warnings" in registered_keys
    assert "route_collisions" in registered_keys
    assert "table_ownership_warnings" in registered_keys
    assert "field_divergence_warnings" in registered_keys

    # Call get_lint
    response = await plugin.get_lint({})
    assert response["success"] is True
    data = response["data"]
    assert "arch_violations" in data
    assert "event_contract_violations" in data
    assert "discovery_naming_violations" in data
    assert "drift_warnings" in data
    assert "route_collisions" in data
    assert "table_ownership_warnings" in data
    assert "field_divergence_warnings" in data


@pytest.mark.anyio
async def test_runtime_route_collisions_hook():
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    logger = MagicMock()
    http = MagicMock()

    plugin = SystemLintPlugin(container=container, logger=logger, http=http)
    await plugin.on_boot()

    plugin._check_runtime_route_collisions([
        {"method": "GET", "path": "/test/path", "owner": "a.PluginA"},
        {"method": "GET", "path": "/test/path", "owner": "b.PluginB"},
    ])

    response = await plugin.get_lint({})
    assert any("GET /test/path" in c for c in response["data"]["route_collisions"])
