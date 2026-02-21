import os
from core.base_plugin import BasePlugin

class SystemDashboardPlugin(BasePlugin):
    def __init__(self, http, logger, registry, db):
        self.http = http
        self.logger = logger
        self.registry = registry
        self.db = db

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

    def get_system_status(self, data: dict, context):
        """Returns the complete registry dump for the dashboard, plus true DB schema."""
        db_schema = {}
        try:
            tables = self.db.query("SELECT name FROM sqlite_master WHERE type='table';")
            for (table_name,) in tables:
                columns = self.db.query(f"PRAGMA table_info({table_name});")
                db_schema[table_name] = [
                    {"cid": c[0], "name": c[1], "type": c[2], "notnull": c[3], "dflt_value": c[4], "pk": c[5]}
                    for c in columns
                ]
        except Exception as e:
            self.logger.error(f"SystemDashboardPlugin: Error extracting DB Schema: {e}")

        dump = self.registry.get_system_dump()
        dump["database_schema"] = db_schema

        return {
            "success": True,
            "data": dump
        }

    def execute(self, **kwargs):
        return {"success": True, "message": "Dashboard handles routes via FastAPI directly."}
