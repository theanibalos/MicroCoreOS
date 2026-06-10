from typing import Optional
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


class UserData(BaseModel):
    id: int
    name: str
    email: EmailStr


class GetUserByIdResponse(BaseModel):
    success: bool
    data: Optional[UserData] = None
    error: Optional[str] = None


class GetUserByIdPlugin(BasePlugin):
    def __init__(self, http, db, logger, auth):
        self.http = http
        self.db = db
        self.logger = logger
        self.auth = auth

    async def on_boot(self):
        self.http.add_endpoint("/users/{user_id}", "GET", self.execute, tags=["Users"],
                               response_model=GetUserByIdResponse,
                               auth_validator=self.auth.validate_token)

    async def execute(self, data: dict, context=None):
        try:
            raw_id = data.get("user_id")
            if not raw_id:
                return {"success": False, "error": "Missing user_id"}
            user_id = int(raw_id)

            row = await self.db.query_one("SELECT id, name, email FROM users WHERE id = $1", [user_id])
            if not row:
                return {"success": False, "error": "User not found"}

            return {"success": True, "data": {"id": row["id"], "name": row["name"], "email": row["email"]}}
        except Exception as e:
            self.logger.error(f"Failed to fetch user {data.get('user_id')}: {e}")
            return {"success": False, "error": "Could not fetch user"}
