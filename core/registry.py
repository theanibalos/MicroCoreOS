import threading

class Registry:
    """
    Componente central del Core para la conciencia arquitectónica.
    Rastrea herramientas, dominios, modelos y plugins de forma interna.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._data = {
            "tools": {},
            "domains": {},
            "plugins": {}
        }

    def register_tool(self, name: str, status: str, message: str = None):
        """Registra el estado y salud de una herramienta."""
        with self._lock:
            self._data["tools"][name] = {
                "status": status,
                "message": message
            }

    def register_domain_metadata(self, domain_name: str, key: str, value: any):
        """Registra metadatos de dominio (modelos, rutas, etc)."""
        with self._lock:
            if domain_name not in self._data["domains"]:
                self._data["domains"][domain_name] = {}
            self._data["domains"][domain_name][key] = value

    def register_plugin(self, name: str, info: dict):
        """Registra metadatos técnicos de un plugin."""
        with self._lock:
            self._data["plugins"][name] = info

    def get_system_dump(self) -> dict:
        """Retorna un dump completo del estado del sistema para observabilidad."""
        with self._lock:
            return {
                "tools": dict(self._data["tools"]),
                "domains": dict(self._data["domains"]),
                "plugins": dict(self._data["plugins"])
            }

    def get_domain_metadata(self) -> dict:
        """Retorna los metadatos de todos los dominios."""
        with self._lock:
            return dict(self._data["domains"])
