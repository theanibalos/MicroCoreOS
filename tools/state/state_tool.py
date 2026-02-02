import threading
from core.base_tool import BaseTool

class StateTool(BaseTool):
    """
    Herramienta de Estado en Memoria (StateTool):
    Permite compartir datos globales volátiles entre hilos de forma segura.
    Ideal para: contadores, cachés temporales y semáforos de negocio.
    """
    
    def __init__(self):
        self._state = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "state"

    def setup(self):
        print("[System] StateTool: Almacén en RAM listo y seguro.")

    def get_interface_description(self) -> str:
        return """
        Herramienta de Estado (state):
        - set(key, value, namespace='default'): Guarda un valor.
        - get(key, default=None, namespace='default'): Recupera un valor.
        - increment(key, amount=1, namespace='default'): Incremento atómico.
        - delete(key, namespace='default'): Elimina una clave.
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
                raise ValueError(f"La clave '{key}' no es numérica.")
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
