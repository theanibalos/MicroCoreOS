import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.system_lint_plugin import SystemLintPlugin
from microcoreos_dev.lint.checkers.routes import check_route_collisions


def make_plugin(http=None):
    container = MagicMock()
    container.registry = MagicMock()
    return SystemLintPlugin(
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

    mock_http.register_pre_mount_hook.assert_called_once_with(plugin._check_runtime_route_collisions)


def test_detects_route_collision_runtime():
    plugin = make_plugin()
    plugin._cache = MagicMock()
    plugin._cache.route_collisions = []
    plugin._check_runtime_route_collisions([
        _endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _endpoint("GET", "/users/me", "billing.AccountPlugin"),
    ])

    calls = [
        call.args for call in plugin.registry.register_domain_metadata.call_args_list
        if call.args[0] == "devtools" and call.args[1] == "route_collisions"
    ]
    assert len(calls) == 1
    domain, key, collisions = calls[0]
    assert domain == "devtools"
    assert key == "route_collisions"
    assert len(collisions) == 1
    assert "GET /users/me" in collisions[0]
    assert "users.ProfilePlugin" in collisions[0]
    assert "billing.AccountPlugin" in collisions[0]


def test_no_collision_for_distinct_routes_runtime():
    plugin = make_plugin()
    plugin._cache = MagicMock()
    plugin._cache.route_collisions = []
    plugin._check_runtime_route_collisions([
        _endpoint("GET", "/users/me", "users.ProfilePlugin"),
        _endpoint("POST", "/users/me", "users.ProfilePlugin"),
        _endpoint("GET", "/billing/invoice", "billing.AccountPlugin"),
    ])

    calls = [
        call.args for call in plugin.registry.register_domain_metadata.call_args_list
        if call.args[0] == "devtools" and call.args[1] == "route_collisions"
    ]
    assert len(calls) == 0


def test_static_route_collision_detection(tmp_path):
    p1 = tmp_path / "domains" / "users" / "plugins"
    p1.mkdir(parents=True)
    (p1 / "profile_plugin.py").write_text(
        "class ProfilePlugin:\n"
        "    def on_boot(self):\n"
        "        self.http.add_endpoint('/users/me', 'GET', self.get_profile)\n",
        encoding="utf-8",
    )
    p2 = tmp_path / "domains" / "billing" / "plugins"
    p2.mkdir(parents=True)
    (p2 / "account_plugin.py").write_text(
        "class AccountPlugin:\n"
        "    def on_boot(self):\n"
        "        self.http.add_endpoint('/users/me', 'GET', self.get_account)\n",
        encoding="utf-8",
    )

    findings = check_route_collisions(root=str(tmp_path))
    assert len(findings) == 1
    assert any("GET /users/me" in f.message for f in findings)
