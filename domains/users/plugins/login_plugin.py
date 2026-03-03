from typing import Optional
from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


# ── Request schema ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ── Response schema ──────────────────────────────────────────────────────────
class LoginData(BaseModel):
    token: str


class LoginResponse(BaseModel):
    success: bool
    data: Optional[LoginData] = None
    error: Optional[str] = None


class LoginPlugin(BasePlugin):
    def __init__(self, http, db, auth, logger):
        self.http = http
        self.db = db
        self.auth = auth
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/auth/login",
            method="POST",
            handler=self.execute,
            tags=["Auth"],
            request_model=LoginRequest,
            response_model=LoginResponse,
        )

    async def execute(self, data: dict, context=None):
        try:
            req = LoginRequest(**data)

            row = await self.db.query_one(
                "SELECT id, password_hash FROM users WHERE email = $1",
                [req.email]
            )

            if not row:
                return {"success": False, "error": "Invalid email or password"}

            if not row["password_hash"]:
                return {"success": False, "error": "User has no password set"}

            if not self.auth.verify_password(req.password, row["password_hash"]):
                return {"success": False, "error": "Invalid email or password"}

            token = self.auth.create_token({"sub": str(row["id"]), "email": req.email})

            if context:
                context.set_cookie("access_token", token, max_age=86400)

            self.logger.info(f"User {req.email} logged in successfully")
            return {"success": True, "data": {"token": token}}

        except Exception as e:
            self.logger.error(f"Login error: {e}")
            return {"success": False, "error": str(e)}
