import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.discovery_naming_linter_plugin import DiscoveryNamingLinterPlugin


def make_plugin():
    container = MagicMock()
    container.registry = MagicMock()
    return DiscoveryNamingLinterPlugin(container=container, logger=MagicMock())


@pytest.mark.anyio
async def test_real_repo_has_no_naming_violations():
    """CI gate: every tool and plugin class in the repo must be discoverable.

    A violation here means the Kernel silently skips a file that defines a tool
    or a plugin — the system boots without it and the only symptom appears far
    away, as a plugin reporting `Missing tools: x`.
    """
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_detects_tool_in_misnamed_file(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools" / "payments"
    tools_dir.mkdir(parents=True)
    (tools_dir / "gateway.py").write_text(
        "from microcoreos import BaseTool\n"
        "class PaymentGatewayTool(BaseTool):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    violations = make_plugin()._perform_scan()

    assert len(violations) == 1
    assert "PaymentGatewayTool(BaseTool)" in violations[0]
    assert "'_tool.py'" in violations[0]


@pytest.mark.anyio
async def test_detects_plugin_in_misnamed_file(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order.py").write_text(
        "from microcoreos import BasePlugin\n"
        "class PlaceOrderPlugin(BasePlugin):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    violations = make_plugin()._perform_scan()

    assert len(violations) == 1
    assert "PlaceOrderPlugin(BasePlugin)" in violations[0]
    assert "'_plugin.py'" in violations[0]


@pytest.mark.anyio
async def test_correctly_named_files_are_clean(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools" / "payments"
    tools_dir.mkdir(parents=True)
    (tools_dir / "payment_tool.py").write_text(
        "from microcoreos import BaseTool\n"
        "class PaymentTool(BaseTool):\n    pass\n",
        encoding="utf-8",
    )
    plugins_dir = tmp_path / "domains" / "orders" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "place_order_plugin.py").write_text(
        "from microcoreos import BasePlugin\n"
        "class PlaceOrderPlugin(BasePlugin):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_helper_modules_are_not_flagged(tmp_path, monkeypatch):
    """The split that motivated the naming rule: helper modules next to a tool
    define no discoverable class, so their name is nobody's business."""
    tools_dir = tmp_path / "tools" / "sqlite"
    tools_dir.mkdir(parents=True)
    (tools_dir / "errors.py").write_text(
        "from microcoreos import ToolUnavailableError\n"
        "class DatabaseError(Exception):\n    pass\n",
        encoding="utf-8",
    )
    (tools_dir / "transaction.py").write_text("class Transaction:\n    pass\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_optional_driver_is_not_flagged(tmp_path, monkeypatch):
    """A driver subclasses EventBusDriver, not BaseTool: it is loaded on demand
    by EVENT_BUS_DRIVER, never by Kernel discovery, so `*_driver.py` is correct."""
    bus_dir = tmp_path / "tools" / "event_bus"
    bus_dir.mkdir(parents=True)
    (bus_dir / "redis_streams_driver.py").write_text(
        "from tools.event_bus.event_bus_tool import EventBusDriver\n"
        "class RedisStreamsDriver(EventBusDriver):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._perform_scan() == []


@pytest.mark.anyio
async def test_extras_are_scanned(tmp_path, monkeypatch):
    """extras/ files are activated by moving them into tools/ — a wrong name
    there is a bug that only detonates the day someone swaps it in."""
    extras_dir = tmp_path / "extras" / "available_tools" / "mongo"
    extras_dir.mkdir(parents=True)
    (extras_dir / "mongo.py").write_text(
        "from microcoreos import BaseTool\n"
        "class MongoTool(BaseTool):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    violations = make_plugin()._perform_scan()

    assert len(violations) == 1
    assert "MongoTool(BaseTool)" in violations[0]
