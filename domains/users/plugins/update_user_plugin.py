from pydantic import BaseModel, EmailStr
from core.base_plugin import BasePlugin


# ── Request schema (lives here, not in models/user.py) ──────────────────────
class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    password: str | None = None  # plain-text; hashed before DB write if provided


class UpdateUserPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger, auth):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger
        self.auth = auth

    async def on_boot(self):
        self.http.add_endpoint(
            "/users/{user_id}",
            "PUT",
            self.execute,
            tags=["Users"],
            request_model=UpdateUserRequest
        )

    async def execute(self, data: dict, context=None):
        try:
            user_id = data.get("user_id")
            if not user_id:
                return {"success": False, "error": "Missing user_id"}

            req = UpdateUserRequest(**data)

            # Build SET clause dynamically — only touch provided fields
            fields = []
            params = []

            if req.name:
                fields.append(f"name = ${len(params) + 1}")
                params.append(req.name)

            if req.email:
                fields.append(f"email = ${len(params) + 1}")
                params.append(str(req.email))

            if req.password:
                fields.append(f"password_hash = ${len(params) + 1}")
                params.append(self.auth.hash_password(req.password))

            if not fields:
                return {"success": False, "error": "No fields to update"}

            params.append(user_id)
            sql = f"UPDATE users SET {', '.join(fields)} WHERE id = ${len(params)}"

            affected = await self.db.execute(sql, params)
            if affected == 0:
                return {"success": False, "error": "User not found"}

            self.logger.info(f"User {user_id} updated")
            return {"success": True, "message": f"User {user_id} updated successfully"}
        except Exception as e:
            self.logger.error(f"Failed to update user: {e}")
            return {"success": False, "error": str(e)}
