import threading
from core.registry import Registry

class Container:
    STATUS_OK, STATUS_FAIL = "OK", "FAIL"

    def __init__(self):
        self._tools = {}
        self._health = {}
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
        with self._lock: return name in self._tools

    def list_tools(self):
        with self._lock: return list(self._tools.keys())

    def set_health(self, name: str, status: str, msg: str = None):
        with self._lock:
            self._health[name] = {"status": status, "message": msg}
            self.registry.register_tool(name, status, msg)

    def get_health(self, name: str):
        with self._lock:
            return self._health.get(name, {"status": self.STATUS_FAIL, "message": "N/A"})

    def is_healthy(self, name: str) -> bool:
        return self.get_health(name)["status"] == self.STATUS_OK