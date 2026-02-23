import threading

class Registry:
    """
    Core component for architectural awareness.
    Maintains a thread-safe in-memory global state (RAM Dictionary).
    Reads are direct references (zero-copy), writes are locked.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {"tools": {}, "domains": {}, "plugins": {}}

    def register_tool(self, name: str, status: str, message: str = None):
        with self._lock:
            self._data["tools"][name] = {"status": status, "message": message}

    def update_tool_status(self, name: str, status: str, message: str = None):
        with self._lock:
            if name in self._data["tools"]:
                self._data["tools"][name].update({"status": status, "message": message})

    def register_domain_metadata(self, domain: str, key: str, val: any):
        with self._lock:
            if domain not in self._data["domains"]:
                self._data["domains"][domain] = {}
            self._data["domains"][domain][key] = val

    def register_plugin(self, name: str, info: dict):
        with self._lock:
            info.update({"status": "BOOTING", "error": None})
            self._data["plugins"][name] = info

    def update_plugin_status(self, name: str, status: str, error: str = None):
        with self._lock:
            if name in self._data["plugins"]:
                self._data["plugins"][name].update({"status": status, "error": error})

    def get_system_dump(self) -> dict:
        """Returns the live reference of the system state."""
        return self._data

    def get_domain_metadata(self) -> dict:
        """Returns the live reference of the domain metadata."""
        return self._data["domains"]
