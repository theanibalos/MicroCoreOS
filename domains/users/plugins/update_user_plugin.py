from core.base_plugin import BasePlugin
from domains.users.models.user import UserEntity

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
            request_model=UserEntity
        )

    async def execute(self, data: dict, context=None):
        try:
            user_id = data.get("user_id")
            if not user_id:
                return {"success": False, "error": "Missing user_id"}

            user = UserEntity(id=user_id, **data)
            password_hash = self.auth.hash_password(user.password) if user.password else None

            if password_hash:
                affected = await self.db.execute(
                    "UPDATE users SET name = $1, email = $2, password_hash = $3 WHERE id = $4",
                    [user.name, user.email, password_hash, user.id]
                )
            else:
                affected = await self.db.execute(
                    "UPDATE users SET name = $1, email = $2 WHERE id = $3",
                    [user.name, user.email, user.id]
                )

            if affected == 0:
                return {"success": False, "error": "User not found"}
            self.logger.info(f"User {user.id} updated")
            await self.bus.publish("user.updated", {"id": user.id, "email": user.email})

            return {"success": True, "data": {"id": user.id, "name": user.name, "email": user.email}}
        except Exception as e:
            self.logger.error(f"Failed to update user: {e}")
            return {"success": False, "error": str(e)}
