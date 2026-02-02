from core.base_plugin import BasePlugin

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint("/users/delete", "DELETE", self.execute, tags=["Users"])
        self.logger.info("DeleteUserPlugin: Endpoint /users/delete registrado.")

    def execute(self, data: dict):
        user_id = data.get("id")
        if not user_id: return {"success": False, "error": "ID requerido"}

        try:
            self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.logger.warning(f"Usuario {user_id} eliminado.")
            self.bus.publish("user_deleted", {"id": user_id})
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
