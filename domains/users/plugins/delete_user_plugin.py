from typing import Optional
from pydantic import BaseModel
from core.base_plugin import BasePlugin


# ── Response schema ──────────────────────────────────────────────────────────
class DeleteUserResponse(BaseModel):
    success: bool
    data: None = None
    error: Optional[str] = None


# ── Event payload schema (publisher owns the contract) ───────────────────────
class UserDeletedPayload(BaseModel):
    id: int


class DeleteUserPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger, auth):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger
        self.auth = auth

    async def on_boot(self):
        self.http.add_endpoint("/users/{user_id}", "DELETE", self.execute, tags=["Users"],
                               response_model=DeleteUserResponse,
                               auth_validator=self.auth.validate_token)

    async def execute(self, data: dict, context=None):
        try:
            raw_id = data.get("user_id")
            if not raw_id:
                return {"success": False, "error": "Missing user_id"}
            user_id = int(raw_id)

            # Ownership: a user can only delete their own account
            auth_payload = data.get("_auth") or {}
            if str(auth_payload.get("sub")) != str(user_id):
                if context:
                    context.set_status(403)
                return {"success": False, "error": "Forbidden"}

            affected = await self.db.execute("DELETE FROM users WHERE id = $1", [user_id])
            if affected == 0:
                return {"success": False, "error": "User not found"}
            self.logger.info(f"User {user_id} deleted")

            await self.bus.publish("user.deleted", UserDeletedPayload(id=user_id).model_dump())

            return {"success": True}
        except Exception as e:
            self.logger.error(f"Failed to delete user: {e}")
            return {"success": False, "error": "Could not delete user"}
