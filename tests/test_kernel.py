import os
import pytest
import asyncio
import importlib
from microcoreos.kernel import Kernel
from microcoreos import BasePlugin
from microcoreos import BaseTool

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

class DummyTool(BaseTool):
    @property
    def name(self) -> str:
        return "dummy"
    
    async def setup(self):
        # Simulate an async process to verify parallelism
        await asyncio.sleep(0.01)
        self.ready = True
        
    def get_interface_description(self) -> str:
        return "Dummy Tool"
        
    async def shutdown(self):
        pass
        
    async def on_boot_complete(self, container):
        self.boot_completed = True

class DummyPlugin(BasePlugin):
    def __init__(self, dummy: DummyTool):
        self.dummy = dummy
        self.booted = False
        
    async def on_boot(self):
        await asyncio.sleep(0.01)
        self.booted = True

@pytest.fixture
def kernel():
    return Kernel()

# ─── 1. Pruebas de Dependency Injection ──────────────────────────────────────

def test_resolve_dependencies_success(kernel):
    # Simulamos que el container ya tiene el tool cargado
    dummy_instance = DummyTool()
    kernel.container.register(dummy_instance)
    
    deps, missing = kernel._resolve_plugin_dependencies(DummyPlugin)
    
    assert "dummy" in deps
    assert not missing
    # The tool's proxy should be injected, not the raw instance
    assert deps["dummy"]._tool is dummy_instance

def test_resolve_dependencies_missing(kernel):
    # Intentamos resolver dependencias de un plugin cuyo tool no existe
    deps, missing = kernel._resolve_plugin_dependencies(DummyPlugin)
    
    assert "dummy" not in deps
    assert "dummy" in missing

# ─── 2. Execution Tests (Call Maybe Async) ───────────────────────────────────

async def test_call_maybe_async(kernel):
    def sync_fn(): 
        return "sync_result"
        
    async def async_fn(): 
        return "async_result"
        
    res_sync = await kernel._call_maybe_async(sync_fn)
    res_async = await kernel._call_maybe_async(async_fn)
    
    assert res_sync == "sync_result"
    assert res_async == "async_result"

# ─── 3. Pruebas del Ciclo de Vida (Boot) ─────────────────────────────────────

async def test_boot_success(kernel, monkeypatch):
    """Prueba que el kernel arranque tools y plugins correctamente cuando todo existe."""
    
    def fake_load_modules(directory, base_class, suffix):
        if base_class == BaseTool:
            return [(DummyTool, None)]
        elif base_class == BasePlugin:
            return [(DummyPlugin, "dummy_domain")]
        return []

    monkeypatch.setattr(kernel, "_load_modules_from_dir", fake_load_modules)
    
    await kernel.boot()
    
    # Verificamos tool
    assert kernel.container.has_tool("dummy")
    assert kernel.container.get("dummy").ready is True
    assert kernel.container.get("dummy").boot_completed is True
    assert kernel.container.registry.get_tool_status("dummy") == "OK"
    
    # Verificamos plugin
    p_name = "dummy_domain.DummyPlugin"
    assert p_name in kernel.plugins
    assert kernel.plugins[p_name].booted is True
    assert kernel.container.registry.get_system_dump()["plugins"][p_name]["status"] == "READY"

async def test_boot_missing_dependencies(kernel, monkeypatch):
    """Verifies that when a tool required by a plugin is missing, the plugin is marked DEAD without blocking boot."""
    
    def fake_load_modules(directory, base_class, suffix):
        # Load the plugin but no tools
        if base_class == BaseTool:
            return []
        elif base_class == BasePlugin:
            return [(DummyPlugin, "dummy_domain")]
        return []

    monkeypatch.setattr(kernel, "_load_modules_from_dir", fake_load_modules)
    
    await kernel.boot()
    
    p_name = "dummy_domain.DummyPlugin"
    assert p_name not in kernel.plugins
    status = kernel.container.registry.get_system_dump()["plugins"][p_name]["status"]
    assert status == "DEAD"
    
    # An error should be recorded in the registry
    dump = kernel.container.registry.get_system_dump()
    assert "Missing tools: dummy" in dump["plugins"][p_name]["error"]


