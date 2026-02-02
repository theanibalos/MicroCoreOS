from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserListResponse

class ListUsersPlugin(BasePlugin):
    def __init__(self, http_server, db, logger):
        self.http = http_server
        self.db = db
        self.logger = logger

    def on_boot(self):
        self.http.add_endpoint(
            path="/users", 
            method="GET", 
            handler=self.execute, 
            tags=["Users"],
            response_model=UserListResponse
        )
        self.logger.info("ListUsersPlugin: Endpoint /users registrado con Schema.")

    def execute(self, data: dict):
        rows = self.db.query("SELECT id, name, email FROM users")
        users = [UserModel.from_row(row).to_dict() for row in rows]
        return {"success": True, "users": users}
