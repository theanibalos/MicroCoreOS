from typing import List, Optional
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


class UserData(BaseModel):
    id: int
    name: str
    email: EmailStr


class ListUsersResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class ListUsersPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/users",
            method="GET",
            handler=self.execute,
            tags=["Users"],
            response_model=ListUsersResponse
        )

    async def execute(self, data: dict, context=None):
        try:
            rows = await self.db.query("SELECT id, name, email FROM users")
            users = [UserData(id=r["id"], name=r["name"], email=r["email"]).model_dump() for r in rows]
            return {"success": True, "data": {"users": users}}
        except Exception as e:
            self.logger.error(f"Failed to list users: {e}")
            if context:
                context.set_status(500)
            return {"success": False, "data": None, "error": "Internal Server Error"}
