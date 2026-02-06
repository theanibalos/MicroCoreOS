import threading
from core.registry import Registry

class Container:
    STATUS_OK = "OK"
    STATUS_FAIL = "FAIL"
    STATUS_DEGRADED = "DEGRADED"

    def __init__(self):
        self._tools = {}
        self._health = {}
        self._lock = threading.RLock()
        # The registry is now an integral part of the container from birth
        self.registry = Registry()

    def register(self, tool):
        """Registers a tool instance using its name"""
        with self._lock:
            self._tools[tool.name] = tool
        print(f"[Container] Tool registered: {tool.name}")

    def get(self, name: str):
        """Returns a tool by its name"""
        with self._lock:
            if name not in self._tools:
                raise Exception(f"Tool '{name}' does not exist.")
            return self._tools[name]

    def has_tool(self, name: str) -> bool:
        """Checks if a tool exists"""
        with self._lock:
            return name in self._tools

    def list_tools(self):
        """Returns the names of all registered tools"""
        with self._lock:
            return list(self._tools.keys())

    def set_health(self, tool_name: str, status: str, message: str = None):
        """Updates the health status of a tool"""
        with self._lock:
            self._health[tool_name] = {"status": status, "message": message}
            # Sync with internal registry
            self.registry.register_tool(tool_name, status, message)

    def get_health(self, tool_name: str):
        """Returns the health status of a tool"""
        with self._lock:
            return self._health.get(tool_name, {"status": self.STATUS_FAIL, "message": "Not initialized"})

    def is_healthy(self, tool_name: str) -> bool:
        """Checks if a tool is in OK status"""
        return self.get_health(tool_name)["status"] == self.STATUS_OK