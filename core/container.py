import threading
from core.registry import Registry

class Container:
    """
    Service Locator for Tools.
    Single responsibility: register, get, and list tools.
    Health/metadata tracking is handled by Registry.
    """

    def __init__(self):
        self._tools = {}
        self._lock = threading.RLock()
        self.registry = Registry()

    def register(self, tool):
        with self._lock:
            self._tools[tool.name] = tool
        print(f"[Container] Tool registered: {tool.name}")

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