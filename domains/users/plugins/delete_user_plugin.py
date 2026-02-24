from core.base_plugin import BasePlugin

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/users/{user_id}", 
            "DELETE", 
            self.handler, 
            tags=["Users"]
        )

    async def handler(self, data: dict, context):
        return await self.execute(data)

    async def execute(self, data: dict):
        try:
            user_id = data.get("user_id")
            if not user_id:
                return {"success": False, "error": "Missing user_id"}
                
            # AWAIT DB query
            exists = await self.db.query("SELECT id FROM users WHERE id = ?", (user_id,))
            if not exists:
                return {"success": False, "error": "User not found"}

            # AWAIT DB execute
            await self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.logger.info(f"User {user_id} deleted")
            
            # AWAIT Event Bus publish
            await self.bus.publish("user.deleted", {"id": user_id})
            
            return {"success": True, "message": f"User {user_id} deleted successfully"}
        except Exception as e:
            self.logger.error(f"Failed to delete user: {e}")
            return {"success": False, "error": str(e)}
