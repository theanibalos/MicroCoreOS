import threading
import copy

class Registry:
    """
    Core component for architectural awareness.
    Uses Copy-on-Write (CoW) pattern: readers are lock-free.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {"tools": {}, "domains": {}, "plugins": {}}

    def _sync(self, update_func):
        """Internal helper for atomic snapshots."""
        with self._lock:
            new_data = copy.deepcopy(self._data)
            update_func(new_data)
            self._data = new_data

    def register_tool(self, name: str, status: str, message: str = None):
        def upd(d): d["tools"][name] = {"status": status, "message": message}
        self._sync(upd)

    def register_domain_metadata(self, domain: str, key: str, val: any):
        def upd(d):
            if domain not in d["domains"]: d["domains"][domain] = {}
            d["domains"][domain][key] = val
        self._sync(upd)

    def register_plugin(self, name: str, info: dict):
        def upd(d):
            info.update({"status": "BOOTING", "error": None})
            d["plugins"][name] = info
        self._sync(upd)

    def update_plugin_status(self, name: str, status: str, error: str = None):
        def upd(d):
            if name in d["plugins"]:
                d["plugins"][name].update({"status": status, "error": error})
        self._sync(upd)

    def get_system_dump(self) -> dict:
        return copy.deepcopy(self._data)

    def get_domain_metadata(self) -> dict:
        return copy.deepcopy(self._data["domains"])
