import os
from core.base_tool import BaseTool

class ConfigTool(BaseTool):
    """
    Herramienta de Configuración:
    Carga variables de entorno y permite acceso centralizado.
    Soporta opcionalmente archivos .env si están presentes.
    """
    
    def __init__(self):
        self._config = {}

    @property
    def name(self) -> str:
        return "config"

    def setup(self):
        """Carga la configuración desde el entorno global"""
        # Simplemente copiamos lo que haya en el sistema
        # (main.py ya se encargó de cargar el .env)
        for key, value in os.environ.items():
            self._config[key] = value
            
        print(f"[System] ConfigTool: {len(self._config)} variables expuestas a plugins.")

    def get_interface_description(self) -> str:
        return """
        Herramienta de Configuración (config):
        - get(key, default=None): Obtiene un valor de configuración.
        """

    def get(self, key: str, default: str = None) -> str:
        return self._config.get(key, default)

    def shutdown(self):
        pass
