from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserUpdateWithId, UserResponse

class UpdateUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/update", 
            method="PUT", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserUpdateWithId,
            response_model=UserResponse
        )
        self.logger.info("UpdateUserPlugin: Endpoint /users/update registrado con Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")
        name = data.get("name")
        email = data.get("email")

        try:
            fields = []
            params = []
            if name:
                fields.append("name = ?")
                params.append(name)
            if email:
                fields.append("email = ?")
                params.append(email)

            if not fields: 
                return {"success": False, "error": "Nada que actualizar"}
            
            params.append(user_id)
            self.db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(params))
            
            # Recuperar usuario actualizado para la respuesta
            row = self.db.query("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
            if not row:
                return {"success": False, "error": "Usuario no encontrado tras actualización"}
            
            user_dict = {"id": row[0][0], "name": row[0][1], "email": row[0][2]}
            
            self.logger.info(f"Usuario {user_id} actualizado.")
            self.bus.publish("users.updated", user_dict)
            
            return {"success": True, "user": user_dict}
        except Exception as e:
            self.logger.error(f"Error en actualización: {e}")
            return {"success": False, "error": str(e)}
