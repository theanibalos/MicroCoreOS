class Container:
    def __init__(self):
        self._tools = {}

    def register(self, tool: BaseTool):
        """Registra la instancia de la herramienta"""
        self._tools[tool.name] = tool
        print(f"[Container] Herramienta registrada: {tool.name}")

    def get(self, name: str):
        """Los plugins llaman a esto para usar una herramienta"""
        if name not in self._tools:
            raise Exception(f"La herramienta '{name}' no existe en el contenedor.")
        return self._tools[name]

    def get_all_contexts(self):
        """Devuelve un mapa de todas las herramientas y sus funciones para la IA"""
        return {name: tool.get_interface_description() for name, tool in self._tools.items()}