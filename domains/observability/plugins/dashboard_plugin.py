import os
from core.base_plugin import BasePlugin

class DashboardPlugin(BasePlugin):
    """
    Plugin that serves a visual dashboard for real-time system observability.
    Uses the http_server tool to mount static files and provide a UI.
    """
    def __init__(self, http_server, logger):
        self.http = http_server
        self.logger = logger
        # Path to the static files directory
        self.static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))

    def on_boot(self):
        """Registers the dashboard route and static files"""
        if os.path.exists(self.static_dir):
            # Mount the directory to serve the dashboard.html
            self.http.mount_static("/dashboard/gui", self.static_dir)
            
            self.logger.info(f"DashboardPlugin: UI available at http://localhost:5000/dashboard/gui/dashboard.html")
        else:
            self.logger.error(f"DashboardPlugin: Static directory not found at {self.static_dir}")

    def execute(self, **kwargs):
        return {
            "success": True,
            "url": "/dashboard/gui/dashboard.html",
            "message": "Dashboard UI is active and monitoring the EventBus."
        }
