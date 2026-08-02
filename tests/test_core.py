"""
Tests for MicroCoreOS core components: Container, Registry, BasePlugin, BaseTool.
These tests provide confidence without altering the framework's explicit philosophy.
"""
import threading
import pytest
from microcoreos.container import Container
from microcoreos.registry import Registry
from microcoreos import BasePlugin
from microcoreos import BaseTool


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

    async def on_boot(self):
        self.booted = True

    async def execute(self, data=None, context=None):
        return {"success": True, "data": "executed"}


# ─── Container Tests ───────────────────────────────────────

class TestContainer:
    def test_register_and_get_tool(self):
        container = Container()
        tool = FakeTool()
        container.register(tool)
        
        from microcoreos.container import ToolProxy
        proxy = container.get("fake_tool")
        assert isinstance(proxy, ToolProxy)
        assert proxy._tool is tool

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

    def test_live_reference_dump(self):
        """Dump should be a live reference for zero-copy reads."""
        reg = Registry()
        reg.register_tool("db", "OK")
        
        dump = reg.get_system_dump()
        assert dump["tools"]["db"]["status"] == "OK"


# ─── BasePlugin Tests ──────────────────────────────────────

class TestBasePlugin:
    @pytest.mark.anyio
    async def test_on_boot_is_callable(self):
        plugin = FakePlugin(FakeTool())
        await plugin.on_boot()
        assert plugin.booted is True

    @pytest.mark.anyio
    async def test_user_defined_execute_works(self):
        plugin = FakePlugin(FakeTool())
        result = await plugin.execute()
        assert result == {"success": True, "data": "executed"}

    def test_event_only_plugin_has_no_execute(self):
        """BasePlugin does not enforce an execute() method — event-driven plugins define only what they need."""
        class EventOnlyPlugin(BasePlugin):
            pass

        plugin = EventOnlyPlugin()
        assert not hasattr(plugin, 'execute')


# ─── Public API ────────────────────────────────────────────

class TestPublicApi:
    """
    `from microcoreos import X` is the address every generated plugin writes.
    It must not depend on which file defines X today: pinning the file layout
    into thousands of generated plugins is what makes core unreorganizable.
    """

    def test_the_five_plugin_facing_names_are_importable_from_the_package(self):
        import microcoreos

        for name in ("BasePlugin", "BaseTool", "ToolUnavailableError",
                     "current_event_id_var", "current_identity_var"):
            assert hasattr(microcoreos, name), f"{name} dropped from the public API"
            assert name in microcoreos.__all__

    def test_boot_machinery_stays_in_its_submodules(self):
        """Kernel/Container/Registry are boot-time machinery, not plugin surface."""
        import microcoreos
        from microcoreos.kernel import Kernel
        from microcoreos.container import Container
        from microcoreos.registry import Registry

        assert all(isinstance(c, type) for c in (Kernel, Container, Registry))
        for name in ("Kernel", "Container", "Registry"):
            assert not hasattr(microcoreos, name)


# ─── Lifecycle & Robustness Tests ──────────────────────────

class TestLifecycleHooksAndMetadata:
    @pytest.mark.anyio
    async def test_base_tool_optional_lifecycle_hooks(self):
        class MinimalTool(BaseTool):
            @property
            def name(self) -> str:
                return "minimal"
            async def setup(self):
                pass
            def get_interface_description(self) -> str:
                return "Minimal"

        tool = MinimalTool()
        await tool.setup()
        await tool.on_boot_complete(None)
        await tool.on_instrument(None)
        await tool.shutdown()

    @pytest.mark.anyio
    async def test_base_plugin_optional_lifecycle_hooks(self):
        class MinimalPlugin(BasePlugin):
            pass

        plugin = MinimalPlugin()
        assert plugin._identity is None
        await plugin.on_boot()
        await plugin.shutdown()

    def test_registry_domain_metadata_storage(self):
        reg = Registry()
        reg.register_domain_metadata("users", "version", "1.0")
        metadata = reg.get_domain_metadata()
        assert "users" in metadata
        assert metadata["users"]["version"] == "1.0"

    def test_registry_tool_and_plugin_dictionary_keys(self):
        reg = Registry()
        reg.register_tool("t1", "OK", "msg1")
        dump = reg.get_system_dump()
        assert "message" in dump["tools"]["t1"]
        assert dump["tools"]["t1"]["message"] == "msg1"

        reg.update_tool_status("t1", "DEAD", "msg2")
        assert "message" in dump["tools"]["t1"]
        assert dump["tools"]["t1"]["message"] == "msg2"

        reg.register_plugin("p1", {"domain": "d1"})
        assert "error" in dump["plugins"]["p1"]
        assert dump["plugins"]["p1"]["error"] is None

    @pytest.mark.anyio
    async def test_container_metrics_sink_error_resilience(self):
        container = Container()

        def faulty_sink(record):
            raise ValueError("Metrics sink failure")

        container.add_metrics_sink(faulty_sink)

        class AsyncRetTool(BaseTool):
            @property
            def name(self) -> str:
                return "async_ret"
            async def setup(self):
                pass
            def get_interface_description(self) -> str:
                return ""
            def sync_returning_async(self):
                async def _inner():
                    return 100
                return _inner()

        tool = AsyncRetTool()
        container.register(tool)
        proxy = container.get("async_ret")
        val = await proxy.sync_returning_async()
        assert val == 100

    @pytest.mark.anyio
    async def test_container_span_factory_and_callbacks_and_async_error(self):
        container = Container()

        # 1. Test span factory registration
        spans_created = []
        def dummy_span_factory(tool_name, method_name):
            class DummySpan:
                def __enter__(self):
                    spans_created.append((tool_name, method_name))
                    return self
                def __exit__(self, *args):
                    pass
            return DummySpan()

        container.register_span_factory(dummy_span_factory)

        # 2. Test tool with _set_core_registry and _set_container callbacks
        class ToolWithCallbacks(BaseTool):
            def _set_core_registry(self, registry):
                self.reg = registry

            def _set_container(self, cnt):
                self.cnt = cnt

            @property
            def name(self) -> str:
                return "tool_with_callbacks"

            async def setup(self):
                pass

            def get_interface_description(self) -> str:
                return ""

            def sync_returning_failing_coro(self):
                async def _failing_inner():
                    raise ValueError("Inner async failure")
                return _failing_inner()

        tool = ToolWithCallbacks()
        container.register(tool)

        assert hasattr(tool, "reg") and tool.reg is container.registry
        assert hasattr(tool, "cnt") and tool.cnt is container

        proxy = container.get("tool_with_callbacks")

        # Execute and check that span was created
        with pytest.raises(ValueError, match="Inner async failure"):
            ret = proxy.sync_returning_failing_coro()
            await ret

        assert len(spans_created) > 0
        assert ("tool_with_callbacks", "sync_returning_failing_coro") in spans_created
