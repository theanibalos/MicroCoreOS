import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.event_schemas_plugin import EventSchemasPlugin


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_plugin(metadata):
    container = MagicMock()
    container.registry.get_domain_metadata.return_value = {
        "devtools": {"event_payload_models": metadata}
    }
    return EventSchemasPlugin(container=container, http=MagicMock(), logger=MagicMock())


@pytest.mark.anyio
async def test_boot_registers_endpoint():
    plugin = make_plugin([])
    await plugin.on_boot()
    args, _ = plugin.http.add_endpoint.call_args
    assert args[0] == "/system/events/schemas"
    assert args[1] == "GET"


@pytest.mark.anyio
async def test_catalog_builds_real_json_schema_from_publisher_plugin():
    """Loads a real publisher of this repo and extracts its payload's JSON Schema."""
    plugin = make_plugin([{
        "event": "user.created",
        "model": "UserCreatedPayload",
        "domain": "users",
        "file": "create_user_plugin.py",
    }])
    result = await plugin.get_schemas({})

    assert result["success"] is True
    catalog = result["data"]["schemas"]
    assert "user.created" in catalog
    entry = catalog["user.created"][0]
    assert entry["model"] == "UserCreatedPayload"
    assert entry["domain"] == "users"
    props = entry["json_schema"]["properties"]
    assert set(props) == {"id", "email", "roles"}
    assert set(entry["json_schema"]["required"]) == {"id", "email", "roles"}


@pytest.mark.anyio
async def test_missing_model_is_skipped_not_fatal():
    plugin = make_plugin([{
        "event": "ghost.event",
        "model": "DoesNotExist",
        "domain": "users",
        "file": "create_user_plugin.py",
    }])
    result = await plugin.get_schemas({})
    assert result["success"] is True
    assert result["data"]["schemas"] == {}
    plugin.logger.warning.assert_called()


@pytest.mark.anyio
async def test_catalog_is_cached_after_first_request():
    plugin = make_plugin([])
    await plugin.get_schemas({})
    await plugin.get_schemas({})
    assert plugin.registry.get_domain_metadata.call_count == 1


@pytest.mark.anyio
async def test_duplicate_entries_are_collapsed():
    entry = {
        "event": "user.created",
        "model": "UserCreatedPayload",
        "domain": "users",
        "file": "create_user_plugin.py",
    }
    plugin = make_plugin([entry, dict(entry)])
    result = await plugin.get_schemas({})
    assert len(result["data"]["schemas"]["user.created"]) == 1
