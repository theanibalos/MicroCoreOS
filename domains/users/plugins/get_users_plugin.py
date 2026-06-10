from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field
from core.base_plugin import BasePlugin


# ── Request schema ───────────────────────────────────────────────────────────
class ListUsersQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ── Response schema ──────────────────────────────────────────────────────────
class UserData(BaseModel):
    id: int
    name: str
    email: EmailStr


class ListUsersData(BaseModel):
    users: List[UserData]
    limit: int
    offset: int


class ListUsersResponse(BaseModel):
    success: bool
    data: Optional[ListUsersData] = None
    error: Optional[str] = None


class ListUsersPlugin(BasePlugin):
    def __init__(self, http, db, logger, auth):
        self.http = http
        self.db = db
        self.logger = logger
        self.auth = auth

    async def on_boot(self):
        self.http.add_endpoint(
            path="/users",
            method="GET",
            handler=self.execute,
            tags=["Users"],
            request_model=ListUsersQuery,
            response_model=ListUsersResponse,
            auth_validator=self.auth.validate_token,
        )

    async def execute(self, data: dict, context=None):
        try:
            query = ListUsersQuery(**{k: v for k, v in data.items() if k in ("limit", "offset")})

            rows = await self.db.query(
                "SELECT id, name, email FROM users ORDER BY id LIMIT $1 OFFSET $2",
                [query.limit, query.offset],
            )
            users = [UserData(id=r["id"], name=r["name"], email=r["email"]).model_dump() for r in rows]
            return {
                "success": True,
                "data": {"users": users, "limit": query.limit, "offset": query.offset},
            }
        except Exception as e:
            self.logger.error(f"Failed to list users: {e}")
            if context:
                context.set_status(500)
            return {"success": False, "data": None, "error": "Internal Server Error"}
