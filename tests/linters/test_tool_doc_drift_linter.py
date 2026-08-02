import pytest
from unittest.mock import MagicMock

from microcoreos import BaseTool
from domains.devtools.plugins.tool_doc_drift_linter_plugin import ToolDocDriftLinterPlugin


class MockDriftTool(BaseTool):
    @property
    def name(self): return "drift_tool"
    async def setup(self): pass
    def get_interface_description(self):
        return "This tool has documented_method"

    def documented_method(self): pass
    def undocumented_method(self): pass


@pytest.mark.anyio
async def test_detects_drift():
    mock_container = MagicMock()
    mock_registry = MagicMock()
    mock_container.registry = mock_registry
    mock_container.get_raw_tools.return_value = [MockDriftTool()]

    plugin = ToolDocDriftLinterPlugin(container=mock_container, logger=MagicMock())
    warnings = plugin._check_tool_drift()

    assert any("'undocumented_method'" in w for w in warnings)
    assert not any("'documented_method'" in w for w in warnings)

    mock_registry.update_tool_status.assert_called_with(
        "drift_tool",
        "WARNING",
        "Documentation drift: missing 'undocumented_method'"
    )


@pytest.mark.anyio
async def test_lifecycle_methods_are_never_faulted():
    """setup/shutdown/name & co. are BaseTool plumbing, not capabilities."""
    class BareTool(BaseTool):
        @property
        def name(self): return "bare"
        async def setup(self): pass
        def get_interface_description(self): return "Does nothing."

    mock_container = MagicMock()
    mock_container.registry = MagicMock()
    mock_container.get_raw_tools.return_value = [BareTool()]

    plugin = ToolDocDriftLinterPlugin(container=mock_container, logger=MagicMock())
    assert plugin._check_tool_drift() == []