async def test_boot_tool_single_mode(kernel):
    """Pipeline entry point: boot ONE tool in isolation and exit."""
    await kernel.boot_tool("db")

    with pytest.raises(RuntimeError, match="No tool named"):
        await kernel.boot_tool("non_existent_tool_999")


async def test_shutdown_error_resilience(kernel):
    """Shutdown swallows exceptions in individual plugins and tools to guarantee complete teardown."""
    class FaultyPlugin(BasePlugin):
        async def shutdown(self):
            raise RuntimeError("Plugin shutdown exception")

    class CleanTool(BaseTool):
        @property
        def name(self) -> str:
            return "clean_tool"
        async def setup(self):
            pass
        def get_interface_description(self) -> str:
            return ""
        async def shutdown(self):
            pass

    class FaultyTool(BaseTool):
        @property
        def name(self) -> str:
            return "faulty_tool"
        async def setup(self):
            pass
        def get_interface_description(self) -> str:
            return ""
        async def shutdown(self):
            raise RuntimeError("Tool shutdown exception")

    kernel.container.register(CleanTool())
    kernel.container.register(FaultyTool())
    kernel.plugins["faulty"] = FaultyPlugin()
    await kernel.shutdown()


async def test_kernel_error_branches_and_edge_cases(kernel, monkeypatch):
    """Hits all exception handling and edge-case branches in Kernel to reach 100% coverage."""
    # 1. Test _load_modules_from_dir outside import root (using real parent dir)
    parent_dir = os.path.dirname(os.getcwd())
    res_outside = kernel._load_modules_from_dir(parent_dir, BaseTool, "_tool.py")
    assert res_outside == []

    res_non_exist = kernel._load_modules_from_dir("non_existent_directory_abc", BaseTool, "_tool.py")
    assert res_non_exist == []

    # 1b. Test _load_modules_from_dir when importlib raises Exception and with domains dir
    real_import = importlib.import_module
    def faulty_import(name):
        if "system_events_plugin" in name:
            raise RuntimeError("Simulated module import error")
        return real_import(name)

    monkeypatch.setattr("importlib.import_module", faulty_import)
    # Scan real domains directory to hit line 79 and line 86-87
    domain_mods = kernel._load_modules_from_dir("domains", BasePlugin, "_plugin.py")
    assert isinstance(domain_mods, list)
    assert len(domain_mods) > 0
    for cls, d_name in domain_mods:
        assert d_name in ("system", "devtools", "ping", "users")
        assert d_name is not None
        assert d_name != ""

    domain_mods_dot = kernel._load_modules_from_dir("./domains", BasePlugin, "_plugin.py")
    assert len(domain_mods_dot) == len(domain_mods)

    tool_mods = kernel._load_modules_from_dir("tools", BaseTool, "_tool.py")
    assert len(tool_mods) > 0
    for cls, d_name in tool_mods:
        assert d_name is None

    tool_mods_dot = kernel._load_modules_from_dir("./tools", BaseTool, "_tool.py")
    assert len(tool_mods_dot) == len(tool_mods)

    # 1c. Test _call_maybe_async with sync function returning a coroutine
    async def _async_target(a, b, c=10):
        import threading
        assert threading.current_thread() is threading.main_thread()
        return a + b + c

    def _sync_target(a, b, c=10):
        return a + b + c

    def _sync_returning_coro(a, b, c=10):
        return _async_target(a, b, c)

    res_async = await kernel._call_maybe_async(_async_target, 1, 2, c=3)
    assert res_async == 6

    res_sync = await kernel._call_maybe_async(_sync_target, 10, 20, c=30)
    assert res_sync == 60

    res_coro = await kernel._call_maybe_async(_sync_returning_coro, 100, 200, c=300)
    assert res_coro == 600

    # 3. Test _resolve_plugin_dependencies with container parameter and default parameter
    class PluginWithContainerAndDefault(BasePlugin):
        def __init__(self, container, timeout: int = 10, *args, **kwargs):
            self.container = container
            self.timeout = timeout

    deps, missing = kernel._resolve_plugin_dependencies(PluginWithContainerAndDefault)
    assert deps["container"] is kernel.container
    assert deps["timeout"] == 10
    assert not missing

    # 4. Test tool setup failure during boot
    class ToolWithFailingSetup(BaseTool):
        @property
        def name(self) -> str:
            return "failing_setup_tool"
        async def setup(self):
            raise RuntimeError("Setup failed")
        def get_interface_description(self) -> str:
            return ""

    # 5. Test plugin on_boot failure and plugin instantiation failure during boot
    class PluginWithFailingBoot(BasePlugin):
        async def on_boot(self):
            raise RuntimeError("on_boot failed")

    class PluginWithFailingInit(BasePlugin):
        def __init__(self):
            raise RuntimeError("init failed")

    # 6. Test tool on_boot_complete failure
    class ToolWithFailingBootComplete(BaseTool):
        @property
        def name(self) -> str:
            return "failing_boot_complete_tool"
        async def setup(self):
            pass
        def get_interface_description(self) -> str:
            return ""
        async def on_boot_complete(self, container):
            raise RuntimeError("on_boot_complete failed")

    def fake_load_modules(directory, base_class, suffix):
        if base_class == BaseTool:
            return [
                (ToolWithFailingSetup, None),
                (ToolWithFailingBootComplete, None),
            ]
        elif base_class == BasePlugin:
            return [
                (PluginWithFailingBoot, "domain_a"),
                (PluginWithFailingInit, "domain_b"),
            ]
        return []

    monkeypatch.setattr(kernel, "_load_modules_from_dir", fake_load_modules)
    await kernel.boot()

    # Verify status in registry
    dump = kernel.container.registry.get_system_dump()
    assert dump["tools"]["failing_setup_tool"]["status"] == "FAIL"
    assert dump["tools"]["failing_setup_tool"]["message"] == "Setup failed"
    assert dump["plugins"]["domain_a.PluginWithFailingBoot"]["status"] == "DEAD"
    assert dump["plugins"]["domain_a.PluginWithFailingBoot"]["error"] == "on_boot failed"
    assert dump["plugins"]["domain_b.PluginWithFailingInit"]["status"] == "DEAD"
    assert dump["plugins"]["domain_b.PluginWithFailingInit"]["error"] == "init failed"


