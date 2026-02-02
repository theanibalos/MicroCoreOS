from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel

class UpdateUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint("/users/update", "PUT", self.execute, tags=["Users"])
        self.logger.info("UpdateUserPlugin: Endpoint /users/update registrado.")

    def execute(self, data: dict):
        user_id = data.get("id")
        name = data.get("name")
        email = data.get("email")

        if not user_id: return {"success": False, "error": "ID requerido"}

        try:
            fields = []
            params = []
            if name:
                ok, err = UserModel.validate_name(name)
                if not ok: return {"success": False, "error": err}
                fields.append("name = ?")
                params.append(name)
            if email:
                ok, err = UserModel.validate_email(email)
                if not ok: return {"success": False, "error": err}
                fields.append("email = ?")
                params.append(email)

            if not fields: return {"success": False, "error": "Nada que actualizar"}
            
            params.append(user_id)
            self.db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(params))
            
            self.logger.info(f"Usuario {user_id} actualizado.")
            self.bus.publish("user_updated", {"id": user_id, "updated_fields": fields})
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
