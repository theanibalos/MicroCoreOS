import inspect
import threading
from core.registry import Registry

class ToolProxy:
    """
    Transparent Proxy that wraps a Tool.
    Intercepts method calls to automatically report health status (DEAD)
    to the Registry if the underlying Tool raises an Exception.
    Correctly handles both sync and async methods.
    """
    def __init__(self, tool, registry: Registry):
        self._tool = tool
        self._registry = registry

    def __getattr__(self, name):
        attr = getattr(self._tool, name)
        
        # We only want to intercept callable methods, not properties like 'name'
        if not callable(attr):
            return attr

        if inspect.iscoroutinefunction(attr):
            async def wrapper(*args, **kwargs):
                try:
                    return await attr(*args, **kwargs)
                except Exception as e:
                    self._registry.update_tool_status(self._tool.name, "DEAD", str(e))
                    raise
        else:
            def wrapper(*args, **kwargs):
                try:
                    result = attr(*args, **kwargs)
                except Exception as e:
                    self._registry.update_tool_status(self._tool.name, "DEAD", str(e))
                    raise

                if inspect.isawaitable(result):
                    async def _monitored():
                        try:
                            return await result
                        except Exception as e:
                            self._registry.update_tool_status(self._tool.name, "DEAD", str(e))
                            raise
                    return _monitored()

                return result
        return wrapper

class Container:
    """
    Service Locator for Tools.
    Single responsibility: register, get, and list tools.
    Health/metadata tracking is handled by Registry via ToolProxy.
    """

    def __init__(self):
        self._tools = {}
        self._lock = threading.RLock()
        self.registry = Registry()

    def register(self, tool):
        with self._lock:
            # Give the tool a direct reference to the registry if it needs it
            # (e.g. RegistryTool), making it available before on_boot_complete.
            if hasattr(tool, '_set_core_registry'):
                tool._set_core_registry(self.registry)
            self._tools[tool.name] = ToolProxy(tool, self.registry)
        print(f"[Container] Tool registered (Proxied): {tool.name}")

    def get(self, name: str):
        with self._lock:
            if name not in self._tools:
                raise Exception(f"Tool '{name}' not found.")
            return self._tools[name]

    def has_tool(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def list_tools(self):
        with self._lock:
            return list(self._tools.keys())