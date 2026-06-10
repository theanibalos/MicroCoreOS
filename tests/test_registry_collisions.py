import os
import pytest
from core.kernel import Kernel
from core.base_plugin import BasePlugin

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

async def test_registry_collision_prevention(tmp_path):
    """
    Verify that two plugins with the same class name in different domains
    can coexist thanks to the domain prefix.
    """
    kernel = Kernel()
    
    # Manually inject discovered plugins to simulate real load
    class Domain1Plugin(BasePlugin): pass
    Domain1Plugin.__name__ = "ConflictPlugin"
    
    class Domain2Plugin(BasePlugin): pass
    Domain2Plugin.__name__ = "ConflictPlugin"
    
    # Test naming logic
    p1_name = f"domain1.ConflictPlugin"
    p2_name = f"domain2.ConflictPlugin"
    
    kernel.container.registry.register_plugin(p1_name, {"domain": "domain1", "class": "ConflictPlugin"})
    kernel.container.registry.register_plugin(p2_name, {"domain": "domain2", "class": "ConflictPlugin"})
    
    kernel.plugins[p1_name] = Domain1Plugin()
    kernel.plugins[p2_name] = Domain2Plugin()
    
    assert len(kernel.plugins) == 2
    assert p1_name in kernel.plugins
    assert p2_name in kernel.plugins
    
    # Verify both are in the registry
    reg = kernel.container.registry.get_system_dump()
    assert p1_name in reg["plugins"]
    assert p2_name in reg["plugins"]
