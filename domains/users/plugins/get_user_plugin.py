from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserResponse, UserIdRequest

class GetUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger):
        self.http = http_server
        self.db = db
        self.logger = logger

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/get", 
            method="GET", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserIdRequest,
            response_model=UserResponse
        )
        self.logger.info("GetUserPlugin: Endpoint /users/get registrado con Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")
        
        row = self.db.query("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
        if not row: 
            return {"success": False, "error": "Usuario no encontrado"}
        
        user = UserModel.from_row(row[0])
        return {"success": True, "user": user.to_dict()}
