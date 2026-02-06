import threading
from core.base_tool import BaseTool

class StateTool(BaseTool):
    """
    In-Memory State Tool (StateTool):
    Allows sharing volatile global data between threads safely.
    Ideal for: counters, temporary caches, and business semaphores.
    """
    
    def __init__(self):
        self._state = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "state"

    def setup(self):
        print("[System] StateTool: In-memory store ready and thread-safe.")

    def get_interface_description(self) -> str:
        return """
        State Tool (state):
        - set(key, value, namespace='default'): Store a value.
        - get(key, default=None, namespace='default'): Retrieve a value.
        - increment(key, amount=1, namespace='default'): Atomic increment.
        - delete(key, namespace='default'): Delete a key.
        """

    def _get_ns(self, namespace):
        if namespace not in self._state:
            self._state[namespace] = {}
        return self._state[namespace]

    def set(self, key, value, namespace='default'):
        with self._lock:
            ns = self._get_ns(namespace)
            ns[key] = value

    def get(self, key, default=None, namespace='default'):
        with self._lock:
            ns = self._get_ns(namespace)
            return ns.get(key, default)

    def increment(self, key, amount=1, namespace='default'):
        with self._lock:
            ns = self._get_ns(namespace)
            current = ns.get(key, 0)
            if not isinstance(current, (int, float)):
                raise ValueError(f"Key '{key}' is not numeric.")
            ns[key] = current + amount
            return ns[key]

    def delete(self, key, namespace='default'):
        with self._lock:
            ns = self._get_ns(namespace)
            if key in ns:
                del ns[key]

    def shutdown(self):
        with self._lock:
            self._state.clear()
