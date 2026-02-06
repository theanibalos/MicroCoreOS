import os
from core.base_tool import BaseTool

class ConfigTool(BaseTool):
    """
    Configuration Tool:
    Loads environment variables and provides centralized access.
    Optionally supports .env files if present.
    """
    
    def __init__(self):
        self._config = {}

    @property
    def name(self) -> str:
        return "config"

    def setup(self):
        """Loads configuration from the global environment"""
        # Simply copy what's in the system environment
        # (main.py already loaded the .env file)
        for key, value in os.environ.items():
            self._config[key] = value
            
        print(f"[System] ConfigTool: {len(self._config)} variables exposed to plugins.")

    def get_interface_description(self) -> str:
        return """
        Configuration Tool (config):
        - get(key, default=None): Gets a configuration value.
        """

    def get(self, key: str, default: str = None) -> str:
        return self._config.get(key, default)

    def shutdown(self):
        pass
