from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel

class GetUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger):
        self.http = http_server
        self.db = db
        self.logger = logger

    def on_boot(self):
        self.http.add_endpoint("/users/get", "GET", self.execute, tags=["Users"])
        self.logger.info("GetUserPlugin: Endpoint /users/get registrado.")

    def execute(self, data: dict):
        user_id = data.get("id")
        if not user_id: return {"success": False, "error": "ID requerido"}
        
        row = self.db.query("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
        if not row: return {"success": False, "error": "Usuario no encontrado"}
        
        user = UserModel.from_row(row[0])
        return {"success": True, "user": user.to_dict()}
