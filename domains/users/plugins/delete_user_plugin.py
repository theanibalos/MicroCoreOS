from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserIdRequest, UserResponse

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/delete", 
            method="DELETE", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserIdRequest,
            response_model=UserResponse
        )
        self.logger.info("DeleteUserPlugin: Endpoint /users/delete registrado con Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")

        try:
            # Verificar existencia antes de borrar para dar mejor feedback
            row = self.db.query("SELECT id FROM users WHERE id = ?", (user_id,))
            if not row:
                return {"success": False, "error": "Usuario no encontrado"}

            self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.logger.warning(f"Usuario {user_id} eliminado.")
            
            # Notificar al sistema
            self.bus.publish("users.deleted", {"id": user_id})
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error en eliminación: {e}")
            return {"success": False, "error": str(e)}
