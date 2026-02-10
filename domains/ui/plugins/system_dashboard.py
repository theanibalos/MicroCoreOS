import os
from core.base_plugin import BasePlugin

class SystemDashboardPlugin(BasePlugin):
    def __init__(self, http, logger, registry):
        self.http = http
        self.logger = logger
        self.registry = registry

    def on_boot(self):
        # 1. Define the static files path relative to the current file
        web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
        
        # Create the directory if it doesn't exist (for safety)
        if not os.path.exists(web_dir):
            os.makedirs(web_dir)

        # 2. Mount the dashboard at /dashboard/
        self.http.mount_static("/dashboard", web_dir)
        
        # 3. Register an endpoint to get system data
        self.http.add_endpoint("/api/system/info", "GET", self.get_system_status)
        
        self.logger.info("SystemDashboardPlugin: Dashboard available at http://localhost:5000/dashboard/index.html")

    def get_system_status(self, data: dict):
        """Returns the complete registry dump for the dashboard."""
        return {
            "success": True,
            "data": self.registry.get_system_dump()
        }

    def execute(self, **kwargs):
        return {"success": True, "message": "Dashboard handles routes via FastAPI directly."}
