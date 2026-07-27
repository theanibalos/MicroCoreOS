import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.event_schemas_plugin import EventSchemasPlugin

# A synthetic domain/plugin pair, isolated from any real business domain.
# devtools tests must never depend on a specific domain existing on disk —
# only flow/e2e tests are allowed to know about concrete business plugins.
FIXTURE_SOURCE = '''\
from pydantic import BaseModel


class SamplePayload(BaseModel):
    id: int
    email: str
    roles: list[str]
'''


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fixture_domain(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "fixture" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "sample_publisher.py").write_text(FIXTURE_SOURCE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


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
async def test_catalog_builds_real_json_schema_from_publisher_plugin(fixture_domain):
    """Loads a real plugin file from disk and extracts its payload's JSON Schema."""
    plugin = make_plugin([{
        "event": "sample.created",
        "model": "SamplePayload",
        "domain": "fixture",
        "file": "sample_publisher.py",
    }])
    result = await plugin.get_schemas({})

    assert result["success"] is True
    catalog = result["data"]["schemas"]
    assert "sample.created" in catalog
    entry = catalog["sample.created"][0]
    assert entry["model"] == "SamplePayload"
    assert entry["domain"] == "fixture"
    props = entry["json_schema"]["properties"]
    assert set(props) == {"id", "email", "roles"}
    assert set(entry["json_schema"]["required"]) == {"id", "email", "roles"}


@pytest.mark.anyio
async def test_missing_model_is_skipped_not_fatal(fixture_domain):
    plugin = make_plugin([{
        "event": "ghost.event",
        "model": "DoesNotExist",
        "domain": "fixture",
        "file": "sample_publisher.py",
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
async def test_duplicate_entries_are_collapsed(fixture_domain):
    entry = {
        "event": "sample.created",
        "model": "SamplePayload",
        "domain": "fixture",
        "file": "sample_publisher.py",
    }
    plugin = make_plugin([entry, dict(entry)])
    result = await plugin.get_schemas({})
    assert len(result["data"]["schemas"]["sample.created"]) == 1
