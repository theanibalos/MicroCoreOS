import json
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from core.base_plugin import BasePlugin


# ── Request schema ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


# ── Response schema ──────────────────────────────────────────────────────────
class LoginData(BaseModel):
    token: str


class LoginResponse(BaseModel):
    success: bool
    data: Optional[LoginData] = None
    error: Optional[str] = None


class LoginPlugin(BasePlugin):
    # Brute-force throttle: fixed window per email (no client IP available in 'data').
    MAX_ATTEMPTS = 5
    WINDOW_SECONDS = 900  # 15 min

    def __init__(self, http, db, auth, logger, state):
        self.http = http
        self.db = db
        self.auth = auth
        self.logger = logger
        self.state = state

    async def on_boot(self):
        self.http.add_endpoint(
            path="/auth/login",
            method="POST",
            handler=self.execute,
            tags=["Auth"],
            request_model=LoginRequest,
            response_model=LoginResponse,
        )

    # ── Throttling helpers ───────────────────────────────────────────────────
    async def _is_throttled(self, email: str) -> bool:
        attempts = await self.state.get(email, default=0, namespace="login_throttle")
        return attempts >= self.MAX_ATTEMPTS

    async def _record_failed_attempt(self, email: str) -> None:
        # TTL applies only when the key is created → fixed window per email.
        await self.state.increment(email, namespace="login_throttle", ttl=self.WINDOW_SECONDS)

    async def execute(self, data: dict, context=None):
        try:
            req = LoginRequest(**data)

            if await self._is_throttled(req.email):
                self.logger.warning(f"Login throttled for {req.email} (too many attempts)")
                if context:
                    context.set_status(429)
                return {"success": False, "error": "Too many attempts. Try again later."}

            row = await self.db.query_one(
                "SELECT id, password_hash, roles FROM users WHERE email = $1",
                [req.email]
            )

            if not row:
                await self._record_failed_attempt(req.email)
                return {"success": False, "error": "Invalid email or password"}

            if not row["password_hash"] or not await self.auth.verify_password(req.password, row["password_hash"]):
                await self._record_failed_attempt(req.email)
                return {"success": False, "error": "Invalid email or password"}

            await self.state.delete(req.email, namespace="login_throttle")

            roles = json.loads(row["roles"]) if row.get("roles") else ["user"]

            # Token and cookie share the same lifetime (24h) — a cookie that
            # outlives its token leaves the client with a phantom session.
            session_minutes = 60 * 24
            token = self.auth.create_token(
                {"sub": str(row["id"]), "email": req.email, "roles": roles},
                expires_delta=session_minutes,
            )

            if context:
                context.set_cookie("access_token", token, max_age=session_minutes * 60)

            self.logger.info(f"User {req.email} logged in successfully")
            return {"success": True, "data": {"token": token}}

        except Exception as e:
            self.logger.error(f"Login error: {e}")
            return {"success": False, "error": "Authentication failed"}
