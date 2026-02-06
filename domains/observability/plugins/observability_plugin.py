from core.base_plugin import BasePlugin

class ObservabilityPlugin(BasePlugin):
    def __init__(self, http_server, registry, logger):
        self.http = http_server
        self.registry = registry
        self.logger = logger

    def on_boot(self):
        """Registers the observability endpoint"""
        self.http.add_endpoint(
            path="/obs/system", 
            method="GET", 
            handler=self.get_system_status,
            tags=["System"]
        )
        self.logger.info("Observability Plugin active at /obs/system")

    def execute(self, **kwargs):
        """Returns system status directly from the registry"""
        return self.registry.get_system_dump()

    def get_system_status(self, data):
        """Handler for the HTTP endpoint"""
        return self.execute()