async def test_kernel_on_boot_complete_and_shutdown_container_passage(kernel, monkeypatch):
    received_container = []
    shutdown_called = []

    class TrackedTool(BaseTool):
        @property
        def name(self) -> str:
            return "tracked_tool"
        async def setup(self):
            pass
        def get_interface_description(self) -> str:
            return ""
        async def on_boot_complete(self, cnt):
            received_container.append(cnt)
        async def shutdown(self):
            shutdown_called.append("tool")

    class TrackedPlugin(BasePlugin):
        async def on_boot_complete(self, cnt):
            received_container.append(cnt)
        async def shutdown(self):
            shutdown_called.append("plugin")

    def fake_load_modules(directory, base_class, suffix):
        if base_class == BaseTool:
            return [(TrackedTool, None)]
        elif base_class == BasePlugin:
            return [(TrackedPlugin, "domain_tracked")]
        return []

    monkeypatch.setattr(kernel, "_load_modules_from_dir", fake_load_modules)

    await kernel.boot_tool("tracked_tool")
    assert len(received_container) == 1
    assert received_container[0] is kernel.container

    received_container.clear()
    await kernel.boot()
    assert len(received_container) == 1
    assert received_container[0] is kernel.container

    await kernel.shutdown()
    assert "tool" in shutdown_called
    assert "plugin" in shutdown_called