import os
from core.base_plugin import BasePlugin

class SystemDashboardPlugin(BasePlugin):
    def __init__(self, http_server, logger, registry):
        self.http = http_server
        self.logger = logger
        self.registry = registry

    def on_boot(self):
        # 1. Definir la ruta de los archivos estáticos relativa al archivo actual
        web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
        
        # Crear el directorio si no existe (por seguridad)
        if not os.path.exists(web_dir):
            os.makedirs(web_dir)

        # 2. Montar el dashboard en /dashboard/
        self.http.mount_static("/dashboard", web_dir)
        
        # 3. Registrar un endpoint para obtener los datos del sistema
        self.http.add_endpoint("/api/system/info", "GET", self.get_system_status)
        
        self.logger.info("SystemDashboardPlugin: Dashboard disponible en http://localhost:5000/dashboard/index.html")

    def get_system_status(self, data: dict):
        """Retorna el dump completo del registry para el dashboard."""
        return {
            "success": True,
            "data": self.registry.get_system_dump()
        }

    def execute(self, **kwargs):
        return {"success": True, "message": "Dashboard handles routes via FastAPI directly."}
