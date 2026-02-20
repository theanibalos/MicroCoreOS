# domains/users/plugins/delete_user.py

from typing import TYPE_CHECKING
import logging
from pydantic import BaseModel
from microcoreos_tools import db, identity, event_bus

if TYPE_CHECKING:
    from microcoreos_tools.http import HttpContext
    from microcoreos_tools.identity import JWTToken

class UserDeleteRequest(BaseModel):
    user_id: str

class DeleteUserPlugin:
    def __init__(self, http_server_tool: 'http', db_tool: 'db', identity_tool: 'identity'):
        self.http_server_tool = http_server_tool
        self.db_tool = db_tool
        self.identity_tool = identity_tool

    async def execute(self, request_data: UserDeleteRequest):
        # Validate user ID
        if not self.identity_tool.verify_user_id(request_data.user_id):
            return {"success": False, "error": "Invalid user ID"}

        # Delete user from database
        await self.db_tool.execute("DELETE FROM users WHERE id = ?", (request_data.user_id,))

        # Publish event to notify other plugins
        event_bus.publish('users.user_deleted', {'user_id': request_data.user_id})

        return {"success": True}

    async def on_boot(self):
        # Register endpoint with schema
        self.http_server_tool.add_endpoint(
            '/users/{user_id}',
            'DELETE',
            self.execute,
            tags=['users'],
            request_model=UserDeleteRequest,
            response_model=dict(success=bool, error=str)
        )

