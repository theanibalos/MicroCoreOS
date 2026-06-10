import pytest
from unittest.mock import MagicMock
from domains.system.plugins.architecture_linter_plugin import ArchitectureLinterPlugin
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
    plugin = ArchitectureLinterPlugin(container=mock_container, logger=mock_logger)
    
    # 3. Perform drift check
    warnings = plugin._check_tool_drift()
    print(f"DEBUG WARNINGS: {warnings}")
    
    # 4. Assertions
    assert any("'undocumented_method'" in w for w in warnings)
    assert not any("'documented_method'" in w for w in warnings)
    
    # Verify registry was updated with WARNING
    mock_registry.update_tool_status.assert_called_with(
        "drift_tool", 
        "WARNING", 
        "Documentation drift: missing 'undocumented_method'"
    )
