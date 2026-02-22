"""
Tests for MicroCoreOS core components: Container, Registry, BasePlugin, BaseTool.
These tests provide confidence without altering the framework's explicit philosophy.
"""
import threading
import pytest
from core.container import Container
from core.registry import Registry
from core.base_plugin import BasePlugin
from core.base_tool import BaseTool


# ─── Fixtures ──────────────────────────────────────────────

class FakeTool(BaseTool):
    """A minimal tool for testing."""
    @property
    def name(self) -> str:
        return "fake_tool"
    
    def setup(self):
        self._setup_called = True
    
    def get_interface_description(self) -> str:
        return "Fake Tool for testing."


class FakePlugin(BasePlugin):
    def __init__(self, fake_tool):
        self.fake_tool = fake_tool
        self.booted = False
    
    def on_boot(self):
        self.booted = True
    
    def execute(self, data=None, context=None):
        return {"success": True, "data": "executed"}


# ─── Container Tests ───────────────────────────────────────

class TestContainer:
    def test_register_and_get_tool(self):
        container = Container()
        tool = FakeTool()
        container.register(tool)
        
        assert container.get("fake_tool") is tool

    def test_get_nonexistent_tool_raises(self):
        container = Container()
        
        with pytest.raises(Exception, match="Tool 'nonexistent' not found"):
            container.get("nonexistent")

    def test_has_tool(self):
        container = Container()
        tool = FakeTool()
        
        assert container.has_tool("fake_tool") is False
        container.register(tool)
        assert container.has_tool("fake_tool") is True

    def test_thread_safety(self):
        """Multiple threads registering tools concurrently."""
        container = Container()
        errors = []
        
        def register_tool(i):
            try:
                tool = type(f"Tool{i}", (BaseTool,), {
                    "name": property(lambda self, i=i: f"tool_{i}"),
                    "setup": lambda self: None,
                    "get_interface_description": lambda self: f"Tool {i}",
                })()
                container.register(tool)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=register_tool, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(container.list_tools()) == 20


# ─── Registry Tests ────────────────────────────────────────

class TestRegistry:
    def test_register_tool(self):
        reg = Registry()
        reg.register_tool("db", "OK")
        
        dump = reg.get_system_dump()
        assert dump["tools"]["db"]["status"] == "OK"

    def test_register_plugin(self):
        reg = Registry()
        reg.register_plugin("CreateUser", {
            "dependencies": ["http", "db"],
            "domain": "users",
            "class": "CreateUserPlugin"
        })
        
        dump = reg.get_system_dump()
        plugin = dump["plugins"]["CreateUser"]
        assert plugin["status"] == "BOOTING"
        assert plugin["domain"] == "users"

    def test_copy_on_write_isolation(self):
        """Mutations to the dump should NOT affect internal state."""
        reg = Registry()
        reg.register_tool("db", "OK")
        
        dump = reg.get_system_dump()
        dump["tools"]["db"]["status"] = "HACKED"
        
        # Internal state should be unchanged
        fresh_dump = reg.get_system_dump()
        assert fresh_dump["tools"]["db"]["status"] == "OK"


# ─── BasePlugin Tests ──────────────────────────────────────

class TestBasePlugin:
    def test_execute_returns_data(self):
        plugin = FakePlugin(FakeTool())
        result = plugin.execute()
        assert result == {"success": True, "data": "executed"}

    def test_unimplemented_execute_raises(self):
        """Plugins that don't override execute() should raise NotImplementedError."""
        class EventOnlyPlugin(BasePlugin):
            pass
        
        plugin = EventOnlyPlugin()
        with pytest.raises(NotImplementedError):
            plugin.execute()
