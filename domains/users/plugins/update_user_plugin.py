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
            self.handler, 
            tags=["Users"],
            request_model=UserEntity
        )

    async def handler(self, data: dict, context):
        return await self.execute(data)

    async def execute(self, data: dict):
        try:
            user_id = data.get("user_id")
            if not user_id:
                return {"success": False, "error": "Missing user_id"}
            
            # Use Pydantic to validate the payload
            user = UserEntity(id=user_id, **data)
            
            # Check if user exists
            exists = await self.db.query("SELECT id FROM users WHERE id = ?", (user.id,))
            if not exists:
                return {"success": False, "error": "User not found"}

            if user.password:
                password_hash = self.auth.hash_password(user.password)
                await self.db.execute(
                    "UPDATE users SET name = ?, email = ?, password_hash = ? WHERE id = ?",
                    (user.name, user.email, password_hash, user.id)
                )
            else:
                await self.db.execute(
                    "UPDATE users SET name = ?, email = ? WHERE id = ?",
                    (user.name, user.email, user.id)
                )
            self.logger.info(f"User {user.id} updated")
            await self.bus.publish("user.updated", {"id": user.id, "email": user.email})
            
            return {"success": True, "data": {"id": user.id, "name": user.name, "email": user.email}}
        except Exception as e:
            self.logger.error(f"Failed to update user: {e}")
            return {"success": False, "error": str(e)}
