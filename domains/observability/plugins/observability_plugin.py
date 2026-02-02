from core.base_plugin import BasePlugin

class ObservabilityPlugin(BasePlugin):
    def __init__(self, http_server, registry, logger):
        self.http = http_server
        self.registry = registry
        self.logger = logger

    def on_boot(self):
        """Registro del endpoint de observabilidad"""
        self.http.add_endpoint(
            path="/obs/system", 
            method="GET", 
            handler=self.get_system_status,
            tags=["System"]
        )
        self.logger.info("Plugin de Observabilidad activo en /obs/system")

    def execute(self, **kwargs):
        """Retorna el estado del sistema directamente desde el registry"""
        return self.registry.get_system_dump()

    def get_system_status(self, data):
        """Handler para el endpoint HTTP"""
        return self.execute()
