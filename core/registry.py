import threading

class Registry:
    """
    Core component for architectural awareness.
    Tracks tools, domains, models, and plugins internally.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._data = {
            "tools": {},
            "domains": {},
            "plugins": {}
        }

    def register_tool(self, name: str, status: str, message: str = None):
        """Registers the status and health of a tool."""
        with self._lock:
            self._data["tools"][name] = {
                "status": status,
                "message": message
            }

    def register_domain_metadata(self, domain_name: str, key: str, value: any):
        """Registers domain metadata (models, routes, etc)."""
        with self._lock:
            if domain_name not in self._data["domains"]:
                self._data["domains"][domain_name] = {}
            self._data["domains"][domain_name][key] = value

    def register_plugin(self, name: str, info: dict):
        """Registers technical metadata for a plugin."""
        with self._lock:
            # Initialize default status
            info["status"] = "BOOTING" 
            info["error"] = None
            self._data["plugins"][name] = info

    def update_plugin_status(self, name: str, status: str, error: str = None):
        """Updates the health status of a plugin."""
        with self._lock:
            if name in self._data["plugins"]:
                self._data["plugins"][name]["status"] = status
                self._data["plugins"][name]["error"] = error

    def get_system_dump(self) -> dict:
        """Returns a complete dump of system state for observability."""
        with self._lock:
            return {
                "tools": dict(self._data["tools"]),
                "domains": dict(self._data["domains"]),
                "plugins": dict(self._data["plugins"])
            }

    def get_domain_metadata(self) -> dict:
        """Returns metadata for all domains."""
        with self._lock:
            return dict(self._data["domains"])
