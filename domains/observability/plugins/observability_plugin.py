from core.base_plugin import BasePlugin

class ObservabilityPlugin(BasePlugin):
    def __init__(self, http_server, container, logger):
        self.http = http_server
        self.container = container
        self.logger = logger

    def on_boot(self):
        """Registro del endpoint de observabilidad"""
        self.http.add_endpoint("/obs/system", "GET", self.get_system_status)
        self.logger.info("Plugin de Observabilidad activo en /obs/system")

    def execute(self, **kwargs):
        """Retorna el estado del sistema directamente"""
        return self.container.get_system_info()

    def get_system_status(self, data):
        """Handler para el endpoint HTTP"""
        return self.execute()
