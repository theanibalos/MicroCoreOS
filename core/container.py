class Container:
    STATUS_OK = "OK"
    STATUS_FAIL = "FAIL"
    STATUS_DEGRADED = "DEGRADED"

    def __init__(self):
        self._tools = {}
        self._health = {}

    def register(self, tool):
        """Registra la instancia de la herramienta usando su nombre"""
        self._tools[tool.name] = tool
        print(f"[Container] Herramienta registrada: {tool.name}")

    def get(self, name: str):
        """Entrega una herramienta por su nombre"""
        if name not in self._tools:
            raise Exception(f"La herramienta '{name}' no existe.")
        return self._tools[name]

    def list_tools(self):
        """Retorna los nombres de todas las herramientas registradas"""
        return list(self._tools.keys())

    def set_health(self, tool_name: str, status: str, message: str = None):
        """Actualiza el estado de salud de una herramienta"""
        self._health[tool_name] = {"status": status, "message": message}

    def get_health(self, tool_name: str):
        """Retorna el estado de salud de una herramienta"""
        return self._health.get(tool_name, {"status": self.STATUS_FAIL, "message": "Not initialized"})

    def is_healthy(self, tool_name: str) -> bool:
        """Verifica si una herramienta está en estado OK"""
        return self.get_health(tool_name)["status"] == self.STATUS_OK