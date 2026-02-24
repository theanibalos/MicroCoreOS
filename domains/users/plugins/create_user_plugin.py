from core.base_plugin import BasePlugin
from domains.users.models.user import UserEntity

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
            self.handler, 
            tags=["Users"],
            request_model=UserEntity
        )

    async def handler(self, data: dict, context):
        return await self.execute(data)

    async def execute(self, data: dict):
        try:
            # Validate input using Pydantic
            user = UserEntity(**data)
            
            # Hash the password if provided (AuthTool is currently sync, but we can call it normally)
            password_hash = self.auth.hash_password(user.password) if user.password else None
            
            # AWAIT Database call
            user_id = await self.db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (user.name, user.email, password_hash)
            )
            self.logger.info(f"User created with ID {user_id}")
            
            # AWAIT Event Bus call
            await self.bus.publish("user.created", {"id": user_id, "email": user.email})
            
            return {"success": True, "data": {"id": user_id, "name": user.name, "email": user.email}}
        except Exception as e:
            self.logger.error(f"Failed to create user: {e}")
            return {"success": False, "error": str(e)}
