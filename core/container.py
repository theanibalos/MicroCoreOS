import threading

class Container:
    STATUS_OK = "OK"
    STATUS_FAIL = "FAIL"
    STATUS_DEGRADED = "DEGRADED"

    def __init__(self):
        self._tools = {}
        self._health = {}
        self._metadata = {"domains": {}}
        self._lock = threading.Lock()

    def register(self, tool):
        """Registra la instancia de la herramienta usando su nombre"""
        with self._lock:
            self._tools[tool.name] = tool
        print(f"[Container] Herramienta registrada: {tool.name}")

    def get(self, name: str):
        """Entrega una herramienta por su nombre"""
        with self._lock:
            if name not in self._tools:
                raise Exception(f"La herramienta '{name}' no existe.")
            return self._tools[name]

    def has_tool(self, name: str) -> bool:
        """Verifica si una herramienta existe"""
        with self._lock:
            return name in self._tools

    def list_tools(self):
        """Retorna los nombres de todas las herramientas registradas"""
        with self._lock:
            return list(self._tools.keys())

    def set_health(self, tool_name: str, status: str, message: str = None):
        """Actualiza el estado de salud de una herramienta"""
        with self._lock:
            self._health[tool_name] = {"status": status, "message": message}

    def get_health(self, tool_name: str):
        """Retorna el estado de salud de una herramienta"""
        with self._lock:
            return self._health.get(tool_name, {"status": self.STATUS_FAIL, "message": "Not initialized"})

    def is_healthy(self, tool_name: str) -> bool:
        """Verifica si una herramienta está en estado OK"""
        return self.get_health(tool_name)["status"] == self.STATUS_OK

    def register_domain_metadata(self, domain_name: str, key: str, value: any):
        """Registra metadatos para un dominio específico (modelos, plugins, etc)"""
        with self._lock:
            if domain_name not in self._metadata["domains"]:
                self._metadata["domains"][domain_name] = {}
            self._metadata["domains"][domain_name][key] = value

    def get_domain_metadata(self):
        """Retorna todo el registro de metadatos de dominios"""
        with self._lock:
            return self._metadata["domains"]