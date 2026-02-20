from core.base_plugin import BasePlugin
from pydantic import BaseModel
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.http_server.http_server_tool import HttpServerTool
    from tools.sqlite.sqlite_tool import SqliteTool
    from tools.event_bus.event_bus_tool import EventBusTool
    from tools.logger.logger_tool import LoggerTool

class UserDeleteRequest(BaseModel):
    user_id: int

class UserDeleteResponse(BaseModel):
    success: bool
    error: str = None

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http: 'HttpServerTool', db: 'SqliteTool', event_bus: 'EventBusTool', logger: 'LoggerTool'):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    def on_boot(self):
        # Register endpoint with schema
        self.http.add_endpoint(
            path="/users/delete",
            method="DELETE",
            handler=self.execute,
            tags=["Users"],
            request_model=UserDeleteRequest,
            response_model=UserDeleteResponse
        )
        self.logger.info("DeleteUserPlugin: Endpoint /users/delete registered.")

    def execute(self, data: dict, context=None):
        user_id = data.get("user_id")
        
        try:
            # Check if user exists
            user = self.db.query_one("SELECT id FROM users WHERE id = ?", (user_id,))
            if not user:
                return {"success": False, "error": "User not found"}

            # Delete user from database
            self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))

            # Publish event to notify other plugins
            self.bus.publish('users.deleted', {'user_id': user_id})
            
            self.logger.info(f"User {user_id} deleted.")
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error deleting user: {str(e)}")
            return {"success": False, "error": str(e)}
