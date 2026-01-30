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
        """Carga la configuración inicial"""
        # Intentar cargar .env de forma manual para evitar dependencias externas pesadas
        if os.path.exists(".env"):
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        self._config[key.strip()] = value.strip()
        
        # Las variables de entorno reales tienen prioridad
        for key, value in os.environ.items():
            self._config[key] = value
            
        print(f"[System] ConfigTool: {len(self._config)} variables cargadas.")

    def get_interface_description(self) -> str:
        return """
        Herramienta de Configuración (config):
        - get(key, default=None): Obtiene un valor de configuración.
        """

    def get(self, key: str, default: str = None) -> str:
        return self._config.get(key, default)

    def shutdown(self):
        pass
