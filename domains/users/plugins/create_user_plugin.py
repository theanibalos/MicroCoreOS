from typing import Optional
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


# ── Request schema ───────────────────────────────────────────────────────────
class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str  # plain-text; hashed before DB write


# ── Response schema ──────────────────────────────────────────────────────────
class CreatedUserData(BaseModel):
    id: int
    name: str
    email: EmailStr


class CreateUserResponse(BaseModel):
    success: bool
    data: Optional[CreatedUserData] = None
    error: Optional[str] = None


class CreateUserPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger, auth):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger
        self.auth = auth

    async def on_boot(self):
        self.http.add_endpoint(
            "/users",
            "POST",
            self.execute,
            tags=["Users"],
            request_model=CreateUserRequest,
            response_model=CreateUserResponse,
        )

    async def execute(self, data: dict, context=None):
        try:
            req = CreateUserRequest(**data)
            password_hash = self.auth.hash_password(req.password)

            user_id = await self.db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES ($1, $2, $3) RETURNING id",
                [req.name, req.email, password_hash]
            )
            self.logger.info(f"User created with ID {user_id}")

            await self.bus.publish("user.created", {"id": user_id, "email": req.email})

            return {"success": True, "data": {"id": user_id, "name": req.name, "email": req.email}}
        except Exception as e:
            self.logger.error(f"Failed to create user: {e}")
            return {"success": False, "error": str(e)}
