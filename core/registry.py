import threading
import copy

class Registry:
    """
    Core component for architectural awareness.
    Uses Copy-on-Write (CoW) pattern for Level 3 Efficiency:
    - Readers (Observability) are 100% lock-free and zero-latency.
    - Writers (Kernel/Plugins) use a lock and create atomic snapshots.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "tools": {},
            "domains": {},
            "plugins": {}
        }

    def _atomic_update(self, update_func):
        """Internal helper for Copy-on-Write atomic updates."""
        with self._lock:
            # 1. Create a deep copy (Snapshot)
            new_data = copy.deepcopy(self._data)
            # 2. Apply the change to the snapshot
            update_func(new_data)
            # 3. Swap the reference (Atomic in Python)
            self._data = new_data

    def register_tool(self, name: str, status: str, message: str = None):
        """Registers the status and health of a tool."""
        def update(data):
            data["tools"][name] = {
                "status": status,
                "message": message
            }
        self._atomic_update(update)

    def register_domain_metadata(self, domain_name: str, key: str, value: any):
        """Registers domain metadata (models, routes, etc)."""
        def update(data):
            if domain_name not in data["domains"]:
                data["domains"][domain_name] = {}
            data["domains"][domain_name][key] = value
        self._atomic_update(update)

    def register_plugin(self, name: str, info: dict):
        """Registers technical metadata for a plugin."""
        def update(data):
            info["status"] = "BOOTING" 
            info["error"] = None
            data["plugins"][name] = info
        self._atomic_update(update)

    def update_plugin_status(self, name: str, status: str, error: str = None):
        """Updates the health status of a plugin."""
        def update(data):
            if name in data["plugins"]:
                data["plugins"][name]["status"] = status
                data["plugins"][name]["error"] = error
        self._atomic_update(update)

    def get_system_dump(self) -> dict:
        """
        Returns a complete dump of system state.
        LOCK-FREE: Readers always get the latest consistent snapshot instantly.
        """
        return self._data

    def get_domain_metadata(self) -> dict:
        """
        Returns metadata for all domains.
        LOCK-FREE: Direct access to the current snapshot.
        """
        return self._data["domains"]
