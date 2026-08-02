import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.route_collision_linter_plugin import RouteCollisionLinterPlugin


def make_plugin(http=None):
    container = MagicMock()
    container.registry = MagicMock()
    return RouteCollisionLinterPlugin(
        container=container, logger=MagicMock(), http=http or MagicMock()
    )


def _endpoint(method, path, owner):
    return {"method": method, "path": path, "owner": owner}


@pytest.mark.anyio
async def test_on_boot_registers_pre_mount_hook():
    """Wiring check: on_boot() must hand the collision check to the http tool
    as a pre-mount hook, since add_endpoint only buffers and the full picture
    is only available once every plugin's on_boot() has run."""
    mock_http = MagicMock()
    plugin = make_plugin(http=mock_http)

    await plugin.on_boot()

    mock_http.register_pre_mount_hook.assert_called_once_with(plugin._check_route_collisions)


def test_detects_route_collision():
    plugin = make_plugin()
    plugin._check_route_collisions([
        _endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _endpoint("GET", "/users/me", "billing.AccountPlugin"),
    ])

    plugin.registry.register_domain_metadata.assert_called_once()
    domain, key, collisions = plugin.registry.register_domain_metadata.call_args[0]
    assert domain == "devtools"
    assert key == "route_collisions"
    assert len(collisions) == 1
    assert "GET /users/me" in collisions[0]
    assert "users.ProfilePlugin" in collisions[0]
    assert "billing.AccountPlugin" in collisions[0]


def test_no_collision_for_distinct_routes():
    plugin = make_plugin()
    plugin._check_route_collisions([
        _endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _endpoint("POST", "/users/me", "users.ProfilePlugin"),
        _endpoint("GET", "/billing/invoice", "billing.AccountPlugin"),
    ])

    plugin.registry.register_domain_metadata.assert_not_called()


def test_same_owner_twice_is_still_a_collision():
    """Starlette routes to the first match regardless of who registered it."""
    plugin = make_plugin()
    plugin._check_route_collisions([
        _endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _endpoint("get", "/users/me", "users.OtherPlugin"),
    ])

    _, _, collisions = plugin.registry.register_domain_metadata.call_args[0]
    assert len(collisions) == 1
