class Container:
    def __init__(self):
        self._tools = {}

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