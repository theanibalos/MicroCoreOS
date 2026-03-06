from typing import Optional
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


# ── Response schema ──────────────────────────────────────────────────────────
class UserData(BaseModel):
    id: int
    name: str
    email: EmailStr


class GetMeResponse(BaseModel):
    success: bool
    data: Optional[UserData] = None
    error: Optional[str] = None


class GetMePlugin(BasePlugin):
    def __init__(self, http, db, auth, logger):
        self.http = http
        self.db = db
        self.auth = auth
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/users/me",
            method="GET",
            handler=self.execute,
            tags=["Users"],
            response_model=GetMeResponse,
            auth_validator=self.auth.validate_token,
        )

    async def execute(self, data: dict, context=None):
        try:
            auth_payload = data.get("_auth")
            if not auth_payload:
                return {"success": False, "error": "Unauthorized"}

            user_id = int(auth_payload.get("sub"))

            row = await self.db.query_one("SELECT id, name, email FROM users WHERE id = $1", [user_id])
            if not row:
                return {"success": False, "error": "User no longer exists"}

            return {
                "success": True,
                "data": {
                    "id": row["id"],
                    "name": row["name"],
                    "email": row["email"]
                }
            }
        except Exception as e:
            self.logger.error(f"Error in /users/me: {e}")
            return {"success": False, "error": str(e)}
